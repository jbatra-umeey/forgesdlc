"""A/B/C vertical slice. Tool execution is real; replay reasoning is scripted."""
import hashlib
import html
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .agents import FIXTURES, ReferenceAgents
from .orchestration import execute_steps
from .policy import PolicyError, contained, evidence_digest, validate_candidate
from .telemetry import correlate, generate

ORACLE = Path(__file__).parent / "oracle.py"


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


class Harness:
    def __init__(self, output, agents=None, backend="stdlib", allow_model_code=False, quiet=False):
        self.root = Path(output).resolve()
        # Never overwrite an existing user directory or an earlier run.
        self.root.mkdir(parents=True, exist_ok=False)
        self.repo = self.root / "repository"
        self.repo.mkdir()
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.agents = agents or ReferenceAgents()
        self.backend = backend
        self.allow_model_code = allow_model_code
        self.quiet = quiet
        self.run_id = uuid.uuid4().hex
        self.events = []
        self.results = {}
        self.db = sqlite3.connect(self.root / "checkpoints.sqlite3")
        self.db.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE issues (operation_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.started = time.monotonic()

    def close(self):
        self.db.close()

    def event(self, scenario, role, action, **data):
        item = {"sequence": len(self.events) + 1, "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": self.run_id, "scenario": scenario, "role": role, "action": action,
                "mode": self.agents.mode, "data": data}
        self.events.append(item)
        with self.db:
            self.db.execute("INSERT INTO events VALUES (?,?)", (item["sequence"], json.dumps(item)))
        with (self.root / "events.jsonl").open("a") as file:
            file.write(json.dumps(item) + "\n")
        if not self.quiet:
            print(f"[{scenario}] {role:14} {action}", flush=True)

    def git(self, *args):
        # Local Git only, no network push, no inherited hooks or author configuration.
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_AUTHOR_NAME": "ForgeSDLC Demo", "GIT_COMMITTER_NAME": "ForgeSDLC Demo",
               "GIT_AUTHOR_EMAIL": "demo@example.invalid", "GIT_COMMITTER_EMAIL": "demo@example.invalid"}
        result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, *args], cwd=self.repo,
                                env=env, text=True, capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError("local Git operation failed: " + result.stderr[:1000])
        return result.stdout.strip()

    def commit(self, message):
        self.git("add", "subscription.py", "server.py", "docs", ".gitignore")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def verify(self, scenario, label):
        start = time.monotonic()
        # The target file is separate from evaluator code; not a secure process boundary.
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = subprocess.run([sys.executable, "-I", str(ORACLE), str(self.repo)],
                                  cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
            result = {"passed": proc.returncode == 0, "exit_code": proc.returncode,
                      "output": proc.stdout + proc.stderr, "duration_seconds": round(time.monotonic() - start, 3),
                      "source_digest": evidence_digest(self.repo),
                      "oracle_sha256": hashlib.sha256(ORACLE.read_bytes()).hexdigest(),
                      "command": ["python", "-I", "oracle.py", "repository"],
                      "oracle_visibility": "public evaluator-owned tests; not a hidden benchmark"}
        except subprocess.TimeoutExpired:
            result = {"passed": False, "exit_code": None, "output": "Verification timed out after 30 seconds",
                      "duration_seconds": 30, "source_digest": evidence_digest(self.repo)}
        write_json(self.artifacts / scenario / (label + ".json"), result)
        self.event(scenario, "verifier", label, passed=result["passed"], exit_code=result["exit_code"])
        return result

    def apply(self, scenario, proposal):
        if self.agents.mode == "live-gateway" and not self.allow_model_code:
            raise PolicyError("live model code requires --approve-model-code inside your disposable sandbox")
        source = validate_candidate(proposal.get("path"), proposal.get("content"))
        target = contained(self.repo, proposal["path"])
        target.write_text(source)
        self.event(scenario, "coder", "candidate-written", path="subscription.py",
                   source_sha256=hashlib.sha256(source.encode()).hexdigest())

    def generate_and_verify(self, scenario, context):
        outcomes = []
        for attempt in range(1, 3):
            self.apply(scenario, self.agents.code(context))
            result = self.verify(scenario, f"candidate-attempt-{attempt}")
            outcomes.append(result)
            if result["passed"]:
                return result
            context = {**context, "previous_source": (self.repo / "subscription.py").read_text(),
                       "verification": result["output"][-10000:]}
            self.event(scenario, "orchestrator", "repair-required", attempt=attempt)
        raise RuntimeError("candidate failed independent verification after two attempts")

    def review_and_bundle(self, scenario, base_commit, verification, title, branch, ticket_key, base_branch="main"):
        source = (self.repo / "subscription.py").read_text()
        review = self.agents.review(source, {key: value for key, value in verification.items() if key != "output"})
        write_json(self.artifacts / scenario / "review.json", review)
        if not verification["passed"] or review.get("recommendation") != "ready-for-human-review":
            raise RuntimeError("review rejected candidate; no PR bundle published")
        candidate = self.git("rev-parse", "HEAD")
        digest = evidence_digest(self.repo)
        if verification["source_digest"] != digest:
            raise RuntimeError("candidate changed after verification")
        patch = self.git("diff", base_commit, candidate, "--", "subscription.py", "server.py", "docs")
        destination = self.artifacts / scenario
        destination.mkdir(exist_ok=True)
        (destination / "changes.patch").write_text(patch + "\n")
        body = (f"# {title}\n\nIssue: {ticket_key}\n\n"
                f"Mode: {self.agents.mode}; external Jira/GitHub writes disabled in demo.\n\n"
                f"Candidate commit: {candidate}\n\nEvidence digest: {digest}\n\n"
                "Independent service and HTTP conformance checks passed.\n\n"
                "Artifacts: changes.patch, candidate-attempt-*.json, review.json.\n\n"
                "Human review required. No deployment or production approval granted.\n")
        (destination / "pull-request.md").write_text(body)
        pr = {"title": title, "ticket": ticket_key, "head": branch,
              "base": base_branch, "base_commit": base_commit, "candidate_commit": candidate, "source_digest": digest,
              "status": "local-draft-bundle", "url": None, "github_created": False,
              "body_path": f"artifacts/{scenario}/pull-request.md"}
        write_json(destination / "pull-request.json", pr)
        self.event(scenario, "reviewer", "local-pr-bundle-ready", commit=candidate,
                   external_write=False, approval="human-review-required")
        return pr

    def scenario_a(self, ticket):
        if (not isinstance(ticket, dict) or not isinstance(ticket.get("fields"), dict)
                or not isinstance(ticket["fields"].get("acceptance_criteria"), list)
                or not ticket["fields"]["acceptance_criteria"]):
            raise ValueError("ticket requires explicit acceptance_criteria")
        (self.repo / "subscription.py").write_text((FIXTURES / "starter.py").read_text())
        (self.repo / "server.py").write_text((FIXTURES / "server.py").read_text())
        (self.repo / ".gitignore").write_text("__pycache__/\n*.pyc\n*.db\n")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "README.md").write_text("Subscription fixture architecture.\n")
        self.git("init", "-b", "main")
        base = self.commit("chore: initial unimplemented subscription fixture")
        self.git("switch", "-c", "demo/subscription-api")
        context = {"ticket": ticket, "source": (self.repo / "subscription.py").read_text(),
                   "interface": "APIError(status,message), SubscriptionService(database), close(), create(payload,key,identity) -> (record,created), get(id,identity), cancel(id,identity), LOOKUP_DELAY_SECONDS = 0.0, PRICES = {'basic':500,'premium':900}. Include calculate_price(plan) with the exact line return PRICES[plan] for the seeded regression injector.",
                   "constraints": ["Only subscription.py may change", "Use SQLite", "No external billing"]}
        state = {}

        def ingest():
            write_json(self.artifacts / "A" / "ticket.json", ticket)
            self.event("A", "issue-adapter", "ticket-ingested", key=ticket["key"], source=ticket.get("source"))

        def plan():
            state["plan"] = self.agents.plan(ticket)
            write_json(self.artifacts / "A" / "plan.json", state["plan"])
            self.event("A", "planner", "tasks-planned", tasks=state["plan"]["tasks"])
            self.architecture()

        def code():
            state["verification"] = self.generate_and_verify("A", {**context, "plan": state["plan"]})
            state["commit"] = self.commit("feat: subscription API with owner-scoped idempotency")

        def review():
            state["pr"] = self.review_and_bundle("A", base, state["verification"],
                                                  "Create subscription API", "demo/subscription-api", ticket["key"])

        execute_steps([("ingest", ingest), ("plan", plan), ("implement_and_verify", code), ("review", review)], self.backend)
        self.results["A"] = {"status": "passed", "title": "Autonomous feature delivery (scripted in replay)",
                             "ticket": ticket["key"], "verification": state["verification"], "pr": state["pr"]}
        return state["commit"]

    def architecture(self):
        docs = self.repo / "docs"
        (docs / "ADR-001.md").write_text(
            "# ADR-001: Subscription sandbox API\n\nStatus: accepted for trusted demonstration only.\n\n"
            "## Decision\n\nHTTPServer adapter → SubscriptionService → SQLite.\n\n"
            "Use integer cents, a unique (customer_id, idempotency_key) constraint, and SQL parameters.\n\n"
            "## Alternatives\n\nPostgreSQL for concurrent production workloads; excluded from this local fixture.\n\n"
            "## Tradeoffs\n\nSingle-process demonstration; no payments, OIDC, network sandbox, or production release.\n\n"
            "X-Customer-Id is an explicitly spoofable sandbox identity, not authentication.\n")
        (docs / "architecture.mmd").write_text(
            'flowchart TD\n  Client["Sandbox client"] --> HTTP["HTTP adapter"]\n'
            '  HTTP --> Service["Subscription service"]\n  Service --> Store["SQLite"]\n')
        schema = {"type": "object", "required": ["customer_id", "plan"], "additionalProperties": False,
                  "properties": {"customer_id": {"type": "string", "minLength": 1, "maxLength": 128},
                                 "plan": {"type": "string", "enum": ["basic", "premium"]}}}
        response = {"type": "object", "properties": {"id": {"type": "string"}, "customer_id": {"type": "string"},
                    "plan": {"type": "string"}, "price_cents": {"type": "integer"}, "status": {"type": "string"}}}
        identity = {"name": "X-Customer-Id", "in": "header", "required": True, "schema": {"type": "string"},
                    "description": "Spoofable sandbox identity only"}
        sid = {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
        def responses(codes):
            return {str(code): {"description": "Success" if code < 300 else "Error",
                               "content": {"application/json": {"schema": response if code < 300 else {
                                   "type": "object", "properties": {"error": {"type": "string"}}}}}} for code in codes}
        spec = {"openapi": "3.0.3", "info": {"title": "Sandbox Subscription API", "version": "1.0.0"},
                "servers": [{"url": "http://127.0.0.1:8080"}], "paths": {
                    "/subscriptions": {"post": {"parameters": [identity, {"name": "Idempotency-Key", "in": "header",
                        "required": True, "schema": {"type": "string", "minLength": 1, "maxLength": 128}}],
                        "requestBody": {"required": True, "content": {"application/json": {"schema": schema}}},
                        "responses": responses([200, 201, 400, 401, 403, 409])}},
                    "/subscriptions/{id}": {"get": {"parameters": [identity, sid], "responses": responses([200, 401, 403, 404])}},
                    "/subscriptions/{id}/cancel": {"post": {"parameters": [identity, sid], "responses": responses([200, 401, 403, 404])}}}}
        write_json(docs / "openapi.json", spec)
        self.event("A", "architect", "architecture-artifacts-generated", artifacts=["ADR-001.md", "openapi.json", "architecture.mmd"],
                   generation="deterministic contract template")

    def scenario_b(self):
        self.git("switch", "-c", "demo/regression")
        target = self.repo / "subscription.py"
        source = target.read_text()
        marker = "return PRICES[plan]"
        if source.count(marker) != 1:
            raise RuntimeError("B replay injector requires the reference calculate_price implementation")
        target.write_text(source.replace(marker, "return 0 if plan == 'premium' else PRICES[plan]"))
        bad_commit = self.commit("test: inject reproducible premium billing regression")
        self.git("switch", "-c", "demo/self-heal")
        self.event("B", "fault-injector", "price-regression-introduced", commit=bad_commit)
        failing = self.verify("B", "regression-before")
        if failing["passed"]:
            raise RuntimeError("regression did not fail the independent oracle")
        diagnosis = self.agents.diagnose(target.read_text(), failing["output"], "premium subscriptions must cost 900 cents")
        write_json(self.artifacts / "B" / "diagnosis.json", diagnosis)
        self.event("B", "diagnostician", "regression-diagnosed", finding=diagnosis.get("finding"))
        fixed = self.generate_and_verify("B", {"task": "Repair premium price without changing other behavior",
                                               "source": target.read_text(), "diagnosis": diagnosis,
                                               "contract": json.loads((FIXTURES / "ticket.json").read_text())})
        self.commit("fix: restore correct premium subscription price")
        pr = self.review_and_bundle("B", bad_commit, fixed, "Repair premium price regression", "demo/self-heal", "LOCAL-REGRESSION-1", "demo/regression")
        evaluation = {"status": "passed", "before_failed": not failing["passed"], "after_passed": fixed["passed"],
                      "oracle_unchanged": failing["oracle_sha256"] == fixed["oracle_sha256"],
                      "attempt_limit": 2, "causal_scope": "seeded fixture mutation", "model_quality_benchmark": False}
        write_json(self.artifacts / "B" / "evaluation.json", evaluation)
        self.results["B"] = {"status": "passed", "title": "Self-healing engineering", "diagnosis": diagnosis,
                             "before": failing, "verification": fixed, "evaluation": evaluation, "pr": pr}
        self.event("B", "evaluator", "repair-verified", **evaluation)
        return pr["candidate_commit"]

    def local_issue(self, operation_key, payload):
        existing = self.db.execute("SELECT payload FROM issues WHERE operation_key=?", (operation_key,)).fetchone()
        if existing:
            return json.loads(existing[0])
        issue = {"key": "LOCAL-LATENCY-1", "source": "local issue ledger; not Jira", "operation_key": operation_key,
                 **payload}
        with self.db:
            self.db.execute("INSERT INTO issues VALUES (?,?)", (operation_key, json.dumps(issue)))
        return issue

    def scenario_c(self, baseline_commit):
        self.git("switch", "-c", "demo/latency-release")
        target = self.repo / "subscription.py"
        source = target.read_text()
        marker = "LOOKUP_DELAY_SECONDS = 0.0"
        if source.count(marker) != 1:
            raise RuntimeError("C replay injector requires the reference delay configuration")
        target.write_text(source.replace(marker, "LOOKUP_DELAY_SECONDS = 0.04"))
        release = self.commit("test: inject sandbox post-release lookup delay")
        self.git("switch", "-c", "demo/latency-remediation")
        deployment = {"release": release, "baseline_release": baseline_commit, "deployed_at": "2026-01-01T12:00:00Z",
                      "environment": "sandbox", "route": "GET /subscriptions/{id}", "cohort": "same-sandbox-profile",
                      "mode": "simulated-deployment-record", "production_deployed": False}
        write_json(self.artifacts / "C" / "deployment.json", deployment)
        rows = generate(release, baseline_commit)
        (self.artifacts / "C" / "telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        observation = correlate(rows, deployment)
        write_json(self.artifacts / "C" / "observation.json", observation)
        if observation["status"] != "regression":
            raise RuntimeError("expected telemetry regression was not detected")
        self.event("C", "observer", "latency-correlated", release=release,
                   ratio=observation["ratio"], source="synthetic-fixture", causal_claim=False)
        key = hashlib.sha256((release + observation["route"]).encode()).hexdigest()[:20]
        issue = self.local_issue(key, {"summary": "Investigate subscription lookup latency after sandbox release",
            "release": release, "observation": observation,
            "acceptance_criteria": ["Remove injected lookup delay", "Preserve service and HTTP conformance"],
            "development_run_id": self.run_id + "-remediation", "parent_run_id": self.run_id})
        write_json(self.artifacts / "C" / "remediation-issue.json", issue)
        self.event("C", "issue-adapter", "remediation-issue-created", key=issue["key"], external_write=False)
        self.event("C", "router", "remediation-routed-to-development", development_run_id=issue["development_run_id"])
        failing = self.verify("C", "latency-before")
        if failing["passed"]:
            raise RuntimeError("lookup delay was not reproduced by verification")
        diagnosis = self.agents.diagnose(target.read_text(), failing["output"], issue["summary"])
        write_json(self.artifacts / "C" / "diagnosis.json", diagnosis)
        plan = self.agents.plan({"key": issue["key"], "fields": {"acceptance_criteria": issue["acceptance_criteria"]}})
        write_json(self.artifacts / "C" / "plan.json", plan)
        verification = self.generate_and_verify("C", {"issue": issue, "plan": plan, "diagnosis": diagnosis,
                                                      "source": target.read_text(), "task": "Remove artificial lookup delay"})
        self.commit("fix: remove artificial lookup latency after sandbox release")
        pr = self.review_and_bundle("C", release, verification, "Remediate subscription lookup latency",
                                    "demo/latency-remediation", issue["key"], "demo/latency-release")
        self.results["C"] = {"status": "passed", "title": "Production intelligence (synthetic telemetry)",
                             "observation": observation, "issue": issue, "before": failing,
                             "verification": verification, "pr": pr,
                             "limitations": "Correlated synthetic telemetry; no real production incident or deployed recovery."}
        self.event("C", "orchestrator", "closed-loop-remediation-verified", candidate=pr["candidate_commit"])

    def run(self, ticket=None):
        try:
            ticket = ticket or json.loads((FIXTURES / "ticket.json").read_text())
            self.event("ALL", "orchestrator", "run-started", backend=self.backend,
                       live_llm=self.agents.mode == "live-gateway", external_writes=False)
            self.scenario_a(ticket)
            healed = self.scenario_b()
            self.scenario_c(healed)
            summary = {"status": "passed", "run_id": self.run_id, "mode": self.agents.mode,
                       "orchestrator": self.backend, "scenarios": self.results,
                       "agent_calls": self.agents.calls, "duration_seconds": round(time.monotonic() - self.started, 3),
                       "live_jira": ticket.get("source") == "live-jira", "live_github_prs": False,
                       "production_deployed": False, "implemented_scenarios": ["A", "B", "C"],
                       "advanced_catalog": {"designed": 60, "fully_implemented": False},
                       "limitations": ["Reference replay is not autonomous LLM inference",
                                       "No hostile-code sandbox", "No durable mid-run crash recovery",
                                       "No Langfuse/OpenTelemetry exporter", "No live model quality benchmark",
                                       "GitHub and Jira publication are optional separate actions"]}
            write_json(self.root / "summary.json", summary)
            self.event("ALL", "orchestrator", "run-completed", status="passed")
            self.render(summary)
            self.manifest()
            return summary
        except Exception as exc:
            self.event("ALL", "orchestrator", "run-failed", error_type=type(exc).__name__, message=str(exc)[:1000])
            write_json(self.root / "failure.json", {"status": "failed", "error": str(exc), "completed": list(self.results)})
            raise
        finally:
            self.close()

    def manifest(self):
        records = []
        for path in sorted(self.root.rglob("*")):
            if (path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
                    and path.name != "manifest.json" and path.suffix not in {".sqlite3", ".db", ".pyc"}):
                records.append({"path": str(path.relative_to(self.root)), "bytes": path.stat().st_size,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        write_json(self.root / "manifest.json", {"run_id": self.run_id, "files": records})

    def render(self, summary):
        template = (Path(__file__).parent / "web" / "report.html").read_text()
        data = json.dumps(summary).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        events = json.dumps(self.events).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        (self.root / "report.html").write_text(template.replace("__SUMMARY_JSON__", data).replace("__EVENTS_JSON__", events))
