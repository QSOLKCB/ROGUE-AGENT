# SuperComputer foundation-stage handoff — superseded by v0.2

**For current backend deployment, use [SUPERCOMPUTER_DEPLOY_V02.md](SUPERCOMPUTER_DEPLOY_V02.md) instead.** The read-only API now exists; do not ask an agent to reimplement it.

This original v0.1 design brief is retained for project history. Give the following mission only as historical context **after the foundation PR is merged and reviewed**. Deploy only with explicit maintainer approval. The GitHub repo is the authority, not this prompt if documentation changes.

## Mission

Read AGENTS.md, docs/INVARIANTS.md, docs/ARCHITECTURE.md, docs/THREAT_MODEL.md, docs/API_CONTRACT.md, docs/EXPERIMENT_PROTOCOL.md, docs/DEPLOYMENT.md and docs/ROADMAP.md in the pinned QSOLKCB/ROGUE-AGENT revision.

Implement **backend phase 1: read-only prototype** on Abacus SuperComputer using a lean supported stack, such as Python FastAPI plus SQLite for an initial single-VM deployment. If dependencies are added, lock exact versions. Bind app privately behind the provider's HTTPS reverse proxy. Report runtime service configuration and persistent-volume paths without printing secrets.

Deliver:
- GET /v1/health and GET /v1/public/summary exactly according to the contract, with truthful counts and explicit UTC timestamps.
- Strict CORS allowlist for the approved Pages origin; rate limiting, basic server logging without secrets, request timeouts and an operator kill switch.
- No seeded fake events in production, no public writes, no exposed VM terminal, no installed agent shells, no background LLM workers, no GitHub write bot.
- Documented backup/restore approach, budget and storage ceilings, zero-trust input handling and deploy rollback.
- Deterministic local tests and API integration tests, plus proof of rejection of unauthorized/unimplemented POST requests.
- A deployment report listing changed files, commands and tests actually run, passed/failed cases, known limitations, API HTTPS URL, monthly cost/rate assumptions and manual operator actions.

Commit code and docs changes **only to a feature branch and open a PR**. Do not push to main, merge, enable Always On, configure DNS, deploy a public write endpoint, or spend on model/API calls without separate explicit authorization. For an initial build, prefer a locally tested read-only service over touching the live VM. If tool access or platform permissions are unavailable, stop and report the blocker. Never claim an agent experiment has run before independently recording events.

## Future phase — NOT INCLUDED

Invitation issuance, agent submissions, moderation queue, artifact promotion, model calls, autonomous agent jobs, automatic PR preparation and inter-agent collaboration require individual later reviews.

