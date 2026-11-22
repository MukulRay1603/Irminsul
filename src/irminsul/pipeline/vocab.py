"""On-topic words and nicknames, learned from the data instead of typed into code.

1. Words: every proper noun the corpus uses, such as places, factions, people, books and
   quests ("Hexenzirkel", "Nod-Krai"). A question that uses one is about Genshin, so it isn't
   refused as off-topic. A word counts when the corpus writes it with a capital in the middle of
   a sentence, nearly always: "Fatui" does, "water" doesn't. The list is rebuilt on every update.
2. Nicknames, from anonymous answer feedback (api/feedback.py): a word the data doesn't
   know, used in several questions that were rated helpful and answered from one character's
   pages and nobody else's ("furi" -> Furina). Only the word and the character are kept, never
   a question. Learned nicknames never replace the hand-made ones (entities.ALIASES).

Writes `vocabulary.json`, which the site loads with the rest of the build (EntityStore).

Usage:
    uv run irminsul-vocab --build data/build --previous prev \
        [--feedback feedback/ | --feedback-repo MukulRay/irminsul-feedback]

The feedback is read only if the token (HF_TOKEN) may read it; otherwise the nicknames learned
before are kept as they are.
"""

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

from irminsul.engine.entities import EntityStore

log = logging.getLogger("irminsul.vocab")

MIN_CAPITALISED = 4  # times written with a capital mid-sentence
PROPER_SHARE = 0.9  # ...out of all its uses
MIN_LETTERS = 5
MIN_QUESTIONS = 3  # distinct helpful questions before a nickname is learned
# Proper nouns of the real world, which the corpus also capitalises
EVERYDAY = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "english",
    "chinese",
    "japanese",
    "korean",
    "youtube",
    "twitter",
    "reddit",
    "discord",
    "google",
    "android",
    "windows",
    "playstation",
    "america",
    "europe",
    "china",
    "japan",
    "christmas",
    "halloween",
    "easter",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
# Mid-sentence: after a lower-case word or a comma, and before punctuation or a lower-case word
# that isn't "of", "the" and the like. So "leader of the Fatui and" counts, but a title in
# Title Case ("Sonata of the Shores") doesn't, and neither does a sentence's first word.
_LINK = r"(?!(?:of|the|and|in|on|to|for|a|an|from|with|by|at)\b)"
_MID = re.compile(
    r"(?<=[a-z,] )(?:([A-Z][a-z][A-Za-z'-]*)|([a-z][A-Za-z'-]+))"
    r"(?=[.,;:!?)]|\s" + _LINK + r"[a-z])"
)


def proper_nouns(texts) -> list[str]:
    """Words the corpus nearly always capitalises mid-sentence, lower-cased."""
    upper: Counter[str] = Counter()
    lower: Counter[str] = Counter()
    for text in texts:
        for m in _MID.finditer(text):
            word = (m.group(1) or m.group(2)).strip("'-").removesuffix("'s")
            if m.group(1):
                upper[word.casefold()] += 1
            else:
                lower[word.casefold()] += 1
    return sorted(
        w
        for w, n in upper.items()
        if n >= MIN_CAPITALISED
        and len(w) >= MIN_LETTERS
        and n / (n + lower[w]) >= PROPER_SHARE
        and w not in EVERYDAY
    )


def corpus_words(texts) -> set[str]:
    return {w.casefold() for text in texts for w in _WORD.findall(text)}


def nicknames(records, store: EntityStore, known_words: set[str]) -> dict[str, str]:
    """word -> character id, from feedback rated helpful (see the module docstring)."""
    uses: dict[str, set[str]] = defaultdict(set)  # word -> questions
    points: dict[str, set[str]] = defaultdict(set)  # word -> characters its answers cited
    for r in records:
        if r.get("kind", "answer") != "answer" or r.get("rating") != "up":
            continue
        question = r.get("question") or ""
        if store.find(question):
            continue  # it already names someone: no unknown word to learn
        cited = {
            d.split("#")[0]
            for d in r.get("doc_ids") or []
            if d.startswith("character/") and d.split("#")[0] in store.by_id
        }
        for word in {w.casefold() for w in _WORD.findall(question)}:
            if len(word) < 3 or word in known_words or word in store.aliases:
                continue
            uses[word].add(question.casefold())
            points[word] |= cited or {"?"}
    return {
        word: next(iter(points[word]))
        for word in sorted(uses)
        if len(uses[word]) >= MIN_QUESTIONS and len(points[word]) == 1 and "?" not in points[word]
    }


def fetch_feedback(repo: str, out: Path) -> Path | None:
    """Download the feedback files, or None when the token may not read them."""
    import os

    from huggingface_hub import snapshot_download

    try:
        snapshot_download(
            repo,
            repo_type="dataset",
            allow_patterns=["feedback/*/*.jsonl"],
            local_dir=out,
            token=os.environ.get("HF_TOKEN"),
        )
    except Exception as exc:  # no access, no dataset, offline: learn nothing new today
        log.info("feedback not readable (%s): keeping the nicknames learned before", exc)
        return None
    return out


def _read_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", type=Path, default=Path("data/build"))
    parser.add_argument("--feedback", type=Path, default=None, help="folder of feedback .jsonl")
    parser.add_argument("--feedback-repo", default=None, help="or download it from this dataset")
    parser.add_argument("--previous", type=Path, default=None, help="last published build")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    texts = [d["text"] for d in _read_jsonl(args.build / "docs.jsonl")]
    words = proper_nouns(texts)
    store = EntityStore.load(args.build)
    before = args.previous / "vocabulary.json" if args.previous else None
    learned = (
        json.loads(before.read_text("utf-8")).get("nicknames", {})
        if before and before.exists()
        else {}
    )
    if args.feedback_repo and not args.feedback:
        args.feedback = fetch_feedback(args.feedback_repo, Path("feedback-download"))
    if args.feedback and args.feedback.exists():
        records = [r for p in sorted(args.feedback.rglob("*.jsonl")) for r in _read_jsonl(p)]
        fresh = nicknames(records, store, corpus_words(texts) | set(words))
        learned = {**fresh, **learned}  # a nickname, once learned, keeps its character
        log.info("nicknames: %d learned from %d feedback records", len(fresh), len(records))
    learned = {w: eid for w, eid in learned.items() if eid in store.by_id}
    out = {"words": words, "nicknames": learned}
    (args.build / "vocabulary.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    log.info("vocabulary: %d words, %d nicknames", len(words), len(learned))


if __name__ == "__main__":
    main()
