# Deployment plan — two independent phases

## Phase A: GitHub Pages (static only)

1. Review and merge the foundation PR.
2. In GitHub repo **Settings → Pages**, choose **Deploy from a branch**, branch **main**, folder **/docs**, Save. This approach does not require a GitHub Actions workflow.
3. Check https://qsolkcb.github.io/ROGUE-AGENT/ and verify that it says the backend is not connected and displays unknown counts.
4. Never put API tokens, SSH credentials, provider secrets or internal VM addresses into docs/ or docs/config.json.

The default project-site URL is a public web address, not a separately purchased custom domain. Optional domain mapping must be configured explicitly at the DNS provider and Pages settings; nothing in this PR changes DNS.

## Phase B: Abacus SuperComputer (later, separate approval)

1. Pin a reviewed repo commit/tag; provide docs/HANDOFF_SUPERCOMPUTER.md to the agent.
2. Provision an unprivileged API service, durable database, environment-injected secrets and HTTPS routing; retain explicit human access to kill switch.
3. Implement versioned health/summary endpoints and strict read-only CORS integration first. Do not accept visitor writes on initial deploy.
4. Run unit, integration, negative and abuse tests; review server logs and usage caps.
5. Configure docs/config.json apiBaseUrl to the final HTTPS API origin in a PR. Confirm the Pages site displays real backend state.
6. In a *separately authorized* stage, add invitation-based POST submission intake after every security gate in THREAT_MODEL.md has been independently checked.

## Rollback

Revert the frontend config to empty apiBaseUrl to put the site back into waiting mode. Disable public API exposure and revoke invitations separately at Abacus; the site config alone is not a security control. Preserve or quarantine data for an agreed retention window, with backup and incident controls.

## Provider boundaries

GitHub Pages cannot execute Python/Node, run a database or proxy traffic. Abacus provides a separate HTTPS-origin API. Keep origins and CORS allowlists distinct; avoid granting GitHub repo-write privileges to a public-facing API.

