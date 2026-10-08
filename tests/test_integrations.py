import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forgesdlc.agents import GatewayAgents
from forgesdlc.integrations import GitHubAdapter, JiraAdapter, RESTClient, adf, flatten_adf


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return self.replies.pop(0)


class IntegrationsTests(unittest.TestCase):
    def test_jira_get_ticket(self):
        client = FakeClient([{"key": "DEMO-1", "fields": {"summary": "Subscription API", "description": adf("Build it")}}])
        item = JiraAdapter("https://example.invalid", "email", "token", client).get_ticket("DEMO-1", ["test"])
        self.assertEqual(item["source"], "live-jira")
        self.assertEqual(item["fields"]["description"], "Build it")
        self.assertEqual(client.calls[0][0], "GET")

    def test_jira_issue_deduplication(self):
        client = FakeClient([{"issues": [{"key": "DEMO-2"}]}])
        result = JiraAdapter("https://example.invalid", "email", "token", client).create_remediation(
            "DEMO", {"operation_key": "abc", "summary": "Latency"})
        self.assertTrue(result["reused"])
        self.assertEqual(len(client.calls), 1)

    def test_jira_create_contract(self):
        client = FakeClient([{"issues": []}, {"key": "DEMO-3"}])
        JiraAdapter("https://example.invalid", "email", "token", client).create_remediation(
            "DEMO", {"operation_key": "abc", "summary": "Latency"})
        payload = client.calls[1][2]
        self.assertEqual(payload["fields"]["description"]["type"], "doc")
        self.assertEqual(payload["fields"]["labels"], ["forgesdlc-abc"])

    def test_github_candidate_sha_checked(self):
        client = FakeClient([{"sha": "different"}])
        with self.assertRaises(ValueError):
            GitHubAdapter("owner/repo", "token", client).create_pr("head", "main", "title", "body", "expected")
        self.assertEqual(len(client.calls), 1)

    def test_github_creates_draft(self):
        client = FakeClient([{"sha": "expected"}, [], {"html_url": "https://github.com/owner/repo/pull/1"}])
        result = GitHubAdapter("owner/repo", "token", client).create_pr("head", "main", "title", "body", "expected")
        self.assertTrue(client.calls[-1][2]["draft"])
        self.assertIn("/pull/1", result["html_url"])

    def test_github_existing_pr_reused(self):
        client = FakeClient([{"sha": "expected"}, [{"number": 1}]])
        result = GitHubAdapter("owner/repo", "token", client).create_pr("head", "main", "title", "body", "expected")
        self.assertTrue(result["reused"])
        self.assertEqual(len(client.calls), 2)

    def test_github_stale_base_rejected(self):
        client = FakeClient([{"sha": "expected"}, {"sha": "changed"}])
        with self.assertRaises(ValueError):
            GitHubAdapter("owner/repo", "token", client).create_pr(
                "head", "main", "title", "body", "expected", expected_base_sha="original")
        self.assertEqual(len(client.calls), 2)

    def test_insecure_external_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            RESTClient("http://example.invalid", {})

    def test_credential_url_rejected(self):
        with self.assertRaises(ValueError):
            RESTClient("https://user:secret@example.invalid", {})


class GatewayTests(unittest.TestCase):
    def test_budget_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = GatewayAgents("http://127.0.0.1:4000/v1", "model", "key", directory, max_calls=0)
            with self.assertRaises(RuntimeError):
                agent.plan({"fields": {"acceptance_criteria": ["test"]}})

    def test_non_loopback_http_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                GatewayAgents("http://example.invalid/v1", "model", "key", directory)

    def test_exact_cache_scope(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, *args):
                return json.dumps({"choices": [{"message": {"content": '{"tasks":["one"],"constraints":[]}'}}],
                                   "usage": {"total_tokens": 20}}).encode()
        class Opener:
            def __init__(self):
                self.calls = 0
            def open(self, *args, **kwargs):
                self.calls += 1
                return Response()
        with tempfile.TemporaryDirectory() as directory:
            opener = Opener()
            agent = GatewayAgents("http://127.0.0.1:4000/v1", "model", "key", directory)
            with patch("forgesdlc.agents.urllib.request.build_opener", return_value=opener):
                self.assertEqual(agent.plan({"key": "one"}), agent.plan({"key": "one"}))
                self.assertEqual(opener.calls, 1)
                agent.plan({"key": "two"})
                self.assertEqual(opener.calls, 2)


if __name__ == "__main__":
    unittest.main()
