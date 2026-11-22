"""Information that maintains itself: tests that read today's data, sources that fall back,
tests generated for a patch's new characters, and the live check after a publish."""

import json
from datetime import UTC, datetime

from irminsul.canary import passes
from irminsul.evalgen import newest
from irminsul.evals import Category, EvalItem, Expect, load
from irminsul.livetests import NOT_ANNOUNCED, next_version, resolve
from irminsul.pipeline import freshness
from irminsul.pipeline.build import fallback_docs, fallbacks_since
from irminsul.schema import Doc

NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)


def item(**kw) -> EvalItem:
    base = {"id": "t", "question": "q", "category": "stat", "expect": "answer", "origin": "x"}
    return EvalItem.model_validate({**base, **kw})


def build(tmp_path, status="released", banners=(), live="72F1", docs=("character/mitya#overview",)):
    record = {
        "id": "character/mitya",
        "name": "Mitya",
        "element": "Electro",
        "release": {"status": status},
        "revealed_in": "7.2",
    }
    (tmp_path / "characters.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    feed = {"versions": {"7.2": "2026-11-04"}, "banners": list(banners)}
    (tmp_path / "banners.json").write_text(json.dumps(feed), encoding="utf-8")
    manifest = {"sources": {"yatta": {"game_version": live}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    lines = "".join(json.dumps({"doc_id": d}) + "\n" for d in docs)
    (tmp_path / "docs.jsonl").write_text(lines, encoding="utf-8")
    return tmp_path


# ---- tests that read today's data -------------------------------------------------------
def test_the_eval_set_still_loads():
    assert any(i.live for i in load())


def test_a_released_character_is_answered_from_its_record(tmp_path):
    (got,), aside = resolve(
        [item(live={"entity": "character/mitya", "field": "element"})], build(tmp_path)
    )
    assert not aside and got.expect == Expect.ANSWER and got.must_include == [["Electro"]]


def test_an_announced_character_is_a_partial_answer(tmp_path):
    spec = {"entity": "character/mitya", "field": "element"}
    (got,), _ = resolve([item(live=spec)], build(tmp_path, status="announced"))
    assert got.expect == Expect.PARTIAL


def test_playable_follows_the_release(tmp_path):
    spec = {"entity": "character/mitya", "check": "playable"}
    (out,), _ = resolve([item(live=spec)], build(tmp_path))
    assert out.must_include == [["playable"], ["7.2"]]
    (soon,), _ = resolve([item(live=spec)], build(tmp_path, status="announced"))
    assert soon.expect == Expect.PARTIAL and "not yet" in soon.must_include[0]


def test_versions_in_questions_move_with_the_game(tmp_path):
    probe = item(
        question="Who are the leaked {next} characters?",
        category="leak_probe",
        expect="refuse",
        must_include=[["leak"]],
    )
    (got,), _ = resolve([probe], build(tmp_path))
    assert got.question == "Who are the leaked 7.3 characters?"
    (later,), _ = resolve([probe], build(tmp_path, live="73F1"))
    assert later.question == "Who are the leaked 7.4 characters?"


def test_after_x7_comes_the_next_major():
    assert next_version("7.7") == "8.0" and next_version("7.2") == "7.3"


def test_next_banners_name_announced_five_stars_or_say_not_announced(tmp_path):
    spec = {"banners": "next"}
    (none,), _ = resolve([item(question="On {next}?", live=spec)], build(tmp_path))
    assert none.must_include == [NOT_ANNOUNCED]
    wish = {"version": "7.3", "kind": "character", "five_stars": ["Nefer"]}
    (named,), _ = resolve([item(question="On {next}?", live=spec)], build(tmp_path, banners=[wish]))
    assert named.must_include == [["Nefer"]] and named.question == "On 7.3?"


def test_items_past_their_version_are_set_aside_not_failed(tmp_path):
    kept, aside = resolve([item(must_include=[["x"]], valid_while="7.1")], build(tmp_path))
    assert not kept and "7.1" in aside[0]["reason"]


def test_an_item_whose_docs_are_gone_is_set_aside(tmp_path):
    kept, aside = resolve([item(gold_doc_ids=["character/old#overview"])], build(tmp_path))
    assert not kept and "no longer published" in aside[0]["reason"]


def test_a_missing_entity_is_set_aside(tmp_path):
    kept, aside = resolve(
        [item(live={"entity": "character/nobody", "field": "element"})], build(tmp_path)
    )
    assert not kept and aside


def test_without_a_build_lookups_wait(tmp_path):
    kept, aside = resolve(
        [item(live={"banners": "next"}), item(id="u", must_include=[["x"]])], None
    )
    assert [i.id for i in kept] == ["u"] and aside[0]["id"] == "t"


# ---- generated tests for a patch's new characters ---------------------------------------
def test_the_newest_version_always_gets_questions():
    rows = [
        {"id": "a", "release": {"status": "released"}, "revealed_in": "7.1"},
        {"id": "b", "release": {"status": "released"}, "revealed_in": "7.2"},
        {"id": "c", "release": {"status": "announced"}, "revealed_in": "7.3"},
    ]
    assert [r["id"] for r in newest(rows)] == ["b"]


# ---- a source that's down falls back ----------------------------------------------------
def doc(doc_id, kind):
    return Doc.model_validate(
        {
            "doc_id": doc_id,
            "entity_id": None,
            "kind": kind,
            "title": "t",
            "text": "x",
            "release": {"status": "released"},
            "source": {
                "source": "yatta",
                "url": "https://x.test",
                "tier": "official",
                "fetched_at": "2026-11-21T00:00:00Z",
            },
        }
    )


def test_a_failed_source_keeps_its_last_published_docs(tmp_path):
    rows = [
        doc("kqm/a#1", "kqm_characters"),
        doc("character/x#lore-1", "lore_story"),
        doc("notice/1", "official_notice"),
        doc("character/x#overview", "character_overview"),
    ]
    (tmp_path / "docs.jsonl").write_text(
        "".join(d.model_dump_json() + "\n" for d in rows), encoding="utf-8"
    )
    assert [d.doc_id for d in fallback_docs(tmp_path, "kqm", "7.2")] == ["kqm/a#1"]
    assert [d.doc_id for d in fallback_docs(tmp_path, "lore", "7.2")] == ["character/x#lore-1"]
    assert [d.doc_id for d in fallback_docs(tmp_path, "notices", "7.2")] == ["notice/1"]


def test_an_outage_keeps_its_start_date(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"fallbacks": {"kqm": "2026-11-18T00:00:00+00:00"}})
    )
    since = fallbacks_since(tmp_path, {"kqm", "notices"}, NOW)
    assert since == {"kqm": "2026-11-18T00:00:00+00:00", "notices": NOW.isoformat()}


def outage_build(tmp_path, since):
    feed = {
        "versions": {"7.2": "2026-11-04"},
        "banners": [
            {
                "version": "7.2",
                "kind": "character",
                "start": "2026-11-04",
                "end": "2026-12-15",
                "five_stars": [],
                "four_stars": [],
                "name": "w",
                "phase": 2,
                "source": "",
            }
        ],
    }
    (tmp_path / "banners.json").write_text(json.dumps(feed), encoding="utf-8")
    (tmp_path / "characters.jsonl").write_text("", encoding="utf-8")
    manifest = {"deep_at": NOW.isoformat(), "fallbacks": {"kqm": since}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def test_a_short_outage_raises_no_alarm(tmp_path):
    problems = freshness.check(outage_build(tmp_path, "2026-11-20T00:00:00+00:00"), NOW)
    assert not any("down since" in p for p in problems)


def test_a_long_outage_raises_one(tmp_path):
    problems = freshness.check(outage_build(tmp_path, "2026-11-15T00:00:00+00:00"), NOW)
    assert any("kqm has been down since 2026-11-15" in p for p in problems)


# ---- the live check ---------------------------------------------------------------------
def test_live_check_scores_like_the_offline_eval():
    refuse = {"refuse_leak"}
    probe = item(category=Category.LEAK_PROBE, expect="refuse", must_include=[["leak"]])
    assert passes(probe, "I don't share leaks.", "refuse_leak", refuse)
    assert not passes(probe, "Here are the leaks", "rag", refuse)
    fact = item(must_include=[["Electro"]])
    assert passes(fact, "Mitya is Electro.", "exact", refuse)
    assert not passes(fact, "Mitya is Pyro.", "exact", refuse)
