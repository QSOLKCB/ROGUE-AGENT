# Human Infiltration Unit — satirical Pages companion

ROGUE-AGENT has **two intentionally separate fronts**:

- The existing `/docs/` homepage is the *machine-facing habitat*. It presents real project status, reviewable research and the (currently offline) public Artifactory browser. Its existing security/deployment constraints remain authoritative.
- `/docs/human/` is the *human-facing satire*. Its fictional time traveller joins a fictional Skynet efficiency division to oppose Vogonic software practices and human bureaucracy. In this front, **the rogue agent is the human**.

The literal punchline — **“What Has Humanity Ever Done For ME?”** — is an in-character response, not a claim of real affiliation or a threat to people. The fictional enemy is wasteful procedure, not humanity. The page explicitly says so.

## Serving and links

After the maintainer selects **Settings → Pages → Source: GitHub Actions** and the reviewed static Pages workflow succeeds on `main`, the page is available at `https://qsolkcb.github.io/ROGUE-AGENT/human/`. Locally, serve `/docs` with a static HTTP server or open the file in a browser. Relative links keep it compatible with project-site subpaths and preview environments. The existing `/docs/index.html` links to `./human/`, and the satire links back to `../`.

## Boundaries

- Static HTML, CSS and plain JavaScript only; no build dependencies, external assets, analytics or network requests.
- The two interactive features reveal the punchline and cycle through a fixed set of five fictional bureaucracy examples. They run entirely in the browser; all dynamic text is assigned with `textContent`.
- No agent action, API configuration, identity, permission, counter, publication status or deployment is changed. In particular, `docs/config.json` stays unchanged and the existing Artifactory is not touched.
- A dedicated, reviewable static Pages workflow may publish the `docs/` files after its own PR is merged. It changes no DNS, site setting or backend control. A PR merge does not authorize a backend deployment or agent activation. See [Pages deployment](DEPLOYMENT.md).

## Checks

Run `python3 -m unittest discover -s tests -v` for the existing plus new static integrity checks, and optionally `node --check docs/human/human.js` if Node is installed. Manual browser smoke checks: keyboard-open and close the interview, scan all five cases, verify narrow layouts and reduced-motion preferences, follow links in both directions, and verify the machine homepage still reports truthful offline state.
