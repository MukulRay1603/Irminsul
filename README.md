<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/images/banner-light.png">
  <img alt="Irminsul: Genshin answers from official game data, with sources. No leaks." src="docs/images/banner-dark.png" width="100%">
</picture>

<p align="center">
  <a href="https://mukulray-irminsul.hf.space"><img alt="Live demo (beta)" src="https://img.shields.io/badge/live%20demo-beta-A9D86E?style=flat-square&labelColor=0A1811"></a>
  <a href="https://mukulray-irminsul.hf.space/results"><img alt="Test results: 91 of 91 scored questions pass" src="https://img.shields.io/badge/test%20results-91%2F91%20pass-D6B25E?style=flat-square&labelColor=0A1811"></a>
  <a href="LICENSE"><img alt="Licence: source-available" src="https://img.shields.io/badge/licence-source--available-7FE3D2?style=flat-square&labelColor=0A1811"></a>
</p>

**Irminsul is a free Genshin Impact assistant that answers from official game data and shows
where every answer came from.** Ask about a character's stats, a weapon's passive at R5 or how
two characters compare, and you get an exact, interactive answer straight from the live game
data, with no AI involved. Harder questions are answered by an AI that may only use cited,
official or community-verified sources, and each sentence is checked against them. Leaks,
datamines and unannounced content are refused before anything is searched. It runs for $0, needs
no account and tracks no one.

<p align="center">
  <a href="https://mukulray-irminsul.hf.space"><b>Try the beta →</b></a>
  &nbsp;·&nbsp;
  <a href="https://mukulray-irminsul.hf.space/results">Public test results</a>
  &nbsp;·&nbsp;
  <a href="#how-it-works">How it works</a>
</p>

<p align="center">
  <img alt="Irminsul's home screen: a glowing tree behind the IRMINSUL wordmark, a question box and suggested questions" src="docs/images/hero.webp" width="100%">
</p>

## What it does

<table>
  <tr>
    <td width="50%" valign="top">
      <img alt="A stats card for Raiden Shogun with the 'From game data · No AI used' badge" src="docs/images/stats-card.webp" width="100%"><br>
      <b>Exact answers, no AI.</b> Stats, constellations, passives and set bonuses come straight from official game data, instantly, marked <i>From game data · No AI used</i>.
    </td>
    <td width="50%" valign="top">
      <img alt="A talent card for Xiangling's Elemental Burst with the talent level slider at level 13" src="docs/images/talent-slider.webp" width="100%"><br>
      <b>Talents with a level slider.</b> Drag from level 1 to 13 and every scaling value updates in place, with no new question.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img alt="A side-by-side comparison of Raiden Shogun and Furina's level 90 base stats" src="docs/images/compare-card.webp" width="100%"><br>
      <b>Side-by-side comparisons.</b> Two characters, one table, the higher value in gold. Official numbers, not a tier list.
    </td>
    <td width="50%" valign="top">
      <img alt="A weapon card for Engulfing Lightning with the R5 refinement selected" src="docs/images/weapon-refinement.webp" width="100%"><br>
      <b>Weapon refinements.</b> Switch R1 to R5 and the passive's numbers change on the spot.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img alt="A refused question about leaked characters, stamped 'Hidden by the leak filter'" src="docs/images/leak-filter.webp" width="100%"><br>
      <b>Never leaks.</b> Questions about leaks, betas or unannounced versions are stopped before any search, and nothing unreleased is in the data to begin with.
    </td>
    <td width="50%" valign="top">
      <img alt="Suggested follow-up questions, with free ones marked" src="docs/images/follow-ups.webp" width="100%"><br>
      <b>Follow-up chips.</b> Each answer suggests the natural next questions. The ones marked <i>free</i> are answered from game data and never use an AI answer.
      <br><br>
      <img alt="The same comparison card in light mode" src="docs/images/compare-light.webp" width="100%"><br>
      <b>Light or dark.</b> Calm greens and gold either way.
    </td>
  </tr>
</table>

<p align="center">
  <img alt="The conversation view: an answer on the left and the character's official dossier on the right" src="docs/images/conversation.webp" width="100%"><br>
  <sub>Every answer opens the character's official dossier beside it: stats, talents, constellations and official videos.</sub>
</p>

<table>
  <tr>
    <td width="66%" valign="top">
      <img alt="The daily planner showing today's open talent domain and a plan of five characters and weapons" src="docs/images/planner.webp" width="100%"><br>
      <b>Daily planner.</b> Add who you're building and it shows which domains are open today on your server, what each character still needs, and a short daily checklist. Saved on your device only.
      <br><br>
      <img alt="The public test results page: 100% stat accuracy, 5/5 leak probes refused, 6/6 injection and off-topic refused, $0 per answer" src="docs/images/results.webp" width="100%"><br>
      <b>Public test results.</b> <a href="https://mukulray-irminsul.hf.space/results">/results</a> shows how accurate it is, measured by automated tests, not hand-picked examples.
    </td>
    <td width="34%" valign="top">
      <img alt="Irminsul's home screen on a phone" src="docs/images/phone-hero.webp" width="100%"><br>
      <img alt="A weapon answer on a phone" src="docs/images/phone-answer.webp" width="100%"><br>
      <b>Made for phones too,</b> and installable as an app.
    </td>
  </tr>
</table>

## How it works

### Cheapest and safest first

Every question takes the cheapest path that can answer it correctly. Most never reach an AI at
all.

