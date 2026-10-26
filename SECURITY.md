# Security policy

Irminsul is a free, public Genshin Impact assistant. It has no accounts, stores no personal
data beyond in-memory rate-limit counters, and runs on free LLM tiers. Security here mostly
means: nobody can run up a bill, take the service down for other players, make it leak
unreleased content, or get secrets out of it.

## Reporting a vulnerability

Please report privately, not in a public issue:

1. Use **Report a vulnerability** under this repository's **Security** tab (GitHub private
   vulnerability reporting).
2. If that option is not available, open an issue titled "Security contact request" with no
   details, and you will be contacted for them privately.

Include what you did, what happened and what you expected. A proof of concept against your
own local copy (`uv run irminsul-serve`) is ideal; please don't load-test the public Space.
You should get an answer within a week. Fixes are credited in the release notes unless you
prefer otherwise.

## Scope

In scope:
- the API (`src/irminsul/api/`: `/ask`, `/ask/stream`, `/quota`, `/health`)
- the answer engine, guards and leak filter (`src/irminsul/engine/`)
- the corpus pipeline and its GitHub workflows (`.github/workflows/`)
- the Docker image (`Dockerfile`)

Out of scope:
- the LLM providers, Hugging Face and GitHub themselves
- answers that are merely wrong or badly worded (please open a normal issue)
- volumetric denial of service against the hosted Space
- the content of third-party sources (Yatta, HoYoWiki, KQM)

## Threat model in brief

| Asset | Threat | Main control |
|---|---|---|
| $0 cost | scripted use of the LLM | a per-player AI-answer allowance, a shared refilling pool, per-provider caps below free tiers |
| availability | one client starving others | burst + daily limits per client, raw body cap, concurrency cap |
| fair limits | forging `X-Forwarded-For` | header trusted only for configured proxy hops |
| leak policy | prompt injection (question or retrieved source) | deterministic guards before any LLM call, sources treated as data |
| API keys | leaking via `/health`, errors or logs | keys only in env, never returned or logged, provider error bodies never read |
| supply chain | vulnerable deps, compromised actions, committed secrets | `pip-audit` and `gitleaks` in CI, actions pinned to SHAs, least-privilege tokens |

Every finding from the v1 audit, with severity and status, is in
[`docs/security.md`](docs/security.md).
