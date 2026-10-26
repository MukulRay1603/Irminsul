"""Structured entity store: exact answers to stat and passive questions without an LLM.

Embedding search is weakest on "what is X's base ATK?" because every character overview
looks alike. Those questions have exact answers in the entity records, so they are
answered here directly, with a citation, in microseconds and at zero cost.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from irminsul.pipeline.gate import normalise_name
from irminsul.schema import ArtifactSet, Character, ReleaseStatus, Weapon

# Short names players use. Values are entity ids.
ALIASES = {
    "raiden": "character/raiden-shogun",
    "ei": "character/raiden-shogun",
    "kazuha": "character/kaedehara-kazuha",
    "itto": "character/arataki-itto",
    "ayaka": "character/kamisato-ayaka",
    "ayato": "character/kamisato-ayato",
    "kokomi": "character/sangonomiya-kokomi",
    "heizou": "character/shikanoin-heizou",
    "sara": "character/kujou-sara",
    "shinobu": "character/kuki-shinobu",
    "yae": "character/yae-miko",
    "childe": "character/tartaglia",
    "scaramouche": "character/wanderer",
    "mizuki": "character/yumemizuki-mizuki",
    "sac sword": "weapon/sacrificial-sword",
    "ttds": "weapon/thrilling-tales-of-dragon-slayers",
    "emblem": "artifact/emblem-of-severed-fate",
    "noblesse": "artifact/noblesse-oblige",
}
# Single words that are also everyday English: only matched as part of a full name.
NOT_SHORT_ALIASES = {"gaming", "prune", "traveler", "kamisato", "shogun", "miko"}

Entity = Character | Weapon | ArtifactSet


@dataclass
class Match:
    entity: Entity
    kind: str  # character | weapon | artifact


def _key(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


class EntityStore:
    def __init__(
        self, characters: list[Character], weapons: list[Weapon], artifacts: list[ArtifactSet]
    ) -> None:
        self.by_id: dict[str, Match] = {}
        for c in characters:
            self.by_id[c.id] = Match(c, "character")
        for w in weapons:
            self.by_id[w.id] = Match(w, "weapon")
        for a in artifacts:
            self.by_id[a.id] = Match(a, "artifact")
        self.aliases: dict[str, str] = {}
        for eid, m in self.by_id.items():
            self.aliases[_key(m.entity.name)] = eid
            words = _key(m.entity.name).split()
            if m.kind == "character" and len(words) > 1:
                for w in words:
                    if w not in NOT_SHORT_ALIASES:
                        self.aliases.setdefault(w, eid)
        for alias, eid in ALIASES.items():
            if eid in self.by_id:
                self.aliases[alias] = eid
        self.max_words = max(len(a.split()) for a in self.aliases)

    @classmethod
    def load(cls, build: Path) -> "EntityStore":
        def read(name, model):
            path = build / name
            if not path.exists():
                return []
            return [
                model.model_validate_json(x)
                for x in path.read_text(encoding="utf-8").splitlines()
                if x
            ]

        return cls(
            read("characters.jsonl", Character),
            read("weapons.jsonl", Weapon),
            read("artifact_sets.jsonl", ArtifactSet),
        )

    def find(self, question: str) -> list[Match]:
        """Entities named in the question, longest alias first, without overlaps."""
        words = _key(question).split()
        found: list[Match] = []
        i = 0
        while i < len(words):
            for n in range(min(self.max_words, len(words) - i), 0, -1):
                eid = self.aliases.get(" ".join(words[i : i + n]))
                if eid:
                    match = self.by_id[eid]
                    if match not in found:
                        found.append(match)
                    i += n
                    break
            else:
                i += 1
        return found

    def is_known_name(self, text: str) -> bool:
        return normalise_name(text) in {normalise_name(m.entity.name) for m in self.by_id.values()}


def released(m: Match) -> bool:
    return m.entity.release.status == ReleaseStatus.RELEASED
