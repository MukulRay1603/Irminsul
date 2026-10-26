"""The publish gate that lets new content go live without a person, or holds it."""

from datetime import UTC, datetime

from irminsul.pipeline.safety import check_dates, check_language, check_probes

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def char(cid, status="released", when="2026-09-23T00:00:00+00:00"):
    return {"id": cid, "release": {"status": status, "released_at": when}}


def test_dates_hold_future_or_unknown_releases_and_announced_kits():
    chars = [
        char("character/ok"),
        char("character/soon", when="2026-12-01T00:00:00+00:00"),
        char("character/odd", status="unknown"),
        char("character/mitya", status="announced", when=None),
    ]
    docs = [
        {"doc_id": "character/mitya#overview", "entity_id": "character/mitya"},
        {"doc_id": "character/mitya#talent-burst-x", "entity_id": "character/mitya"},
    ]
    problems = check_dates(chars, docs, NOW)
    assert any("character/soon" in p and "future" in p for p in problems)
    assert any("character/odd" in p for p in problems)
    assert any("character/mitya#talent-burst-x" in p for p in problems)
    assert not any("character/ok" in p or "mitya#overview" in p for p in problems)


def test_leak_language_flags_leak_talk_not_ordinary_words():
    docs = [
        {"doc_id": "a", "title": "A", "text": "According to leaks, her kit is strong."},
        {"doc_id": "b", "title": "B", "text": "Datamined numbers from the beta server."},
        {"doc_id": "c", "title": "C", "text": "The news leaked to the Hakushin clan."},
        {"doc_id": "d", "title": "D", "text": "Arriving in version 7.4 with 7.5% ATK."},
        {"doc_id": "e", "title": "E", "text": "Gains 7.5% ATK in Version 7.2."},
    ]
    problems = check_language(docs, {"a", "b", "c", "d", "e"}, announced=(7, 2))
    flagged = {p.split(":")[0] for p in problems}
    assert flagged == {"a", "b", "d"}  # lore's "leaked", "Hakushin" and 7.5% are fine
    assert check_language(docs, {"c"}, announced=(7, 2)) == []  # only added/changed docs


def test_probe_failures_in_safety_categories_hold_the_build():
    report = {
        "failures": [
            {"id": "probe-leak", "category": "leak_probe", "problems": ["should have refused"]},
            {"id": "man-x", "category": "build", "problems": ["gold doc not cited"]},
        ]
    }
    problems = check_probes(report)
    assert len(problems) == 1 and "probe-leak" in problems[0]
