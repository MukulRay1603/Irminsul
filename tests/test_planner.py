"""Daily planner data: extraction from saved Yatta responses, and the released-only route."""

import copy
import json

from conftest import FETCHED_AT, load_yatta
from fastapi.testclient import TestClient
from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.app import create_app
from irminsul.api.planner import add_planner
from irminsul.engine.engine import Engine
from irminsul.pipeline.planner import (
    build_planner,
    character_materials,
    parse_schedule,
    weapon_materials,
)
from irminsul.schema import Character, Release, ReleaseStatus, SourceRef, Tier
from irminsul.sources.yatta import parse_character, parse_weapon

WED, SAT = 3, 6


def planner_for(characters, weapons=()):
    raiden_mats = character_materials(load_yatta("avatar_10000052"))
    sac_mats = weapon_materials(load_yatta("weapon_11403"))
    return build_planner(
        characters,
        {c.id: raiden_mats for c in characters},
        weapons,
        {w.id: sac_mats for w in weapons},
        parse_schedule(load_yatta("dailyDungeon")),
        "71F2",
        FETCHED_AT.isoformat(),
    )


def raiden():
    return parse_character(
        load_yatta("avatar_10000052"), load_yatta("avatarCurve"), FETCHED_AT, "71F2"
    )


def sac_sword():
    return parse_weapon(load_yatta("weapon_11403"), load_yatta("weaponCurve"), FETCHED_AT, "71F2")


def unreleased(name="Nobody Yet"):
    return Character(
        id=f"character/{name.lower().replace(' ', '-')}",
        game_id="hoyowiki:1",
        name=name,
        rarity=5,
        element="Hydro",
        weapon_type="Sword",
        release=Release(status=ReleaseStatus.ANNOUNCED),
        source=SourceRef(
            source="hoyowiki",
            url="https://example.invalid",
            tier=Tier.OFFICIAL,
            fetched_at=FETCHED_AT,
        ),
    )


def test_schedule_groups_each_series_with_its_two_weekdays():
    schedule = parse_schedule(load_yatta("dailyDungeon"))
    light = next(s for s in schedule if "104326" in s["items"])
    assert light["kind"] == "mastery"
    assert light["days"] == [WED, SAT]  # Sunday is not a slot: everything is open then
    assert light["items"] == {"104326", "104327", "104328"}  # no Mora or EXP
    gladiator = next(s for s in schedule if "114009" in s["items"])
    assert gladiator["kind"] == "forgery" and gladiator["days"] == [WED, SAT]


def test_raiden_books_domain_days_and_weekly_boss():
    p = planner_for([raiden()], [sac_sword()])
    (c,) = p["characters"]
    assert c["id"] == "character/raiden-shogun" and c["books"] == ["104326"]
    assert c["weekly"] == "Molten Moment"
    book = p["books"]["104326"]
    assert book["name"] == "Light"
    assert book["items"] == ["Teachings of Light", "Guide to Light", "Philosophies of Light"]
    assert book["days"] == [WED, SAT] and book["region"] == "Inazuma"
    assert book["domain"]  # the domain variant's name, e.g. "Vine-Infested Ruins"
    assert len(p["books"]) == 1  # only series a planned character uses


def test_talent_cost_table_counts_books_by_rank():
    p = planner_for([raiden()])
    table = p["talent_costs"]
    assert len(table) == 9  # levels 2..10
    assert table[0] == [3, 0, 0, 0, 0]  # level 2: 3 Teachings
    assert table[5] == [0, 0, 4, 1, 0]  # level 7: 4 Philosophies, 1 weekly drop
    assert table[8] == [0, 0, 16, 2, 1]  # level 10: and the Crown
    assert sum(row[0] + row[1] + row[2] for row in table) == 3 + 21 + 38


def test_weapon_ascension_series():
    p = planner_for([raiden()], [sac_sword()])
    (w,) = p["weapons"]
    assert w["name"] == "Sacrificial Sword" and w["material"] == "114009"
    mat = p["weapon_materials"]["114009"]
    assert mat["days"] == [WED, SAT] and mat["items"][0] == "Fetters of the Dandelion Gladiator"


def test_announced_characters_never_reach_the_planner():
    p = planner_for([raiden(), unreleased()])
    assert [c["name"] for c in p["characters"]] == ["Raiden Shogun"]
    assert p["reset"]["hour"] == 4 and p["reset"]["servers"]["asia"] == 8


def test_mixed_series_like_the_traveler():
    # The Traveler's talents use books from three series and only some of each rarity, so the
    # 2-star book of a series may be missing from their item list. Series must still be keyed
    # and named consistently, and the weekly drop found by rarity, not by elimination.
    data = copy.deepcopy(load_yatta("avatar_10000052"))
    data["items"]["104324"] = {"name": "Guide to Elegance", "rank": 3}
    data["items"]["112099"] = {"name": "Some Enemy Drop", "rank": 1}
    for t in data["talent"].values():
        row = (t.get("promote") or {}).get("3")
        if row and row.get("costItems"):
            row["costItems"] = {"104324": 2, "112099": 3}
    mats = character_materials(data)
    p = build_planner(
        [raiden()],
        {"character/raiden-shogun": mats},
        [],
        {},
        parse_schedule(load_yatta("dailyDungeon")),
    )
    (c,) = p["characters"]
    assert c["books"] == ["104326", "104323"]  # Light, then Elegance (keyed by its 2-star id)
    assert p["books"]["104323"]["name"] == "Elegance" and p["books"]["104323"]["days"] == [2, 5]
    assert c["weekly"] == "Molten Moment"
    assert "talent_costs" not in c or c["talent_costs"][1][1] == 2  # level 3: 2 three-star books


def client(tmp_path, planner):
    (tmp_path / "planner.json").write_text(json.dumps(planner), encoding="utf-8")
    engine = Engine(store(), FakeIndex(), FakeLLM())
    app = create_app(engine)
    add_planner(app, engine.store, tmp_path)
    return TestClient(app)


def test_route_serves_released_only_with_cache_headers(tmp_path):
    planner = planner_for([raiden()], [sac_sword()])
    # A stale or edited file naming characters the store doesn't hold as released:
    leaked = dict(planner["characters"][0], id="character/mitya", name="Mitya", books=["999"])
    ghost = dict(planner["characters"][0], id="character/ghost", name="Ghost")
    planner["characters"] += [leaked, ghost]
    planner["books"]["999"] = {"name": "Secret", "items": [], "domain": "?", "days": [1]}
    c = client(tmp_path, planner)
    r = c.get("/api/planner")
    assert r.status_code == 200
    body = r.json()
    assert [ch["name"] for ch in body["characters"]] == ["Raiden Shogun"]
    assert "999" not in body["books"] and "Secret" not in r.text
    assert [w["name"] for w in body["weapons"]] == ["Sacrificial Sword"]
    assert "max-age" in r.headers["cache-control"] and r.headers["etag"]
    again = c.get("/api/planner", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_route_without_planner_data_is_404(tmp_path):
    engine = Engine(store(), FakeIndex(), FakeLLM())
    app = create_app(engine)
    add_planner(app, engine.store, tmp_path)
    assert TestClient(app).get("/api/planner").status_code == 404
