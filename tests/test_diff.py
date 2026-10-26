from irminsul.pipeline.diff import compare, guard, to_markdown


def manifest(
    chars=129,
    weapons=252,
    kqm=1429,
    hashes=None,
    announced=(),
    unverified=(),
    dropped=(),
    version="71F2",
):
    return {
        "built_at": "2026-11-01T06:17:00+00:00",
        "sources": {"yatta": {"game_version": version}},
        "counts": {
            "characters": {"fetched": chars, "kept": chars},
            "weapons": {"fetched": weapons, "kept": weapons},
            "kqm": {"pages": 297, "docs": kqm},
            "announced": list(announced),
        },
        "docs": chars + weapons + kqm,
        "doc_hashes": hashes if hashes is not None else {"a": "1", "b": "2"},
        "unverified": list(unverified),
        "dropped": list(dropped),
    }


def test_compare_finds_added_removed_changed_and_versions():
    old = manifest(hashes={"keep": "1", "edit": "1", "gone": "1"}, version="71F2")
    new = manifest(
        hashes={"keep": "1", "edit": "2", "new": "1"}, version="72A0", announced=["Mitya"]
    )
    d = compare(old, new)
    assert (d.added, d.removed, d.changed) == (["new"], ["gone"], ["edit"])
    assert d.versions["yatta"] == ("71F2", "72A0")
    text = to_markdown(d, new, [])
    assert "| yatta | 71F2 | 72A0 |" in text and "Mitya" in text and "`new`" in text


def test_guard_trips_on_big_drops_and_unverified():
    assert guard(manifest(), manifest()) == []
    problems = guard(manifest(weapons=252), manifest(weapons=100))
    assert any(p.startswith("weapons: 252 -> 100") for p in problems)
    assert any("unverified" in p for p in guard(manifest(), manifest(unverified=["w/x"])))
    assert guard({}, manifest()) == []  # first build: nothing to compare against


def test_new_leak_gate_drops_are_listed():
    old = manifest(dropped=[{"id": "x/old", "reason": "r"}])
    new = manifest(
        dropped=[
            {"id": "x/old", "reason": "r"},
            {"id": "weapon/new", "reason": "not listed on official HoYoWiki"},
        ]
    )
    d = compare(old, new)
    assert [x["id"] for x in d.new_drops] == ["weapon/new"]
    assert "Newly dropped by the leak gate (1)" in to_markdown(d, new, [])


def test_decide_publishes_routine_changes_and_asks_about_new_content():
    from irminsul.pipeline.diff import CorpusDiff, decide

    assert decide(CorpusDiff()) == {"changed": False, "review": False, "reasons": []}
    routine = decide(CorpusDiff(changed=["character/raiden-shogun#overview"], added=["kqm/x#1"]))
    assert routine["changed"] and not routine["review"]
    new_char = decide(CorpusDiff(added=["character/new-hero#overview"]))
    assert new_char["review"] and "added or removed" in new_char["reasons"][0]
    announced = decide(CorpusDiff(announced=(["Mitya"], ["Mitya", "Valeriy"])))
    assert announced["changed"] and announced["review"] and "Valeriy" in announced["reasons"][0]
