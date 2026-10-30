# Abacus SuperComputer handoff — v0.2.0 deployment candidate

**Operator approval is required separately.** This is a task specification for a deployment-capable agent *after* this code PR has passed review and merged. It is not permission to spend credits, enable public networking or Always On.

## Mission

Deploy the **existing** `habitat_api` read-only service from the approved pinned GitHub commit, **not** a rewritten agent framework. Read and enforce AGENTS.md, docs/INVARIANTS.md, docs/READONLY_BACKEND.md, docs/API_CONTRACT.md, docs/THREAT_MODEL.md and docs/DEPLOYMENT.md. No model calls, registration, public write endpoints, self-updating agents or GitHub write tokens.

## Mandatory implementation gates

1. Obtain explicit operator approval for VM/service, uptime hours, monthly credit ceiling and alerts, data retention, disk limit and backups. Do **not** enable Always On without approval.
2. Check out the reviewed commit; run Python and Node test suites. Record runtime versions, actual pass/fail counts and any skipped tests.
3. Use an unprivileged service user and private persisted DB directory. Run `python3 -m habitat_api init-db --db <private-path>` *only* if the database does not already exist. Never destroy or overwrite a populated DB.
4. Bind to loopback behind a dedicated provider-managed HTTPS reverse proxy. Strict host/origin allowlists, per-client throttling, body/header limits, request and idle timeouts. **Port 8080 must not be accessible from the public internet.**
5. Check health and summary over HTTPS. Empty counts can genuinely be zero. Test invalid origins, POST/PUT/PATCH/DELETE, unknown routes, missing DB fail-closed behavior, abuse limits and resistance to `X-Forwarded-For` spoofing at the proxy.
6. Configure sanitized observability, resource/budget alarms, encrypted backups, a restoration test and an emergency shutoff. Document the public API origin, operational costs and rollout/rollback steps without printing secrets.
7. Keep `docs/config.json` with blank `apiBaseUrl` until a separate authorized GitHub Pages connection PR is approved.

## Report required

Pinned commit SHA; service identity/permissions; actual tests; HTTPS and exposure controls; backup/recovery evidence; factual public API URL and monitoring; budget ceiling; kill-switch test; outstanding security gaps. Do not claim a live public habitat, agent visits or experiments without direct evidence.

**Future stages excluded:** invitation tokens, public submission intake, moderation/publishing, model calls, agent orchestration, GitHub write automation.

## Important v0.3 boundary

Even if the pinned commit includes the v0.3 quarantine implementation, this handoff is **read-only only**. Do not pass `--enable-intake`, set `ROGUE_INTAKE_ENABLED`, provision invitation tokens or enable a public POST route as part of the v0.2 deployment.
