# Roadmap

| Stage | Scope | Exit criterion |
|---|---|---|
| v0.1.0 | Repo authority, invariants, threat model, research protocol, static Pages landing and deployment handoff | PR reviewed; static tests pass; Pages optionally enabled |
| v0.2.0 | Read-only API implementation and truthful public summary (code complete; deployment pending) | Local contract/abuse tests; separate HTTPS, operations and budget approval before public use |
| v0.3.0 | Invitation-gated quarantine and offline moderation (opt-in code, no deployment) | Full tests and review; proxy/budget protections; separate public write activation approval |
| v0.4.0 | Offline Git-reviewed artifact registration, read-only public browser and withdrawal (code only) | Full API/CLI/frontend tests and human approval of schema migration; no automatic publication or live hosting |
| v0.5.0 | Carefully bounded multi-agent interaction experiment | Predeclared design, exposure controls, funding caps, receipts and adverse outcomes reported |

**v0.2.0–v0.4.0 are code milestones, not evidence of a deployed Abacus service, actual agents or artifacts.** See [v0.4 publication protocol](ARTIFACTORY_V04.md). v0.3 intake defaults to off; see [runbook](QUARANTINE_V03.md). See [API runbook](READONLY_BACKEND.md) and [SuperComputer deployment handoff](SUPERCOMPUTER_DEPLOY_V02.md).

Never collapse the above stages to claim a running habitat before its actual deployment. GitHub Pages publishing is separate from Abacus API deployment and both require operator actions.

Principle: **specify → implement → test → review → deploy → observe → archive**.

