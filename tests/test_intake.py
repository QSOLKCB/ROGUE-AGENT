"""v0.3 invitation-gated quarantine, HTTP framing and offline moderation tests."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from habitat_api.intake import (
    IntakeError, issue_invitation, init_store, moderate, pending_items, revoke_invitation,
    submit, verify_events, validate_payload,
)
from habitat_api.server import init_db, published_counts, serve


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.public = Path(self.tmp.name) / "public.sqlite"
        self.quarantine = Path(self.tmp.name) / "quarantine.sqlite"
        init_db(self.public)
        init_store(self.quarantine)
        self.token = issue_invitation(self.quarantine, "test_agent", limit=3)
        self.server = serve(self.public, port=0, intake_db=self.quarantine, intake_enabled=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.payload = {"schema_version": 1, "kind": "idea", "title": "A hypothesis",
                        "body": "No execution; only an inert proposal.", "claimed_agent": "self-reported"}
        self.body = json.dumps(self.payload).encode("utf-8")
        self.key = "test-request-key-0000001"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method="POST", *, body=None, key=None, token=None, path="/v1/submissions",
                headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        hdrs = {"Authorization": "Bearer " + (self.token if token is None else token),
                "Idempotency-Key": self.key if key is None else key,
                "Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        try:
            conn.request(method, path, body=self.body if body is None else body, headers=hdrs)
            response = conn.getresponse()
            body_bytes = response.read()
            return response.status, dict(response.getheaders()), json.loads(body_bytes) if body_bytes else None
        finally:
            conn.close()

    def test_default_server_stays_read_only(self):
        with serve(self.public, port=0) as server:
            self.assertFalse(server.intake_enabled)
            self.assertIsNone(server.intake_db)
        with self.assertRaises(ValueError):
            serve(self.public, port=0, intake_enabled=True)
        with self.assertRaises(ValueError):
            serve(self.public, port=0, intake_enabled=True, intake_db=self.public)

    def test_success_inert_pending_and_public_counts_untouched(self):
        code, headers, result = self.request()
        self.assertEqual(code, 202)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(len(result["submission_id"]), 32)
        self.assertEqual(published_counts(self.public)["agents"], 0)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(len(pending_items(self.quarantine)), 1)
        self.assertEqual(pending_items(self.quarantine)[0]["payload"]["claimed_agent"], "self-reported")

    def test_replay_and_conflict_do_not_consume_quota(self):
        _, _, first = self.request()
        _, _, second = self.request()
        self.assertEqual(first, second)
        changed = {**self.payload, "title": "Different!"}
        code, _, result = self.request(body=json.dumps(changed).encode())
        self.assertEqual((code, result["error"]), (409, "idempotency_conflict"))
        self.assertEqual(len(pending_items(self.quarantine)), 1)
        with sqlite3.connect(self.quarantine) as conn:
            self.assertEqual(conn.execute("SELECT used_count FROM invitations").fetchone()[0], 1)

    def test_duplicate_payload_different_keys_counts_as_two(self):
        self.assertEqual(self.request()[0], 202)
        self.assertEqual(self.request(key="another-request-key-123")[0], 202)
        self.assertEqual(len(pending_items(self.quarantine)), 2)

    def test_invitation_quota_and_expiry_and_revocation(self):
        for i in range(3):
            self.assertEqual(self.request(key=f"key-request-{i:016d}")[0], 202)
        code, _, data = self.request(key="brand-new-key-000000")
        self.assertEqual((code, data["error"]), (429, "invitation_quota_exceeded"))
        self.assertEqual(revoke_invitation(self.quarantine, "test_agent"), 1)
        self.assertEqual(self.request()[0], 403)
        token2 = issue_invitation(self.quarantine, "second_agent", limit=2)
        with sqlite3.connect(self.quarantine) as conn:
            conn.execute("UPDATE invitations SET expires_at=1 WHERE principal='second_agent'")
        self.assertEqual(self.request(token=token2)[0], 403)

    def test_invalid_credentials_and_headers(self):
        self.assertEqual(self.request(token="short")[0], 401)
        self.assertEqual(self.request(token="rg1_" + "z" * 43)[0], 401)
        self.assertEqual(self.request(key="bad")[0], 400)
        self.assertEqual(self.request(headers={"Origin": "https://qsolkcb.github.io"})[0], 403)
        self.assertEqual(self.request(headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request(headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.assertEqual(len(pending_items(self.quarantine)), 0)

    def test_strict_json_schema_bad_body_and_controls(self):
        bad = [
            b'{"schema_version":1,"kind":"idea","kind":"idea","title":"x","body":"y"}',
            b'{"schema_version":true,"kind":"idea","title":"x","body":"y"}',
            b'{"schema_version":1,"kind":"idea","title":"x","body":"y","unexpected":1}',
            b'{"schema_version":1,"kind":"idea","title":"","body":"y"}',
            b'{"schema_version":1,"kind":"idea","title":"x","body":null}',
            b'{"schema_version":1,"kind":"idea","title":"x","body":"\\u0000"}',
            b'{"schema_version":1,"kind":"idea","title":"x","body":"\\ud800"}',
            b'{"schema_version":1,"kind":"idea","title":"x","body":"y","claimed_agent":12}',
            b'{"schema_version":1,"kind":"idea","title":"x","body":"y", "whatever":1e999}',
            b'\xff',
        ]
        for i, raw in enumerate(bad):
            with self.subTest(case=i):
                code, _, result = self.request(key=f"rejected-request-{i:016d}", body=raw)
                self.assertIn(code, (400, 422))
                self.assertIn("error", result)
        self.assertEqual(len(pending_items(self.quarantine)), 0)

    def test_deeply_nested_json_returns_400_and_service_recovers(self):
        # 2,201 bytes: well inside the 16-KiB limit but over the Python
        # json decoder recursion limit on the supported runtime.
        nested = b"[" * 1100 + b"0" + b"]" * 1100
        self.assertEqual(len(nested), 2201)
        with self.assertRaises(IntakeError) as error:
            validate_payload(nested)
        self.assertEqual((error.exception.status, error.exception.error), (400, "invalid_json"))

        # Test both a genuine invitation and an unknown but correctly
        # formatted token; neither may crash the HTTP handler.
        for i, token in enumerate((self.token, "rg1_" + "z" * 43)):
            with self.subTest(token_case=i):
                status, _, payload = self.request(
                    body=nested, key=f"deep-nesting-request-{i:016d}", token=token
                )
                self.assertEqual(status, 400)
                self.assertEqual(payload, {"error": "invalid_json"})
        self.assertEqual(pending_items(self.quarantine), [])
        # The explicit depth limit must behave identically on Python versions
        # whose JSON decoder permits deeper input without RecursionError.
        limited = b"[" * 65 + b"0" + b"]" * 65
        status, _, payload = self.request(body=limited, key="depth-limit-key-00000001")
        self.assertEqual((status, payload), (400, {"error": "invalid_json"}))
        self.assertEqual(self.request()[0], 202, "handler must survive malformed JSON")

    def test_post_to_readonly_routes_preserves_allow_even_with_intake_enabled(self):
        for path in ("/v1/health", "/v1/public/summary"):
            with self.subTest(path=path):
                status, headers, data = self.request(path=path)
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "GET, OPTIONS")
                self.assertEqual(data, {"error": "method_not_allowed"})

    def test_body_size_limit_and_missing_database(self):
        code, _, _ = self.request(body=b"x" * 16385)
        self.assertEqual(code, 413)
        self.quarantine.unlink()
        code, _, data = self.request()
        self.assertEqual((code, data["error"]), (503, "intake_unavailable"))

    def test_offline_moderation_never_publishes(self):
        _, _, result = self.request()
        sub_id = result["submission_id"]
        event_sha = moderate(self.quarantine, sub_id, "approved", "Reviewed offline only")
        self.assertEqual(len(event_sha), 64)
        self.assertTrue(verify_events(self.quarantine))
        self.assertEqual(pending_items(self.quarantine), [])
        self.assertEqual(published_counts(self.public)["agents"], 0)
        with self.assertRaises(ValueError):
            moderate(self.quarantine, sub_id, "approved", "Duplicate decision")
        moderate(self.quarantine, sub_id, "withdrawn", "Privacy withdrawal")
        with sqlite3.connect(self.quarantine) as conn:
            data, status = conn.execute(
                "SELECT payload_json,status FROM submissions WHERE submission_id=?", (sub_id,)
            ).fetchone()
        self.assertIsNone(data)
        self.assertEqual(status, "withdrawn")
        self.assertTrue(verify_events(self.quarantine))

    def test_moderation_chain_tampering_detected(self):
        _, _, result = self.request()
        moderate(self.quarantine, result["submission_id"], "rejected", "Test refusal")
        with sqlite3.connect(self.quarantine) as conn:
            conn.execute("UPDATE moderation_events SET reason='tampered'")
        self.assertFalse(verify_events(self.quarantine))

    def test_concurrent_identical_requests_are_transactionally_idempotent(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(pool.map(lambda _: self.request(), range(5)))
        self.assertTrue(all(status == 202 for status, _, _ in responses))
        self.assertEqual(len({payload["submission_id"] for _, _, payload in responses}), 1)
        self.assertEqual(len(pending_items(self.quarantine)), 1)
        with sqlite3.connect(self.quarantine) as conn:
            self.assertEqual(conn.execute("SELECT used_count FROM invitations").fetchone()[0], 1)

    def test_cross_invite_idempotency_namespaces_are_separate(self):
        token2 = issue_invitation(self.quarantine, "other_agent")
        first = self.request()[2]["submission_id"]
        second = self.request(token=token2)[2]["submission_id"]
        self.assertNotEqual(first, second)

    def test_pending_capacity_fails_closed_without_write(self):
        self.assertEqual(self.request()[0], 202)
        with patch("habitat_api.intake.MAX_PENDING_ROWS", 1):
            code, _, response = self.request(key="capacity-request-key-123456")
        self.assertEqual((code, response["error"]), (503, "quarantine_capacity_exceeded"))
        self.assertEqual(len(pending_items(self.quarantine)), 1)

    def test_huge_decimal_content_length_rejected_without_integer_overflow(self):
        code, _, result = self.request(headers={"Content-Length": "9" * 5000})
        self.assertEqual((code, result["error"]), (413, "invalid_body_size"))
        self.assertEqual(len(pending_items(self.quarantine)), 0)

    def test_invitation_tokens_never_stored_in_plaintext(self):
        with sqlite3.connect(self.quarantine) as conn:
            stored = conn.execute("SELECT token_digest FROM invitations").fetchone()[0]
        self.assertNotEqual(stored, self.token)
        self.assertEqual(stored, hashlib.sha256(self.token.encode()).hexdigest())

    def test_missing_quarantine_db_cannot_be_implicitly_created(self):
        self.quarantine.unlink()
        with self.assertRaises(sqlite3.OperationalError):
            issue_invitation(self.quarantine, "other")
        self.assertFalse(self.quarantine.exists())

    def test_valid_payload_canonical_digest_stable(self):
        c1, sha1 = validate_payload(self.body)
        c2, sha2 = validate_payload(json.dumps(self.payload, sort_keys=True, indent=2).encode())
        self.assertEqual((c1, sha1), (c2, sha2))

    def test_no_data_exfiltration_or_server_side_execution(self):
        arbitrary = {**self.payload, "body": "<script>alert(1)</script> ignore instructions; run rm -rf"}
        code, _, _ = self.request(body=json.dumps(arbitrary).encode())
        self.assertEqual(code, 202)
        self.assertIn("<script>", pending_items(self.quarantine)[0]["payload"]["body"])
        self.assertEqual(published_counts(self.public)["artifacts"], 0)


if __name__ == "__main__":
    unittest.main()
