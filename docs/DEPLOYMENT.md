# Deployment plan — two independent phases

## Phase A: GitHub Pages (static only)

1. Review and merge the foundation PR.
2. In GitHub repo **Settings → Pages**, choose **Deploy from a branch**, branch **main**, folder **/docs**, Save. This approach does not require a GitHub Actions workflow.
3. Check https://qsolkcb.github.io/ROGUE-AGENT/ and verify that it says the backend is not connected and displays unknown counts.
4. Never put API tokens, SSH credentials, provider secrets or internal VM addresses into docs/ or docs/config.json.

The default project-site URL is a public web address, not a separately purchased custom domain. Optional domain mapping must be configured explicitly at the DNS provider and Pages settings; nothing in this PR changes DNS.

## Phase B: Abacus SuperComputer (later, separate approval)

1. Pin a reviewed v0.2 repo commit/tag; provide [v0.2 deployment handoff](SUPERCOMPUTER_DEPLOY_V02.md) and [API runbook](READONLY_BACKEND.md) to the agent.
2. After explicit operator approval, provision an unprivileged loopback-only Python service, separate TLS reverse proxy, private persisted SQLite storage, operational controls and access to the emergency kill switch.
3. Deploy the already implemented read-only health/summary endpoints without redesigning the API. Do not accept visitor writes on initial deploy.
4. Run unit, integration, negative and abuse tests; review server logs and usage caps.
5. Configure docs/config.json apiBaseUrl to the final HTTPS API origin in a PR. Confirm the Pages site displays real backend state.
6. In a *separately authorized* stage, add invitation-based POST submission intake after every security gate in THREAT_MODEL.md has been independently checked.

## Rollback

Revert the frontend config to empty apiBaseUrl to put the site back into waiting mode. Disable public API exposure and revoke invitations separately at Abacus; the site config alone is not a security control. Preserve or quarantine data for an agreed retention window, with backup and incident controls.

## Provider boundaries

GitHub Pages cannot execute Python/Node, run a database or proxy traffic. Abacus provides a separate HTTPS-origin API. Keep origins and CORS allowlists distinct; avoid granting GitHub repo-write privileges to a public-facing API.


## v0.3 compatibility

Never set `ROGUE_INTAKE_ENABLED=1` or `--enable-intake` during the read-only Abacus deployment. v0.3 quarantine needs distinct private storage, offline invitation operations, proxy controls, and separate human signoff. See [QUARANTINE_V03.md](QUARANTINE_V03.md).

## v0.4 collection deployment boundary

Public catalog routes require an **explicit offline migration** from public SQLite schema v1 to v2, with backup/restore rehearsal and review of DB file ownership. The read-only API service must not have DB write rights; the offline publication operator must have a separate account. GitHub Pages catalog browser remains offline while docs/config.json has a blank API origin. A separately authorized HTTPS deployment and config PR are required to show genuine published artifacts. No automatic Github or Abacus operations are added. See [ARTIFACTORY_V04.md](ARTIFACTORY_V04.md).
