"""Sums in answers: each expected value is worked by hand from KQM's formula files."""

from datetime import UTC, datetime

import pytest

from irminsul.engine import calc
from irminsul.engine.grounding import best_quote

PLANNER = {
    "reset": {"hour": 4, "servers": {"america": -5, "europe": 1, "asia": 8}},
    "talent_costs": [
        [3, 0, 0, 0, 0],
        [0, 2, 0, 0, 0],
        [0, 4, 0, 0, 0],
        [0, 6, 0, 0, 0],
        [0, 9, 0, 0, 0],
        [0, 0, 4, 1, 0],
        [0, 0, 6, 1, 0],
        [0, 0, 12, 2, 0],
        [0, 0, 16, 2, 1],
    ],
    "books": {
        "1": {"items": ["Teachings of Freedom"], "domain": "Frosted Altar", "days": [1, 4]},
        "2": {"items": ["Teachings of Justice"], "domain": "Pale Forgotten Glory", "days": [2, 5]},
    },
    "characters": [{"name": "Amber", "books": ["1"]}, {"name": "Furina", "books": ["2"]}],
}


@pytest.mark.parametrize(
    "em,reaction,expected",
    [
        (800, "vaporize", 2.78 * 800 / 2200),
        (1000, "swirl", 16 * 1000 / 3000),
        (200, "aggravate", 5 * 200 / 1400),
    ],
)
def test_em_bonus_matches_the_formula(em, reaction, expected):
    assert calc.em_bonus(em, reaction) == pytest.approx(expected)


def test_em_question_shows_its_working():
    answer = calc.calculate("How much does 800 EM add to Vaporize?", None)
    assert "101.1%" in answer.text and "2.78 × 800" in answer.text
    assert answer.citations[0].tier == "kqm"


def test_def_multiplier():
    assert calc.def_multiplier(90, 100) == pytest.approx(190 / 390)
    answer = calc.calculate("DEF multiplier for level 90 vs level 100 with 30% DEF shred", None)
    assert f"{190 / (190 + 200 * 0.7):.1%}" in answer.text


def test_def_reduction_is_capped():
    answer = calc.calculate("DEF multiplier level 90 vs level 100 with 95% def shred", None)
    assert "90% DEF reduction" in answer.text


@pytest.mark.parametrize("res,expected", [(-0.2, 1.1), (0.1, 0.9), (0.75, 0.25), (1.0, 0.2)])
def test_res_multiplier_branches(res, expected):
    assert calc.res_multiplier(res) == pytest.approx(expected)


def test_res_question_applies_shred():
    answer = calc.calculate("Resistance multiplier at 10% res with 40% shred", None)
    assert "-30%" in answer.text and "115.0%" in answer.text


def test_talent_cost_sums_the_table():
    answer = calc.calculate("How many books for a talent from 1 to 10?", PLANNER)
    assert "3 Teachings, 21 Guides and 38 Philosophies" in answer.text
    assert "6 weekly boss drops and 1 Crown" in answer.text


def test_missing_numbers_are_never_guessed():
    assert calc.calculate("How does EM affect Vaporize?", PLANNER) is None
    assert calc.calculate("How many books does a talent need?", PLANNER) is None
    assert calc.calculate("Talent books from 8 to 40?", PLANNER) is None


def test_formulas_stay_off_with_kqm():
    assert calc.calculate("How much does 800 EM add to Vaporize?", PLANNER, formulas=False) is None


def test_server_comes_from_the_uid():
    assert [calc.server_of(u) for u in ("612345678", "712345678", "812345678", "912345678")] == [
        "america",
        "europe",
        "asia",
        "asia",
    ]


def test_game_day_turns_over_at_reset():
    # Tuesday 08:30 UTC is 03:30 in America: still Monday until the 04:00 reset
    assert calc.server_weekday(PLANNER, "america", datetime(2026, 11, 3, 8, 30, tzinfo=UTC)) == 1
    assert calc.server_weekday(PLANNER, "america", datetime(2026, 11, 3, 9, 30, tzinfo=UTC)) == 2


def names(text):
    return [n for n in ("Amber", "Furina") if n in text]


ASK = (
    "What should I farm today? (My showcased characters: Amber C6; Furina C0) (My server: America)"
)


def test_farm_today_matches_roster_to_open_domains():
    monday = datetime(2026, 11, 2, 15, tzinfo=UTC)
    answer = calc.farm_today(ASK, PLANNER, names, monday)
    assert "1 showcased characters" in answer.text
    assert "Amber" in answer.text and "Furina" not in answer.text


def test_everything_is_open_on_sunday():
    sunday = datetime(2026, 11, 8, 15, tzinfo=UTC)
    assert "2 showcased" in calc.farm_today(ASK, PLANNER, names, sunday).text


def test_farm_today_without_a_uid_asks_for_one():
    answer = calc.farm_today("What should I farm today?", PLANNER, names, datetime.now(UTC))
    assert "Share your UID" in answer.text


def test_other_farming_questions_are_left_alone():
    assert calc.farm_today("What should I farm first?", PLANNER, names, datetime.now(UTC)) is None


def test_best_quote_picks_the_line_behind_the_claim():
    source = (
        "Citlali is a Cryo support.\nShe lowers Pyro RES by 20% for 12 seconds. Unrelated text."
    )
    assert best_quote(["Citlali lowers Pyro RES"], source).startswith("She lowers Pyro RES")


def test_best_quote_stays_short():
    assert len(best_quote(["word " * 3 + "alpha"], "alpha " * 200)) <= 200


def test_nothing_in_common_means_no_quote():
    assert best_quote(["zebra"], "Citlali is a Cryo support.") is None
