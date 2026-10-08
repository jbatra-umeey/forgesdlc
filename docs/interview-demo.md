# The 6½-minute A/B/C interview demonstration

Before presenting, run the demo, verify its manifest, and start the evidence server. Use the precomputed report for navigation; trigger a fresh replay only if you can accommodate the measured run time. A prerecorded run is not a live LLM run. Real Jira/GitHub links require separately configured and verified adapters.

## 0:00–0:30 — Establish the boundary

“This is a delivery harness with explicit roles and independent verification. I will show one service through feature delivery, self-healing, and a telemetry-to-development loop. This run uses deterministic reference agents; Git and tests are real. Production telemetry is simulated.”

Show the mode banner and execution summary. If running live models, say so only when the summary actually records provider calls.

## 0:30–2:45 — A: Autonomous feature-delivery workflow

1. Open `artifacts/A/ticket.json`. Show the acceptance criteria, source label, and scope.
2. Filter the report to A. Show planning and architecture events.
3. Open the generated ADR and OpenAPI contract under `repository/docs`.
4. Open `artifacts/A/changes.patch` and the actual Git candidate SHA.
5. Show `candidate-attempt-1.json`: service checks and real HTTP request tests.
6. Show `pull-request.md` and `pull-request.json`. Call this a **local PR bundle**, unless you have a separately verified GitHub publication receipt and URL.

Explain idempotency, conflicting-key errors, owner checks, integer cents, and the sandbox-only identity header. Do not describe this as a real billing platform.

## 2:45–4:35 — B: Self-healing engineering

1. Open `artifacts/B/regression-before.json`. Show the premium-price assertion failure.
2. Open `diagnosis.json`. Link the finding to `calculate_price`.
3. Open `changes.patch`: removal of the deliberately injected zero-price branch.
4. Show the final verification and `evaluation.json`: failed before, passed after, unchanged evaluator hash.
5. Explain the two-attempt ceiling and inability to override a failing critical check with a favorable reviewer response.

In replay, diagnosis is a seeded-mutation rule and the patch is a reference implementation. Do not claim arbitrary autonomous bug repair or a model-quality benchmark.

## 4:35–6:05 — C: Production intelligence

1. Open `deployment.json` and `observation.json`: same cohort/route, baseline and candidate versions, 30 samples per window, and synthetic p95 increase.
2. Point out `causal_claim: false`: the release is correlated, not proven responsible by telemetry alone.
3. Open `remediation-issue.json`, including operation key, trace IDs, parent run, and linked development run.
4. Filter to C and show the routing event followed by planning, diagnosis, patch, checks, and the PR bundle.
5. Show that the injected source delay is removed and the conformance tests pass. This is not measured production recovery.

## 6:05–6:30 — Wrap up

“The important loop is not just generating code: observations become scoped engineering work, tests determine success, and each transition leaves evidence. The next integration stages are real Jira/GitHub webhooks, hardened execution, LangGraph persistence, live-provider evaluation, and verified sandbox releases.”

Point to the explicit built-versus-designed table. The broader 60-scenario catalog is a roadmap, not a completed test suite.