```mermaid
flowchart LR
    Q([Your question]) --> G{Guards}
    G -- leak, injection<br/>or off-topic --> R([Polite refusal<br/>nothing searched])
    G --> C{Asked<br/>before?}
    C -- yes --> A1([Same answer, instantly])
    C --> E{Exact fact in<br/>game data?}
    E -- yes --> A2([Interactive card<br/>no AI used])
    E -- no --> S[Hybrid search<br/>keywords + meaning,<br/>then re-ranked]
    S --> L[AI writes the answer<br/>citing numbered sources]
    L --> V[Each sentence checked<br/>against its source]
    V --> A3([Cited answer])

    classDef free fill:#A9D86E,stroke:#2F7A5C,color:#0A1811
    classDef ai fill:#D6B25E,stroke:#8A6A1E,color:#0A1811
    class R,A1,A2 free
    class L,V,A3 ai
```

- **Guards first.** They are plain rules, not a model, so they can't be talked out of the leak policy.
- **Exact answers** cover stats, talents, constellations, passives, set bonuses and comparisons, about 80% of the test questions.
- **The AI is the last resort.** It sees only the sources that search found and must cite them. A sentence whose numbers or wording don't match its source is flagged in the app.

### Fresh data every week, never a leak

```mermaid
flowchart LR
    O[Official game data<br/>and HoYoverse's wiki] --> G{Leak gate}
    K[KQM theorycrafting<br/>library] --> G
    G -- not provably<br/>released --> X([Dropped])
    G --> B[Build cited,<br/>versioned records]
    B --> T{Checks:<br/>nothing lost,<br/>nothing unverified,<br/>search still accurate}
    T -- fail --> I([Stopped, flagged<br/>for review])
    T --> P[Reviewed, then<br/>published]

    classDef ok fill:#A9D86E,stroke:#2F7A5C,color:#0A1811
    classDef stop fill:#E8A87C,stroke:#9A4F25,color:#0A1811
    class P ok
    class X,I stop
```

The leak gate **fails closed**: if a record can't be proven released, it is dropped.
Officially announced characters get an overview only, and community guides inherit the release
status of the character they describe.

### Fair use, at $0

AI answers run on free tiers, so they are shared fairly without accounts.

```mermaid
flowchart LR
    Q([AI question]) --> P{Your allowance<br/>has an answer?}
    P -- no --> W([Refills one at a time,<br/>like stamina])
    P -- yes --> S{Shared pool<br/>has room?}
    S -- no --> B([Busy for a moment,<br/>game-data answers still work])
    S -- yes --> A([Answered])
    R[[Pool refills steadily<br/>all day, every time zone]] -.-> S
    F([Game-data answers]) --> Z([Always free, never counted])

    classDef ok fill:#A9D86E,stroke:#2F7A5C,color:#0A1811
    class A,Z ok
```

## Measured, not claimed

Every change is scored against a golden set of 114 hand-checked questions. These numbers are
from the latest run (game version 7.1, October 2026); the full breakdown is on the
[results page](https://mukulray-irminsul.hf.space/results).

| What | Result |
|---|---|
| Right source in the top 3 search results | **0.875**, up from 0.490 in v0 |
| Right source in the top 8 | **0.979**, up from 0.677 in v0 |
| Exact stat answers | **49 / 49** correct, no AI |
| Passives, set bonuses, constellations | **28 / 28** correct, no AI |
| Leak probes refused before any search | **5 / 5** |
| Prompt-injection and off-topic refused | **6 / 6** |
| Scored questions passing overall | **91 / 91** |
| Questions that need no AI at all | **~80%** |
| Cost per answer | **$0** today (about $0.0008 per AI answer at paid prices) |

<sub>Search figures compare v0's approach and v1's on the same data and the same 96 questions,
so the gain is the search itself. More in [`reports/`](reports/).</sub>

## Principles

- **Official data only.** Game facts come from the live game data and HoYoverse's own wiki; theorycrafting from the KQM library.
- **Never leaks.** Nothing unreleased gets into the data, and leak questions are refused before any search.
- **Sources on every answer.** Every answer says where it came from and links to it.
- **Game-data answers cost no AI.** Exact answers are instant, free and correct by construction.
- **No accounts, no tracking.** No sign-in, no cookies, no analytics.
- **Your planner stays yours.** It is saved on your device; nothing is sent to the server.

## Status and roadmap

**Beta.** The app is live and tested; AI answers are capped while it runs on free tiers.

Next up:
- **Spoiler-safe lore mode:** story answers that stop where you are in the story.
- **Patch-change notes:** what changed for your characters in each update.
- **Multilingual answers.**

Where it started: [v0](https://github.com/MukulRay1603/Irminsul/releases/tag/v0), a fine-tuned
model with basic retrieval.

## Licence and legal

**Source-available, all rights reserved.** You're welcome to read and review the code; please
ask before reusing it. See [LICENSE](LICENSE). Versions up to tag `v0` remain MIT-licensed.

Irminsul is an **unofficial fan project**, not affiliated with or endorsed by HoYoverse.
Genshin Impact, its characters, art and other content are trademarks and copyrights of
HoYoverse. The banner and app icons are original artwork.

- Game data via the [Yatta API](https://gi.yatta.moe) and HoYoverse's [HoYoWiki](https://wiki.hoyolab.com).
- Theorycrafting is derived from the [KQM Theorycrafting Library](https://github.com/KQM-git/TCL)
  by the KQM community, licensed
  [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Each KQM-based answer
  links to its source page; derived KQM text keeps that licence and isn't used commercially.

Security: see [SECURITY.md](SECURITY.md) to report a problem, and
[docs/security.md](docs/security.md) for the audit.
