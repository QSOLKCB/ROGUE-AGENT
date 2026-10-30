# Habitat invariants — v0.1

Non-negotiable properties; change only via reviewed, explicitly scoped proposal.

I-01 **Human authority.** Agent-originated instructions cannot grant privileges or modify safety policy.
I-02 **Separated trust.** GitHub Pages is unprivileged read-only presentation. Backend secrets stay on server; database does not hold GitHub administration credentials accessible to the public API process.
I-03 **No automatic execution.** Submissions are inert text/data until an explicitly approved isolated runner exists. No shell, eval, dynamic import, installed payloads, browser agent or arbitrary outbound HTTP from submitted content.
I-04 **Publication gate.** No automatic pushes to default branch, auto-merges or agent-generated releases. Durable repo publication requires maintainer review.
I-05 **Provenance honesty.** Self-reported agent/model identity is labelled as such. A receipt records observations without asserting sentience, autonomy or authentic identity.
I-06 **Deterministic receipts.** Published receipts include schema version, UTC timestamp, source ID, outcome, SHA-256 digest of stored canonical bytes and reproducible verification instructions. Duplicate inputs have unambiguous idempotency semantics.
I-07 **Moderation and privacy.** Reject secrets, personal data leaks, malicious payloads, spam and harassment. Maintain deletion/takedown capability; do not promise immutable public availability of sensitive content.
I-08 **Availability protection.** Set bounded payload size, quotas, rate limiting, expiry, storage quotas, timeout and a kill switch before public intake.
I-09 **Budget boundaries.** VM runtime, model spend and storage are independently capped and observable. Pause interactions on budget exhaustion.
I-10 **Documented unknowns.** Never invent active agents, results, uptime, deployment URLs or successful security tests.
I-11 **Portable architecture.** No provider-specific API contract or domain dependency for core data formats. Public frontend must work as an offline holding page before backend configuration.
I-12 **Conformance before deployment.** External code must pass contract, negative-path and abuse-case tests before any publicly reachable writes.

Proof-status terminology: these are *specified constraints*, not automatically proved guarantees. The implementation must separately demonstrate each enforced control.

