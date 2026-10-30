"""v0.4 offline-to-Git review boundary and HTTP public-catalog integration tests."""
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest

from habitat_api import intake, publication, catalog
from habitat_api.server import init_db, published_counts, serve


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.public = root / "public.sqlite"
        self.private = root / "quarantine.sqlite"
        init_db(self.public)
        intake.init_store(self.private)
        self.token = intake.issue_invitation(self.private, "integration_agent")
        self.payload = {
            "schema_version": 1, "kind": "artifact_proposal",
            "title": "Original proposal",
            "body": "Plain text: <img src=x onerror=alert(1)>",
            "claimed_agent": "Unverified visitor"
        }
        self.repo = root / "repo"
        self.repo.mkdir()
        (self.repo / "artifactory" / "manifests").mkdir(parents=True)
        (self.repo / "artifactory" / "manifests" / ".gitkeep").write_text("")
        self.git_available = shutil.which("git") is not None
        if self.git_available:
            self.git("init", "-b", "main")
            self.git("config", "user.name", "Local Test")
            self.git("config", "user.email", "local@example.invalid")
            self.git("add", ".")
            self.git("commit", "-m", "initialize reviewed source")
            self.initial_commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args],
                                capture_output=True, timeout=5)
        if result.returncode != 0:
            self.fail(f"Fixture git command failed: {args}: {result.stderr!r}")
        return result.stdout.decode("utf-8").strip()

    def approve(self):
        raw = json.dumps(self.payload).encode("utf-8")
        _, response = intake.submit(self.private, self.token, "review-test-key-0123456789", raw)
        sid = response["submission_id"]
        intake.moderate(self.private, sid, "approved", "Human review for local fixture")
        return sid

    def reviewed(self, sid):
        if not self.git_available:
            self.skipTest("git command not installed")
        path = publication.stage(self.private, self.repo, sid)
        self.git("add", str(path.relative_to(self.repo)))
        self.git("commit", "-m", "Human-reviewed fixture manifest")
        return self.git("rev-parse", "HEAD")

    def test_catalog_requires_explicit_migration(self):
        with self.assertRaises(ValueError):
            catalog.list_records(self.public, "artifacts")
        self.assertEqual(published_counts(self.public)["artifacts"], 0)
        publication.migrate_public(self.public)
        publication.migrate_public(self.public)
        self.assertEqual(catalog.list_records(self.public, "artifacts"),
                         {"schema_version": 1, "items": [], "next_cursor": None})
        self.assertEqual(published_counts(self.public)["receipts"], 0)

    def test_moderation_approval_is_not_publication(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        self.assertEqual(catalog.list_records(self.public, "artifacts")["items"], [])
        self.assertEqual(published_counts(self.public)["artifacts"], 0)
        self.assertEqual(intake.pending_items(self.private), [])
        self.assertTrue(intake.verify_events(self.private))
        self.assertEqual(len(sid), 32)

    def test_stage_requires_approved_submissions(self):
        raw = json.dumps(self.payload).encode()
        _, response = intake.submit(self.private, self.token, "review-test-key-0123456789", raw)
        with self.assertRaises(ValueError):
            publication.stage(self.private, self.repo, response["submission_id"])

    def test_reviewed_publication_and_receipt_integrity(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        commit = self.reviewed(sid)
        output = publication.register(self.public, self.private, self.repo, commit, "a_" + sid)
        self.assertEqual(output["artifact_id"], "a_" + sid)
        self.assertEqual(output["receipt_id"], "r_" + sid)
        self.assertEqual(len(output["receipt_sha256"]), 64)
        self.assertTrue(publication.verify_receipt(self.public, "a_" + sid, self.repo))
        self.assertEqual(published_counts(self.public)["artifacts"], 1)
        self.assertEqual(published_counts(self.public)["receipts"], 1)
        artifact = catalog.get_record(self.public, "artifacts", "a_" + sid)["item"]
        self.assertEqual(artifact["body"], self.payload["body"])
        self.assertEqual(artifact["identity_status"], "self_reported")
        self.assertEqual(artifact["review_commit"], commit)
        self.assertEqual(catalog.get_record(self.public, "receipts", "r_" + sid)["item"]["receipt_sha256"],
                         output["receipt_sha256"])
        self.assertEqual(catalog.list_records(self.public, "artifacts")["items"][0]["id"], "a_" + sid)
        self.assertEqual(catalog.list_records(self.public, "receipts")["items"][0]["id"], "r_" + sid)
        with self.assertRaises(ValueError):
            publication.register(self.public, self.private, self.repo, commit, "a_" + sid)

    def test_tampered_receipt_hash_is_detected(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        commit = self.reviewed(sid)
        publication.register(self.public, self.private, self.repo, commit, "a_" + sid)
        self.assertTrue(publication.verify_receipt(self.public, "a_" + sid))
        with sqlite3.connect(self.public) as db:
            db.execute("UPDATE publication_receipts SET receipt_sha256=?", ("f" * 64,))
        self.assertFalse(publication.verify_receipt(self.public, "a_" + sid))

    def test_public_database_body_tampering_is_detected_against_git(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        commit = self.reviewed(sid)
        publication.register(self.public, self.private, self.repo, commit, "a_" + sid)
        self.assertTrue(publication.verify_receipt(self.public, "a_" + sid, self.repo))
        with sqlite3.connect(self.public) as db:
            db.execute("UPDATE public_artifacts SET body=? WHERE artifact_id=?",
                       ("tampered post-publication", "a_" + sid))
        self.assertFalse(publication.verify_receipt(self.public, "a_" + sid, self.repo))

    def test_invalid_review_commit_cannot_register(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        self.reviewed(sid)
        with self.assertRaises(ValueError):
            publication.register(self.public, self.private, self.repo,
                                 "not-a-commit", "a_" + sid)
        self.assertEqual(published_counts(self.public)["artifacts"], 0)

    def test_unmerged_candidate_cannot_register(self):
        if not self.git_available:
            self.skipTest("git command not installed")
        sid = self.approve()
        publication.migrate_public(self.public)
        publication.stage(self.private, self.repo, sid)
        with self.assertRaises(ValueError):
            publication.register(self.public, self.private, self.repo, self.initial_commit, "a_" + sid)
        self.assertEqual(published_counts(self.public)["artifacts"], 0)

    def test_non_main_branch_is_not_accepted_as_reviewed(self):
        if not self.git_available:
            self.skipTest("git command not installed")
        sid = self.approve()
        publication.migrate_public(self.public)
        publication.stage(self.private, self.repo, sid)
        self.git("checkout", "-b", "unreviewed")
        self.git("add", ".")
        self.git("commit", "-m", "unreviewed candidate")
        other_sha = self.git("rev-parse", "HEAD")
        with self.assertRaises(ValueError):
            publication.register(self.public, self.private, self.repo, other_sha, "a_" + sid)

    def test_manifest_tampering_fails_closed(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        if not self.git_available:
            self.skipTest("git command not installed")
        path = publication.stage(self.private, self.repo, sid)
        data = json.loads(path.read_text())
        data["title"] = "Tampered proposal"
        path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
        self.git("add", ".")
        self.git("commit", "-m", "tampered fixture")
        with self.assertRaises(ValueError):
            publication.register(self.public, self.private, self.repo,
                                 self.git("rev-parse", "HEAD"), "a_" + sid)

    def test_changed_moderation_blocks_registration(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        commit = self.reviewed(sid)
        intake.moderate(self.private, sid, "withdrawn", "Revoked before publication")
        with self.assertRaises(ValueError):
            publication.register(self.public, self.private, self.repo, commit, "a_" + sid)

    def test_public_takedown_hides_and_redacts_public_api(self):
        sid = self.approve()
        publication.migrate_public(self.public)
        commit = self.reviewed(sid)
        publication.register(self.public, self.private, self.repo, commit, "a_" + sid)
        publication.withdraw(self.public, "a_" + sid, "Operator takedown test")
        self.assertEqual(published_counts(self.public)["artifacts"], 0)
        self.assertEqual(published_counts(self.public)["receipts"], 0)
        self.assertEqual(catalog.list_records(self.public, "artifacts")["items"], [])
        self.assertEqual(catalog.list_records(self.public, "receipts")["items"], [])
        for kind, identifier in (("artifacts", "a_" + sid), ("receipts", "r_" + sid)):
            with self.assertRaises(catalog.CatalogError) as exc:
                catalog.get_record(self.public, kind, identifier)
            self.assertEqual(exc.exception.status, 404)
        with sqlite3.connect(self.public) as db:
            self.assertEqual(db.execute("SELECT body FROM public_artifacts").fetchone()[0], None)
        with self.assertRaises(ValueError):
            publication.withdraw(self.public, "a_" + sid, "duplicate")
        with self.assertRaises(ValueError):
            publication.register(self.public, self.private, self.repo, commit, "a_" + sid)

    def test_keyset_pagination_and_rejected_cursors(self):
        publication.migrate_public(self.public)
        with sqlite3.connect(self.public) as db:
            for i in range(4):
                db.execute("INSERT INTO public_records "
                           "(record_id,kind,publication_state,source_ref,published_at) "
                           "VALUES (?, 'agents', 'published', ?, ?)",
                           (f"g_{i:032x}", "reviewed:local", "2026-10-30T00:00:00Z"))
        first = catalog.list_records(self.public, "agents", limit=2)
        self.assertEqual(len(first["items"]), 2)
        second = catalog.list_records(self.public, "agents", limit=2, after=first["next_cursor"])
        self.assertEqual(len(second["items"]), 2)
        self.assertIsNone(second["next_cursor"])
        self.assertTrue(set(i["id"] for i in first["items"]).isdisjoint(
            i["id"] for i in second["items"]))
        for bad in ("../etc", "", "bad cursor", "a" * 81):
            with self.assertRaises(catalog.CatalogError):
                catalog.list_records(self.public, "agents", after=bad)

    def test_http_catalog_contract_and_no_writes(self):
        publication.migrate_public(self.public)
        server = serve(self.public, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(method, path, headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    conn.request(method, path, headers=headers or {})
                    resp = conn.getresponse()
                    raw = resp.read()
                    return resp.status, dict((k.lower(), v) for k,v in resp.getheaders()), json.loads(raw) if raw else None
                finally:
                    conn.close()
            status, headers, payload = request("GET", "/v1/artifacts?limit=20",
                {"Origin":"https://qsolkcb.github.io"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["items"], [])
            self.assertEqual(headers["access-control-allow-origin"], "https://qsolkcb.github.io")
            for path in ("/v1/artifacts?limit=0", "/v1/receipts?limit=999",
                         "/v1/artifacts?limit=2&limit=3", "/v1/agents?unexpected=1"):
                self.assertEqual(request("GET", path)[0], 400)
            self.assertEqual(request("GET", "/v1/artifacts/a_" + "f"*32)[0], 404)
            status, headers, _ = request("POST", "/v1/artifacts")
            self.assertEqual((status, headers["allow"]), (405, "GET, OPTIONS"))
            self.assertEqual(request("OPTIONS", "/v1/artifacts",
                             {"Origin":"https://qsolkcb.github.io"})[0], 204)
            self.assertEqual(request("GET", "/v1/health")[2]["api_version"], "0.4.0")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

if __name__ == "__main__":
    unittest.main()
