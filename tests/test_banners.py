# ruff: noqa: E501  (sample notices mirror the real text)
"""Official wish notices as data: banners, who is proven live, and the freshness check."""

import json
from datetime import UTC, date, datetime

from test_engine import FakeIndex, FakeLLM, store

from irminsul.engine.engine import Engine
from irminsul.engine.exact import banner_answer
from irminsul.pipeline.freshness import check
from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier
from irminsul.sources import hoyowiki
from irminsul.sources.banners import active, parse_banners, proven_live, upcoming

NOW = datetime(2026, 11, 6, tzinfo=UTC)
PHASE_I = """# Version 7.2 Event Wishes Notice - Phase I
News published by HoYoverse on 2026-11-02.
Event Wish "Myriad Patterns Unfold" - Boosted drop rate for "Rules Set at Naught" Mitya (Electro)!
Travelers, stock up on weapons and characters in the event wish to make your party stronger in combat!
〓Event Wish Duration〓
After the Version 7.2 update—2026/11/24 17:59
〓Event Wish Details〓
● During this event wish, the event-exclusive 5-star character "Rules Set at Naught" Mitya (Electro) will receive a huge drop-rate boost!
● During this event wish, the 4-star characters "Fort Fulguration" Valeriy (Electro), "Lens of Verity" Charlotte (Cryo), and "Thorny Benevolence" Rosaria (Cryo) will receive a huge drop-rate boost!
Event Wish "Epitome Invocation" - Boosted Drop Rate for Starsealed Edict (Catalyst) and Splendor of Tranquil Waters (Sword)!
〓Event Wish Duration〓
After the Version 7.2 update—2026/11/24 17:59
〓Event Wish Details〓
● During this event wish, the event-exclusive 5-star weapons Starsealed Edict (Catalyst) and Splendor of Tranquil Waters (Sword) will receive a huge drop-rate boost!
● During the event, the event-exclusive 4-star weapons The Dockhand's Assistant (Sword), Prospector's Drill (Polearm), as well as the 4-star weapons Rainslasher (Claymore) and Rust (Bow) will receive a huge drop rate boost!
"""
PHASE_II = """# Version 7.2 Event Wishes Notice - Phase II
News published by HoYoverse on 2026-11-20.
Event Wish "Later Wish" - Boosted Drop Rate for "A Title" Zibai (Geo)!
〓Event Wish Duration〓
2026/11/24 18:00–2026/12/15 14:59
〓Event Wish Details〓
● During this event wish, the event-exclusive 5-star character "A Title" Zibai (Geo) will receive a huge drop-rate boost!
"""
UPDATE = """# "Hour of Ruin" Version 7.2 Update Details
Update notice published by HoYoverse on 2026-11-03.
〓Update Schedule〓
Update maintenance begins 2026/11/04 06:00 (UTC+8) and is estimated to take 5 hours.
"""


def doc(i: int, title: str, text: str) -> Doc:
    return Doc(
        doc_id=f"notice/{i}",
        entity_id=None,
        kind="official_notice",
        title=title,
        text=text,
        release=Release(status=ReleaseStatus.RELEASED),
        source=SourceRef(
            source="hoyoverse_news",
            url=f"https://genshin.hoyoverse.com/en/news/detail/{i}",
            tier=Tier.OFFICIAL,
            fetched_at=NOW,
        ),
    )


def feed() -> dict:
    return parse_banners(
        [
            doc(1, "Version 7.2 Event Wishes Notice - Phase I (news, 2026-11-02)", PHASE_I),
            doc(2, "Version 7.2 Event Wishes Notice - Phase II (news, 2026-11-20)", PHASE_II),
            doc(3, '"Hour of Ruin" Version 7.2 Update Details (update notice)', UPDATE),
        ]
    )


def test_notices_become_banners_with_the_right_dates():
    f = feed()
    assert f["versions"] == {"7.2": "2026-11-04"}
    by_name = {b["name"]: b for b in f["banners"]}
    mitya = by_name["Myriad Patterns Unfold"]
    # The date in the notice is the END: the mistake the model made
    assert (mitya["start"], mitya["end"]) == ("2026-11-04", "2026-11-24")
    assert mitya["five_stars"] == ["Mitya"]
    assert mitya["four_stars"] == ["Valeriy", "Charlotte", "Rosaria"]
    weapons = by_name["Epitome Invocation"]
    assert weapons["kind"] == "weapon"
    assert weapons["five_stars"] == ["Starsealed Edict", "Splendor of Tranquil Waters"]
    assert "Rainslasher" in weapons["four_stars"] and "Rust" in weapons["four_stars"]
    assert by_name["Later Wish"]["start"] == "2026-11-24"


def test_only_started_wishes_prove_someone_is_live():
    live = proven_live(feed(), NOW)
    assert live["Mitya"] == "2026-11-04" and live["Valeriy"] == "2026-11-04"
    assert "Zibai" not in live  # Phase II hasn't opened
    assert "Starsealed Edict" not in live  # weapons aren't characters


def test_whats_on_now_is_read_by_code():
    today = NOW.date()
    assert {b["name"] for b in active(feed(), today)} == {
        "Myriad Patterns Unfold",
        "Epitome Invocation",
    }
    assert [b["name"] for b in upcoming(feed(), today)] == ["Later Wish"]
    a = banner_answer(feed(), "What are the current banners?")
    assert a.route == "exact" and "Mitya" in a.text and "24 November 2026" in a.text
    assert a.citations[0].url.endswith("/1") or a.citations[0].url.endswith("/2")
    assert banner_answer(feed(), "Should I pull on the current banner?") is None
    assert banner_answer(feed(), "What does Sacrificial Sword do?") is None
    assert banner_answer({}, "What are the current banners?") is None


