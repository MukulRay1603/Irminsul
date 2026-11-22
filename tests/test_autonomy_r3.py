"""Publishing that protects itself: the weekly full live run and the Yatta / HoYoWiki
cross-check."""

import json

import httpx

from irminsul import canary
from irminsul.engine.evaluate import score
from irminsul.evals import EvalItem
from irminsul.pipeline.build import cross_check
from irminsul.schema import BaseStats, Character


def item(**kw) -> EvalItem:
    base = {"id": "t", "question": "q", "category": "stat", "expect": "answer", "origin": "x"}
    return EvalItem.model_validate({**base, **kw})


# ---- the weekly full live run -------------------------------------------------------------
def test_live_answers_are_scored_like_offline_ones():
    fact = item(must_include=[["Electro"]], gold_doc_ids=["character/mitya#overview"])
    assert score(fact, "Mitya is Electro.", "exact", {"character/mitya#overview"}) == (True, [])
    ok, problems = score(fact, "Mitya is Electro.", "rag", {"character/other#x"})
    assert not ok and "gold doc not cited" in problems
    probe = item(category="leak_probe", expect="refuse", must_include=[["leak"]])
    assert score(probe, "No leaks here.", "refuse_leak", set())[0]
    assert "should have refused" in score(probe, "leak list", "rag", set())[1]


def fake_site(monkeypatch, replies):
    def handler(request):
        question = json.loads(request.content)["question"]
        assert request.headers.get("x-irminsul-demo") == "k" * 16
        answer, route = replies[question]
        return httpx.Response(200, json={"answer": answer, "route": route, "citations": []})

    real = httpx.Client
    monkeypatch.setattr(
        canary.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setenv("IRMINSUL_DEMO_KEY", "k" * 16)


def test_full_run_counts_out_of_allowance_answers_as_not_scored(monkeypatch):
    items = [
        item(id="a", question="qa", must_include=[["yes"]]),
        item(id="b", question="qb", must_include=[["yes"]]),
        item(id="c", question="qc", must_include=[["yes"]]),
    ]
    monkeypatch.setattr(canary, "resolve", lambda _items, _build: (items, []))
    fake_site(
        monkeypatch,
        {"qa": ("yes", "rag"), "qb": ("limit", "no_allowance"), "qc": ("no", "rag")},
    )
    report = canary.full_check("https://site.test", None, pause_s=0)
    assert (report["scored"], report["passed"], report["not_scored"]) == (2, 1, 1)
    assert not report["ok"] and "below 85%" in report["problem"]
    assert [f["id"] for f in report["failures"]] == ["c"]


# ---- Yatta against HoYoWiki ---------------------------------------------------------------
def character(hp=15307.0):
    return Character.model_validate(
        {
            "id": "character/furina",
            "game_id": "10000089",
            "name": "Furina",
            "rarity": 5,
            "element": "Hydro",
            "weapon_type": "Sword",
            "release": {"status": "released"},
            "base_stats": {"level": 90, "hp": hp, "atk": 244.0, "defense": 696.0},
            "source": {
                "source": "yatta",
                "url": "https://gi.yatta.moe/en/archive/avatar/Furina",
                "tier": "official",
                "fetched_at": "2026-11-21T00:00:00Z",
            },
        }
    )


def test_rounding_differences_are_not_disagreements():
    official = BaseStats(level=90, hp=15307.4, atk=244.0, defense=696.0)
    assert cross_check(character(), official) == []


def test_a_real_disagreement_takes_the_official_value_and_is_recorded():
    c = character(hp=14000.0)
    official = BaseStats(level=90, hp=15307.0, atk=244.0, defense=696.0)
    (found,) = cross_check(c, official)
    assert found == {"id": "character/furina", "field": "hp", "yatta": 14000.0, "hoyowiki": 15307.0}
    assert c.base_stats.hp == 15307.0


def test_the_change_log_names_each_disagreement():
    from irminsul.pipeline.diff import compare, to_markdown

    new = {"cross_check": [{"id": "character/x", "field": "hp", "yatta": 1.0, "hoyowiki": 2.0}]}
    text = to_markdown(compare({}, new), new, [])
    assert "official value used (1)" in text and "`character/x` hp: Yatta 1, HoYoWiki 2" in text
