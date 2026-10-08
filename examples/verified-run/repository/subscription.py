"""Trusted reference implementation used ONLY by replay agents.

SQLite demo billing records, not a payment service. Sandbox identity headers
must not be treated as production authentication.
"""
import json
import sqlite3
import time
import uuid

LOOKUP_DELAY_SECONDS = 0.0
PRICES = {"basic": 500, "premium": 900}


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def calculate_price(plan):
    return PRICES[plan]


class SubscriptionService:
    def __init__(self, database=":memory:"):
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, plan TEXT NOT NULL,
          price_cents INTEGER NOT NULL, status TEXT NOT NULL,
          idem_key TEXT NOT NULL, payload TEXT NOT NULL,
          UNIQUE(customer_id, idem_key))""")

    def close(self):
        self.db.close()

    def _record(self, row):
        if not row:
            raise APIError(404, "subscription not found")
        return dict(zip(("id", "customer_id", "plan", "price_cents", "status"), row[:5]))

    def create(self, payload, key, identity):
        if not isinstance(payload, dict):
            raise APIError(400, "JSON object required")
        customer = payload.get("customer_id")
        plan = payload.get("plan")
        if (not isinstance(customer, str) or not customer.strip()
                or not isinstance(plan, str) or plan not in PRICES
                or not isinstance(key, str) or not key.strip()
                or len(key) > 128 or len(customer) > 128
                or set(payload) != {"customer_id", "plan"}):
            raise APIError(400, "valid customer_id, plan and idempotency key required")
        if identity != customer:
            raise APIError(403, "customer identity does not match")
        canonical = json.dumps(payload, sort_keys=True)
        row = self.db.execute("SELECT * FROM subscriptions WHERE customer_id=? AND idem_key=?",
                              (customer, key)).fetchone()
        if row:
            if row[6] != canonical:
                raise APIError(409, "idempotency key has a different payload")
            return self._record(row), False
        record = (str(uuid.uuid4()), customer, plan, calculate_price(plan), "active", key, canonical)
        try:
            with self.db:
                self.db.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?,?,?)", record)
        except sqlite3.IntegrityError:
            # Another serialized request may already own this key.
            return self.create(payload, key, identity)
        return self._record(record), True

    def get(self, subscription_id, identity):
        time.sleep(LOOKUP_DELAY_SECONDS)
        record = self._record(self.db.execute("SELECT * FROM subscriptions WHERE id=?",
                                             (subscription_id,)).fetchone())
        if identity != record["customer_id"]:
            raise APIError(403, "subscription belongs to another customer")
        return record

    def cancel(self, subscription_id, identity):
        record = self.get(subscription_id, identity)
        with self.db:
            self.db.execute("UPDATE subscriptions SET status='cancelled' WHERE id=?",
                            (subscription_id,))
        record["status"] = "cancelled"
        return record