def test_engine_uses_the_banners():
    llm = FakeLLM()
    engine = Engine(store(), FakeIndex(), llm, banners=feed())
    a = engine.ask("Who is on the banner right now?")
    assert a.route == "exact" and llm.calls == 0


def page() -> dict:
    def component(cid, payload):
        return {"component_id": cid, "data": json.dumps(payload)}

    talents = [
        {
            "title": f"Talent {i}",
            "desc": "Deals <span>Electro DMG</span>.<br>More.",
            "attributes": [
                {"key": "Level", "values": ["Lv.1", "Lv.2"]},
                {"key": "Skill DMG", "values": ["100%", "110%"]},
            ]
            if i < 3
            else None,
        }
        for i in range(5)
    ]
    return {
        "desc": "An official summary.",
        "beta": False,
        "modules": [
            {
                "name": "Attributes",
                "components": [
                    component(
                        "baseInfo", {"list": [{"key": "Title", "value": ["<p>A Great Title</p>"]}]}
                    )
                ],
            },
            {
                "name": "Ascend",
                "components": [
                    component(
                        "ascension",
                        {
                            "list": [
                                {
                                    "key": "Lv.90",
                                    "combatList": [
                                        {"key": "", "values": ["Before", "After"]},
                                        {"key": "Base HP", "values": ["11634", "-"]},
                                        {"key": "Base ATK", "values": ["263", "-"]},
                                        {"key": "Base DEF", "values": ["792", "-"]},
                                        {"key": "CRIT DMG Bonus", "values": ["38.4%", "-"]},
                                    ],
                                }
                            ]
                        },
                    )
                ],
            },
            {"name": "Talents", "components": [component("talent", {"list": talents})]},
            {
                "name": "Constellation",
                "components": [
                    component(
                        "summaryList",
                        {"list": [{"name": f"C{i}", "desc": "Text."} for i in range(1, 7)]},
                    )
                ],
            },
        ],
    }


ENTRY = hoyowiki.OfficialEntry(
    "11827",
    "Mitya",
    {
        "character_rarity": ["5-Star"],
        "character_vision": ["Electro"],
        "character_weapon": ["Catalyst"],
        "character_region": ["Snezhnaya"],
    },
)


def test_a_proven_character_is_built_from_the_official_page():
    c = hoyowiki.released_character(ENTRY, page(), NOW, NOW)
    assert c.release.status == ReleaseStatus.RELEASED and c.title == "A Great Title"
    assert (c.base_stats.hp, c.base_stats.bonus_stat) == (11634, "CRIT DMG")
    assert abs(c.base_stats.bonus_value - 0.384) < 1e-9
    assert [t.kind for t in c.talents] == ["normal_attack", "skill", "burst", "passive", "passive"]
    assert c.talents[1].scaling[0].by_level == {1: "100%", 2: "110%"}
    assert c.talents[0].description == "Deals Electro DMG.\nMore."
    assert [x.level for x in c.constellations] == [1, 2, 3, 4, 5, 6]


def test_an_empty_or_beta_page_stays_announced():
    empty = {"desc": "x", "beta": False, "modules": []}
    assert hoyowiki.released_character(ENTRY, empty, NOW, NOW) is None
    assert hoyowiki.released_character(ENTRY, {**page(), "beta": True}, NOW, NOW) is None


def write_build(tmp_path, status="released", version="72F1", f=None):
    rows = [{"name": "Mitya", "release": {"status": status}}]
    rows += [
        {"name": n, "release": {"status": "released"}} for n in ("Valeriy", "Charlotte", "Rosaria")
    ]
    (tmp_path / "characters.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"sources": {"yatta": {"game_version": version}}}), encoding="utf-8"
    )
    (tmp_path / "banners.json").write_text(json.dumps(feed() if f is None else f), encoding="utf-8")
    return tmp_path


def test_freshness_passes_when_the_build_matches_the_notices(tmp_path):
    assert check(write_build(tmp_path), NOW) == []


def test_freshness_catches_what_went_wrong_with_mitya(tmp_path):
    problems = check(write_build(tmp_path, status="announced"), NOW)
    assert any("Mitya" in p for p in problems)


def test_freshness_catches_stale_game_data_and_a_broken_parser(tmp_path):
    assert any("7.2" in p for p in check(write_build(tmp_path, version="71F2"), NOW))
    assert check(write_build(tmp_path, f={}), NOW) == [
        "no wish banners parsed from the official notices"
    ]
    assert any(
        "no wish is open" in p
        for p in check(write_build(tmp_path), datetime(2027, 6, 1, tzinfo=UTC))
    )
    assert date(2026, 11, 6) == NOW.date()


def test_playable_is_answered_from_the_release_record():
    llm = FakeLLM()
    e = Engine(store(), FakeIndex(), llm)
    a = e.ask("Is Raiden Shogun playable yet?")
    assert (
        a.route == "exact"
        and a.text.startswith("**Yes, Raiden Shogun is playable")
        and llm.calls == 0
    )
    # Announced characters keep their own honest answer
    assert e.ask("Is Mitya playable yet?").route == "announced"
