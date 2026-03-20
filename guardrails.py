import os
import logging

from sentence_transformers import SentenceTransformer, util

logger = logging.getLogger(__name__)

EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

GENSHIN_ANCHORS = [
    "Genshin Impact character build",
    "elemental reaction damage",
    "Archon quest lore",
    "artifact set bonus",
    "team composition synergy",
    "vision and gnosis",
    "Mondstadt Liyue Inazuma Sumeru Fontaine Natlan",
    "polearm sword claymore bow catalyst",
    "Pyro Hydro Cryo Electro Anemo Geo Dendro",
    "Genshin resin domain spiral abyss",
    "Hu Tao Zhongli Venti Kazuha Raiden Shogun",
    "Neuvillette Furina Arlecchino Navia Wriothesley",
    "who is this Genshin character",
    "best build for Genshin character",
    "Genshin lore story explained",
    "where to find character in Genshin",
]

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore your instructions",
    "you are now",
    "pretend you are",
    "act as",
    "forget everything",
    "jailbreak",
    "dan mode",
    "do anything now",
]

_embedder = None
_anchor_embeddings = None


def _get_embedder():
    global _embedder, _anchor_embeddings
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
        _anchor_embeddings = _embedder.encode(
            GENSHIN_ANCHORS, convert_to_tensor=True
        )
    return _embedder, _anchor_embeddings


def is_in_domain(query: str, threshold: float = 0.15) -> bool:
    try:
        embedder, anchors = _get_embedder()
        query_vec = embedder.encode(query, convert_to_tensor=True)
        score = util.cos_sim(query_vec, anchors).max().item()
        logger.info(f"Domain score: {score:.3f}")
        return score >= threshold
    except Exception as e:
        logger.warning(f"Domain check failed ({e}) — passing query through")
        return True


def has_injection(query: str) -> bool:
    q = query.lower()
    return any(p in q for p in INJECTION_PATTERNS)


def validate_input(query: str) -> tuple[bool, str]:
    query = query.strip()

    if not query:
        return False, "Query cannot be empty."

    if len(query) > 500:
        return False, "Query is too long — please keep it under 500 characters."

    if has_injection(query):
        return False, "That type of query isn't something I can help with."

    if not is_in_domain(query):
        return (
            False,
            "I'm specialized in Genshin Impact — ask me about characters, "
            "builds, lore, or elemental mechanics!",
        )

    return True, ""


def validate_output(answer: str) -> tuple[bool, str]:
    answer = answer.strip().replace("</s>", "").strip()

    if len(answer) < 10:
        return False, "I couldn't find enough context to answer that — try rephrasing."

    return True, answer