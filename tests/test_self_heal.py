"""The parts that keep the data current with nobody watching."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from irminsul.engine.engine import Engine
from irminsul.engine.exact import weapon_answer
from irminsul.engine.guards import BLOCKED_OUTPUT_REPLY, check_output
from irminsul.pipeline import freshness
from irminsul.pipeline.build import carried_docs, curated_guides, wiki_version
from irminsul.pipeline.gamedays import decide, game_days
from irminsul.pipeline.render import quest_doc, weapon_docs
from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier
from irminsul.sources import hoyowiki
from irminsul.sources.banners import proven_weapons
from irminsul.sources.guides import guide_urls, read_guide
from irminsul.sources.team_facts import parse_facts
from irminsul.sources.yatta import parse_quest

NOW = datetime(2026, 11, 6, 10, tzinfo=UTC)
RELEASED = Release(status=ReleaseStatus.RELEASED)
SOURCE = SourceRef(source="yatta", url="https://x.test", tier=Tier.OFFICIAL, fetched_at=NOW)
FEED = {
    "versions": {"7.1": "2026-09-23", "7.2": "2026-11-04"},
    "banners": [
        {
            "kind": "weapon",
            "version": "7.2",
            "start": "2026-11-04",
            "end": "2026-11-24",
            "five_stars": ["Starsealed Edict"],
            "four_stars": [],
        },
        {
            "kind": "character",
            "version": "7.2",
            "start": "2026-11-25",
            "end": "2026-12-15",
            "five_stars": ["Mitya"],
            "four_stars": [],
        },
    ],
}


def weapon_page():
    attributes = {
        "list": [
            {"key": "Name", "value": ["Starsealed Edict"]},
            {"key": "Source", "value": None},
            {"key": "Secondary Attributes", "value": ["CRIT DMG"]},
            {
                "key": "Dawnstar's Flowing Trail",
                "value": [
                    "Increases CRIT DMG by <color=#99FFFFFF>24%/30%/36%/42%/48%</color>. "
                    "EM by <color=#99FFFFFF>48/60/72/84/96</color> for 20s."
                ],
            },
        ]
    }
    component = {"component_id": "baseInfo", "data": json.dumps(attributes)}
    return {"desc": "A hefty tome.", "modules": [{"name": "Attributes", "components": [component]}]}


def official_weapon():
    entry = hoyowiki.OfficialEntry(
        "13625", "Starsealed Edict", {"weapon_rarity": ["5-Star"], "weapon_type": ["Catalyst"]}
    )
    return hoyowiki.released_weapon(entry, weapon_page(), NOW, NOW)


def test_a_weapon_on_a_started_wish_is_proven():
    assert proven_weapons(FEED, NOW) == {"Starsealed Edict": "2026-11-04"}


def test_weapon_from_its_official_page_has_each_refinement():
    w = official_weapon()
    assert (w.rarity, w.weapon_type, w.secondary_stat) == (5, "Catalyst", "CRIT DMG")
    assert w.passive_name == "Dawnstar's Flowing Trail"
    assert w.passive_by_refinement[0] == "Increases CRIT DMG by 24%. EM by 48 for 20s."
    assert w.passive_by_refinement[4] == "Increases CRIT DMG by 48%. EM by 96 for 20s."
    assert "R5: Increases CRIT DMG by 48%" in weapon_docs(w)[0].text


def test_a_weapon_page_with_no_passive_is_not_guessed():
    entry = hoyowiki.OfficialEntry("1", "Blank", {})
    page = weapon_page()
    page["modules"] = []
    assert hoyowiki.released_weapon(entry, page, NOW, NOW) is None


def test_exact_answer_works_without_base_atk():
    w = official_weapon()
    answer = weapon_answer(SimpleNamespace(entity=w), "What does Starsealed Edict's passive do?")
    assert "CRIT DMG by 24%" in answer.text
    assert "base ATK" not in answer.text


def freshness_build(tmp_path, weapons):
    (tmp_path / "banners.json").write_text(json.dumps(FEED), encoding="utf-8")
    (tmp_path / "characters.jsonl").write_text("", encoding="utf-8")
    lines = "\n".join(json.dumps({"name": n}) for n in weapons)
    (tmp_path / "weapons.jsonl").write_text(lines, encoding="utf-8")
    manifest = {"deep_at": "2026-10-01T00:00:00+00:00"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_freshness_catches_a_missing_weapon_and_an_old_deep_run(tmp_path):
    problems = freshness.check(freshness_build(tmp_path, []), NOW)
    assert any("Starsealed Edict" in p for p in problems)
    assert any("deep run" in p for p in problems)


def test_freshness_passes_once_the_weapon_is_there(tmp_path):
    problems = freshness.check(freshness_build(tmp_path, ["Starsealed Edict"]), NOW)
    assert not any("Starsealed Edict" in p for p in problems)


# ---- the game calendar ------------------------------------------------------------------
def test_game_days_come_from_the_notices():
    days = game_days(FEED)
    assert days["2026-11-04"] == "Version 7.2 starts"
    assert "wishes change" in days["2026-11-25"]
    assert days["2026-12-16"] == "the next version is expected"


def at(day):
    return datetime.fromisoformat(f"{day}T10:00:00+00:00")


def test_deep_runs_on_game_days_once():
    assert decide(FEED, at("2026-11-25"), "2026-11-20T10:00:00+00:00") is not None
    assert decide(FEED, at("2026-11-25"), "2026-11-25T02:00:00+00:00") is None


def test_deep_runs_on_endgame_resets_even_with_no_notices():
    assert decide({}, at("2026-11-16"), "2026-11-14T10:00:00+00:00") == "monthly endgame reset"


def test_quiet_days_stay_quick():
    assert decide(FEED, at("2026-11-10"), "2026-11-09T10:00:00+00:00") is None


def test_a_missed_week_heals_itself():
    assert decide({}, at("2026-11-10"), "2026-11-02T10:00:00+00:00") == "weekly refresh"
    assert decide({}, at("2026-11-10"), None) == "no deep run on record"


def test_deep_can_be_forced():
    assert decide({}, at("2026-11-10"), "2026-11-10T01:00:00+00:00", forced=True)


# ---- quests -----------------------------------------------------------------------------
QUEST = {
    "info": {"id": 1704, "type": "aq", "chapterNum": "Chapter VII: Act V", "chapterTitle": "Hour"},
    "storyList": {
        "0": {
            "info": {"title": "Like Melting Snow", "description": "Unusual activity."},
            "story": {
                "0": {"title": "Go to Snezhnograd", "isHidden": False},
                "1": {"title": "Go to Snezhnograd", "isHidden": False},
                "2": {"title": None, "isHidden": False},
                "3": {"title": "A secret", "isHidden": True},
                "4": {"title": "Talk to Vesna", "isHidden": False},
            },
        }
    },
}


def test_wiki_versions_read_the_luna_names():
    assert wiki_version("7.0") == "7.0"
    assert wiki_version("Luna VIII") == "6.7"
    assert wiki_version("soon") is None


def test_quest_keeps_objectives_in_order_and_skips_hidden_steps():
    quest = parse_quest(QUEST)
    assert quest["parts"] == [
        ("Like Melting Snow", "Unusual activity.", ["Go to Snezhnograd", "Talk to Vesna"])
    ]


def test_quest_doc_carries_its_version_for_story_safe_mode():
    doc = quest_doc(parse_quest(QUEST), "Archon Quest", RELEASED, SOURCE, "7.2")
    assert doc.doc_id == "quest/1704#main"
    assert doc.revealed_in == "7.2"
    assert "Objectives: Go to Snezhnograd; Talk to Vesna." in doc.text
    assert "Chapter VII: Act V" in doc.text


def test_a_quest_with_nothing_to_show_is_skipped():
    assert parse_quest({"info": {}, "storyList": {}}) is None


def test_wiki_quest_reads_linked_names():
    body = (
        '<table><tr><td><p>Unlock</p></td><td><p><custom-entry epid="1" name="Burn the Stables" '
        'menuid="31"></custom-entry> first</p></td></tr></table>'
    )
    attributes = {"list": [{"key": "Region", "value": ["<p>Snezhnaya</p>"]}]}
    page = {
        "modules": [
            {
                "name": "Attributes",
                "components": [{"component_id": "baseInfo", "data": json.dumps(attributes)}],
            },
            {
                "name": "Quest Information",
                "components": [{"component_id": "customize", "data": json.dumps({"data": body})}],
            },
        ]
    }
    quest = hoyowiki.quest_page(page)
    assert quest["region"] == "Snezhnaya"
    assert "Burn the Stables first" in quest["info"]


# ---- last good data ---------------------------------------------------------------------
def doc(doc_id, revealed_in=None):
    return Doc(
        doc_id=doc_id,
        entity_id=None,
        kind="quest",
        title="t",
        text="x",
        release=RELEASED,
        source=SOURCE,
        revealed_in=revealed_in,
    )


def previous_docs(tmp_path):
    rows = [
        doc("quest/1#main", "7.0"),
        doc("book/2#a"),
        doc("character/x#main"),
        doc("quest/3#main", "7.3"),
    ]
    text = "\n".join(d.model_dump_json() for d in rows)
    (tmp_path / "docs.jsonl").write_text(text + "\n", encoding="utf-8")
    return tmp_path


def test_slow_sources_carry_over_between_deep_runs(tmp_path):
    kept = {d.doc_id for d in carried_docs(previous_docs(tmp_path), ("yatta",), "7.2")}
    assert kept == {"quest/1#main", "book/2#a"}  # never a doc from after the live version


def test_a_source_that_was_read_is_not_carried(tmp_path):
    kept = {d.doc_id for d in carried_docs(previous_docs(tmp_path), ("quests",), "7.2")}
    assert kept == {"book/2#a"}


def test_no_previous_build_carries_nothing():
    assert carried_docs(None, ("yatta",), "7.2") == []


# ---- guides -----------------------------------------------------------------------------
def card(kind, name):
    image = f'<img src="a.webp" data-gi-type="{kind}" data-gi-id="1">'
    return f"<td>{image}<br><strong>{name}</strong></td>"


GUIDE = f"""
<meta property="article:modified_time" content="2026-11-20T03:14:32+00:00">
<h1><span></span>Artifacts</h1>
<h2>Artifact Stats</h2>
<table><tr><td><strong>Sands</strong></td><td><strong>Goblet</strong></td>
<td><strong>Circlet</strong></td></tr>
<tr><td>HP% or ER%</td><td>HP% &gt; Hydro DMG Bonus</td><td>CRIT Rate</td></tr></table>
<p class="substats"><strong>Stat Priority:</strong> ER &gt; CRIT</p>
<h2>Artifact Sets</h2>
<table><tr>{card("artifact", "<strong>4pc Golden Troupe (GT)</strong>")}
<td>Prose about Fake Set.</td></tr>
<tr>{card("artifact", "4pc Made Up Set")}</tr></table>
<h1>Weapons</h1>
<table><tr>{card("weapon", "Splendor of Tranquil Waters")}
<td>Better than Favonius Sword.</td></tr>
<tr>{card("weapon", "Uraku Misugiri (R5)")}</tr>
<tr>{card("weapon", "Sword That Does Not Exist")}</tr>
<tr>{card("weapon", "<span>5★ Festering Desire</span>")}</tr></table>
<h1>Teams</h1>
<table><tr>{card("weapon", "Favonius Sword")}</tr></table>
"""
WEAPONS = {"splendoroftranquilwaters", "urakumisugiri", "festeringdesire", "favoniussword"}
SETS = {"goldentroupe"}


def known(names):
    from irminsul.pipeline.gate import normalise_name

    return {normalise_name(n) for n in names}


def read():
    weapons = known(
        ["Splendor of Tranquil Waters", "Uraku Misugiri", "Festering Desire", "Favonius Sword"]
    )
    return read_guide(
        GUIDE, "https://keqingmains.com/q/x-quickguide/", weapons, known(["Golden Troupe"])
    )


def test_guide_reads_picks_in_order_and_only_from_their_section():
    build = read()
    assert build.weapons == ["Splendor of Tranquil Waters", "Uraku Misugiri", "Festering Desire"]
    assert build.sets == ["Golden Troupe"]


def test_guide_cannot_invent_an_item():
    text = " ".join(read().lines("7.2", "2026-11-20"))
    assert "Does Not Exist" not in text and "Made Up" not in text and "Fake" not in text


def test_guide_reads_stats_and_date():
    build = read()
    assert build.main_stats == "Sands HP% or ER%; Goblet HP% > Hydro DMG Bonus; Circlet CRIT Rate"
    assert build.priority == "ER > CRIT"
    assert build.modified == "2026-11-20"


def test_guide_lines_become_docs_marked_as_machine_read():
    lines = "\n".join(["## Furina", *read().lines("7.2", "2026-11-20")])
    docs = parse_facts(
        lines, NOW, (7, 2), prefix="auto-builds", what="builds", checked_by="read by machine"
    ).docs
    assert docs[0].doc_id == "auto-builds/furina#1"
    assert "read by machine" in docs[0].title
    assert docs[0].source.tier == Tier.KQM


def test_an_empty_guide_says_nothing():
    assert read_guide("<h1>Weapons</h1>", "https://x.test/", set(), set()).lines("7.2", "d") == []


def test_guide_urls_try_the_given_name():
    assert guide_urls("Mitya") == ["https://keqingmains.com/q/mitya-quickguide/"]
    assert guide_urls("Kamisato Ayaka")[1] == "https://keqingmains.com/q/ayaka-quickguide/"


def test_curated_guides_finds_what_to_watch():
    text = (
        "## Furina\n- A | https://keqingmains.com/q/furina-quickguide/ | 2026-11-05 | 7.2\n"
        "## Cyno\n- B | https://www.prydwen.gg/cyno | 2026-11-05 | 7.2\n"
    )
    assert curated_guides(text) == {
        "Furina": ("https://keqingmains.com/q/furina-quickguide/", "2026-11-05")
    }


# ---- answers ----------------------------------------------------------------------------
def test_ar_18_is_not_adult_content():
    text, flags = check_output("You need **AR 18+** to start this quest. [1]", [])
    assert flags == [] and "AR 18+" in text
    assert check_output("Some 18+ content", [])[0] == BLOCKED_OUTPUT_REPLY


def chunk(doc_id):
    return SimpleNamespace(chunk=SimpleNamespace(doc_id=doc_id))


def engine_for(name, slug, owners):
    character = SimpleNamespace(
        id=f"character/{slug}",
        name=name,
        source=SimpleNamespace(url="https://x.test", tier="official"),
    )
    engine = Engine.__new__(Engine)
    engine.store = SimpleNamespace(
        find=lambda q: [SimpleNamespace(kind="character", entity=character)]
    )
    engine.index = SimpleNamespace(
        chunks=[SimpleNamespace(doc_id=f"team-builds/{o}#1") for o in owners]
    )
    engine._build_owners = None
    return engine


def test_new_character_gets_a_plain_not_yet_instead_of_a_neighbours_build():
    engine = engine_for("Mitya", "mitya", ["cyno", "furina"])
    hits, answer = engine._own_builds("Best build for Mitya", [chunk("team-builds/cyno#1")])
    assert answer.route == "no_build"
    assert "don't have a checked build for Mitya" in answer.text


def test_other_characters_builds_are_dropped_from_a_build_question():
    engine = engine_for("Furina", "furina", ["cyno", "furina"])
    hits = [chunk("team-builds/cyno#1"), chunk("team-builds/furina#1"), chunk("character/furina#a")]
    kept, answer = engine._own_builds("Best build for Furina", hits)
    assert answer is None
    assert [h.chunk.doc_id for h in kept] == ["team-builds/furina#1", "character/furina#a"]


def test_team_questions_still_see_other_builds():
    engine = engine_for("Mitya", "mitya", ["cyno"])
    hits = [chunk("team-builds/cyno#1")]
    assert engine._own_builds("Who works well with Mitya?", hits) == (hits, None)
