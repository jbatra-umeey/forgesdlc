# ForgeSDLC

**One subscription service. Three evidence-backed engineering loops.**

A runnable AI-native SDLC vertical slice for a 5–7 minute interview demonstration. The default mode is **reference-agent replay**: agent decisions use curated templates and rules, while code writes, Git commits, tests, HTTP requests, patches, and issue routing execute for real. It is not autonomous LLM inference.

## Run in two commands

Prerequisites: Python 3.11+ and Git. No third-party packages or credentials are required for replay. Run from this directory; package installation is optional.

```bash
python3 -m forgesdlc demo --output runs/interview
python3 -m forgesdlc serve --output runs/interview
```

Open `http://127.0.0.1:8765/report.html`. Each run requires a fresh output directory; existing files are never overwritten. For another run use `--output runs/interview-2`.

```bash
python3 -m unittest discover -s tests -v
python3 -m forgesdlc verify-evidence --output runs/interview
```

Optional report interaction smoke test (Node.js; no extra packages):

```bash
node tests/report-smoke.cjs runs/interview/report.html
```

This verifies the report JavaScript, cards and filters using a minimal DOM. It is not a rendered-browser layout test; no browser binary was available during verification.

## The three scenarios

| Scenario | Workflow | Actual evidence |
|---|---|---|
| A — Feature delivery | Jira-shaped ticket → task plan → architecture → subscription API → independent checks → PR draft | ADR, OpenAPI, local Git commit, patch, service and HTTP test output |
| B — Self-healing | Inject premium-price bug → detect failing test → diagnose → patch → rerun → evaluate | Failed-before/passed-after outputs, unchanged oracle hash, repair patch |
| C — Production intelligence | Generate simulated post-release latency → correlate release → create local remediation issue → route → repair → verify | Synthetic trace records, p95 comparison, issue operation key, linked development run, tested patch |

Scenario C does not stop at an alert: its local issue is routed into the same development harness, with planning, diagnosis, code, verification, and a PR bundle. The release/latency observations are **synthetic**, while removal of the injected source delay and conformance verification are real. Correlation is explicitly not proof of causality. There is no production deployment.

### Subscription fixture

`POST /subscriptions`, `GET /subscriptions/{id}`, `POST /subscriptions/{id}/cancel`. SQLite storage, integer-cent basic/premium pricing, customer-scoped idempotency, conflicting-key errors, input validation, and owner checks. No real billing, payments, taxation, renewals, webhooks, or account authentication.

`X-Customer-Id` is a spoofable **sandbox identity**, not a production auth solution. The sample HTTP service binds to loopback.

To use the generated API:

```bash
cd runs/interview/repository
python3 server.py --port 8080
```

In another terminal:

```bash
curl -X POST http://127.0.0.1:8080/subscriptions \
  -H 'Content-Type: application/json' -H 'X-Customer-Id: alice' \
  -H 'Idempotency-Key: first-request' \
  -d '{"customer_id":"alice","plan":"premium"}'
```

## Role and tool separation

Planner, architect, coder, diagnostician, verifier, reviewer, observer, and router appear in the evidence timeline. Replay roles are bounded deterministic fixtures, not separate LLM workers. The independent verifier executes evaluator-owned tests from outside the agent checkout; the coder can only propose `subscription.py`. The tests are public reproducibility checks, not a hidden benchmark.

The verifier and policy own hard outcomes; a role's favorable review cannot override a failed test. Repairs stop after two candidate attempts. All external writes are disabled during the default demo.

## Optional real model gateway

The adapter calls an OpenAI-compatible `/chat/completions` endpoint, such as a configured LiteLLM proxy. Live calls are **implemented but not verified against a real provider in this build**. A compatible endpoint must support JSON-object responses and return usage information. Provider-specific prompt caching is not implemented here. Exact response caching applies only to non-coder roles and is partitioned by gateway, credential digest, model, prompt, role, and task scope.

Do not run arbitrary generated Python on your main computer. Live mode requires explicit approval inside a disposable, network-restricted environment with narrowly scoped credentials. AST checks are not a sandbox; this repository does not provision hardened isolation.

```bash
export FORGE_GATEWAY_URL='http://127.0.0.1:4000/v1'
export FORGE_MODEL='your-configured-model-alias'
# Set FORGE_GATEWAY_KEY through your normal secret mechanism; never commit it.
python3 -m forgesdlc demo --mode live --approve-model-code --output runs/live-demo
```

The fixture injector requires `calculate_price` to use the prescribed source marker and `LOOKUP_DELAY_SECONDS = 0.0`. If generated code does not conform, the run stops rather than fabricating a successful regression. Gateway requests have bounded call/unit reservations; unknown usage blocks further calls. These conservative units are not a dollar spending cap. Cost remains unknown unless obtained from the configured gateway.

## Optional LangGraph orchestration

The default runner uses a simple standard-library step executor. A separate LangGraph adapter maps feature-delivery steps to `StateGraph` nodes:

```bash
python3 -m pip install -e '.[graph]'
python3 -m forgesdlc demo --backend langgraph --output runs/graph-demo
```

