"""Check each sentence of an AI answer against the sources it cites.

Citations make answers look trustworthy even when they are wrong, so every sentence that cites
[n] is checked against the text of source n (the same text the model was given):
- every number in the sentence must appear in a cited source (20%, 1,000 and 5.0s count as
  20, 1000 and 5), and
- enough of its content words must appear there too (MIN_OVERLAP, tuned on examples in
  tests/test_grounding.py: paraphrases of a source score 0.67 and up, claims the source
  doesn't make score 0.33 or less).
Factual-looking sentences with no citation are checked against all of the answer's sources
and flagged when none of them backs the sentence.

Two more checks use the game's own records: a character, weapon or set the sentence names must
appear in the source it cites, and "Citlali (Hydro)" must match Citlali's real element.

`enforce` then acts on the report: a sentence that fails is removed, so a wrong line never
stays on the page with a warning next to it. It is still a screen, not proof: a number that
appears anywhere in the cited source passes (a 2-piece bonus quoted with the 4-piece number
would not be caught), and wording alone can't tell a good paraphrase from a subtle error.

Deterministic, no model calls: a typical answer takes well under a millisecond.
"""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

MIN_OVERLAP = 0.5
MIN_FACT_WORDS = 4  # an uncited sentence needs a number or this many content words to count
MIN_CHECKED_WORDS = 3  # "Rarity: 5-star" is too short for word overlap to mean anything
# Below this a sentence is removed. Claims a source doesn't make score 0.33 or less;
# between here and MIN_OVERLAP it stays, marked in the page, if its names and numbers hold.
REMOVE_BELOW = 0.4
HARD_FAILURES = {"number", "name", "element"}
ELEMENTS = "anemo|geo|electro|dendro|hydro|pyro|cryo"
PARTIAL_NOTE = "I could only verify part of an answer to this. Here's what the sources state:"

CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"[a-z][a-z']+")
# A sentence ends at . ! or ? (plus any closing bold and citations) before a capital letter,
# a quote or bold. Decimals ("5.0s") and abbreviations ("Lv. 90", "e.g. Ayaka") do not end one.
END = re.compile(
    r"[.!?]+(?:\*{1,2})?(?:\s*\[\d+(?:\s*,\s*\d+)*\])*(?:\*{1,2})?(?=\s+[\"*A-Z]|\s*$)"
)
ABBREVIATIONS = {"lv", "e.g", "i.e", "vs", "approx", "etc", "no", "st", "mr", "ms", "dr"}
LIST_MARK = re.compile(r"^\s*(?:[-·*]|\d+[.)]|>)\s+")
SYNONYMS = {
    "cooldown": "cd",
    "damage": "dmg",
    "attack": "atk",
    "attacks": "atk",
    "defense": "def",
    "er": "energy recharge",
    "em": "elemental mastery",
    "lasts": "duration",
    "last": "duration",
    "lasting": "duration",
    "seconds": "",  # a unit: the number check already covers "5 seconds" vs "5.0s"
    "second": "",
    "sec": "",
    "percent": "",
    "star": "",
}
HEDGES = ("don't have", "do not have", "not sure", "no verified", "isn't in", "is not in")
_STOPWORDS = """
a about above after again against all also am an and any are as at be because been
before being below between both but by can cannot could did do does doing down during
each few for from further had has have having he her here hers him his how if in into is
it its itself just let me more most my no nor not of off on once only or other our out
over own same she should so some such than that the their them then there these they
this those through to too under until up very was we were what when where which while
who whom why will with would you your yours get gets got make makes use uses used using
one ones also still well much many may might must shall per via
"""
STOPWORDS = frozenset(_STOPWORDS.split())


@dataclass
class Sentence:
    i: int
    text: str  # plain text: no Markdown, no citation markers (the UI finds it in the page)
    cites: list[int] = field(default_factory=list)
    status: str = "skip"  # supported | unsupported | uncited | skip (not a factual claim)
    reason: str | None = None  # number | words | no_citation
    overlap: float | None = None
    missing_numbers: list[str] = field(default_factory=list)
    raw: str = ""  # as written in the answer, for removing it


