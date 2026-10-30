"""Offline, human-gated artifact preparation, registration and takedown.

There is deliberately NO HTTP endpoint, GitHub push/merge, or automatic approval.
A local Git checkout's main ref is used as an offline *operator-side* review
assertion; it is not independent verification of GitHub's remote state.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

from . import intake

ARTIFACT_RE = re.compile(r"a_[a-f0-9]{32}\Z", re.ASCII)
COMMIT_RE = re.compile(r"[a-f0-9]{40}\Z", re.ASCII)
HEX64_RE = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)

MIGRATION = (
    """CREATE TABLE IF NOT EXISTS public_artifacts (
        artifact_id TEXT PRIMARY KEY REFERENCES public_records(record_id),
        submission_id TEXT NOT NULL UNIQUE,
        title TEXT,
        body TEXT,
        claimed_agent TEXT,
        source_sha256 TEXT NOT NULL,
        moderation_sha256 TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        receipt_id TEXT NOT NULL UNIQUE,
        review_commit TEXT NOT NULL,
        review_path TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS publication_receipts (
        receipt_id TEXT PRIMARY KEY REFERENCES public_records(record_id),
        artifact_id TEXT NOT NULL UNIQUE REFERENCES public_artifacts(artifact_id),
        receipt_sha256 TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        moderation_sha256 TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        review_commit TEXT NOT NULL,
        review_path TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS publication_takedowns (
        artifact_id TEXT PRIMARY KEY REFERENCES public_artifacts(artifact_id),
        withdrawn_at TEXT NOT NULL,
        reason TEXT NOT NULL
    )""",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _rw(path: Path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=3,
                         isolation_level=None)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        return db
    except BaseException:
        db.close()
        raise


def migrate_public(path: Path) -> None:
    """Operator-only, transactional additive migration of a preexisting v0.3 DB."""
    with closing(_rw(path)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("PRAGMA user_version").fetchone()[0]
            if current not in (1, 2):
                raise ValueError("Unknown public database version")
            db.execute("SELECT record_id FROM public_records LIMIT 0")
            for statement in MIGRATION:
                db.execute(statement)
            db.execute("PRAGMA user_version=2")
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise


def _approved(intake_path: Path, submission_id: str) -> tuple[dict, str, str]:
    if not re.fullmatch(r"[a-f0-9]{32}", submission_id):
        raise ValueError("Invalid submission ID")
    if not intake.verify_events(intake_path):
        raise ValueError("Quarantine moderation audit failed")
    with intake._connect(intake_path) as db:
        row = db.execute(
            "SELECT status,payload_json,payload_sha256 FROM submissions WHERE submission_id=?",
            (submission_id,)
        ).fetchone()
        event = db.execute(
            "SELECT decision,event_sha256 FROM moderation_events "
            "WHERE submission_id=? ORDER BY event_id DESC LIMIT 1", (submission_id,)
        ).fetchone()
    if row is None or event is None or row[0] != "approved" or event[0] != "approved" or row[1] is None:
        raise ValueError("Submission is not currently approved for staging")
    data = json.loads(row[1])
    canonical, digest = intake.validate_payload(row[1].encode("utf-8"))
    if canonical != row[1] or digest != row[2] or not HEX64_RE.fullmatch(event[1]):
        raise ValueError("Quarantined submission failed integrity check")
    return data, row[2], event[1]


def _manifest(submission_id: str, payload: dict, source: str, moderation: str) -> dict:
    return {
        "schema_version": 1,
        "artifact_id": "a_" + submission_id,
        "submission_id": submission_id,
        "kind": payload["kind"],
        "title": payload["title"],
        "body": payload["body"],
        "claimed_agent": payload.get("claimed_agent"),
        "identity_status": "self_reported",
        "source_sha256": source,
        "moderation_sha256": moderation,
        "publication_status": "candidate_unpublished",
    }


def _canonical(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def stage(intake_db: Path, checkout: Path, submission_id: str) -> Path:
    """Create a candidate manifest for a HUMAN-REVIEWED pull request; never commit it."""
    payload, digest, moderation = _approved(intake_db, submission_id)
    root = checkout.resolve(strict=True)
    target_dir = root / "artifactory" / "manifests"
    if not target_dir.is_dir() or target_dir.is_symlink() or target_dir.resolve() != target_dir:
        raise ValueError("Expected existing, non-symlink artifactory/manifests directory")
    target = target_dir / ("a_" + submission_id + ".json")
    if target.exists() or target.is_symlink():
        raise FileExistsError("Refusing to replace an artifact manifest")
    data = _canonical(_manifest(submission_id, payload, digest, moderation))
    if len(data) > 16384:
        raise ValueError("Manifest exceeds 16 KiB")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
    return target


def _git(checkout: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(checkout), *args],
                            capture_output=True, timeout=8, check=False)
    if result.returncode != 0:
        raise ValueError("Local Git review verification failed")
    return result.stdout


def _read_reviewed_manifest(checkout: Path, commit: str, artifact_id: str) -> tuple[dict, str]:
    if not COMMIT_RE.fullmatch(commit) or not ARTIFACT_RE.fullmatch(artifact_id):
        raise ValueError("Invalid commit or artifact identifier")
    root = checkout.resolve(strict=True)
    path = f"artifactory/manifests/{artifact_id}.json"
    # This is an assertion about the local checkout's main ref. A maintainer
    # must separately confirm the commit actually merged on remote GitHub.
    _git(root, "merge-base", "--is-ancestor", commit, "refs/heads/main")
    tree = _git(root, "ls-tree", commit, "--", path).decode("ascii", "strict")
    if not tree.startswith("100644 blob ") or not tree.rstrip().endswith("\t" + path):
        raise ValueError("Manifest must be a regular reviewed Git blob")
    data = _git(root, "show", f"{commit}:{path}")
    if not 1 <= len(data) <= 16384:
        raise ValueError("Reviewed manifest is oversized")
    try:
        item = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=intake._no_duplicate_keys)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("Invalid manifest JSON") from None
    if type(item) is not dict or set(item) != {
        "schema_version", "artifact_id", "submission_id", "kind", "title",
        "body", "claimed_agent", "identity_status", "source_sha256",
        "moderation_sha256", "publication_status"
    }:
        raise ValueError("Unexpected manifest schema")
    if data != _canonical(item):
        raise ValueError("Manifest must be canonical UTF-8 JSON")
    return item, hashlib.sha256(data).hexdigest()


def register(public_db: Path, intake_db: Path, checkout: Path, commit: str,
             artifact_id: str) -> dict:
    """Offline registration AFTER explicit human review and merge of a manifest."""
    item, manifest_hash = _read_reviewed_manifest(checkout, commit, artifact_id)
    payload, source, moderation = _approved(intake_db, item["submission_id"])
    if item != _manifest(item["submission_id"], payload, source, moderation):
        raise ValueError("Reviewed manifest differs from approved quarantine evidence")
    if item["artifact_id"] != artifact_id:
        raise ValueError("Mismatched artifact ID")
    receipt_id = "r_" + item["submission_id"]
    path = f"artifactory/manifests/{artifact_id}.json"
    with closing(_rw(public_db)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] != 2:
                raise ValueError("Public database needs explicit v0.4 migration")
            existing = db.execute("SELECT manifest_sha256,review_commit FROM public_artifacts "
                                  "WHERE artifact_id=?", (artifact_id,)).fetchone()
            if existing is not None:
                raise ValueError("Artifact already registered; no silent republishing")
            now = _utc()
            ref = f"github:QSOLKCB/ROGUE-AGENT@{commit}:{path}"
            for record_id, kind in ((artifact_id, "artifacts"), (receipt_id, "receipts")):
                db.execute("INSERT INTO public_records "
                           "(record_id,kind,publication_state,source_ref,published_at) "
                           "VALUES (?,?,'published',?,?)", (record_id, kind, ref, now))
            db.execute("INSERT INTO public_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (artifact_id, item["submission_id"], item["title"], item["body"],
                        item["claimed_agent"], source, moderation, manifest_hash,
                        receipt_id, commit, path))
            receipt = {"schema_version": 1, "artifact_id": artifact_id, "receipt_id": receipt_id,
                       "source_sha256": source, "moderation_sha256": moderation,
                       "manifest_sha256": manifest_hash, "review_commit": commit,
                       "review_path": path, "published_at": now}
            receipt_hash = hashlib.sha256(_canonical(receipt)).hexdigest()
            db.execute("INSERT INTO publication_receipts VALUES (?,?,?,?,?,?,?,?)",
                       (receipt_id, artifact_id, receipt_hash, source, moderation,
                        manifest_hash, commit, path))
            db.execute("COMMIT")
            return {"artifact_id": artifact_id, "receipt_id": receipt_id,
                    "receipt_sha256": receipt_hash, "published_at": now}
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise


def verify_receipt(public_db: Path, artifact_id: str, checkout: Path | None = None) -> bool:
    """Offline verification of stored receipt bytes, optionally against local Git."""
    if not ARTIFACT_RE.fullmatch(artifact_id):
        raise ValueError("Invalid artifact ID")
    with closing(_rw(public_db)) as db:
        row = db.execute(
            "SELECT p.receipt_id,p.source_sha256,p.moderation_sha256,"
            "p.manifest_sha256,p.review_commit,p.review_path,p.receipt_sha256,r.published_at,"
            "a.title,a.body,a.claimed_agent,ar.withdrawn_at "
            "FROM publication_receipts p JOIN public_records r ON r.record_id=p.receipt_id "
            "JOIN public_artifacts a ON a.artifact_id=p.artifact_id "
            "JOIN public_records ar ON ar.record_id=p.artifact_id "
            "WHERE p.artifact_id=?", (artifact_id,)
        ).fetchone()
    if row is None:
        return False
    (receipt_id, source, moderation, manifest, commit, path, recorded, published_at,
     stored_title, stored_body, stored_agent, withdrawn_at) = row
    candidate = {"schema_version": 1, "artifact_id": artifact_id, "receipt_id": receipt_id,
                 "source_sha256": source, "moderation_sha256": moderation,
                 "manifest_sha256": manifest, "review_commit": commit,
                 "review_path": path, "published_at": published_at}
    if hashlib.sha256(_canonical(candidate)).hexdigest() != recorded:
        return False
    if checkout is not None:
        try:
            item, observed_sha = _read_reviewed_manifest(checkout, commit, artifact_id)
        except (ValueError, OSError, subprocess.SubprocessError):
            return False
        if observed_sha != manifest or item["source_sha256"] != source or item["moderation_sha256"] != moderation:
            return False
        # Public text is an independently mutable DB copy. Compare it to the
        # reviewed Git blob while the record is active; withdrawals redact it.
        if withdrawn_at is None and (stored_title != item["title"] or
                                     stored_body != item["body"] or
                                     stored_agent != item["claimed_agent"]):
            return False
    return True


def withdraw(public_db: Path, artifact_id: str, reason: str) -> None:
    """Offline takedown: hide public API content; Git history needs separate handling."""
    if not ARTIFACT_RE.fullmatch(artifact_id):
        raise ValueError("Invalid artifact ID")
    if not 1 <= len(reason) <= 300 or any(ord(c) < 32 for c in reason):
        raise ValueError("A short private takedown reason is required")
    with closing(_rw(public_db)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            item = db.execute("SELECT receipt_id FROM public_artifacts WHERE artifact_id=?",
                              (artifact_id,)).fetchone()
            active = db.execute("SELECT withdrawn_at FROM public_records WHERE record_id=?",
                                (artifact_id,)).fetchone()
            if item is None or active is None or active[0] is not None:
                raise ValueError("Artifact is not active")
            now = _utc()
            db.execute("UPDATE public_records SET withdrawn_at=? WHERE record_id IN (?,?)",
                       (now, artifact_id, item[0]))
            db.execute("UPDATE public_artifacts SET body=NULL,title=NULL,claimed_agent=NULL "
                       "WHERE artifact_id=?", (artifact_id,))
            db.execute("INSERT INTO publication_takedowns VALUES (?,?,?)",
                       (artifact_id, now, reason))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline-only reviewed publication controls")
    subs = parser.add_subparsers(dest="action", required=True)
    migration = subs.add_parser("migrate")
    migration.add_argument("--public-db", type=Path, required=True)
    staged = subs.add_parser("stage")
    staged.add_argument("--intake-db", type=Path, required=True)
    staged.add_argument("--checkout", type=Path, required=True)
    staged.add_argument("--submission-id", required=True)
    registered = subs.add_parser("register")
    registered.add_argument("--public-db", type=Path, required=True)
    registered.add_argument("--intake-db", type=Path, required=True)
    registered.add_argument("--checkout", type=Path, required=True)
    registered.add_argument("--commit", required=True)
    registered.add_argument("--artifact-id", required=True)
    verified = subs.add_parser("verify")
    verified.add_argument("--public-db", type=Path, required=True)
    verified.add_argument("--artifact-id", required=True)
    verified.add_argument("--checkout", type=Path)
    withdrawn = subs.add_parser("withdraw")
    withdrawn.add_argument("--public-db", type=Path, required=True)
    withdrawn.add_argument("--artifact-id", required=True)
    withdrawn.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if args.action == "migrate":
        migrate_public(args.public_db)
        print("Public database migrated; no records published.")
    elif args.action == "stage":
        print("Candidate file (submit for review; NOT published):",
              stage(args.intake_db, args.checkout, args.submission_id))
    elif args.action == "register":
        print(json.dumps(register(args.public_db, args.intake_db, args.checkout,
                                  args.commit, args.artifact_id), sort_keys=True))
    elif args.action == "verify":
        ok = verify_receipt(args.public_db, args.artifact_id, args.checkout)
        print("Publication receipt:", "OK" if ok else "FAILED")
        if not ok:
            raise SystemExit(1)
    elif args.action == "withdraw":
        withdraw(args.public_db, args.artifact_id, args.reason)
        print("Public API withdrawal complete. GitHub history/caches require separate review.")


if __name__ == "__main__":
    main()
