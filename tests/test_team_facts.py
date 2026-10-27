# ruff: noqa: E501  (sample lines mirror the real file format)
from datetime import UTC, datetime
from pathlib import Path

from irminsul.schema import Tier
from irminsul.sources.team_facts import parse_facts, tier_for

NOW = datetime(2026, 10, 26, tzinfo=UTC)
LIVE = (7, 1)

SAMPLE = """# Team facts

## 1. Wishes

- Character Event Wishes guarantee a 5-star within 90 wishes. | https://genshin-impact.fandom.com/wiki/Wish | 2026-10-26 | 7.1
- Pity carries over to the next banner of the same type. | https://genshin-impact.fandom.com/wiki/Wish | 2026-10-26 | 7.1
- Capturing Radiance arrived with Version 5.0. | https://genshin.hoyoverse.com/en/news/detail/125553 | 2026-10-26 | 7.1 (since 5.0)

## 5. Energy Recharge (KQM)

- KQM recommends about 160-200% ER for Kazuha. | https://keqingmains.com/q/kazuha-quickguide/ | 2026-10-26 | 7.1
"""


def test_facts_group_by_section_and_source():
    r = parse_facts(SAMPLE, NOW, LIVE)
    assert r.kept_lines == 4 and not r.dropped
    assert [d.doc_id for d in r.docs] == [
        "team/wishes#1",
        "team/wishes#2",
        "team/energy-recharge-kqm#1",
    ]
    fandom = r.docs[0]
    assert fandom.source.url == "https://genshin-impact.fandom.com/wiki/Wish"
    assert "90 wishes" in fandom.text and "Pity carries over" in fandom.text
    assert "checked 2026-10-26" in fandom.text


def test_tier_follows_the_source():
    r = parse_facts(SAMPLE, NOW, LIVE)
    assert [d.source.tier for d in r.docs] == [Tier.COMMUNITY, Tier.RAYY_VERIFIED, Tier.KQM]
    assert tier_for("https://www.hoyolab.com/article/497840") == Tier.COMMUNITY  # a player post
    assert tier_for("https://wiki.hoyolab.com/pc/genshin/entry/766") == Tier.RAYY_VERIFIED


def test_unsafe_lines_are_dropped():
    bad = """## Wishes
- According to the leaks, a new banner is coming. | https://example.com/a | 2026-10-26 | 7.1
- Email me at someone@example.com for pulls. | https://example.com/b | 2026-10-26 | 7.1
- A future rule. | https://example.com/c | 2026-10-26 | 7.3
- An insecure source. | http://example.com/d | 2026-10-26 | 7.1
- A line without the four parts.
"""
    r = parse_facts(bad, NOW, LIVE)
    assert not r.docs
    assert [reason for _, reason in r.dropped] == [
        "leak language",
        "personal data",
        "newer than the live game",
        "no https source",
        "malformed",
    ]


def test_the_published_file_parses_cleanly():
    text = Path(__file__).parents[1].joinpath("config/team_facts.md").read_text(encoding="utf-8")
    r = parse_facts(text, NOW, LIVE)
    assert r.kept_lines >= 70 and not r.dropped
    assert len({d.doc_id for d in r.docs}) == len(r.docs)


def test_the_published_builds_file_parses_into_its_own_docs():
    text = Path(__file__).parents[1].joinpath("config/team_builds.md").read_text(encoding="utf-8")
    r = parse_facts(text, NOW, LIVE, prefix="team-builds", what="builds")
    assert r.kept_lines >= 100 and not r.dropped
    assert all(d.doc_id.startswith("team-builds/") and d.kind == "team_builds" for d in r.docs)
    assert any(d.title.startswith("Escoffier builds") for d in r.docs)
    assert {d.source.tier for d in r.docs} <= {Tier.KQM, Tier.COMMUNITY}
