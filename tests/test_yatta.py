"""Parser tests against saved Yatta responses. Expected numbers are the in-game values."""

from conftest import FETCHED_AT, load_yatta

from irminsul.pipeline.render import character_docs, weapon_docs
from irminsul.schema import ReleaseStatus, Tier
from irminsul.sources.yatta import parse_artifact_set, parse_character, parse_weapon


def test_raiden_lv90_stats(avatar_curve):
    c = parse_character(load_yatta("avatar_10000052"), avatar_curve, FETCHED_AT, "71F2")
    s = c.base_stats
    assert (s.hp, s.atk, s.defense) == (12907, 337, 789)
    assert s.bonus_stat == "Energy Recharge"
    assert round(s.bonus_value, 2) == 0.32


def test_raiden_identity_and_kit(avatar_curve):
    c = parse_character(load_yatta("avatar_10000052"), avatar_curve, FETCHED_AT, "71F2")
    assert c.id == "character/raiden-shogun"
    assert (c.element, c.weapon_type, c.rarity, c.region) == ("Electro", "Polearm", 5, "Inazuma")
    kinds = [t.kind for t in c.talents]
    assert kinds[:3] == ["normal_attack", "skill", "burst"]
    assert kinds.count("passive") == 3
    assert [con.level for con in c.constellations] == [1, 2, 3, 4, 5, 6]
    burst = next(t for t in c.talents if t.kind == "burst")
    assert burst.name == "Secret Art: Musou Shinsetsu"
    assert burst.scaling and set(burst.scaling[0].by_level) == {1, 6, 9, 10, 13}
    assert c.release.status == ReleaseStatus.RELEASED and c.release.released_at is not None
    assert c.source.tier == Tier.OFFICIAL and c.source.game_version == "71F2"


def test_sacrificial_sword(weapon_curve):
    w = parse_weapon(load_yatta("weapon_11403"), weapon_curve, FETCHED_AT, "71F2")
    assert (w.name, w.weapon_type, w.rarity) == ("Sacrificial Sword", "Sword", 4)
    assert w.base_atk == 454
    assert w.secondary_stat == "Energy Recharge"
    assert round(w.secondary_value, 3) == 0.613
    assert w.passive_name == "Composed"
    assert len(w.passive_by_refinement) == 5
    assert "40%" in w.passive_by_refinement[0] and "<color" not in w.passive_by_refinement[0]


def test_artifact_set_bonuses():
    items = load_yatta("reliquary_list")["items"]
    a = parse_artifact_set(items["10001"], FETCHED_AT, "71F2")
    assert a.name == "Resolution of Sojourner"
    assert a.bonuses == {2: "ATK +18%.", 4: "Increases Charged Attack CRIT Rate by 30%."}


def test_docs_have_stable_ids_and_provenance(avatar_curve, weapon_curve):
    c = parse_character(load_yatta("avatar_10000052"), avatar_curve, FETCHED_AT, "71F2")
    docs = character_docs(c)
    ids = [d.doc_id for d in docs]
    assert len(ids) == len(set(ids))
    assert ids[0] == "character/raiden-shogun#overview"
    assert all(d.source.url.startswith("https://gi.yatta.moe/") for d in docs)
    # Same input -> same ids and hashes, so re-ingesting never duplicates.
    again = character_docs(c)
    assert [(d.doc_id, d.content_hash) for d in again] == [(d.doc_id, d.content_hash) for d in docs]
    w_doc = weapon_docs(parse_weapon(load_yatta("weapon_11403"), weapon_curve, FETCHED_AT, "71F2"))
    assert "Base ATK 454" in w_doc[0].text and "61.3%" in w_doc[0].text
