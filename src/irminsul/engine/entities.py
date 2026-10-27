"""Structured entity store: exact answers to stat and passive questions without an LLM.

Embedding search is weakest on "what is X's base ATK?" because every character overview
looks alike. Those questions have exact answers in the entity records, so they are
answered here directly, with a citation, in microseconds and at zero cost.
"""

import difflib
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
    # Player nicknames
    "neuv": "character/neuvillette",
    "neuvi": "character/neuvillette",
    "xq": "character/xingqiu",
    "xl": "character/xiangling",
    "zl": "character/zhongli",
    "arle": "character/arlecchino",
    "wrio": "character/wriothesley",
    "chev": "character/chevreuse",
    "kuki": "character/kuki-shinobu",
    "tao": "character/hu-tao",
    "fischl": "character/fischl",
}
# Everyday words a typo match must never turn into a character ("bloom" is not "Bloom" here)
COMMON_WORDS = {
    "build",
    "teams",
    "great",
    "which",
    "where",
    "there",
    "their",
    "about",
    "should",
    "would",
    "could",
    "weapon",
    "skill",
    "burst",
    "pulls",
    "banner",
    "primo",
    "level",
    "talent",
    "artifact",
    "artifacts",
    "stats",
    "better",
    "best",
    "worth",
    "guide",
    "story",
    "night",
    "light",
    "water",
    "flower",
    "heart",
    "blade",
    "spear",
    "sword",
    "shield",
    "damage",
}
# Single words that are also everyday English: only matched as part of a full name.
NOT_SHORT_ALIASES = {
    "gaming",
    "prune",
    "traveler",
    "kamisato",
    "shogun",
    "miko",
    # "Traveler (Electro)": an element word alone means the element, not the Traveler
    "anemo",
    "geo",
    "electro",
    "dendro",
    "hydro",
    "pyro",
    "cryo",
}

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
                self.aliases.setdefault("".join(words), eid)  # "hutao", "raidenshogun"
                for w in words:
                    if w not in NOT_SHORT_ALIASES:
                        self.aliases.setdefault(w, eid)
        for alias, eid in ALIASES.items():
            if eid in self.by_id:
                self.aliases[alias] = eid
        self.max_words = max(len(a.split()) for a in self.aliases)
        # Character names a typo can be matched against ("raidne" -> raiden): 5+ letters only
        self._fuzzy = sorted(
            a
            for a, eid in self.aliases.items()
            if " " not in a
            and len(a) >= 5
            and self.by_id[eid].kind == "character"
            and not a.startswith("traveler")  # one name, seven elements: never guess
        )

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
        if not found:
            found = self._close_names(words)
        return found

    def _close_names(self, words: list[str]) -> list[Match]:
        """A typo'd character name ("raidne", "neuvilette"), when nothing matched exactly."""
        found: list[Match] = []
        for w in words:
            if len(w) < 5 or w in COMMON_WORDS:
                continue
            # 0.83 keeps swapped letters (raidne, kazuah) and drops event/Venti, election/Electro
            close = difflib.get_close_matches(w, self._fuzzy, n=1, cutoff=0.83)
            if close:
                match = self.by_id[self.aliases[close[0]]]
                if match not in found:
                    found.append(match)
        return found

    def is_known_name(self, text: str) -> bool:
        return normalise_name(text) in {normalise_name(m.entity.name) for m in self.by_id.values()}


def released(m: Match) -> bool:
    return m.entity.release.status == ReleaseStatus.RELEASED
