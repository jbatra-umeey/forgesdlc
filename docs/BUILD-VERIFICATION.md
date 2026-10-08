# Build verification — 8 October 2026

Verified in the supplied Python 3.12 environment:

- 37 Python unit/integration-fixture tests passed. This includes a full A/B/C replay, policy checks, bounded failures, issue deduplication, cache scoping, telemetry filtering, candidate-SHA checks, and mocked Jira/GitHub transport contracts.
- The independent interview replay completed in 1.478 seconds in this environment. This is execution time, not the intended 6½-minute presentation duration.
- A, B and C final candidates each passed 16 service/HTTP conformance checks. B's injected price regression and C's injected delay first failed their checks as expected.
- Artifact checksums verified without mismatches.
- Report JavaScript syntax and a minimal-DOM interaction smoke test passed: three scenario cards, 23 timeline events, working A/B/C filters, and remediation metadata.

Not verified here: live gateway inference, live Jira/GitHub account permissions or publication, LangGraph execution, browser-rendered layout, hardened execution, physical devices, production deployment, tracing exporters, or the broader 60-scenario catalog.

The published `examples/verified-run` directory (the ZIP archive uses `runs/interview`) contains actual output from the local replay. Provider call counts are zero in that run. C telemetry is synthetic: baseline p95 108 ms, candidate p95 658 ms. Those numbers are fixture observations, not measured production performance.

Reproduce verification with the commands in README.md. Do not compare these execution times across machines as a benchmark.

