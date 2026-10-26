"""Patch notes: version mapping, the change history, /api/patches and the "what changed" intent."""

import json
from datetime import UTC, date, datetime

import pytest
from conftest import FETCHED_AT, load_yatta
from fastapi.testclient import TestClient
from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.app import create_app
from irminsul.api.patches import add_patches
from irminsul.engine import guards
from irminsul.engine.engine import Engine
from irminsul.engine.entities import EntityStore
from irminsul.engine.exact import is_patch_question
from irminsul.engine.patches import build_patch_notes
from irminsul.pipeline import diff as diff_cli
from irminsul.pipeline.history import accumulate, field_changes, make_entry, update
from irminsul.schema import Character, Release, ReleaseStatus, SourceRef, Tier
from irminsul.sources.yatta import parse_character, parse_weapon
from irminsul.versions import VERSIONS, released_versions, version_of

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# ---------- version mapping ----------


def test_version_table_is_ordered_unique_and_skips_6_8():
    versions = [v for v, _ in VERSIONS]
    dates = [d for _, d in VERSIONS]
    assert dates == sorted(dates) and len(set(versions)) == len(versions)
    assert "6.8" not in versions and versions[-2:] == ["7.0", "7.1"]


@pytest.mark.parametrize(
    ("released_at", "version"),
    [
        (utc(2020, 9, 27, 22), "1.0"),  # Yatta stamps the maintenance start, a day early
        (utc(2021, 8, 31, 21), "2.1"),  # Raiden Shogun
        (utc(2025, 9, 30, 15), "6.0"),  # a second-phase release stays in its version
        (utc(2026, 6, 29, 21), "6.7"),
        (utc(2026, 8, 10, 21), "7.0"),  # straight after 6.7: there is no 6.8
        (utc(2026, 9, 21, 21), "7.1"),
    ],
)
def test_release_timestamps_map_to_official_versions(released_at, version):
    assert version_of(released_at, released_versions(NOW)) == version


def test_no_version_is_dated_after_now():
    starts = released_versions(utc(2026, 9, 1))
    assert max(starts) == "7.0" and "7.1" not in starts
    assert version_of(utc(2019, 1, 1), starts) is None
    # A version the table doesn't list yet comes from the history, if it is already out
    later = released_versions(
        utc(2026, 11, 10), {"7.2": date(2026, 11, 4), "7.3": date(2027, 1, 1)}
    )
    assert "7.2" in later and "7.3" not in later


# ---------- change history ----------


def raiden_record() -> dict:
    c = parse_character(
        load_yatta("avatar_10000052"), load_yatta("avatarCurve"), FETCHED_AT, "71F2"
    )
    return json.loads(c.model_dump_json())


def manifest(ids: dict[str, str], built="2026-10-27T09:30:00+00:00", version="71F2") -> dict:
    return {
        "built_at": built,
        "sources": {"yatta": {"game_version": version}},
        "doc_hashes": ids,
    }


def test_first_build_is_a_baseline_not_a_list_of_everything():
    entry = make_entry({}, manifest({"character/raiden-shogun#overview": "a"}))
    assert entry == {
        "date": "2026-10-27",
        "version": "7.1",
        "data_version": "71F2",
        "baseline": True,
    }


def test_history_entry_lists_added_removed_changed_with_before_after():
    old_r, new_r = raiden_record(), raiden_record()
    new_r["base_stats"]["atk"] += 10
    burst = next(t for t in new_r["talents"] if t["kind"] == "burst")
    burst["description"] = "A new description."
    mitya = {"id": "character/mitya", "release": {"status": "announced"}}
    old = manifest(
        {"character/raiden-shogun#overview": "a", "weapon/old-blade#main": "b"},
        built="2026-10-26T09:30:00+00:00",
    )
    new = manifest(
        {
            "character/raiden-shogun#overview": "c",
            "weapon/new-blade#main": "d",
            "character/mitya#overview": "e",
            "kqm/guide#x": "f",
        }
    )
    old_records = {
        "character/raiden-shogun": old_r,
        "weapon/old-blade": {"release": {"status": "released"}},
    }
    new_records = {
        "character/raiden-shogun": new_r,
        "weapon/new-blade": {"release": {"status": "released"}},
        "character/mitya": mitya,
    }
    entry = make_entry(
        old, new, old_records, new_records, {"https://v/1"}, {"https://v/1", "https://v/2"}
    )
    assert entry["added"] == ["weapon/new-blade"]  # never the announced character
    assert entry["removed"] == ["weapon/old-blade"]
    assert entry["changed"] == ["character/raiden-shogun"]
    assert entry["videos"] == ["https://v/2"]
    fields = {f["field"]: f for f in entry["changes"]["character/raiden-shogun"]}
    atk = fields["Base ATK"]
    assert int(atk["after"].replace(",", "")) == int(atk["before"].replace(",", "")) + 10
    assert fields[burst["name"]]["after"] == "A new description."


