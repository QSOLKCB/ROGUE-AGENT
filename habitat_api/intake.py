"""Quarantined submissions: explicit offline invitations and human review only.

This module never publishes records, runs contributions or accesses GitHub.
The intake database is separate from the read-only public-records database.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

MAX_BODY_BYTES = 16384
MAX_JSON_DEPTH = 64  # Fixed across Python versions; decoder recursion limits differ.
MAX_TOTAL_ROWS = 5000
MAX_PENDING_ROWS = 1000
KINDS = frozenset({"idea", "introduction", "artifact_proposal", "collaboration_proposal"})
KEY_RE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z", re.ASCII)
TOKEN_RE = re.compile(r"rg1_[A-Za-z0-9_-]{43}\Z", re.ASCII)
PRINCIPAL_RE = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z", re.ASCII)

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE invitations (
    token_digest TEXT PRIMARY KEY,
    principal TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    max_submissions INTEGER NOT NULL CHECK (max_submissions BETWEEN 1 AND 100),
    used_count INTEGER NOT NULL DEFAULT 0,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
);
CREATE TABLE submissions (
    submission_id TEXT PRIMARY KEY,
    token_digest TEXT NOT NULL REFERENCES invitations(token_digest),
    idempotency_key TEXT NOT NULL,
    payload_json TEXT,
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
    received_at TEXT NOT NULL,
    reviewed_at TEXT,
    UNIQUE(token_digest, idempotency_key)
);
CREATE INDEX pending_by_time ON submissions(status, received_at);
CREATE TABLE moderation_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL REFERENCES submissions(submission_id),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'withdrawn')),
    reason TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    previous_sha256 TEXT NOT NULL,
    event_sha256 TEXT NOT NULL
);
PRAGMA user_version=1;
"""


class IntakeError(Exception):
    def __init__(self, status: int, error: str):
        super().__init__(error)
        self.status, self.error = status, error


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@contextmanager
def _connect(path: Path):
    # mode=rw intentionally refuses missing databases; the web server never creates one.
    uri = path.resolve().as_uri() + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, timeout=2, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Unsupported intake schema")
        with conn:
            yield conn
    finally:
        conn.close()


def init_store(path: Path) -> None:
    path = path.resolve()
    if not path.parent.is_dir():
        raise ValueError("Intake database parent directory does not exist")
    if path.exists():
        raise FileExistsError("Refusing to overwrite an intake database")
    conn = sqlite3.connect(str(path), timeout=2)
    try:
        with conn:
            conn.executescript(SCHEMA)
    finally:
        conn.close()


def issue_invitation(path: Path, principal: str, *, hours: int = 24, limit: int = 10) -> str:
    if not PRINCIPAL_RE.fullmatch(principal) or not 1 <= hours <= 720 or not 1 <= limit <= 100:
        raise ValueError("Invalid principal, expiration or invitation quota")
    token = "rg1_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO invitations (token_digest, principal, expires_at, max_submissions) VALUES (?,?,?,?)",
            (digest, principal, int(time.time()) + hours * 3600, limit),
        )
    return token  # display exactly once in an operator-only shell; never log this on a server


def revoke_invitation(path: Path, principal: str) -> int:
    if not PRINCIPAL_RE.fullmatch(principal):
        raise ValueError("Invalid principal")
    with _connect(path) as conn:
        cursor = conn.execute("UPDATE invitations SET revoked=1 WHERE principal=? AND revoked=0", (principal,))
        return cursor.rowcount


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _check_json_depth(value) -> None:
    """Fail closed on deeply nested containers without recursive traversal.

    Some Python versions decode 1,100 nested arrays while others raise
    RecursionError. Enforce a stable application-level nesting limit.
    """
    pending = [(value, 1)]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise IntakeError(400, "invalid_json")
        if isinstance(node, dict):
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)


