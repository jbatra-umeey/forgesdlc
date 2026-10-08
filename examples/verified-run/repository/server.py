"""HTTP wrapper for the trusted local sample service. Loopback by default."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from subscription import APIError, SubscriptionService


def make_server(port=8080, database=":memory:"):
    service = SubscriptionService(database)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_api(self):
            try:
                identity = self.headers.get("X-Customer-Id")
                if not identity:
                    raise APIError(401, "sandbox identity header required")
                parts = self.path.split("?")[0].strip("/").split("/")
                if self.command == "POST" and parts == ["subscriptions"]:
                    try:
                        size = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        raise APIError(400, "invalid Content-Length")
                    if size < 1 or size > 8192:
                        raise APIError(400, "body must be 1..8192 bytes")
                    try:
                        data = json.loads(self.rfile.read(size))
                    except (ValueError, UnicodeDecodeError):
                        raise APIError(400, "invalid JSON")
                    body, created = service.create(data, self.headers.get("Idempotency-Key"), identity)
                    status = 201 if created else 200
                elif self.command == "GET" and len(parts) == 2 and parts[0] == "subscriptions":
                    body, status = service.get(parts[1], identity), 200
                elif (self.command == "POST" and len(parts) == 3
                      and parts[0] == "subscriptions" and parts[2] == "cancel"):
                    body, status = service.cancel(parts[1], identity), 200
                else:
                    raise APIError(404, "route not found")
            except APIError as exc:
                body, status = {"error": exc.message}, exc.status
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_POST = handle_api
        do_GET = handle_api

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.subscription_service = service
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--database", default=":memory:")
    args = parser.parse_args()
    server = make_server(args.port, args.database)
    print(f"Sandbox subscription API: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.subscription_service.close()