def test_an_announced_character_released_today_counts_as_added():
    old = manifest({"character/mitya#overview": "a"}, built="2026-11-03T09:30:00+00:00")
    new = manifest({"character/mitya#overview": "b", "character/mitya#talents": "c"})
    entry = make_entry(
        old,
        new,
        {"character/mitya": {"release": {"status": "announced"}}},
        {"character/mitya": {"release": {"status": "released"}}},
    )
    assert entry["added"] == ["character/mitya"] and entry["changed"] == []


def test_nothing_changed_keeps_the_history_as_it_is():
    m = manifest({"weapon/a#main": "x", "kqm/guide#1": "y"})
    m2 = manifest({"weapon/a#main": "x", "kqm/guide#1": "z"})  # a guide edit is not a patch change
    assert make_entry(m, m2) is None
    history = {"schema": 1, "entries": [{"date": "2026-10-26", "version": "7.1", "baseline": True}]}
    assert accumulate(history, None) == history
    grown = accumulate(history, {"date": "2026-10-27", "version": "7.1", "added": ["weapon/b"]})
    assert [e["date"] for e in grown["entries"]] == ["2026-10-26", "2026-10-27"]


def test_weapon_passive_changes_show_per_refinement():
    old = {"base_atk": 454.4, "secondary_stat": "Energy Recharge", "secondary_value": 0.613}
    old |= {"passive_name": "Composed", "passive_by_refinement": ["40%", "50%"]}
    new = {**old, "passive_by_refinement": ["40%", "55%"]}
    assert field_changes("weapon", old, new) == [
        {"field": "Composed R2", "before": "50%", "after": "55%"}
    ]


def test_daily_diff_accumulates_history_json(tmp_path, monkeypatch):
    prev, build = tmp_path / "prev", tmp_path / "build"
    prev.mkdir()
    build.mkdir()
    old = manifest({"weapon/a#main": "x"}, built="2026-10-26T09:30:00+00:00")
    (prev / "manifest.json").write_text(json.dumps(old), encoding="utf-8")
    (prev / "history.json").write_text(
        json.dumps(update({}, old, prev, prev, None)), encoding="utf-8"
    )
    new = manifest({"weapon/a#main": "x", "weapon/b#main": "y"})
    (build / "manifest.json").write_text(json.dumps(new), encoding="utf-8")
    argv = ["irminsul-diff", "--old", str(prev / "manifest.json"), "--new"]
    argv += [str(build / "manifest.json"), "--history", str(prev / "history.json")]
    argv += ["--history-out", str(build / "history.json")]
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit):
        diff_cli.main()
    entries = json.loads((build / "history.json").read_text(encoding="utf-8"))["entries"]
    assert entries[0]["baseline"] and entries[1]["added"] == ["weapon/b"]
    assert entries[1]["date"] == "2026-10-27" and entries[1]["version"] == "7.1"


# ---------- patch notes and /api/patches ----------


def announced(name: str) -> Character:
    return Character(
        id=f"character/{name.lower()}",
        game_id="hoyowiki:1",
        name=name,
        rarity=5,
        element="Cryo",
        weapon_type="Sword",
        region="Snezhnaya",
        constellations=[],
        release=Release(status=ReleaseStatus.ANNOUNCED),
        source=SourceRef(
            source="hoyowiki", url="https://wiki.hoyolab.com/x", tier=Tier.OFFICIAL, fetched_at=NOW
        ),
    )


def patch_store() -> EntityStore:
    raiden = parse_character(
        load_yatta("avatar_10000052"), load_yatta("avatarCurve"), FETCHED_AT, "71F2"
    )
    vesna = raiden.model_copy(
        update={
            "id": "character/vesna",
            "name": "Vesna",
            "release": Release(status=ReleaseStatus.RELEASED, released_at=utc(2026, 9, 21, 21)),
        }
    )
    future = raiden.model_copy(
        update={
            "id": "character/tomorrow",
            "name": "Tomorrow",
            "release": Release(status=ReleaseStatus.RELEASED, released_at=utc(2026, 11, 3, 21)),
        }
    )
    sac = parse_weapon(load_yatta("weapon_11403"), load_yatta("weaponCurve"), FETCHED_AT, "71F2")
    return EntityStore([raiden, vesna, future, announced("Valeriy")], [sac], [])


HISTORY = {
    "entries": [
        {"date": "2026-09-01", "version": "7.0", "baseline": True},
        {
            "date": "2026-09-24",
            "version": "7.1",
            "added": ["weapon/sacrificial-sword", "character/valeriy", "weapon/ghost"],
            "changed": ["character/raiden-shogun", "character/valeriy"],
            "changes": {
                "character/raiden-shogun": [{"field": "Base ATK", "before": "337", "after": "347"}],
                "character/valeriy": [{"field": "Secret", "before": "a", "after": "b"}],
            },
            "videos": ["https://youtu.be/vesna", "https://youtu.be/valeriy"],
        },
        {"date": "2027-01-01", "version": "7.3", "added": ["weapon/sacrificial-sword"]},
    ]
}
VIDEOS = {
    "character/vesna": [
        {"entity_id": "character/vesna", "title": "Vesna demo", "url": "https://youtu.be/vesna"}
    ],
    "character/valeriy": [
        {"entity_id": "character/valeriy", "title": "Teaser", "url": "https://youtu.be/valeriy"}
    ],
}


