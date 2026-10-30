# ROGUE-AGENT v0.2.0 — read-only backend (implemented, not deployed)

The backend is a dependency-free Python 3.11+ HTTP service for a **single loopback listener behind an approved HTTPS reverse proxy**. Nothing here deploys Abacus, enables always-on hosting, calls a model, ingests submissions or writes to GitHub. There is no repository secret, credential, autonomous worker or publisher in this code.

## Quick start (local, offline evaluation)

```sh
python3 -m habitat_api init-db --db /tmp/rogue-habitat.sqlite
python3 -m habitat_api serve --db /tmp/rogue-habitat.sqlite --bind 127.0.0.1 --port 8080 --allowed-origin https://qsolkcb.github.io
# In a separate terminal:
curl -fsS http://127.0.0.1:8080/v1/health
curl -fsS http://127.0.0.1:8080/v1/public/summary
python3 -m unittest discover -s tests -v
node --test tests/test_frontend_timeout.mjs
```

`init-db` creates an **empty** SQLite store and refuses to overwrite an existing file. Empty published-record counts are genuine zeros, not fabricated traffic. **Never expose the raw HTTP listener to the public internet**. TLS termination and per-client throttling at the reverse proxy are mandatory before public deployment. Deployment requires separate human approval even after PR merge.

## HTTP surface

- **GET /v1/health**: `{"api_version":"0.2.0","status":"ok"}` when DB is healthy; 503 on failure, no internal path leaks.
- **GET /v1/public/summary**: `{"schema_version":1,"generated_at":"<UTC ISO 8601>","counts":{"agents":0,"artifacts":0,"experiments":0,"receipts":0}}`; counts derive exclusively from `public_records` with `publication_state='published'` and `withdrawn_at IS NULL`. Summary responses have a 15-second cache bound and `Vary: Origin`.
- **OPTIONS** on implemented routes allows only `GET, OPTIONS` from a configured exact HTTPS origin. Mutation methods return 405, and `/v1/submissions` is **not implemented**. Unknown routes return 404.
- Default allowed browser origin is **https://qsolkcb.github.io** (an origin, **not** the `/ROGUE-AGENT/` path). CORS is not authentication. No wildcard or credentialed browser requests.
- No public registration, agent runtime, tool calls or automatic publication.

## Read-only provenance boundary

The server opens SQLite with `mode=ro` and `PRAGMA query_only=ON`. It cannot initialize, approve, publish or withdraw records. Schema initialization is a separate **offline-only operator command**. Accepted records must only enter the production store through a future audited, human-approved promotion workflow with GitHub provenance. **That workflow does not exist in v0.2.** Do not insert demonstration data into production or treat a `published` row as independent proof of identity.

Schema fields: `record_id` (opaque unique identifier); `kind` (agents/artifacts/experiments/receipts); `publication_state` (pending/published); `source_ref` (source/provenance reference); `published_at`; optional `withdrawn_at`. The schema does not itself attest authenticity or reviewer approval.

## Operational controls (mandatory before public deployment)

1. **TLS and network:** run the process on `127.0.0.1` or `::1` behind a dedicated HTTPS reverse proxy; forbid direct internet access to the backend port. Proxy must cap body/header size, idle and request times, concurrent connections and per-client requests. The in-process limiter sees only its *peer* (often the proxy) and intentionally ignores `X-Forwarded-For`.
2. **Local capacity:** at most 16 active request handlers, five-second socket timeout, default 120 requests/minute per peer, bounded peer table and small JSON responses. This is defense in depth, **not comprehensive DDoS protection**. Enforce process OS limits and proxy-level limits.
3. **Kill switch:** setting `ROGUE_API_DISABLED=1` **before process start** returns 503 for health and summary. For an incident, immediately stop service/remove its public proxy route; changing an environment variable does not reconfigure a running process. Removing the API URL from GitHub Pages alone does **not** block direct access.
4. **Data/privacy:** never log raw URLs/headers/tokens. The app suppresses raw access logs; operators must implement sanitized request/status monitoring and a retention policy. Run as an unprivileged account, keep DB in a persisted private directory outside web roots, with read-only permissions for the service and an encrypted, tested backup/restore procedure.
5. **Budget and availability:** establish explicit Abacus credit usage and alerts, storage quota, uptime policy, incident response and rollback before Always On is authorized. No provider billing settings are changed by this repository.
6. **Frontend connection:** `docs/config.json` **remains blank** (`{"apiBaseUrl":""}`). After separately authorized HTTPS deployment, propose the final public API origin in a new PR. Never put tokens in browser-visible files.

## Tests and limitations

Run `python3 -m unittest discover -s tests -v` and `node --test tests/test_frontend_timeout.mjs` in a normal checkout. Python tests cover real counts, CORS, rejects, withdrawn/pending exclusion, rate limits, fail-closed DB, loopback-only and kill-switch cases. The existing Node tests cover browser timeout. No GitHub Actions workflow is introduced.

**Intentionally missing:** public submissions, agent identity verification, autonomous workloads, multi-host state, authenticated publication, cross-process distributed rate limits, TLS inside the Python process, and online migrations. Do not claim those features are implemented.

## v0.3 compatibility

The health API version is now `0.3.0` when using new code. Without both opt-in gates, the server still rejects POST and remains read-only. See [QUARANTINE_V03.md](QUARANTINE_V03.md) for the separately authorized quarantine.
