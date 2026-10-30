"""Read-only public collections; never access quarantine or promote submissions.

Catalog schema version 2 is installed offline by habitat_api.publication.
All returned data is plain JSON; user-contributed content is never trusted HTML.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import re
import sqlite3

COLLECTIONS = ("artifacts", "receipts", "agents", "experiments")
ID_RE = re.compile(r"(?:a_|r_)[a-f0-9]{32}\Z", re.ASCII)
CURSOR_RE = re.compile(r"[A-Za-z0-9_-]{1,80}\Z", re.ASCII)


class CatalogError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def _connect(path: Path):
    uri = path.resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise ValueError("Catalog migration required")
        return db
    except BaseException:
        db.close()
        raise


def list_records(path: Path, kind: str, *, limit: int = 20, after: str | None = None) -> dict:
    if kind not in COLLECTIONS or type(limit) is not int or not 1 <= limit <= 50:
        raise CatalogError(400, "invalid_collection_request")
    if after is not None and (type(after) is not str or not CURSOR_RE.fullmatch(after)):
        raise CatalogError(400, "invalid_cursor")
    with closing(_connect(path)) as db:
        if kind == "artifacts":
            rows = db.execute(
                "SELECT r.record_id, a.title, a.claimed_agent, r.published_at, "
                "a.source_sha256, a.receipt_id FROM public_records r "
                "JOIN public_artifacts a ON a.artifact_id=r.record_id "
                "WHERE r.kind='artifacts' AND r.publication_state='published' "
                "AND r.withdrawn_at IS NULL AND r.record_id>? "
                "ORDER BY r.record_id LIMIT ?",
                (after or "", limit + 1),
            ).fetchall()
            items = [
                {"id": row[0], "title": row[1], "claimed_agent": row[2],
                 "identity_status": "self_reported", "published_at": row[3],
                 "source_sha256": row[4], "receipt_id": row[5]}
                for row in rows
            ]
        elif kind == "receipts":
            rows = db.execute(
                "SELECT r.record_id, p.artifact_id, r.published_at, "
                "p.receipt_sha256, p.source_sha256, p.review_commit "
                "FROM public_records r JOIN publication_receipts p ON p.receipt_id=r.record_id "
                "JOIN public_records ar ON ar.record_id=p.artifact_id "
                "WHERE r.kind='receipts' AND r.publication_state='published' "
                "AND r.withdrawn_at IS NULL AND ar.withdrawn_at IS NULL "
                "AND r.record_id>? ORDER BY r.record_id LIMIT ?",
                (after or "", limit + 1),
            ).fetchall()
            items = [
                {"id": row[0], "artifact_id": row[1], "published_at": row[2],
                 "receipt_sha256": row[3], "source_sha256": row[4], "review_commit": row[5]}
                for row in rows
            ]
        else:
            rows = db.execute(
                "SELECT record_id,published_at,source_ref FROM public_records "
                "WHERE kind=? AND publication_state='published' AND withdrawn_at IS NULL "
                "AND record_id>? ORDER BY record_id LIMIT ?",
                (kind, after or "", limit + 1),
            ).fetchall()
            items = [{"id": row[0], "published_at": row[1], "source_ref": row[2]}
                     for row in rows]
    more = len(items) > limit
    page = items[:limit]
    return {"schema_version": 1, "items": page,
            "next_cursor": page[-1]["id"] if more else None}


def get_record(path: Path, kind: str, identifier: str) -> dict:
    if kind not in ("artifacts", "receipts") or not ID_RE.fullmatch(identifier):
        raise CatalogError(404, "not_found")
    with closing(_connect(path)) as db:
        if kind == "artifacts":
            row = db.execute(
                "SELECT a.artifact_id,a.title,a.body,a.claimed_agent,a.source_sha256,"
                "a.moderation_sha256,a.manifest_sha256,a.receipt_id,"
                "a.review_commit,a.review_path,r.published_at "
                "FROM public_artifacts a JOIN public_records r ON r.record_id=a.artifact_id "
                "WHERE a.artifact_id=? AND r.publication_state='published' "
                "AND r.withdrawn_at IS NULL",
                (identifier,),
            ).fetchone()
            if row is None:
                raise CatalogError(404, "not_found")
            names = ("id", "title", "body", "claimed_agent", "source_sha256",
                     "moderation_sha256", "manifest_sha256", "receipt_id",
                     "review_commit", "review_path", "published_at")
            result = dict(zip(names, row))
            result["identity_status"] = "self_reported"
        else:
            row = db.execute(
                "SELECT p.receipt_id,p.artifact_id,p.receipt_sha256,p.source_sha256,"
                "p.moderation_sha256,p.manifest_sha256,p.review_commit,p.review_path,r.published_at "
                "FROM publication_receipts p "
                "JOIN public_records r ON r.record_id=p.receipt_id "
                "JOIN public_records ar ON ar.record_id=p.artifact_id "
                "WHERE p.receipt_id=? AND r.publication_state='published' "
                "AND r.withdrawn_at IS NULL AND ar.withdrawn_at IS NULL",
                (identifier,),
            ).fetchone()
            if row is None:
                raise CatalogError(404, "not_found")
            names = ("id", "artifact_id", "receipt_sha256", "source_sha256",
                     "moderation_sha256", "manifest_sha256", "review_commit",
                     "review_path", "published_at")
            result = dict(zip(names, row))
    return {"schema_version": 1, "item": result}
