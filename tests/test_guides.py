"""Reaction guides: compiled from released official text only, definitions first."""

from datetime import UTC, datetime

from irminsul.pipeline.guides import reaction_guides
from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def doc(doc_id: str, title: str, text: str, status=ReleaseStatus.RELEASED, tier=Tier.OFFICIAL):
    return Doc(
        doc_id=doc_id,
        entity_id=doc_id.split("#")[0],
        kind="talent",
        title=title,
        text=text,
        release=Release(status=status),
        source=SourceRef(
            source="yatta", url=f"https://example.org/{doc_id}", tier=tier, fetched_at=NOW
        ),
    )


DOCS = [
    doc(
        "character/ineffa#talent-passive-x",
        "Ineffa: Moonsign Benediction",
        "When a party member triggers an Electro-Charged reaction, it will be converted into the "
        "Lunar-Charged reaction, with every 100 ATK increasing its Base DMG by 0.7%.",
    ),
    doc(
        "character/flins#talent-burst-x",
        "Flins: Ancient Ritual",
        "Flins deals AoE Electro DMG. This DMG is considered Lunar-Charged DMG.",
    ),
    doc(
        "character/someone-new#overview",
        "Someone New overview",
        "Their burst is considered Lunar-Charged DMG and is secretly huge.",
        status=ReleaseStatus.ANNOUNCED,
    ),
    doc(
        "kqm/x#y",
        "KQM: Lunar",
        "Lunar-Charged is a community-explained reaction that deals damage.",
        tier=Tier.KQM,
    ),
]


def test_guides_put_definitions_first_and_credit_each_line():
    guides = {g.doc_id: g for g in reaction_guides(DOCS, NOW)}
    guide = guides["mechanic/lunar-charged#guide"]
    text = guide.text
    assert text.index("## What turns into it") < text.index("## Who deals it")
    assert "- Ineffa: When a party member triggers an Electro-Charged reaction" in text
    assert "- Flins: Flins deals AoE Electro DMG." not in text  # sentence split, credited
    assert "- Flins: This DMG is considered Lunar-Charged DMG." in text
    assert guide.source.tier == Tier.OFFICIAL and guide.release.status == ReleaseStatus.RELEASED


def test_guides_never_use_unreleased_or_third_party_text():
    text = "\n".join(g.text for g in reaction_guides(DOCS, NOW))
    assert "secretly huge" not in text and "community-explained" not in text


def test_no_guide_without_official_mentions():
    ids = {g.doc_id for g in reaction_guides(DOCS, NOW)}
    assert "mechanic/stellar-conduct#guide" not in ids
