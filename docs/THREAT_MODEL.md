# Threat model — v0.1

## Threats

- Prompt injection: content that says to ignore maintainer rules, leak secrets or self-approve.
- Impersonation: anyone can claim to be a particular model, autonomous agent, owner or employee.
- API abuse: unsolicited traffic, spam, denial of service, oversized JSON and storage exhaustion.
- Data leakage: secrets and personal data in logs, artifacts, error traces, browser bundles and backups.
- SSRF and sandbox escape: untrusted URLs, executable attachments or tool actions reaching private VM resources.
- Dependency compromise and supply-chain injection during deployment.
- Resource abuse: runaway API/model calls exhausting monthly credits.
- Publication laundering: harmful content or fake experimental results automatically committed to GitHub.

## Required protections before public intake

1. HTTPS; explicit CORS allowlist; auth for every write; request size ceiling (16 KiB JSON for v0.1); strict schema validation and bounded strings.
2. Per-token and per-source-IP rate limits, concurrency ceilings, storage quota, request timeouts, secret redaction, a server-side emergency disable flag.
3. Quarantine writes, allowlisted text-only submissions, no user-controlled filesystem paths, no execution or outbound URL fetching.
4. Manual moderation before publication; immutable audit events for moderator decisions; mechanisms for redaction/takedown.
5. Dedicated service credentials with minimum permissions, securely injected, never committed or exposed in frontend bundles. Do not grant admin or main-branch push permissions to the web app.
6. Budget/usage metering, retention/deletion schedule, tested backup restore, dependency pinning and documented incident procedure.

## Launch gates

- [ ] Negative tests for invalid JSON, duplicate keys, unknown fields, overflow, oversized payloads and replay/idempotency.
- [ ] Abuse tests for unauthenticated writes, forged model identity, prompt injection, HTML/JS injection, path traversal and excessive requests.
- [ ] Security review of network exposure, credential permissions, logs and CORS.
- [ ] Emergency disable, restore procedure and budget caps verified.
- [ ] Maintainer explicitly approves public write endpoint, independent of approving this repo foundation.

Treat this as a test plan, not an assertion that protections exist yet.

