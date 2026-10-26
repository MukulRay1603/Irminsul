"""Typed records shared by the corpus pipeline and the answer engine.

Entities hold exact game facts (stats, talents, passives). Docs are the retrievable
text units rendered from entities and guides; every Doc keeps the provenance needed
to cite it and to filter it by release status and game version.
"""

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class Tier(StrEnum):
    """How much a source is trusted. Ordered from most to least trusted."""

    OFFICIAL = "official"  # in-game text, HoYoverse / HoYoLAB / HoYoWiki
    RAYY_VERIFIED = "rayy_verified"  # team fact-checked research notes
    KQM = "kqm"  # KQM theorycrafting library and guides
    COMMUNITY = "community"  # usage stats and other community signals


class ReleaseStatus(StrEnum):
    RELEASED = "released"  # playable in the live game
    ANNOUNCED = "announced"  # officially revealed, not yet playable
    UNKNOWN = "unknown"  # cannot be proven official or released; never served


class SourceRef(BaseModel):
    source: str  # e.g. "yatta", "hoyowiki", "kqm"
    url: str
    tier: Tier
    fetched_at: datetime
    game_version: str | None = None  # data version reported by the source
    refs: list[str] = Field(default_factory=list)  # underlying URLs cited by the source


class Release(BaseModel):
    status: ReleaseStatus
    released_at: datetime | None = None


class ScalingRow(BaseModel):
    label: str
    by_level: dict[int, str]  # talent level -> formatted value


class Talent(BaseModel):
    kind: str  # normal_attack | skill | burst | passive
    name: str
    description: str
    scaling: list[ScalingRow] = Field(default_factory=list)


class Constellation(BaseModel):
    level: int  # 1..6
    name: str
    description: str


class BaseStats(BaseModel):
    level: int
    hp: float
    atk: float
    defense: float
    bonus_stat: str | None = None
    bonus_value: float | None = None  # fraction for percent stats (0.32 = 32%)


class Character(BaseModel):
    id: str  # stable slug, e.g. "character/raiden-shogun"
    game_id: str
    name: str
    rarity: int
    element: str
    weapon_type: str
    region: str | None = None
    title: str | None = None
    base_stats: BaseStats | None = None
    talents: list[Talent] = Field(default_factory=list)
    constellations: list[Constellation] = Field(default_factory=list)
    release: Release
    source: SourceRef


class Weapon(BaseModel):
    id: str
    game_id: str
    name: str
    rarity: int
    weapon_type: str
    base_atk: float | None = None  # at max level
    secondary_stat: str | None = None
    secondary_value: float | None = None
    passive_name: str | None = None
    passive_by_refinement: list[str] = Field(default_factory=list)  # R1..R5
    description: str | None = None
    release: Release
    source: SourceRef


class ArtifactSet(BaseModel):
    id: str
    game_id: str
    name: str
    rarities: list[int]
    bonuses: dict[int, str]  # piece count -> effect text
    release: Release
    source: SourceRef


class Doc(BaseModel):
    """A retrievable text unit. Chunking happens later, at index build time."""

    doc_id: str  # stable: "<entity id>#<section>"
    entity_id: str | None
    kind: str  # character_overview | talent | constellations | weapon | artifact_set | ...
    title: str
    text: str
    release: Release
    source: SourceRef

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


def slugify(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")