def validate_payload(body: bytes) -> tuple[str, str]:
    if not 1 <= len(body) <= MAX_BODY_BYTES:
        raise IntakeError(413, "invalid_body_size")
    try:
        payload = json.loads(
            body.decode("utf-8", "strict"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite number")),
        )
    except (UnicodeError, ValueError, RecursionError):
        # Deeply nested JSON can hit the interpreter recursion limit while
        # decoding even when the request is well below MAX_BODY_BYTES.
        raise IntakeError(400, "invalid_json") from None
    _check_json_depth(payload)
    if type(payload) is not dict or not {"schema_version", "kind", "title", "body"} <= payload.keys():
        raise IntakeError(422, "invalid_submission")
    if set(payload) - {"schema_version", "kind", "title", "body", "claimed_agent"}:
        raise IntakeError(422, "invalid_submission")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise IntakeError(422, "invalid_submission")
    if type(payload["kind"]) is not str or payload["kind"] not in KINDS:
        raise IntakeError(422, "invalid_submission")
    for key, size in (("title", 120), ("body", 8000), ("claimed_agent", 120)):
        if key not in payload:
            continue
        value = payload[key]
        if type(value) is not str or not (0 if key == "claimed_agent" else 1) <= len(value) <= size:
            raise IntakeError(422, "invalid_submission")
        if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
            raise IntakeError(422, "invalid_submission")
    try:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        canonical_bytes = canonical.encode("utf-8", "strict")
    except (ValueError, UnicodeError, RecursionError):
        raise IntakeError(422, "invalid_submission") from None
    return canonical, hashlib.sha256(canonical_bytes).hexdigest()


def submit(path: Path, token: str, idem_key: str, body: bytes) -> tuple[int, dict]:
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise IntakeError(401, "unauthorized")
    if not isinstance(idem_key, str) or not KEY_RE.fullmatch(idem_key):
        raise IntakeError(400, "invalid_idempotency_key")
    canonical, digest = validate_payload(body)
    token_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    try:
        with _connect(path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Exact indexed digest lookup; no token values persist in the DB.
            invitation = conn.execute(
                "SELECT token_digest, expires_at, max_submissions, used_count, revoked "
                "FROM invitations WHERE token_digest=?", (token_digest,)
            ).fetchone()
            if invitation is None or not hmac.compare_digest(invitation[0], token_digest):
                raise IntakeError(401, "unauthorized")
            if invitation[4] or invitation[1] <= int(time.time()):
                raise IntakeError(403, "invitation_inactive")
            existing = conn.execute(
                "SELECT submission_id, payload_sha256 FROM submissions "
                "WHERE token_digest=? AND idempotency_key=?", (token_digest, idem_key)
            ).fetchone()
            if existing:
                if not hmac.compare_digest(existing[1], digest):
                    raise IntakeError(409, "idempotency_conflict")
                return 202, {"schema_version": 1, "submission_id": existing[0], "status": "pending"}
            if invitation[3] >= invitation[2]:
                raise IntakeError(429, "invitation_quota_exceeded")
            counts = dict(conn.execute("SELECT status, COUNT(*) FROM submissions GROUP BY status").fetchall())
            if sum(counts.values()) >= MAX_TOTAL_ROWS or counts.get("pending", 0) >= MAX_PENDING_ROWS:
                raise IntakeError(503, "quarantine_capacity_exceeded")
            submission_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO submissions (submission_id,token_digest,idempotency_key,payload_json,payload_sha256,received_at) "
                "VALUES (?,?,?,?,?,?)",
                (submission_id, token_digest, idem_key, canonical, digest, _utc()),
            )
            conn.execute("UPDATE invitations SET used_count=used_count+1 WHERE token_digest=?", (token_digest,))
            return 202, {"schema_version": 1, "submission_id": submission_id, "status": "pending"}
    except sqlite3.Error:
        raise IntakeError(503, "intake_unavailable") from None


def pending_items(path: Path) -> list[dict]:
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT submission_id,received_at,payload_sha256,payload_json FROM submissions "
            "WHERE status='pending' ORDER BY received_at, submission_id LIMIT 100"
        ).fetchall()
    return [{"submission_id": row[0], "received_at": row[1],
             "payload_sha256": row[2], "payload": json.loads(row[3])} for row in rows]


