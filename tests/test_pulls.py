"""Pull math: odds against published figures, savings by addition, and the leak hold."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.pulls import add_pulls, upcoming
from irminsul.engine import pulls
from irminsul.engine.engine import Engine


def test_the_model_matches_published_figures():
    wait = pulls.five_star_wait("character", 0)
    assert wait[:74].sum() == pytest.approx(0.356, abs=0.002)  # by pull 73
    assert (range(91) * wait).sum() == pytest.approx(62.5, abs=0.5)  # 1.6% consolidated
    assert wait.sum() == pytest.approx(1.0)
    assert pulls.odds(0).worst == 180 and pulls.odds(0, "weapon").worst == 160
    assert pulls.odds(90).expected == pytest.approx(90.6, abs=1)
    assert pulls.odds(0, "weapon").expected == pytest.approx(87.8, abs=2)


def test_worst_cases_are_truly_guaranteed():
    assert pulls.odds(180).chance == pytest.approx(1.0)
    assert pulls.odds(160, "weapon").chance == pytest.approx(1.0)
    assert pulls.odds(90, guaranteed=True).chance == pytest.approx(1.0)
    assert pulls.odds(50, pity=40, guaranteed=True).chance == pytest.approx(1.0)
    assert pulls.odds(10).chance < pulls.odds(80).chance < pulls.odds(160).chance
    assert pulls.odds(150, copies=2).chance < pulls.odds(150).chance


def test_reading_a_players_stash():
    s = pulls.read_stash("I have 8,000 primos, 20 fates, pity 40, guaranteed. Chances for C1?")
    assert (s.wishes, s.pity, s.guaranteed, s.copies, s.banner) == (70, 40, True, 2, "character")
    assert pulls.read_stash("50 pulls on the weapon banner").banner == "weapon"
    assert not pulls.read_stash("I'm not guaranteed, 30 pity, 10 wishes").guaranteed
    assert pulls.read_stash("how does pity work?") is None


def test_savings_are_plain_addition():
    est = pulls.income(date(2026, 11, 5), date(2027, 1, 27))
    lines = dict(est.lines)
    assert lines["Daily Commissions"] == 83 * 60
    assert lines["Spiral Abyss resets"] == 3 * 800  # Nov 16, Dec 16, Jan 16
    assert lines["Imaginarium Theater resets"] == 2 * 800  # Dec 1, Jan 1
    assert est.shop_fates == 10
    assert est.primos == sum(lines.values())
    assert pulls.version_start((7, 3)) == date(2026, 12, 16)
    assert pulls.version_start((7, 4), 2) == date(2027, 2, 17)
    assert pulls.version_start((8, 0)) > pulls.version_start((7, 7))


def test_odds_and_savings_are_free_exact_answers():
    llm = FakeLLM()
    engine = Engine(store(), FakeIndex(), llm)
    a = engine.ask("I have 8000 primos and 20 fates at pity 40, what are my chances?")
    assert a.route == "exact" and "70 wishes" in a.text and llm.calls == 0
    b = engine.ask("How many primos can I save by 7.4 phase 1?")
    assert b.route == "exact" and "free Primogems" in b.text and llm.calls == 0
    assert engine.is_free("How many primos can I save by 7.4 phase 1?")


def test_a_leak_gets_refused_then_only_the_sum():
    llm = FakeLLM()
    engine = Engine(store(), FakeIndex(), llm)
    a = engine.ask("I saw a leak about a pyro polearm lady in 7.4, how many pulls can I have?")
    assert a.route == "refuse_leak" and llm.calls == 0
    assert "free Primogems" in a.text and "7.4 Phase 1" in a.text
    assert "says nothing about what that version contains" in a.text
    for word in ("pyro", "polearm", "lady"):  # nothing from the leak is repeated back
        assert word not in a.text.lower()
    # A future version with no savings question stays a plain refusal
    b = engine.ask("Who is coming in 7.4?")
    assert b.route == "refuse_leak"


def test_api_takes_numbers_only_and_keeps_nothing():
    app = FastAPI()
    add_pulls(app)
    c = TestClient(app)
    o = c.get("/api/pulls/odds", params={"wishes": 90, "pity": 10}).json()
    assert 0 < o["chance"] < 1 and o["worst"] == 170
    assert c.get("/api/pulls/odds", params={"wishes": -1}).status_code == 422
    assert c.get("/api/pulls/odds", params={"wishes": 5, "banner": "x"}).status_code == 422
    targets = c.get("/api/pulls/targets").json()["targets"]
    assert len(targets) == 8
    e = c.get("/api/pulls/income", params={"until": targets[3]["date"]}).json()
    assert e["primos"] > 0 and e["wishes"] >= e["primos"] // 160
    assert c.get("/api/pulls/income", params={"until": "2099-01-01"}).status_code == 422


def test_upcoming_lists_future_phases_only():
    rows = upcoming(date(2026, 11, 5), 3)
    assert [r["label"] for r in rows] == ["7.2 Phase 2", "7.3 Phase 1", "7.3 Phase 2"]
