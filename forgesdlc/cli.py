"""Explicit CLI actions; demo never publishes remotely by default."""
import argparse
import hashlib
import json
import os
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agents import FIXTURES, GatewayAgents, ReferenceAgents
from .engine import Harness, write_json
from .integrations import GitHubAdapter, JiraAdapter
from .policy import PolicyError, evidence_digest


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(name + " must be configured; credentials are never included in output")
    return value


def jira():
    return JiraAdapter(required_env("JIRA_BASE_URL"), required_env("JIRA_EMAIL"), required_env("JIRA_API_TOKEN"))


def inspect_manifest(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    failures = []
    for record in manifest["files"]:
        target = (root / record["path"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            failures.append(record["path"])
        elif hashlib.sha256(target.read_bytes()).hexdigest() != record["sha256"]:
            failures.append(record["path"])
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(prog="forgesdlc", description="Evidence-first A/B/C demo")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="run A/B/C using actual Git and tests")
    demo.add_argument("--output", default="runs/interview")
    demo.add_argument("--mode", choices=["replay", "live"], default="replay")
    demo.add_argument("--backend", choices=["stdlib", "langgraph"], default="stdlib")
    demo.add_argument("--ticket", type=Path)
    demo.add_argument("--approve-model-code", action="store_true",
                      help="execute generated code ONLY inside a disposable, network-restricted sandbox")
    demo.add_argument("--quiet", action="store_true")
    serve = sub.add_parser("serve", help="serve evidence report on loopback")
    serve.add_argument("--output", default="runs/interview")
    serve.add_argument("--port", type=int, default=8765)
    verify = sub.add_parser("verify-evidence")
    verify.add_argument("--output", default="runs/interview")
    fetch = sub.add_parser("fetch-ticket", help="read a real Jira issue; no writes")
    fetch.add_argument("--key", required=True)
    fetch.add_argument("--criteria", type=Path, required=True, help="JSON list of explicit criteria")
    fetch.add_argument("--output", type=Path, required=True)
    publish = sub.add_parser("publish-pr", help="create/reconcile a real draft PR for an already-pushed branch")
    publish.add_argument("--output", default="runs/interview")
    publish.add_argument("--scenario", choices=["A", "B", "C"], required=True)
    publish.add_argument("--repo", required=True)
    publish.add_argument("--base", required=True)
    publish.add_argument("--confirm-external-write", action="store_true")
    issue = sub.add_parser("publish-issue", help="create/reconcile the real Jira remediation issue")
    issue.add_argument("--output", default="runs/interview")
    issue.add_argument("--project", required=True)
    issue.add_argument("--issue-type", default="Task")
    issue.add_argument("--confirm-external-write", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            if args.mode == "live":
                if not args.approve_model_code:
                    raise PolicyError("live mode executes untrusted generated Python; use a disposable sandbox and --approve-model-code")
                agents = GatewayAgents(required_env("FORGE_GATEWAY_URL"), required_env("FORGE_MODEL"),
                                       os.environ.get("FORGE_GATEWAY_KEY", ""), Path(args.output).parent / "gateway-cache")
            else:
                agents = ReferenceAgents()
            ticket = json.loads(args.ticket.read_text()) if args.ticket else None
            result = Harness(args.output, agents, args.backend, args.approve_model_code, args.quiet).run(ticket)
            print(json.dumps({"status": result["status"], "mode": result["mode"],
                              "report": str(Path(args.output).resolve() / "report.html")}, indent=2))
        elif args.command == "serve":
            root = Path(args.output).resolve()
            if not (root / "report.html").is_file():
                raise ValueError("run the demo before serving its report")
            class Handler(SimpleHTTPRequestHandler):
                def __init__(self, *arguments, **kwargs):
                    super().__init__(*arguments, directory=str(root), **kwargs)
                def log_message(self, *arguments):
                    pass
                def do_GET(self):
                    # Evidence server must not expose Git internals or private cache files.
                    decoded = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                    if any(part.startswith(".") for part in decoded.split("/")[1:]):
                        self.send_error(403)
                        return
                    super().do_GET()
                def do_HEAD(self):
                    decoded = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
                    if any(part.startswith(".") for part in decoded.split("/")[1:]):
                        self.send_error(403)
                        return
                    super().do_HEAD()
            server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
            print(f"Evidence report: http://127.0.0.1:{args.port}/report.html", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        elif args.command == "verify-evidence":
            failures = inspect_manifest(args.output)
            print(json.dumps({"passed": not failures, "mismatched": failures}, indent=2))
            if failures:
                raise SystemExit(1)
        elif args.command == "fetch-ticket":
            criteria = json.loads(args.criteria.read_text())
            if not isinstance(criteria, list) or not criteria or not all(isinstance(x, str) for x in criteria):
                raise ValueError("criteria must be a nonempty JSON list of strings")
            if args.output.exists():
                raise ValueError("ticket destination already exists")
            write_json(args.output, jira().get_ticket(args.key, criteria))
            print("Jira ticket read and saved; no external write.")
        elif args.command in {"publish-pr", "publish-issue"}:
            if not args.confirm_external_write:
                raise PolicyError("explicit --confirm-external-write required")
            root = Path(args.output).resolve()
            if inspect_manifest(root):
                raise PolicyError("evidence changed; publication blocked")
            if args.command == "publish-pr":
                bundle = json.loads((root / "artifacts" / args.scenario / "pull-request.json").read_text())
                if args.base != bundle["base"]:
                    raise PolicyError("PR base must match the tested scenario base branch: " + bundle["base"])
                body = (root / bundle["body_path"]).read_text()
                result = GitHubAdapter(args.repo, required_env("GITHUB_TOKEN")).create_pr(
                    bundle["head"], args.base, bundle["title"], body, bundle["candidate_commit"],
                    expected_base_sha=bundle["base_commit"])
                write_json(root / f"published-pr-{args.scenario}.json", result)
                print(json.dumps({"url": result.get("html_url"), "reused": result.get("reused", False)}, indent=2))
            else:
                item = json.loads((root / "artifacts" / "C" / "remediation-issue.json").read_text())
                result = jira().create_remediation(args.project, item, args.issue_type)
                write_json(root / "published-jira-issue.json", result)
                print(json.dumps({"key": result.get("key"), "reused": result.get("reused", False)}, indent=2))
    except (ValueError, RuntimeError, FileExistsError, FileNotFoundError) as exc:
        print(f"Blocked: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        # Never print remote response bodies, tokens, Authorization headers, or credential URLs.
        print(f"Operation failed ({type(exc).__name__}); inspect configured service logs. "
              "For uncertain external-write outcomes, reconcile before retrying.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

