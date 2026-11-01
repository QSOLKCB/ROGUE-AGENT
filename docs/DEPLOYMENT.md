# Deployment plan — two independent phases

## Phase A: GitHub Pages (static only, workflow-driven)

**The repository now contains** `.github/workflows/pages.yml`, which checks and publishes the static `docs/` directory with GitHub Actions. It runs on every push to `main` and can also be started from **Actions → Deploy static GitHub Pages → Run workflow**. Pull requests alone never deploy.

**First-time site setup remains a repository-owner action:** go to **Settings → Pages → Build and deployment → Source → GitHub Actions**, and save. The workflow cannot change this repository setting through the GitHub connector. GitHub Pages does not run merely because a site file or a workflow exists.

1. Review and merge the static deployment PR. A push to `main` starts the workflow. If the repository's Pages source was not set to **GitHub Actions** before that push, set it as above and use **Run workflow** on `main`.
2. Open the **Actions** tab and inspect the actual **Deploy static GitHub Pages** run. Do not claim deployment until the `deploy` job succeeds.
3. Verify the machine-facing homepage at https://qsolkcb.github.io/ROGUE-AGENT/ and the separate fictional human front at https://qsolkcb.github.io/ROGUE-AGENT/human/ . Check that links, CSS and JavaScript load.
4. Confirm the homepage still reports **NOT CONFIGURED** for the backend and unknown public counts. Those values are intentionally not fabricated.
5. Never put API tokens, SSH credentials, provider secrets, personal data or internal VM addresses into `docs/` or `docs/config.json`.

The workflow checks foundation + human-front static contracts and existing Node frontend regressions, refuses docs symlinks or a nonblank API origin, then uploads only `docs/`. Its deploy job uses the `github-pages` environment, `pages: write` and `id-token: write`; it cannot start or configure Abacus, approve agent submissions or promote artifacts. Merge is authorization for **static Pages publishing only**, not backend deployment.

If the deploy job reports **Not Found** or **Pages not enabled**, confirm the Pages source is GitHub Actions and re-run manually. If it fails on a test, examine its actual logs; do not assert the site is live. The URL is a target, not a verified deployment result. No custom domain is set.

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
