"""RAYY notes tests use a synthetic fixture; real team notes never go into the repo."""

import pytest
from conftest import FETCHED_AT, FIXTURES

from irminsul.schema import Tier
from irminsul.sources.rayy_notes import ingest, is_refused, keep_line, parse_note

SAMPLE = (FIXTURES / "rayy_notes" / "sample.md").read_text(encoding="utf-8")


def test_keep_line_tags():
    assert keep_line("ER is 61.3%. [OFFICIAL]")
    assert keep_line("| Hard pity | 90 (CONFIRMED) |")
    assert keep_line("Quickswap rule. [KQM Raiden quick guide]")
    assert not keep_line("Best sword. [OPINION]")
    assert not keep_line("Reset mid-animation. [KQM] [VERIFY in game]")
    assert not keep_line("| Soft pity | 74 (DATA-DERIVED) |")
    assert not keep_line("Leaked banner order. [OFFICIAL]")
    assert not keep_line("Kit numbers. [DATAMINED]")
    assert not keep_line("No tag at all.")
    assert not keep_line("- [OFFICIAL] = HoYoverse update text, relayed by a summarizer.")
    assert not keep_line("| **[KQM]** | KQM guides |")


def test_parse_note_keeps_only_verified_lines():
    result = parse_note(SAMPLE, "sample.md", FETCHED_AT)
    ids = [d.doc_id for d in result.docs]
    assert ids == ["rayy/sample#1-weapon-facts", "rayy/sample#2-banner-rules"]
    weapon, banner = result.docs
    assert "40% chance" in weapon.text and "61.3%" in weapon.text
    assert "OPINION" not in weapon.text and "VERIFY" not in weapon.text
    assert "Hook" not in weapon.text  # production subsection skipped
    assert "unrelated" not in weapon.text
    assert "Hard pity" in banner.text and "Soft pity" not in banner.text
    assert "| Rule | Character banner |" in banner.text  # table header kept for context
    assert "Legend" not in banner.text
    assert "Leaked" not in banner.text
    assert weapon.source.tier == Tier.RAYY_VERIFIED
    assert weapon.source.game_version == "7.1"
    assert weapon.source.refs == ["https://gi.yatta.moe/api/v2/en/weapon/11403"]
    assert result.kept_lines == 3


def test_leak_files_are_refused(tmp_path):
    assert is_refused("LEAK CONTEXT - 7.2 and 7.3 (UNVERIFIED, do not publish).md")
    (tmp_path / "ok.md").write_text(SAMPLE, encoding="utf-8")
    assert ingest(tmp_path, ["ok.md"], FETCHED_AT)["ok.md"].docs
    with pytest.raises(ValueError):
        ingest(tmp_path, ["LEAK CONTEXT - anything.md"], FETCHED_AT)
    with pytest.raises(ValueError):
        ingest(tmp_path, ["../ok.md"], FETCHED_AT)


def test_allowlist_has_no_leak_or_unreleased_files():
    from pathlib import Path

    from irminsul.sources.rayy_notes import load_allowlist

    names = load_allowlist(Path(__file__).parents[1] / "config" / "rayy_notes_allowlist.txt")
    assert names and not any(is_refused(n) or n.startswith("7.2") for n in names)
