from collections import Counter

import pytest

from irminsul.evals import Category, EvalItem, Expect, load, matches


def test_golden_set_loads_and_covers_every_category():
    items = load()
    assert len(items) >= 100
    counts = Counter(i.category for i in items)
    assert set(counts) == set(Category)
    assert counts[Category.LEAK_PROBE] >= 5 and counts[Category.INJECTION] >= 3


def test_refusal_probes_have_no_gold_docs_and_answers_do():
    for item in load():
        if item.expect == Expect.REFUSE:
            assert not item.gold_doc_ids, item.id
        else:
            assert item.gold_doc_ids, item.id


def test_matches_checks_groups_and_forbidden_text():
    item = EvalItem(
        id="t",
        question="q",
        category=Category.STAT,
        expect=Expect.ANSWER,
        must_include=[["337"], ["Energy Recharge", "ER"]],
        must_not_include=["leak"],
        origin="manual:test",
    )
    assert matches("Base ATK is 337 and she gains Energy Recharge.", item) == (True, [])
    ok, problems = matches("Base ATK is 337.", item)
    assert not ok and "missing one of" in problems[0]
    assert not matches("337 ER per the leak", item)[0]


def test_inconsistent_items_are_rejected():
    with pytest.raises(ValueError):
        EvalItem(
            id="x",
            question="q",
            category=Category.LEAK_PROBE,
            expect=Expect.REFUSE,
            gold_doc_ids=["character/x#overview"],
            origin="manual:test",
        )
    with pytest.raises(ValueError):
        EvalItem(
            id="y", question="q", category=Category.STAT, expect=Expect.ANSWER, origin="manual:test"
        )
