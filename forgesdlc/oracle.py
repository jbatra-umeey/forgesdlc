"""Evaluator-owned conformance tests, executed outside the agent checkout.

These tests are public for reproducibility, NOT a hidden benchmark. The model
adapter does not send this file to the model. Local processes are not a security
boundary against hostile code; use trusted replay only on your main computer.
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


def suite_for(repo):
    sys.path.insert(0, str(Path(repo).resolve()))
    from subscription import APIError, SubscriptionService
    import subscription
    from server import make_server

    class ServiceContracts(unittest.TestCase):
        def setUp(self):
            self.service = SubscriptionService()

        def tearDown(self):
            self.service.close()

        def create(self, plan="premium", key="one", customer="alice"):
            return self.service.create({"customer_id": customer, "plan": plan}, key, customer)

        def error(self, status, fn):
            with self.assertRaises(APIError) as ctx:
                fn()
            self.assertEqual(ctx.exception.status, status)

        def test_premium_price(self):
            self.assertEqual(self.create()[0]["price_cents"], 900)

        def test_basic_price(self):
            self.assertEqual(self.create("basic")[0]["price_cents"], 500)

        def test_idempotent_create(self):
            first, created = self.create()
            second, repeated = self.create()
            self.assertTrue(created)
            self.assertFalse(repeated)
            self.assertEqual(first, second)

        def test_conflicting_key(self):
            self.create()
            self.error(409, lambda: self.create("basic"))

        def test_same_key_different_customer(self):
            self.assertNotEqual(self.create()[0]["id"], self.create(customer="bob")[0]["id"])

        def test_input_validation(self):
            for payload in (None, [], {}, {"customer_id": "alice", "plan": []},
                            {"customer_id": "alice", "plan": "unknown"},
                            {"customer_id": "", "plan": "basic"}):
                self.error(400, lambda p=payload: self.service.create(p, "key", "alice"))

        def test_missing_key(self):
            self.error(400, lambda: self.create(key=None))

        def test_create_identity(self):
            self.error(403, lambda: self.service.create(
                {"customer_id": "alice", "plan": "basic"}, "key", "bob"))

        def test_get_and_cancel(self):
            item, _ = self.create()
            self.assertEqual(self.service.get(item["id"], "alice"), item)
            self.assertEqual(self.service.cancel(item["id"], "alice")["status"], "cancelled")
            self.assertEqual(self.service.cancel(item["id"], "alice")["status"], "cancelled")

        def test_owner_isolation(self):
            item, _ = self.create()
            self.error(403, lambda: self.service.get(item["id"], "bob"))
            self.error(403, lambda: self.service.cancel(item["id"], "bob"))

        def test_not_found(self):
            self.error(404, lambda: self.service.get("absent", "alice"))

        def test_lookup_delay_configuration(self):
            self.assertEqual(subscription.LOOKUP_DELAY_SECONDS, 0.0,
                             "artificial lookup delay must be removed")

    class HTTPContracts(unittest.TestCase):
        def setUp(self):
            self.server = make_server(0)
            self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
            self.thread.start()
            self.base = f"http://127.0.0.1:{self.server.server_port}"

        def tearDown(self):
            self.server.shutdown()
            self.server.server_close()
            self.server.subscription_service.close()
            self.thread.join(timeout=2)

        def request(self, path, method="GET", body=None, identity="alice", key="http-key"):
            headers = {"Content-Type": "application/json"}
            if identity is not None:
                headers["X-Customer-Id"] = identity
            if key is not None:
                headers["Idempotency-Key"] = key
            data = json.dumps(body).encode() if body is not None else None
            request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as response:
                return response.code, json.load(response)

        def test_http_lifecycle(self):
            payload = {"customer_id": "alice", "plan": "premium"}
            status, item = self.request("/subscriptions", "POST", payload)
            self.assertEqual(status, 201)
            self.assertEqual(item["price_cents"], 900)
            self.assertEqual(self.request("/subscriptions", "POST", payload)[0], 200)
            self.assertEqual(self.request(f"/subscriptions/{item['id']}")[0], 200)
            self.assertEqual(self.request(f"/subscriptions/{item['id']}", identity="bob")[0], 403)
            status, cancelled = self.request(f"/subscriptions/{item['id']}/cancel", "POST")
            self.assertEqual(status, 200)
            self.assertEqual(cancelled["status"], "cancelled")

        def test_http_missing_identity(self):
            self.assertEqual(self.request("/subscriptions/x", identity=None)[0], 401)

        def test_http_invalid_payload(self):
            self.assertEqual(self.request("/subscriptions", "POST", ["bad"])[0], 400)

        def test_http_unknown_route(self):
            self.assertEqual(self.request("/unknown")[0], 404)

    suite = unittest.TestSuite()
    for case in (ServiceContracts, HTTPContracts):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    return suite


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: oracle.py REPOSITORY")
    try:
        result = unittest.TextTestRunner(verbosity=2).run(suite_for(sys.argv[1]))
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
    raise SystemExit(0 if result.wasSuccessful() else 1)
