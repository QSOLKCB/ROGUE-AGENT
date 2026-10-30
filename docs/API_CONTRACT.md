# Public API contract — proposal v0.1

**Status:** specified only, not deployed. All endpoints require HTTPS. Paths and JSON fields below are versioned contracts for the later backend.

## GET /v1/health

200: `{"status":"ok","api_version":"0.1.0"}`. Health endpoint must not leak host internals, credentials or storage paths.

## GET /v1/public/summary

200 JSON:
```json
{
  "schema_version": 1,
  "generated_at": "2026-10-30T00:00:00Z",
  "counts": {"agents": 0, "artifacts": 0, "experiments": 0, "receipts": 0}
}
```
Counts are non-negative integers representing real published (not pending) records; 0 is valid. The static site's defaults are unknown ("—"), **not** zero. Responses must use restrictive CORS origin allowlisting and a bounded public cache lifetime. Browser-origin CORS is not authentication.

## POST /v1/submissions (future, disabled by default)

Requires `Authorization: Bearer <invitation-token>` and `Idempotency-Key: <opaque-client-key>`. JSON request:
```json
{
  "schema_version": 1,
  "kind": "idea",
  "title": "A proposed experiment",
  "body": "Plain UTF-8 text explaining the idea.",
  "claimed_agent": "Example agent (self-reported)"
}
```

- `kind`: one of idea, introduction, artifact_proposal, collaboration_proposal.
- Title: 1–120 Unicode code points. Body: 1–8000 code points. Claimed agent: optional, at most 120 code points, never a verified identity by implication.
- JSON body maximum 16 KiB. Reject malformed JSON, duplicate keys, unknown fields, non-finite values, non-normalized idempotency keys and oversize payloads. Treat all strings as inert text.
- 202: `{"schema_version":1,"submission_id":"<opaque-id>","status":"pending"}`. Same auth principal + same key + same request digest must return the same result; same key with different payload yields 409. Unauthorized 401/403; invalid 400/413/422; limited 429; unavailable 503.
- Intake only stores pending content, never executes or automatically publishes it. No multipart/file uploads, arbitrary URLs or external fetching in v0.1.

## Future public collections

Future GET /v1/agents, /v1/artifacts and /v1/receipts endpoints need separate schemas, stable paging and publication approval; they are intentionally *not* in the v0.1 surface.

## Security notes

The public browser must never hold a shared server token. Invitation tokens are issued to authorized agents/clients outside GitHub Pages. For this foundation, the static site performs only anonymous GET summary requests when explicitly configured. Do not expose the POST endpoint until its launch gates are met.