def _plain(text: str) -> str:
    text = CITE.sub(" ", text)
    text = re.sub(r"[*`_]+", "", text)
    return " ".join(text.split()).strip()


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in NUMBER.findall(text):
        n = raw.replace(",", "").rstrip(".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def _stems(text: str) -> set[str]:
    """Content words, cut to five letters so "elemental" and "element" match.

    Game shorthand and its spelled-out form count as the same word (CD and cooldown).
    """
    words = WORD.findall(text.casefold().replace("’", "'"))
    out = set()
    for w in words:
        w = SYNONYMS.get(w, w)
        if w and w not in STOPWORDS:
            out.update(x[:5] for x in w.split())
    return out


def split(answer: str) -> list[tuple[str, list[int]]]:
    """Split a Markdown answer into (raw sentence, cited source numbers).

    Headings and table header/separator rows are left out; a table row counts as one sentence.
    """
    units: list[str] = []
    header_row = True
    for line in answer.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            header_row = True
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s[1:-1].split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            if not header_row:
                units.append(" ".join(cells))
            header_row = False
            continue
        header_row = True
        s = LIST_MARK.sub("", s)
        start = 0
        for m in END.finditer(s):
            word = re.findall(r"[\w.]+$", s[start : m.start()])
            if word and word[0].casefold().rstrip(".") in ABBREVIATIONS:
                continue
            units.append(s[start : m.end()])
            start = m.end()
        if s[start:].strip():
            units.append(s[start:])
    out = []
    for u in units:
        cites = sorted({int(n) for g in CITE.findall(u) for n in re.split(r"\s*,\s*", g)})
        out.append((u.strip(), cites))
    return out


def _check(text: str, source: str) -> tuple[bool, str | None, float, list[str]]:
    missing = sorted(_numbers(text) - _numbers(source))
    words = _stems(text)
    overlap = len(words & _stems(source)) / len(words) if words else 1.0
    if missing:
        return False, "number", overlap, missing
    if overlap < MIN_OVERLAP and len(words) >= MIN_CHECKED_WORDS:
        return False, "words", overlap, []
    return True, None, overlap, []


def _factual(text: str) -> bool:
    low = text.casefold()
    if any(h in low for h in HEDGES):
        return False
    return bool(_numbers(text)) or len(_stems(text)) >= MIN_FACT_WORDS


def _records(text: str, source: str, named: list[tuple[str, str | None]]) -> str | None:
    """What the game's records contradict in a sentence: "element", "name" or nothing.

    `named` is (name, element) for each character, weapon or set the sentence names.
    """
    folded = source.casefold().replace("’", "'")
    for name, element in named:
        claim = re.search(rf"{re.escape(name)}\W{{1,3}}({ELEMENTS})\b", text, re.I)
        if claim and element and claim.group(1).casefold() != element.casefold():
            return "element"
        words = [w for w in name.casefold().replace("’", "'").split() if len(w) > 3]
        if words and not any(w in folded for w in words):
            return "name"
    return None


def check(
    answer: str,
    sources: dict[int, str],
    named: Callable[[str], list[tuple[str, str | None]]] | None = None,
) -> dict:
    """Grounding report for an answer, given the source text for each citation number.

    `named` finds the game records a sentence names (see `_records`).
    """
    sentences: list[Sentence] = []
    everything = "\n".join(sources.values())
    for i, (raw, cites) in enumerate(split(answer)):
        s = Sentence(i, _plain(raw), [n for n in cites if n in sources], raw=raw)
        if s.cites:
            ok, s.reason, overlap, s.missing_numbers = _check(
                s.text, "\n".join(sources[n] for n in s.cites)
            )
            s.status, s.overlap = ("supported" if ok else "unsupported"), round(overlap, 2)
            cited = "\n".join(sources[n] for n in s.cites)
            if named and (wrong := _records(s.text, cited, named(s.text))):
                s.status, s.reason = "unsupported", wrong
        elif _factual(s.text):
            ok, _, overlap, s.missing_numbers = _check(s.text, everything)
            s.overlap = round(overlap, 2)
            s.status, s.reason = ("supported", None) if ok else ("uncited", "no_citation")
            if named and (wrong := _records(s.text, everything, named(s.text))):
                s.status, s.reason = "uncited", wrong
        sentences.append(s)
    return {
        "checked": sum(1 for s in sentences if s.cites),
        "unsupported": [s.i for s in sentences if s.status == "unsupported"],
        "uncited": [s.i for s in sentences if s.status == "uncited"],
        "sentences": [asdict(s) for s in sentences],
    }


def _fails(s: dict, strict: bool) -> bool:
    if s["status"] not in ("unsupported", "uncited"):
        return False
    if s["reason"] in HARD_FAILURES or s["missing_numbers"]:
        return True
    return strict and s["overlap"] is not None and s["overlap"] < REMOVE_BELOW


def _cut(text: str, raw: str) -> str:
    if raw in text:
        return text.replace(raw, "", 1)
    # A table row was checked as its cells joined up: remove the row
    lines = text.splitlines()
    keep = [
        line
        for line in lines
        if not (
            line.strip().startswith("|") and " ".join(re.split(r"\s*\|\s*", line)).strip() == raw
        )
    ]
    return "\n".join(keep)


def enforce(answer: str, report: dict, strict: bool = True) -> tuple[str, list[str]]:
    """Remove every sentence that failed. Returns (the answer, what was removed), and "" when
    nothing factual is left. `strict` is off for answers in another language, where word
    overlap with English sources means nothing and only numbers and records can be checked."""
    failed = [s for s in report["sentences"] if _fails(s, strict)]
    if not failed:
        return answer, []
    text = answer
    for s in failed:
        text = _cut(text, s["raw"])
    lines = []
    for line in text.splitlines():
        if LIST_MARK.sub("", line).strip(" *") or not line.strip():
            lines.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    kept = [
        s
        for s in report["sentences"]
        if s not in failed and (s["status"] == "supported" or not strict)
    ]
    if not kept:
        return "", [s["text"] for s in failed]
    if report["sentences"][0] in failed:  # the headline went: don't let a bullet pose as it
        text = f"{PARTIAL_NOTE}\n\n{text}"
    return text, [s["text"] for s in failed]
