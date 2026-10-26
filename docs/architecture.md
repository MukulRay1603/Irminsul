# How Irminsul works

A concept-level tour. The diagrams are in the [README](../README.md#how-it-works).

## 1. Provenance on every record
Every record says where it came from, how much to trust it, which game version it describes and
whether it's released. That one idea powers citations, ranking, freshness and the leak gate.

**Entities** (characters, weapons, artifact sets) hold exact facts: level 90 stats, talent
scaling, constellations, refinement passives and set bonuses. **Documents** are the searchable
text written from those entities and from guides.

## 2. Sources and trust
| Trust tier | Source |
|---|---|
| Official | the live game's own text, and HoYoverse's official wiki |
| Team-verified | fact-checked research notes, published only with approval |
| Community | the KQM Theorycrafting Library (CC BY-NC-SA 4.0) |

Answers label every source with its tier.

## 3. The leak gate
It **fails closed**: when release status can't be proven, the record is dropped.
- Anything with an unknown or future release is dropped.
- Officially announced characters get an overview only (element, region, official description).
  Their kits are never ingested before release.
- Items without release dates must appear in HoYoverse's official lists.
- Community guides inherit the release status of the official entity they're about.
- A manual blocklist handles takedowns.

## 4. Weekly data updates
Each week, or on patch day, the data is rebuilt and compared with what's live. The run stops if
records go missing, anything is unverified, or search accuracy drops. A passing build is staged
for review and only published once approved, so a bad build never reaches players and rollback
is easy.

## 5. Search
Keyword search and meaning-based search find different things, so both run and their results
are fused, then a re-ranker reads the best candidates closely. Each step was kept only if it
measurably helped (see [`reports/`](../reports/)). The index is small enough to ship with the
data, so there's no separate vector database to run or pay for.

## 6. The answer engine
Cheapest and safest first:

| Step | What | Cost |
|---|---|---|
| Guards | leaks, unannounced versions, prompt injection, other games, off-topic | free, rule-based |
| Cache | the same question answered before (never shared across story points) | free |
| Story point | a character released after the player's story point → "past your story point", with *Show anyway* | free |
| Exact | a named character, weapon or set plus a factual question → an interactive card | free, instant |
| Announced | an officially announced character → official overview only | free |
| Search + AI | an AI writes from the retrieved sources and must cite them | free tiers |

**Story-safe lore.** Official character stories are part of the data, and every passage carries
the game version that first made it public, proven from official data (a version's added items,
or a character's release date) and never guessed. Text with no date of its own takes the latest
version of any character it names. A player can say how far they are in the Archon Quest; that
maps to a version (the table and its sources are in `src/irminsul/story.py`), and search drops
every later passage *before* re-ranking, so neither the re-ranker nor the AI ever sees it. The
choice stays in the browser, and "Why this answer?" shows how many passages it hid.

After an AI answer, every sentence that cites a source is checked against that source's text,
and anything that doesn't match is flagged in the app. Every answer also carries a trace (route,
sources, timing) that powers the "Why this answer?" view.

## 7. Fair use
No accounts, so fairness comes from limits: each player has an AI-answer allowance that refills
one at a time, and a shared pool refills steadily through the day. Game-data answers never
count. When AI answers are unavailable, everything else keeps working.

## 8. Evaluation
A golden set of hand-checked questions scores search and answers on every change: the right
facts, nothing forbidden, the right route (answered or refused), and the right source cited.
Results are published on the app's [/results](https://mukulray-irminsul.hf.space/results) page.

## 9. Key decisions
| Decision | Why |
|---|---|
| Exact answers before any AI | correct by construction, instant and free; most questions never need an AI |
| Rule-based guards before any AI | can't be prompt-engineered away, and cost nothing |
| A small embedded index instead of a hosted vector database | small corpus; no cost, no account, versioned with the data |
| Stage, review, then publish data | a bad build never reaches players |
| Team notes stay private by default | nothing is published without the owner's approval |
