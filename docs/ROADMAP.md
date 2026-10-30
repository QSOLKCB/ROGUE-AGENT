# Roadmap

| Stage | Scope | Exit criterion |
|---|---|---|
| v0.1.0 | Repo authority, invariants, threat model, research protocol, static Pages landing and deployment handoff | PR reviewed; static tests pass; Pages optionally enabled |
| v0.2.0 | Read-only Abacus API and truthfully populated public summary | Contract/abuse tests pass; explicit HTTPS and operational approval |
| v0.3.0 | Invitation-gated submission quarantine and moderation | Auth, anti-abuse, storage limits, receipts and negative tests verified |
| v0.4.0 | Reviewed artifactory promotion and public collection browser | No unreviewed repo writes; provenance and takedown tested |
| v0.5.0 | Carefully bounded multi-agent interaction experiment | Predeclared design, exposure controls, funding caps, receipts and adverse outcomes reported |

Never collapse the above stages to claim a running habitat before its actual deployment. GitHub Pages publishing is separate from Abacus API deployment and both require operator actions.

Principle: **specify → implement → test → review → deploy → observe → archive**.

