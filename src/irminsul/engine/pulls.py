"""Pull math: wish odds from pity, and free-Primogem estimates. Code does the sums, not a model.

Rates: official consolidated odds and guarantees, with the community-measured soft pity
(0.6% then +6% a pull from 74 on character banners; 0.7% then +7% from 63 on weapon banners).
Capturing Radiance is folded into HoYoverse's stated 55% consolidated chance on a 50/50.

Savings estimates add only recurring free sources, so they are a floor: events, exploration
and achievements come on top. Version dates follow the 42-day cadence and are estimates. An
estimate for a future version says nothing about what that version contains.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

WISH_PRICE = 160
WIN_5050 = 0.55  # official consolidated chance, Capturing Radiance included
WEAPON_CHOSEN = 0.375  # 75% promotional, split between two weapons; else 1 Fate Point
MAX_WISHES = 3000

# Recurring free Primogems (team research, Oct 2026)
DAILY = 60
ABYSS = 800  # 16th of each month
THEATER = 800  # 1st of each month
PER_VERSION = {"update compensation": 600, "livestream codes": 300, "Stygian": 450, "trials": 80}
SHOP_FATES = 5  # Paimon's Bargains, 1st of each month, for Masterless Stardust

CADENCE_DAYS = 42
ANCHOR_VERSION = (7, 2)  # official start date; later ones follow the cadence
ANCHOR_DATE = date(2026, 11, 4)
MINORS_PER_MAJOR = 8  # x.0 to x.7 since 5.x


def _rates(banner: str) -> np.ndarray:
    """Chance of a 5-star on pull n since the last one (index 0 is pull 1)."""
    base, soft, step, hard = (0.007, 63, 0.07, 80) if banner == "weapon" else (0.006, 74, 0.06, 90)
    n = np.arange(1, hard + 1)
    rates = base + step * np.maximum(n - soft + 1, 0)
    rates[-1] = 1.0
    return np.minimum(rates, 1.0)


def five_star_wait(banner: str, pity: int) -> np.ndarray:
    """Chance the next 5-star lands exactly k pulls from now (index 0 is k = 0, always 0)."""
    rates = _rates(banner)[pity:]
    left = np.concatenate(([1.0], np.cumprod(1 - rates)[:-1]))
    return np.concatenate(([0.0], rates * left))


def _combine(a: np.ndarray, b: np.ndarray, limit: int) -> np.ndarray:
    return np.convolve(a, b)[: limit + 1]


def _pad(a: np.ndarray, limit: int) -> np.ndarray:
    return np.pad(a[: limit + 1], (0, max(0, limit + 1 - len(a))))


def target_wait(banner: str, pity: int, guaranteed: bool, copies: int, limit: int) -> np.ndarray:
    """Chance the last of `copies` wanted items lands exactly k pulls from now, up to `limit`."""
    win = WEAPON_CHOSEN if banner == "weapon" else WIN_5050
    fresh = five_star_wait(banner, 0)
    first = five_star_wait(banner, pity)
    one = _pad(win * fresh, limit) + (1 - win) * _pad(_combine(fresh, fresh, limit), limit)
    if guaranteed:
        total = _pad(first, limit)
    else:
        total = win * _pad(first, limit) + (1 - win) * _pad(_combine(first, fresh, limit), limit)
    for _ in range(copies - 1):
        total = _pad(_combine(total, one, limit), limit)
    return total


@dataclass
class Odds:
    chance: float  # of getting all the wanted copies within the wishes
    expected: float  # average wishes needed
    worst: int  # most wishes it can take


def odds(
    wishes: int, banner: str = "character", pity: int = 0, guaranteed: bool = False, copies: int = 1
) -> Odds:
    hard = 80 if banner == "weapon" else 90
    pity = max(0, min(pity, hard - 1))
    copies = max(1, min(copies, 7))
    wishes = max(0, min(wishes, MAX_WISHES))
    worst = (hard - pity) + (0 if guaranteed else hard) + 2 * hard * (copies - 1)
    wait = target_wait(banner, pity, guaranteed, copies, worst)
    expected = float((np.arange(len(wait)) * wait).sum())
    return Odds(float(wait[: wishes + 1].sum()), expected, worst)


def wishes_from(primos: int = 0, fates: int = 0) -> int:
    return fates + primos // WISH_PRICE


# ---- free-Primogem estimates --------------------------------------------------------------


def version_start(version: tuple[int, int], phase: int = 1) -> date:
    steps = (version[0] * MINORS_PER_MAJOR + version[1]) - (
        ANCHOR_VERSION[0] * MINORS_PER_MAJOR + ANCHOR_VERSION[1]
    )
    return ANCHOR_DATE + timedelta(days=CADENCE_DAYS * steps + (21 if phase == 2 else 0))


def _monthly(start: date, end: date, day: int) -> int:
    """How many times the given day of the month falls after `start`, up to `end`."""
    count, y, m = 0, start.year, start.month
    while date(y, m, 1) <= end:
        if start < date(y, m, day) <= end:
            count += 1
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return count


@dataclass
class Income:
    until: date
    days: int
    lines: list[tuple[str, int]]
    shop_fates: int

    @property
    def primos(self) -> int:
        return sum(amount for _, amount in self.lines)

    @property
    def wishes(self) -> int:
        return self.primos // WISH_PRICE + self.shop_fates


def income(today: date, until: date, welkin: bool = False) -> Income:
    days = max(0, (until - today).days)
    abyss, theater = _monthly(today, until, 16), _monthly(today, until, 1)
    versions = 0
    step = ANCHOR_DATE
    while step <= until:
        if step > today:
            versions += 1
        step += timedelta(days=CADENCE_DAYS)
    lines = [
        ("Daily Commissions", DAILY * days),
        ("Spiral Abyss resets", ABYSS * abyss),
        ("Imaginarium Theater resets", THEATER * theater),
        (
            "Version rewards (compensation, codes, Stygian, trials)",
            sum(PER_VERSION.values()) * versions,
        ),
    ]
    if welkin:
        lines.append(("Welkin Moon", 90 * days))
    return Income(until, days, lines, SHOP_FATES * theater)


# ---- reading a player's question ----------------------------------------------------------

_NUM = r"(\d[\d,]*)"
_PRIMOS = re.compile(_NUM + r"\s*(?:primo\w*|gems?)\b", re.I)
_FATES = re.compile(_NUM + r"\s*(?:intertwined\s*)?(?:fates?)\b", re.I)
_WISHES = re.compile(_NUM + r"\s*(?:wish(?:es)?|pulls?|rolls?)\b", re.I)
_PITY = re.compile(r"\b(?:" + _NUM + r"\s*pity|pity\s*(?:is|at|of|=|:)?\s*" + _NUM + r")", re.I)
_GUARANTEED = re.compile(r"\bguarantee[d]?\b|\blost (?:my|the|a) (?:50|fifty)", re.I)
_NOT_GUARANTEED = re.compile(r"\b(?:not|no|isn'?t|without)\s+(?:a\s+)?guarantee", re.I)
_COPIES = re.compile(r"\bc([1-6])\b", re.I)
_REFINE = re.compile(r"\br([2-5])\b", re.I)
_WEAPON_ASK = re.compile(
    r"\bweapon banner\b|\bepitome\b|\bweapon\b.*\bbanner\b|\bfate points?\b", re.I
)
_ODDS_ASK = re.compile(
    r"\bchances?\b|\bodds\b|\bprobability\b|\bhow likely\b|\benough\b|\bcan i (?:get|afford)\b"
    r"|\bwill i (?:get|have)\b|\bwhat are my\b",
    re.I,
)
_SAVINGS_ASK = re.compile(
    r"\bhow (?:many|much)\b.*\b(?:primo\w*|wish(?:es)?|pulls?|gems?)\b"
    r"|\b(?:save|saving|savings|estimate|budget|free primo\w*)\b",
    re.I,
)
_VERSION = re.compile(r"\b(?:version |v|patch )?([4-9])\.(\d)\b", re.I)
_PHASE = re.compile(r"\b(?:phase|half)\s*([12])\b|\b(first|second) half\b", re.I)


def _int(text: str | None) -> int:
    return int(text.replace(",", "")) if text else 0


@dataclass
class Stash:
    wishes: int
    pity: int
    guaranteed: bool
    copies: int
    banner: str


def read_stash(question: str) -> Stash | None:
    """The numbers in 'I have 8000 primos, 20 fates, pity 40, guaranteed', if there are any."""
    primos, fates, pulls = (
        _PRIMOS.search(question),
        _FATES.search(question),
        _WISHES.search(question),
    )
    if not (primos or fates or pulls):
        return None
    wishes = wishes_from(_int(primos and primos.group(1)), _int(fates and fates.group(1)))
    wishes += _int(pulls and pulls.group(1))
    pity = _PITY.search(question)
    weapon = bool(_WEAPON_ASK.search(question) or _REFINE.search(question))
    copy = _COPIES.search(question)
    refine = _REFINE.search(question)
    copies = int(copy.group(1)) + 1 if copy else int(refine.group(1)) if refine else 1
    guaranteed = bool(_GUARANTEED.search(question)) and not _NOT_GUARANTEED.search(question)
    return Stash(
        wishes,
        _int(pity and (pity.group(1) or pity.group(2))),
        guaranteed,
        copies,
        "weapon" if weapon else "character",
    )


def target_version(question: str) -> tuple[tuple[int, int], int] | None:
    """The version (and phase) a question names, if any."""
    m = _VERSION.search(question)
    if not m:
        return None
    p = _PHASE.search(question)
    phase = 2 if p and (p.group(1) == "2" or (p.group(2) or "").lower() == "second") else 1
    return (int(m.group(1)), int(m.group(2))), phase


def is_savings_question(question: str) -> bool:
    return bool(_SAVINGS_ASK.search(question)) and target_version(question) is not None


def is_odds_question(question: str) -> bool:
    return bool(_ODDS_ASK.search(question)) and read_stash(question) is not None


def odds_text(s: Stash) -> str:
    o = odds(s.wishes, s.banner, s.pity, s.guaranteed, s.copies)
    want = f"{s.copies} cop{'y' if s.copies == 1 else 'ies'} of the featured "
    want += "weapon you chose" if s.banner == "weapon" else "character"
    state = f"pity {s.pity}" + (", guaranteed" if s.guaranteed else "")
    return (
        f"**About {o.chance:.0%} to get {want} with {s.wishes} wishes** ({state}).\n\n"
        f"- On average it takes about **{o.expected:.0f} wishes**.\n"
        f"- At the very worst it takes **{o.worst} wishes**, which is guaranteed.\n\n"
        "Based on official rates and the community-measured soft pity, so treat it as a good "
        "estimate. Odds are odds: no number here promises a result."
    )


def income_text(today: date, version: tuple[int, int], phase: int) -> str | None:
    until = version_start(version, phase)
    if until <= today or until > today + timedelta(days=CADENCE_DAYS * 12):
        return None
    est = income(today, until)
    rows = "\n".join(f"- {label}: {amount:,}" for label, amount in est.lines if amount)
    fates = f"\n- Shop Fates for Stardust: {est.shop_fates}" if est.shop_fates else ""
    return (
        f"**A rough floor of {est.primos:,} free Primogems ({est.wishes} wishes) from today "
        f"until {version[0]}.{version[1]} Phase {phase}**, around "
        f"{until.strftime('%b')} {until.day}, {until.year}.\n\n{rows}{fates}\n\n"
        "That's simple addition of recurring free rewards, assuming you clear the Abyss and "
        "Theater and do your dailies. Events, exploration and achievements add more. Add it to "
        "what you've saved. The date is an estimate from the 42-day update cycle, and says "
        "nothing about what that version contains."
    )
