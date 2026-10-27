"""Suggested follow-up questions, picked from game data and never written by an LLM.

They cost nothing, can't leak (only released entities get entity-specific suggestions), and
each is marked `free` when Irminsul will answer it straight from game data, so players can
see which questions don't use their AI-answer allowance.
"""

import re

from irminsul.engine.entities import EntityStore, Match, released
from irminsul.engine.exact import answer_exact
from irminsul.engine.types import Answer

# (topic, template). A topic the question already asked about is skipped.
TEMPLATES = {
    "character": [
        ("stats", "What are {n}'s base stats at level 90?"),
        ("constellation", "What does {n}'s C1 do?"),
        ("burst", "What does {n}'s Elemental Burst do?"),
        ("weapon", "Which weapons suit {n}?"),
        ("team", "What teams work well with {n}?"),
    ],
    "weapon": [
        ("passive", "What does {n}'s passive do?"),
        ("stats", "What is {n}'s base ATK?"),
        ("who", "Which characters use {n}?"),
    ],
    "artifact": [
        ("set", "What does the {n} set bonus do?"),
        ("who", "Which characters use {n}?"),
    ],
}
TOPICS = {
    "stats": r"\bstats?\b|\bbase\b|\bhp\b|\batk\b|\bdef\b|\blevel 90\b",
    "constellation": r"\bconstellations?\b|\bc[1-6]\b",
    "burst": r"\bburst\b|\bultimate\b",
    "weapon": r"\bweapons?\b|\bsignature\b",
    "team": r"\bteams?\b|\bcomps?\b|\bparty\b",
    "passive": r"\bpassive\b|\brefinement\b|\br[1-5]\b",
    "set": r"\bset\b|\bpiece\b|\b[24]pc\b|\bbonus\b",
    "who": r"\bwho\b|\bwhich characters\b",
}
# For refusals and questions without a single released entity: safe, always-answerable starters.
STARTERS = [
    "How does pity work on the character event banner?",
    "What are Raiden Shogun's base stats at level 90?",
    "What does Sacrificial Sword's passive do?",
]
# Questions about wishing get wishing suggestions, not a random character's stats
GACHA = re.compile(r"\bwish\w*|\bpulls?\b|\bpity\b|\bbanners?\b|\bprimo\w*|\bfates?\b|50/50", re.I)
GACHA_STARTERS = [
    "How does pity work on the character event banner?",
    "What happens if I lose the 50/50?",
    "How many Primogems do 10 wishes cost?",
]
MAX = 3


def _entity(store: EntityStore, question: str, answer: Answer) -> Match | None:
    ids = [answer.trace.get("entity")] + [(c.doc_id or "").split("#")[0] for c in answer.citations]
    for eid in ids:
        if eid and eid in store.by_id:
            return store.by_id[eid]
    found = store.find(question)
    return found[0] if len(found) == 1 else None


def follow_ups(store: EntityStore, question: str, answer: Answer) -> list[dict]:
    """Up to three next questions as {"question", "free"}; empty for nothing useful."""
    if answer.route in ("busy", "no_allowance") or answer.route.startswith("refuse"):
        return []  # no more AI questions when they can't be answered, nothing after a refusal
    asked = question.casefold()
    match = None if answer.route.startswith("refuse") else _entity(store, question, answer)
    if match is not None and released(match):
        name = match.entity.name
        candidates = [
            t.format(n=name)
            for topic, t in TEMPLATES[match.kind]
            if not re.search(TOPICS[topic], asked, re.I)
        ]
    else:
        candidates = list(GACHA_STARTERS if GACHA.search(asked) else STARTERS)
    out = []
    for q in candidates:
        if q.casefold() == asked:
            continue
        exact = answer_exact(store, q)
        out.append({"question": q, "free": exact is not None and exact.route == "exact"})
        if len(out) == MAX:
            break
    # Free questions first: they answer instantly and never use the player's allowance.
    return sorted(out, key=lambda f: not f["free"])
