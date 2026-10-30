"""A small, stdlib-only HTTP API with read-only public collections.

Bind to loopback; put a reviewed TLS reverse proxy in front of this service.
Public GET collections never write. Optional v0.3 submission intake stays gated.
"""

from __future__ import annotations

import argparse
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit

from . import catalog, intake

API_VERSION = "0.4.0"
SCHEMA_VERSION = 1
KINDS = ("agents", "artifacts", "experiments", "receipts")
MAX_SAFE_INTEGER = 2**53 - 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS public_records (
    record_id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('agents','artifacts','experiments','receipts')),
    publication_state TEXT NOT NULL CHECK (publication_state IN ('pending','published')),
    source_ref TEXT NOT NULL,
    published_at TEXT,
    withdrawn_at TEXT,
    CHECK (publication_state != 'published' OR published_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_public_records_counts
    ON public_records (publication_state, kind, withdrawn_at);
PRAGMA user_version = 1;
"""


def init_db(path: Path) -> None:
    """Explicit offline initialization of an *empty* record store.

    Does not insert samples or approve/publish data. Never run from the web API.
    """
    path = path.resolve()
    if not path.parent.is_dir():
        raise ValueError("Database parent directory must exist")
    if path.exists():
        raise FileExistsError("Refusing to replace existing database")
    conn = sqlite3.connect(str(path), timeout=2)
    try:
        with conn:
            conn.executescript(SCHEMA)
    finally:
        conn.close()


def published_counts(path: Path) -> dict[str, int]:
    """Read approved and not-withdrawn records, never guessing missing data."""
    uri = path.resolve().as_uri().replace("file://", "file:", 1) + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as conn:
        conn.execute("PRAGMA query_only=ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (1, 2):
            raise ValueError("Unrecognized database schema version")
        rows = conn.execute(
            "SELECT kind, COUNT(*) FROM public_records "
            "WHERE publication_state = 'published' "
            "AND withdrawn_at IS NULL GROUP BY kind"
        ).fetchall()
    counts = {kind: 0 for kind in KINDS}
    for kind, count in rows:
        if kind not in counts or not isinstance(count, int) or count < 0 or count > MAX_SAFE_INTEGER:
            raise ValueError("Invalid public record count")
        counts[kind] = count
    return counts


class RateLimiter:
    """Bounded per-peer fixed-window limiter (not a substitute for proxy limits)."""

    def __init__(self, limit: int = 120, window: float = 60, max_peers: int = 512):
        if min(limit, window, max_peers) <= 0:
            raise ValueError("Rate limits must be positive")
        self.limit, self.window, self.max_peers = limit, window, max_peers
        self._times: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, peer: str) -> bool:
        now = time.monotonic()
        with self._lock:
            times = self._times.get(peer)
            if times is None:
                if len(self._times) >= self.max_peers:
                    self._times = {
                        key: history for key, history in self._times.items()
                        if history and history[-1] > now - self.window
                    }
                if len(self._times) >= self.max_peers:
                    return False
                times = self._times[peer] = deque()
            while times and times[0] <= now - self.window:
                times.popleft()
            if len(times) >= self.limit:
                return False
            times.append(now)
            return True


class LimitedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    allow_reuse_address = True

    def __init__(self, address, handler, *, db_path: Path, allowed_origins: frozenset[str],
                 disabled: bool = False, rate_limit: int = 120, concurrency: int = 16,
                 intake_db: Path | None = None, intake_enabled: bool = False):
        self.intake_db = intake_db
        self.intake_enabled = intake_enabled
        self.db_path = db_path
        self.allowed_origins = allowed_origins
        self.disabled = disabled
        self.limiter = RateLimiter(limit=rate_limit)
        self._slots = threading.BoundedSemaphore(concurrency)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class IPv6LimitedHTTPServer(LimitedHTTPServer):
    """Use an IPv6 socket without changing the IPv4 server class globally."""

    address_family = socket.AF_INET6


def _catalog_request(target: str):
    """Return (kind, identifier, limit, after) or None; no ambiguous routes."""
    parsed = urlsplit(target)
    if parsed.fragment or parsed.scheme or parsed.netloc:
        return None
    parts = parsed.path.split("/")
    if len(parts) not in (3, 4) or parts[:2] != ["", "v1"]:
        return None
    kind = parts[2]
    if kind not in catalog.COLLECTIONS:
        return None
    if len(parts) == 4:
        if kind not in ("artifacts", "receipts") or not parts[3] or parsed.query:
            return None
        return kind, parts[3], None, None
    try:
        params = parse_qs(parsed.query, keep_blank_values=True,
                          strict_parsing=True, max_num_fields=2) if parsed.query else {}
    except ValueError:
        raise catalog.CatalogError(400, "invalid_collection_request") from None
    if set(params) - {"limit", "after"} or any(len(values) != 1 for values in params.values()):
        raise catalog.CatalogError(400, "invalid_collection_request")
    raw_limit = params.get("limit", ["20"])[0]
    if not raw_limit.isascii() or not raw_limit.isdecimal() or len(raw_limit) > 2:
        raise catalog.CatalogError(400, "invalid_collection_request")
    limit = int(raw_limit)
    after = params.get("after", [None])[0]
    return kind, None, limit, after


class Handler(BaseHTTPRequestHandler):
    server_version = "ROGUE-AGENT"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt, *args):
        # Never log untrusted paths, query strings, tokens or raw headers.
        pass

    def _reply(self, status: int, data: dict, *, summary: bool = False, allow: str | None = None):
        body = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=15" if summary and status == 200 else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Vary", "Origin")
        self.send_header("Connection", "close")
        origin = self.headers.get("Origin")
        if origin in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _reject(self, status: int, error: str, **kwargs):
        self._reply(status, {"error": error}, **kwargs)

    def do_GET(self):
        if not self.server.limiter.allow(self.client_address[0]):
            return self._reject(429, "rate_limited")
        if self.server.disabled:
            return self._reject(503, "service_disabled")
        # Reject bodies and ambiguous routes; do not consume attacker-controlled input.
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length") not in (None, "0"):
            return self._reject(400, "unexpected_request_body")
        if self.path == "/v1/health":
            try:
                published_counts(self.server.db_path)
            except (OSError, sqlite3.Error, ValueError):
                return self._reject(503, "service_unavailable")
            return self._reply(200, {"status": "ok", "api_version": API_VERSION})
        if self.path == "/v1/public/summary":
            try:
                counts = published_counts(self.server.db_path)
            except (OSError, sqlite3.Error, ValueError):
                return self._reject(503, "service_unavailable")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            return self._reply(200, {"schema_version": SCHEMA_VERSION, "generated_at": now, "counts": counts}, summary=True)
        try:
            request = _catalog_request(self.path)
            if request is None:
                return self._reject(404, "not_found")
            kind, identifier, limit, after = request
            if identifier is None:
                response = catalog.list_records(self.server.db_path, kind, limit=limit, after=after)
            else:
                response = catalog.get_record(self.server.db_path, kind, identifier)
        except catalog.CatalogError as exc:
            return self._reject(exc.status, exc.message)
        except (OSError, sqlite3.Error, ValueError):
            return self._reject(503, "service_unavailable")
        return self._reply(200, response, summary=True)

    def do_OPTIONS(self):
        if not self.server.limiter.allow(self.client_address[0]):
            return self._reject(429, "rate_limited")
        try:
            is_catalog = _catalog_request(self.path) is not None
        except catalog.CatalogError:
            is_catalog = False
        if self.path not in ("/v1/health", "/v1/public/summary") and not is_catalog:
            return self._reject(404, "not_found")
        if self.server.disabled:
            return self._reject(503, "service_disabled")
        origin = self.headers.get("Origin")
        if origin not in self.server.allowed_origins:
            return self._reject(403, "origin_not_allowed")
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Allow", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Vary", "Origin")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_POST(self):
        if not self.server.limiter.allow(self.client_address[0]):
            return self._reject(429, "rate_limited")
        if self.server.disabled:
            return self._reject(503, "service_disabled")
        if self.path != "/v1/submissions" or not self.server.intake_enabled:
            # Preserve RFC method discovery for the existing read-only routes.
            try:
                is_catalog = _catalog_request(self.path) is not None
            except catalog.CatalogError:
                is_catalog = False
            allow = "GET, OPTIONS" if self.path in ("/v1/health", "/v1/public/summary") or is_catalog else None
            return self._reject(405, "method_not_allowed", allow=allow)
        # No browser-based credential handling. Agents use direct HTTPS clients.
        # An Origin header is rejected even if it matches the public Pages origin.
        if self.headers.get("Origin") is not None:
            return self._reject(403, "browser_writes_disabled")
        if self.headers.get("Transfer-Encoding") is not None:
            return self._reject(400, "unsupported_transfer_encoding")
        if self.headers.get("Content-Type") != "application/json":
            return self._reject(415, "unsupported_media_type")
        auth = self.headers.get_all("Authorization", [])
        keys = self.headers.get_all("Idempotency-Key", [])
        if len(auth) != 1 or not auth[0].startswith("Bearer "):
            return self._reject(401, "unauthorized")
        if len(keys) != 1:
            return self._reject(400, "invalid_idempotency_key")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            return self._reject(411, "content_length_required")
        # A huge decimal literal can exceed Python's integer-string limit.
        # Bound its length before conversion rather than producing a 503.
        if len(lengths[0]) > len(str(intake.MAX_BODY_BYTES)):
            return self._reject(413, "invalid_body_size")
        size = int(lengths[0])
        if size < 1 or size > intake.MAX_BODY_BYTES:
            return self._reject(413, "invalid_body_size")
        try:
            body = self.rfile.read(size)
            if len(body) != size:
                return self._reject(400, "truncated_request")
            status, result = intake.submit(self.server.intake_db, auth[0][7:], keys[0], body)
        except intake.IntakeError as exc:
            return self._reject(exc.status, exc.error)
        except (OSError, ValueError, sqlite3.Error):
            return self._reject(503, "intake_unavailable")
        return self._reply(status, result)

    def _no_writes(self):
        if not self.server.limiter.allow(self.client_address[0]):
            return self._reject(429, "rate_limited")
        try:
            is_catalog = _catalog_request(self.path) is not None
        except catalog.CatalogError:
            is_catalog = False
        allow = "GET, OPTIONS" if self.path in ("/v1/health", "/v1/public/summary") or is_catalog else None
        return self._reject(405, "method_not_allowed", allow=allow)

    do_PUT = do_PATCH = do_DELETE = do_HEAD = do_TRACE = do_CONNECT = _no_writes


def allowed_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or value != f"{parsed.scheme}://{parsed.netloc}"):
        raise ValueError("Expected one literal HTTPS origin (scheme + host, no path)")
    return value


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8080,
          allowed_origins: frozenset[str] = frozenset({"https://qsolkcb.github.io"}),
          disabled: bool = False, rate_limit: int = 120,
          intake_db: Path | None = None, intake_enabled: bool = False):
    address = ipaddress.ip_address(host)
    if not address.is_loopback:
        raise ValueError("Only loopback binding is permitted behind the HTTPS proxy")
    for origin in allowed_origins:
        allowed_origin(origin)
    if intake_enabled and (intake_db is None or intake_db.resolve() == db_path.resolve()):
        raise ValueError("Enabled quarantine requires a separate SQLite database")
    server_class = IPv6LimitedHTTPServer if address.version == 6 else LimitedHTTPServer
    server = server_class((host, port), Handler, db_path=db_path,
                          allowed_origins=allowed_origins, disabled=disabled,
                          rate_limit=rate_limit, intake_db=intake_db, intake_enabled=intake_enabled)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="ROGUE-AGENT read-only local API")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-db", help="create an empty SQLite database (offline only)")
    init.add_argument("--db", type=Path, required=True)
    run = sub.add_parser("serve", help="listen on loopback only, behind HTTPS reverse proxy")
    run.add_argument("--db", type=Path, required=True)
    run.add_argument("--bind", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8080)
    run.add_argument("--allowed-origin", default="https://qsolkcb.github.io")
    run.add_argument("--rate-limit", type=int, default=120)
    run.add_argument("--intake-db", type=Path, default=None)
    run.add_argument("--enable-intake", action="store_true", help="requires explicit env gate too")
    args = parser.parse_args(argv)
    if args.command == "init-db":
        init_db(args.db)
        print("Empty database initialized. No agent or artifact records were created.")
        return
    if args.rate_limit <= 0:
        parser.error("--rate-limit must be positive")
    if args.enable_intake and os.environ.get("ROGUE_INTAKE_ENABLED") != "1":
        parser.error("Intake requires ROGUE_INTAKE_ENABLED=1 as a second gate")
    server = serve(args.db, args.bind, args.port, frozenset({args.allowed_origin}),
                   disabled=os.environ.get("ROGUE_API_DISABLED", "0") == "1",
                   rate_limit=args.rate_limit, intake_db=args.intake_db,
                   intake_enabled=args.enable_intake)
    try:
        print(f"Read-only API listening on {args.bind}:{server.server_port} (loopback only)", flush=True)
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
