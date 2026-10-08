# Threat model and explicit limitations

Assets: generated source, test evidence, model context, configured integration credentials, candidate SHA, Jira issues, GitHub PRs, and local audit history.

Trust boundaries: issue text/code/tool outputs are data; provider responses are untrusted; independent conformance assertions own pass/fail. Default replay source is a trusted fixture. Gateway credentials are not included in role context; redirects are denied for credential-bearing REST requests.

Implemented guardrails: one candidate file, workspace containment including symlink checks, narrow imports/builtins, candidate size limit, two repair attempts, subprocess timeouts, bounded gateway call/unit reservations, unknown-usage stop, access-scope-partitioned response caching, explicit external-write commands, candidate-SHA checks, local issue deduplication, and artifact checksums.

**Not a security sandbox:** Python AST restrictions do not stop all harmful behavior. The verification subprocess inherits the local process environment and has filesystem access. Live generated Python must never execute with production secrets or on an unisolated host. Supply an independently hardened environment, restricted network, minimal credentials, and resource limits before live execution.

**Not production identity:** X-Customer-Id can be spoofed. The fixture has owner checks but not verified authentication. It binds to loopback.

**Not comprehensive prompt-injection defense:** role instructions and tool policy limit obvious actions. No claim of robust adversarial isolation, tenant separation, or secret redaction across arbitrary provider outputs.

**Not exactly once:** external PR/issue lookups reduce duplicates but can race or have ambiguous outcomes. No mutation is automatically retried. A distributed operation ledger and reconciliation worker remain future work.

**Not signed provenance:** local SHA-256 checks detect changed bytes, not malicious rewrites of both evidence and manifest. No external signing authority or immutable audit store is configured.

**Not real production intelligence:** telemetry and deployment records are synthetic; observed temporal correlation is not causal proof. The local code fix is verified, but no production rollback or recovery is executed.

**Not cost-certified:** default replay has zero provider requests. Gateway cost is unknown without authoritative pricing/accounting. Conservative request-unit reservations are not guaranteed financial caps.

No third-party vulnerability scanner, hardened worker, authenticated MCP server, tracing exporter, canary controller, schema migration runner, or tenant-isolation suite is implemented. Their intended scenarios remain in the blueprint catalog.