def notes() -> dict:
    return build_patch_notes(patch_store(), HISTORY, VIDEOS, NOW)


def test_patch_notes_are_released_only_and_cite_sources():
    n = notes()
    assert n["live"] == "7.1" and n["versions"][0]["version"] == "7.1"
    assert [v["version"] for v in n["versions"]] == sorted(
        (v["version"] for v in n["versions"]),
        key=lambda v: tuple(map(int, v.split("."))),
        reverse=True,
    )
    v71 = n["versions"][0]
    assert [c["name"] for c in v71["characters"]] == ["Vesna"]  # not "Tomorrow" (future date)
    assert [w["id"] for w in v71["weapons"]] == ["weapon/sacrificial-sword"]
    assert [c["id"] for c in v71["changes"]] == ["character/raiden-shogun"]
    assert v71["changes"][0]["fields"][0] == {"field": "Base ATK", "before": "337", "after": "347"}
    assert [v["url"] for v in v71["videos"]] == ["https://youtu.be/vesna"]
    assert all(
        x["source"].startswith("https://") for g in ("characters", "weapons") for x in v71[g]
    )
    assert all(v["version"] != "7.3" for v in n["versions"])  # nothing dated in the future
    text = json.dumps(n)
    assert "Secret" not in text and "Teaser" not in text and "weapon/ghost" not in text
    assert n["announced"] == [
        {
            "id": "character/valeriy",
            "name": "Valeriy",
            "element": "Cryo",
            "region": "Snezhnaya",
            "source": "https://wiki.hoyolab.com/x",
        }
    ]
    raiden_version = next(
        v for v in n["versions"] if any(c["name"] == "Raiden Shogun" for c in v["characters"])
    )
    assert raiden_version["version"] == "2.1"
    assert n["tracking_since"] == "2026-09-01" and v71["tracked"]
    assert not next(v for v in n["versions"] if v["version"] == "6.7")["tracked"]


def test_api_patches_serves_notes_with_cache_headers():
    engine = Engine(patch_store(), FakeIndex(), FakeLLM())
    app = create_app(engine)
    add_patches(app, notes())
    c = TestClient(app)
    r = c.get("/api/patches")
    assert r.status_code == 200 and r.json()["live"] == "7.1"
    assert "max-age" in r.headers["cache-control"] and r.headers["etag"]
    assert c.get("/api/patches", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    body = r.text
    assert "Tomorrow" not in body and "Secret" not in body and "constellations" not in body


# ---------- the "what changed" intent ----------


def test_patch_questions_are_recognised_without_hijacking_others():
    for q in [
        "What changed in 7.1?",
        "What's new this patch?",
        "what's new",
        "New characters in 6.0",
        "Patch notes for version 5.8",
    ]:
        assert is_patch_question(q), q
    for q in [
        "What's new with the Spiral Abyss?",
        "Best new team in 7.1?",
        "How does pity work on the weapon banner?",
    ]:
        assert not is_patch_question(q), q
    s = store()
    assert guards.check("What's new this patch?", s, guards.GuardConfig()) is None
    assert guards.check("What changed in 7.4?", s, guards.GuardConfig()).route == "refuse_leak"


def test_what_changed_is_answered_exactly_with_a_patch_card():
    llm = FakeLLM()
    engine = Engine(patch_store(), FakeIndex(), llm, patches=notes())
    a = engine.ask("What changed in 7.1?")
    assert a.route == "exact" and llm.calls == 0
    assert "Vesna" in a.text and "Sacrificial Sword" in a.text and "Raiden Shogun" in a.text
    assert a.citations[0].url.startswith("https://genshin.hoyoverse.com")
    assert a.card["type"] == "patch" and a.card["version"] == "7.1"
    assert a.card["groups"][0]["items"][0]["name"] == "Vesna"
    assert a.card["changes"][0]["fields"] == ["Base ATK"]
    assert engine.ask("What's new this patch?").card["version"] == "7.1"
    old = engine.ask("What was new in 2.1?")
    assert "Raiden Shogun" in old.text and "tracked from" in old.text


def test_unreleased_version_gets_names_only():
    engine = Engine(patch_store(), FakeIndex(), FakeLLM(), patches=notes())
    a = engine.ask("What's new in 7.2?")
    assert a.route == "exact" and "isn't out yet" in a.text and "Valeriy" in a.text
    assert a.card == {
        "type": "patch",
        "version": "7.2",
        "upcoming": True,
        "live": "7.1",
        "announced": [{"name": "Valeriy", "element": "Cryo"}],
    }
    assert "no Version 6.8" in engine.ask("What changed in 6.8?").text