This optional path is not verified in the supplied environment because LangGraph is unavailable. B/C currently use ordinary Python control flow. SQLite checkpoints are an audit/event history, **not** durable mid-run crash recovery. No LangSmith, Langfuse, OpenTelemetry exporter, hardened worker, or MCP server is implemented in this vertical slice.

## Optional real Jira and GitHub integrations

REST adapters are implemented and transport-mocked unit-tested. Live accounts and permissions have not been verified. Credentials are read only when you explicitly invoke these commands. External mutations have no automatic retry; reconcile uncertain outcomes before retrying. Deduplication is best-effort, not an exactly-once guarantee under concurrency.

### Read a Jira ticket

Configure `JIRA_BASE_URL` (HTTPS), `JIRA_EMAIL`, and `JIRA_API_TOKEN`. Supply a reviewed JSON list of acceptance criteria rather than guessing a Jira custom-field mapping.

```bash
python3 -m forgesdlc fetch-ticket --key YOURPROJECT-101 \
  --criteria criteria.json --output jira-ticket.json
python3 -m forgesdlc demo --ticket jira-ticket.json --output runs/jira-demo
```

This runner is specific to the subscription fixture, not a general Jira-to-any-feature system. A real ticket must describe that service contract.

### Publish the generated draft PRs

The generated fixture is a separate local repository. First choose a dedicated sandbox GitHub repository and explicitly push the generated branches yourself. Do not push into an unrelated repository.

```bash
cd runs/interview/repository
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_SANDBOX_REPOSITORY.git
git push origin main demo/subscription-api demo/regression demo/self-heal \
  demo/latency-release demo/latency-remediation
```

From the ForgeSDLC project directory, configure `GITHUB_TOKEN`, then explicitly publish:

```bash
python3 -m forgesdlc publish-pr --output runs/interview --scenario A \
  --repo YOUR_ACCOUNT/YOUR_SANDBOX_REPOSITORY --base main --confirm-external-write
python3 -m forgesdlc publish-pr --output runs/interview --scenario B \
  --repo YOUR_ACCOUNT/YOUR_SANDBOX_REPOSITORY --base demo/regression --confirm-external-write
python3 -m forgesdlc publish-pr --output runs/interview --scenario C \
  --repo YOUR_ACCOUNT/YOUR_SANDBOX_REPOSITORY --base demo/latency-release --confirm-external-write
```

The adapter checks the remote head SHA against the tested local candidate, reuses an existing open PR when found, and otherwise creates a draft. It does not push, merge, approve, deploy, or automatically update the static report's integration status. Publication receipts are separate JSON files.

### Publish the C remediation issue to Jira

```bash
python3 -m forgesdlc publish-issue --output runs/interview \
  --project YOURPROJECT --confirm-external-write
```

This exports the already-routed local issue. Live Jira webhooks and automatic live-Jira issue-to-run scheduling are future work.

## Evidence layout

```text
runs/interview/
  report.html             # filterable A/B/C evidence viewer
  summary.json            # mode, results, limitations, model-call records
  events.jsonl            # role/tool timeline
  checkpoints.sqlite3     # persisted events and deduplicated local issues
  manifest.json           # SHA-256 artifact checksums
  repository/             # generated service and real local Git history
  artifacts/A/            # ticket, plan, test output, review, patch, PR bundle
  artifacts/B/            # failed test, diagnosis, fix, evaluation, PR bundle
  artifacts/C/            # simulated deployment/telemetry, issue, remediation
```

The evidence manifest detects accidental changes, not tampering by an attacker who can rewrite the manifest. PR publication is distinct from deployment authorization. An exact-candidate approval helper is unit-tested but not a production release controller.

## What's built versus designed

| Capability | Status |
|---|---|
| A/B/C local replay with actual tools and tests | Built and tested |
| CLI, evidence report, Git patch/commit bundles | Built and tested |
| Basic role/path/import checks, bounded repairs, issue deduplication | Built and tested; not comprehensive security |
| Live gateway, Jira, GitHub adapters | Implemented; mocked tests only |
| Optional LangGraph feature flow | Implemented; not executed here |
| 60 advanced scenarios | Design catalog, not 60 passing implementations |
| Physical-device performance, canary, migrations, tenant isolation, hardened sandbox | Future integration stages |

See `docs/interview-demo.md`, `docs/architecture.md`, `docs/threat-model.md`, and the expanded `docs/ForgeSDLC-Blueprint.md`.

## Official integration references

- Jira issues: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
- GitHub PRs: https://docs.github.com/en/rest/pulls/pulls
- LangGraph: https://docs.langchain.com/oss/python/langgraph/graph-api
- LiteLLM gateway: https://docs.litellm.ai/docs/simple_proxy

License: MIT. All sample data and identities are synthetic.

## Published sample evidence

The [`examples/verified-run`](examples/verified-run) directory contains the verified local reference replay, its patches, test outputs, synthetic telemetry and an HTML report. Download/clone the repository to open the report; GitHub displays HTML as source. These are local fixture results, not live-provider or production claims. Run the commands above to generate a fresh execution.

