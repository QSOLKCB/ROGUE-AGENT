"""Full offline integration tests; no external service, credentials or budget use."""
import http.client
import json
from pathlib import Path
import sqlite3
import socket
import tempfile
import threading
import unittest
from datetime import datetime

from habitat_api.server import RateLimiter, allowed_origin, init_db, published_counts, serve


class ReadOnlyAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "habitat.sqlite"
        init_db(self.db)
        self.server = serve(self.db, port=0, rate_limit=120)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, *, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            r = conn.getresponse()
            payload = r.read()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, json.loads(payload) if payload else None
        finally:
            conn.close()

    def publish(self, kind, id_, state="published", withdrawn=None):
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO public_records (record_id,kind,publication_state,source_ref,published_at,withdrawn_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (id_, kind, state, f"offline-reviewed:{id_}", "2026-10-30T00:00:00Z" if state == "published" else None, withdrawn)
            )

    def test_health_does_not_disclose_internal_state(self):
        code, headers, payload = self.request("GET", "/v1/health")
        self.assertEqual(code, 200)
        self.assertEqual(payload, {"status": "ok", "api_version": "0.2.0"})
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertNotIn(str(self.db), json.dumps(payload))

    def test_empty_database_means_real_zero_not_fabricated_samples(self):
        code, headers, payload = self.request("GET", "/v1/public/summary")
        self.assertEqual(code, 200)
        self.assertEqual(payload["counts"], {"agents": 0, "artifacts": 0, "experiments": 0, "receipts": 0})
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00")).utcoffset().total_seconds(), 0)
        self.assertEqual(headers["cache-control"], "public, max-age=15")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["vary"], "Origin")

    def test_published_only_and_withdrawn_excluded(self):
        self.publish("agents", "a1")
        self.publish("agents", "a2", "pending")
        self.publish("artifacts", "b1")
        self.publish("artifacts", "b2", withdrawn="2026-10-30T01:00:00Z")
        self.publish("receipts", "r1")
        self.assertEqual(published_counts(self.db), {"agents": 1, "artifacts": 1, "experiments": 0, "receipts": 1})
        _, _, data = self.request("GET", "/v1/public/summary")
        self.assertEqual(data["counts"], published_counts(self.db))

    def test_cors_explicit_allowlist_only(self):
        good = "https://qsolkcb.github.io"
        code, headers, _ = self.request("GET", "/v1/public/summary", headers={"Origin": good})
        self.assertEqual(code, 200)
        self.assertEqual(headers["access-control-allow-origin"], good)
        _, headers, _ = self.request("GET", "/v1/public/summary", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", headers)
        code, headers, _ = self.request("OPTIONS", "/v1/public/summary", headers={"Origin": good})
        self.assertEqual(code, 204)
        self.assertEqual(headers["access-control-allow-methods"], "GET, OPTIONS")
        code, headers, payload = self.request("OPTIONS", "/v1/public/summary", headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertEqual(payload["error"], "origin_not_allowed")

    def test_no_public_mutations_or_submission_api(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD"):
            with self.subTest(method=method):
                status, headers, payload = self.request(method, "/v1/public/summary", body="hello" if method == "POST" else None)
                self.assertEqual(status, 405)
                self.assertEqual(headers["allow"], "GET, OPTIONS")
        for method in ("GET", "POST"):
            status, _, _ = self.request(method, "/v1/submissions", body="x" if method == "POST" else None)
            self.assertNotEqual(status, 200)
            self.assertNotEqual(status, 202)
        self.assertEqual(published_counts(self.db)["agents"], 0)

    def test_ambiguous_path_and_get_with_body_are_rejected(self):
        for path in ("/v1/public/summary?all=true", "/v1/public/summary/", "/v1/public/summary%2F", "/.env"):
            self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("GET", "/v1/health", body="unauthorized")[0], 400)

    def test_kill_switch_fails_closed(self):
        self.server.disabled = True
        for path in ("/v1/health", "/v1/public/summary"):
            code, _, data = self.request("GET", path)
            self.assertEqual(code, 503)
            self.assertEqual(data["error"], "service_disabled")

    def test_missing_or_invalid_database_fails_closed(self):
        self.db.unlink()
        code, headers, data = self.request("GET", "/v1/public/summary")
        self.assertEqual(code, 503)
        self.assertEqual(data["error"], "service_unavailable")
        self.assertNotIn("database", json.dumps(data))
        init_db(self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA user_version=99")
        self.assertEqual(self.request("GET", "/v1/health")[0], 503)

    def test_rate_limit_is_enforced_and_forwarded_header_cannot_bypass(self):
        self.server.limiter = RateLimiter(limit=2)
        for _ in range(2):
            self.assertEqual(self.request("GET", "/v1/health")[0], 200)
        code, headers, data = self.request("GET", "/v1/health", headers={"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(code, 429)
        self.assertEqual(data["error"], "rate_limited")
        self.assertEqual(headers["cache-control"], "no-store")

    def test_init_db_refuses_overwrite_and_no_writes_during_serving(self):
        with self.assertRaises(FileExistsError):
            init_db(self.db)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM public_records").fetchone()[0], 0)

    def test_ipv4_loopback_keeps_ipv4_socket_family(self):
        self.assertEqual(self.server.address_family, socket.AF_INET)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.request("GET", "/v1/health")[0], 200)

    def test_ipv6_loopback_serves_health_and_summary_when_available(self):
        if not socket.has_ipv6:
            self.skipTest("This host has no IPv6 support")
        # Probe the operating system independently of the server code. Do not
        # skip an actual serve() failure: that was the original regression.
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("::1", 0))
            except OSError as exc:
                self.skipTest(f"IPv6 loopback is disabled on this host: {exc}")

        ipv6_server = serve(self.db, host="::1", port=0)
        self.assertEqual(ipv6_server.address_family, socket.AF_INET6)
        self.assertEqual(ipv6_server.server_address[0], "::1")
        thread = threading.Thread(target=ipv6_server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("::1", ipv6_server.server_port, timeout=3)
            try:
                conn.request("GET", "/v1/health")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["api_version"], "0.2.0")
                conn.request("GET", "/v1/public/summary")
            finally:
                conn.close()
            # The API still binds to the exact loopback host, never a wildcard.
            self.assertEqual(ipv6_server.server_address[0], "::1")
        finally:
            ipv6_server.shutdown()
            ipv6_server.server_close()
            thread.join(timeout=2)

    def test_non_loopback_rejected_and_origin_validation(self):
        with self.assertRaises(ValueError):
            serve(self.db, "0.0.0.0", 0)
        for url in ("http://qsolkcb.github.io", "https://qsolkcb.github.io/path", "https://user@qsolkcb.github.io", "*", "https://qsolkcb.github.io/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                allowed_origin(url)
        self.assertEqual(allowed_origin("https://qsolkcb.github.io"), "https://qsolkcb.github.io")


if __name__ == "__main__":
    unittest.main()
