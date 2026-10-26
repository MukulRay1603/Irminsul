"""Parser tests against saved TCL Markdown (tests/fixtures/kqm/docs mirrors TCL's docs/)."""

from pathlib import Path

from conftest import FETCHED_AT, FIXTURES

from irminsul.schema import ReleaseStatus, Tier
from irminsul.sources.kqm import iter_pages, parse_page, strip_mdx

DOCS = FIXTURES / "kqm" / "docs"
SHA = "7fb4e7d54d38e9e7549f778ac9bdcfc626c646d5"


def parse(rel: str, blocklist: set[str] | None = None):
    path = Path(rel)
    return parse_page((DOCS / path).read_text(encoding="utf-8"), path, SHA, FETCHED_AT, blocklist)


def test_strip_mdx_removes_imports_components_and_comments():
    raw = (DOCS / "characters/electro/raiden-shogun.md").read_text(encoding="utf-8")
    text = strip_mdx(raw.split("---\n", 2)[2], {"description": "Her Excellency."})
    assert "@site/" not in text and "@theme/" not in text
    for tag in ("<Image", "<Tabs", "</TabItem", "<Skill", "<Constellation", "<div", "{char}"):
        assert tag not in text
    assert "Raiden Mains Discord" not in text and "<!--" not in text
    assert "Her Excellency." in text  # {frontMatter.description} is substituted
    assert "### Skill" in text  # tab labels survive as headings
    assert "| Particles | -       | 0~1 (1:1)          |" in text
    # Code fences are kept verbatim, including import lines inside them.
    assert "import frames from './frames'" in text


def test_strip_mdx_handles_multiline_jsx_attributes():
    text = strip_mdx("Before\n<DocCardList items={\n  xs.filter((i) => i.ok)\n} />\nAfter")
    assert text == "Before\n\nAfter"


def test_sections_and_stable_ids():
    result = parse("characters/electro/raiden-shogun.md")
    ids = [d.doc_id for d in result.docs]
    assert ids == [
        "kqm/characters/raiden-shogun#intro",
        "kqm/characters/raiden-shogun#resources",
        "kqm/characters/raiden-shogun#attacks",
        "kqm/characters/raiden-shogun#constellations",
        "kqm/characters/raiden-shogun#frames",
    ]
    attacks = result.docs[2]
    assert attacks.title == "Raiden Shogun: Attacks"
    assert attacks.text.startswith("# Raiden Shogun\n## Attacks\n")
    assert "Elemental Burst DMG Bonus" in attacks.text
    assert all(d.entity_id == "character/raiden-shogun" for d in result.docs)
    assert all(d.kind == "kqm_characters" for d in result.docs)
    # Same input -> same ids and hashes, so re-ingesting never duplicates.
    again = parse("characters/electro/raiden-shogun.md")
    assert [(d.doc_id, d.content_hash) for d in again.docs] == [
        (d.doc_id, d.content_hash) for d in result.docs
    ]


def test_non_character_pages_have_no_entity_and_skip_empty_sections():
    result = parse("equipment/weapons/swords.md")
    assert [d.doc_id for d in result.docs] == [
        "kqm/equipment/weapons/swords#5-stars",
        "kqm/equipment/weapons/swords#4-stars",  # "Bleak" is not a leak keyword
    ]
    assert all(d.entity_id is None for d in result.docs)
    assert "### Aquila Favonia" in result.docs[0].text


def test_beta_and_leak_content_is_dropped():
    raiden = parse("characters/electro/raiden-shogun.md")
    assert not any("beta" in d.doc_id for d in raiden.docs)
    assert raiden.dropped == [
        (
            "kqm/characters/raiden-shogun#beta-changes",
            "mentions beta/leak/unreleased: 'Beta Changes'",
        )
    ]
    page = parse("characters/hydro/test-unreleased.md")
    assert page.docs == []
    assert page.dropped[0][0] == "kqm/characters/test-unreleased"


def test_blocklisted_character_is_dropped():
    result = parse("characters/electro/raiden-shogun.md", {"character/raiden-shogun"})
    assert result.docs == [] and result.dropped == [("kqm/characters/raiden-shogun", "blocklisted")]


def test_attribution_url_and_provenance():
    doc = parse("characters/electro/raiden-shogun.md").docs[0]
    assert doc.source.url == (
        f"https://github.com/KQM-git/TCL/blob/{SHA}/docs/characters/electro/raiden-shogun.md"
    )
    assert doc.source.source == "kqm" and doc.source.tier == Tier.KQM
    assert doc.source.game_version == SHA
    assert doc.release.status == ReleaseStatus.RELEASED


def test_iter_pages_skips_partials_and_evidence():
    assert [p.as_posix() for p in iter_pages(DOCS)] == [
        "characters/electro/raiden-shogun.md",
        "characters/hydro/test-unreleased.md",
        "equipment/weapons/swords.md",
    ]
