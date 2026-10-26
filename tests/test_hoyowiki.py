"""HoYoWiki parser tests against trimmed real API responses (fetched Oct 26 2026)."""

import json
from datetime import UTC, datetime

from conftest import FETCHED_AT, FIXTURES

from irminsul.pipeline.build import fetch_official
from irminsul.pipeline.render import character_docs
from irminsul.schema import Character, Release, ReleaseStatus, SourceRef, Tier
from irminsul.sources import hoyowiki


def load(name: str) -> dict:
    return json.loads((FIXTURES / "hoyowiki" / f"{name}.json").read_text(encoding="utf-8"))


def entries(name: str) -> list[hoyowiki.OfficialEntry]:
    return [hoyowiki.parse_entry(raw) for raw in load(name)["data"]["list"]]


def page(name: str) -> dict:
    return load(name)["data"]["page"]


def test_parse_entry_filters():
    mitya = next(e for e in entries("list_characters") if e.name == "Mitya")
    assert mitya.entry_id == "11827"
    assert mitya.first("character_vision") == "Electro"


def test_kit_detection():
    # Mitya's official page exists, but its talent/constellation/ascension modules are empty.
    assert not hoyowiki.page_has_kit(page("page_mitya"))
    assert hoyowiki.page_has_kit(page("page_lisa"))


def test_announced_character_is_overview_only():
    mitya_entry = next(e for e in entries("list_characters") if e.name == "Mitya")
    c = hoyowiki.announced_character(mitya_entry, page("page_mitya"), FETCHED_AT)
    assert c.id == "character/mitya"
    assert c.release.status == ReleaseStatus.ANNOUNCED
    assert c.source.tier == Tier.OFFICIAL
    assert c.source.url == "https://wiki.hoyolab.com/pc/genshin/entry/11827"
    assert (c.element, c.talents, c.constellations, c.base_stats) == ("Electro", [], [], None)
    assert c.summary and "<" not in c.summary
    docs = character_docs(c)
    assert [d.doc_id for d in docs] == ["character/mitya#overview"]
    assert "not yet playable" in docs[0].text and "Talents" not in docs[0].text
    assert "Unknown" not in docs[0].text and "Electro character" in docs[0].text


def test_beta_pages_are_skipped():
    beta = dict(page("page_mitya"), beta=True)
    mitya_entry = next(e for e in entries("list_characters") if e.name == "Mitya")
    assert hoyowiki.announced_character(mitya_entry, beta, FETCHED_AT) is None


def test_official_videos():
    videos = hoyowiki.parse_videos(page("page_mitya"), "character/mitya", FETCHED_AT)
    trailer = next(v for v in videos if v.group == "Character Details")
    assert trailer.youtube_id == "y2Zcmcbrm9s"
    assert trailer.source.tier == Tier.OFFICIAL
    assert hoyowiki.youtube_id("https://youtu.be/QgLZe9BtRJE") == "QgLZe9BtRJE"
    assert hoyowiki.youtube_id("https://example.org/video") is None


def _released(name: str) -> Character:
    return Character(
        id=f"character/{name.lower().replace(' (', '-').rstrip(')')}",
        game_id="0",
        name=name,
        rarity=4,
        element="Electro",
        weapon_type="Catalyst",
        release=Release(
            status=ReleaseStatus.RELEASED, released_at=datetime(2020, 9, 28, tzinfo=UTC)
        ),
        source=SourceRef(
            source="yatta", url="https://gi.yatta.moe", tier=Tier.OFFICIAL, fetched_at=FETCHED_AT
        ),
    )


class FakeWiki:
    pages = {"11827": "page_mitya", "11828": "page_mitya", "2": "page_lisa"}

    def entries(self, menu_id: str) -> list[hoyowiki.OfficialEntry]:
        return entries(
            {"2": "list_characters", "4": "list_weapons", "5": "list_artifacts"}[menu_id]
        )

    def page(self, entry_id: str) -> dict:
        return page(self.pages.get(entry_id, "page_lisa"))


def test_fetch_official_finds_announced_but_not_traveler_hub():
    live = [_released("Lisa"), _released("Traveler (Cryo)")]
    official = fetch_official(FakeWiki(), live, FETCHED_AT, limit=None)
    assert sorted(c.name for c in official.announced) == ["Mitya", "Valeriy"]
    assert "Breezeborne Refrain" in official.names["weapons"]
    assert any(v.entity_id == "character/mitya" for v in official.videos)


def test_partial_builds_never_mark_announced():
    official = fetch_official(FakeWiki(), [_released("Lisa")], FETCHED_AT, limit=2)
    assert official.announced == []