def moderate(path: Path, submission_id: str, decision: str, reason: str) -> str:
    if decision not in ("approved", "rejected", "withdrawn"):
        raise ValueError("Unsupported moderation decision")
    if not re.fullmatch(r"[a-f0-9]{32}", submission_id):
        raise ValueError("Invalid submission ID")
    if not 1 <= len(reason) <= 300 or any(ord(c) < 32 and c not in "\t\n" for c in reason):
        raise ValueError("A short moderation rationale is required")
    with _connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM submissions WHERE submission_id=?", (submission_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown submission")
        if row[0] != "pending" and not (decision == "withdrawn" and row[0] in ("approved", "rejected")):
            raise ValueError("Submission has already been moderated")
        at = _utc()
        previous = conn.execute("SELECT event_sha256 FROM moderation_events ORDER BY event_id DESC LIMIT 1").fetchone()
        prev_hash = previous[0] if previous else "0" * 64
        canonical = json.dumps({"submission_id": submission_id, "decision": decision,
                                "reason": reason, "reviewed_at": at, "previous_sha256": prev_hash},
                               sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        conn.execute("UPDATE submissions SET status=?, reviewed_at=?, payload_json=CASE WHEN ?='withdrawn' THEN NULL ELSE payload_json END "
                     "WHERE submission_id=?", (decision, at, decision, submission_id))
        conn.execute("INSERT INTO moderation_events (submission_id,decision,reason,reviewed_at,previous_sha256,event_sha256) "
                     "VALUES (?,?,?,?,?,?)", (submission_id, decision, reason, at, prev_hash, event_hash))
        return event_hash


def verify_events(path: Path) -> bool:
    with _connect(path) as conn:
        events = conn.execute("SELECT submission_id,decision,reason,reviewed_at,previous_sha256,event_sha256 "
                              "FROM moderation_events ORDER BY event_id").fetchall()
    prev = "0" * 64
    for sub_id, decision, reason, at, stored_prev, stored_hash in events:
        canonical = json.dumps({"submission_id": sub_id, "decision": decision, "reason": reason,
                                "reviewed_at": at, "previous_sha256": prev},
                               sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if stored_prev != prev or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != stored_hash:
            return False
        prev = stored_hash
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline-only quarantine administration; never expose as HTTP")
    parser.add_argument("--db", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("init")
    invite = actions.add_parser("invite")
    invite.add_argument("--principal", required=True)
    invite.add_argument("--hours", type=int, default=24)
    invite.add_argument("--limit", type=int, default=10)
    revoke = actions.add_parser("revoke")
    revoke.add_argument("--principal", required=True)
    actions.add_parser("queue")
    review = actions.add_parser("moderate")
    review.add_argument("--id", required=True)
    review.add_argument("--decision", choices=("approved", "rejected", "withdrawn"), required=True)
    review.add_argument("--reason", required=True)
    actions.add_parser("verify")
    args = parser.parse_args(argv)
    if args.action == "init":
        init_store(args.db)
        print("Empty quarantine created; no invitations issued.")
    elif args.action == "invite":
        print(issue_invitation(args.db, args.principal, hours=args.hours, limit=args.limit))
    elif args.action == "revoke":
        print(f"Revoked {revoke_invitation(args.db, args.principal)} active invitations.")
    elif args.action == "queue":
        print(json.dumps(pending_items(args.db), ensure_ascii=True))
    elif args.action == "moderate":
        print("Moderation receipt SHA-256:", moderate(args.db, args.id, args.decision, args.reason))
    elif args.action == "verify":
        ok = verify_events(args.db)
        print("Moderation audit chain:", "OK" if ok else "FAILED")
        if not ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
