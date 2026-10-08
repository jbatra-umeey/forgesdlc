import json
import tempfile
import unittest
from pathlib import Path

from forgesdlc.agents import FIXTURES, ReferenceAgents
from forgesdlc.cli import inspect_manifest, main
from forgesdlc.engine import Harness
from forgesdlc.orchestration import execute_steps
from forgesdlc.policy import PolicyError, contained, evidence_digest, validate_approval, validate_candidate
from forgesdlc.telemetry import correlate, generate, percentile


class PolicyTests(unittest.TestCase):
    def test_reference_code_allowed(self):
        validate_candidate("subscription.py", (FIXTURES / "reference.py").read_text())

    def test_only_allowed_path(self):
        with self.assertRaises(PolicyError):
            validate_candidate("../oracle.py", "pass")

    def test_network_and_process_imports_denied(self):
        for source in ("import subprocess", "import socket", "from os import system", "import urllib.request"):
            with self.assertRaises(PolicyError):
                validate_candidate("subscription.py", source)

    def test_dynamic_execution_denied(self):
        with self.assertRaises(PolicyError):
            validate_candidate("subscription.py", "exec('pass')")

    def test_invalid_python_denied(self):
        with self.assertRaises(PolicyError):
            validate_candidate("subscription.py", "def !")

    def test_workspace_escape_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PolicyError):
                contained(directory, "../outside")

    def test_symlink_escape_denied(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            (Path(directory) / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(PolicyError):
                contained(directory, "link/code.py")

    def test_stale_approval_denied(self):
        with self.assertRaises(PolicyError):
            validate_approval({"decision": "approved", "commit": "old", "digest": "x"}, "new", "x")

    def test_unapproved_denied(self):
        with self.assertRaises(PolicyError):
            validate_approval({"decision": "rejected", "commit": "x", "digest": "y"}, "x", "y")

    def test_current_approval_allowed(self):
        validate_approval({"decision": "approved", "commit": "x", "digest": "y"}, "x", "y")


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {"release": "new", "baseline_release": "old", "environment": "sandbox",
                           "route": "GET /subscriptions/{id}", "cohort": "same-sandbox-profile",
                           "deployed_at": "2026-01-01T12:00:00Z"}
        self.rows = generate("new", "old")

    def test_latency_correlated(self):
        result = correlate(self.rows, self.deployment)
        self.assertEqual(result["status"], "regression")
        self.assertEqual(result["before_count"], 30)
        self.assertGreater(result["ratio"], 6)
        self.assertFalse(result["causal_claim"])

    def test_insufficient_samples(self):
        self.assertEqual(correlate(self.rows[:5], self.deployment)["status"], "inconclusive")

    def test_wrong_environment_ignored(self):
        for row in self.rows[30:]:
            row["environment"] = "production"
        self.assertEqual(correlate(self.rows, self.deployment)["status"], "inconclusive")

    def test_wrong_release_ignored(self):
        for row in self.rows[30:]:
            row["release"] = "unrelated"
        self.assertEqual(correlate(self.rows, self.deployment)["status"], "inconclusive")

    def test_wrong_time_ignored(self):
        for row in self.rows[30:]:
            row["timestamp"] = "2026-01-01T11:00:00Z"
        self.assertEqual(correlate(self.rows, self.deployment)["status"], "inconclusive")

    def test_healthy_release(self):
        for row in self.rows[30:]:
            row["latency_ms"] = 110
        self.assertEqual(correlate(self.rows, self.deployment)["status"], "healthy")

    def test_invalid_metric(self):
        self.rows[0]["latency_ms"] = -1
        with self.assertRaises(ValueError):
            correlate(self.rows, self.deployment)

    def test_percentile(self):
        self.assertEqual(percentile(list(range(1, 101)), .95), 95)


class ExecutionTests(unittest.TestCase):
    def test_ordered_orchestration(self):
        executed = []
        result = execute_steps([("a", lambda: executed.append("a")), ("b", lambda: executed.append("b"))])
        self.assertEqual(result["completed"], executed)

    def test_existing_directory_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "user-file.txt"
            marker.write_text("do not change")
            with self.assertRaises(FileExistsError):
                Harness(directory)
            self.assertEqual(marker.read_text(), "do not change")

    def test_issue_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = Harness(Path(directory) / "run", quiet=True)
            try:
                first = harness.local_issue("key", {"summary": "one"})
                second = harness.local_issue("key", {"summary": "changed"})
                self.assertEqual(first, second)
                self.assertEqual(harness.db.execute("SELECT count(*) FROM issues").fetchone()[0], 1)
            finally:
                harness.close()

    def test_full_abc_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            result = Harness(root, quiet=True).run()
            self.assertEqual(result["status"], "passed")
            self.assertEqual(set(result["scenarios"]), {"A", "B", "C"})
            self.assertFalse(result["scenarios"]["B"]["before"]["passed"])
            self.assertTrue(result["scenarios"]["B"]["evaluation"]["oracle_unchanged"])
            self.assertFalse(result["scenarios"]["C"]["before"]["passed"])
            self.assertEqual(result["scenarios"]["C"]["issue"]["parent_run_id"], result["run_id"])
            self.assertFalse(result["live_github_prs"])
            self.assertEqual(inspect_manifest(root), [])
            self.assertIn("REFERENCE REPLAY", (root / "report.html").read_text())
            (root / "repository" / "subscription.py").write_text("tampered")
            self.assertIn("repository/subscription.py", inspect_manifest(root))

    def test_bounded_failed_candidates(self):
        class BrokenAgents(ReferenceAgents):
            def code(self, context):
                return {"path": "subscription.py", "content": (FIXTURES / "starter.py").read_text()}
        with tempfile.TemporaryDirectory() as directory:
            harness = Harness(Path(directory) / "run", BrokenAgents(), quiet=True)
            with self.assertRaises(RuntimeError):
                harness.run()
            self.assertTrue((harness.artifacts / "A" / "candidate-attempt-2.json").is_file())
            self.assertFalse((harness.artifacts / "A" / "candidate-attempt-3.json").exists())

    def test_live_execution_requires_opt_in(self):
        class LiveStub(ReferenceAgents):
            mode = "live-gateway"
        with tempfile.TemporaryDirectory() as directory:
            harness = Harness(Path(directory) / "run", LiveStub(), quiet=True)
            try:
                with self.assertRaises(PolicyError):
                    harness.apply("A", {"path": "subscription.py", "content": "pass"})
            finally:
                harness.close()

    def test_external_publication_requires_opt_in(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["publish-pr", "--scenario", "A", "--repo", "owner/repo", "--base", "main"])
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
