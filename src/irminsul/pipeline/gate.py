"""Leak gate: only officially released (or officially announced) content may be served.

Every record passes through here before it can reach the index. The rules are
deliberately strict: when release status cannot be proven, the record is dropped.
"""

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from irminsul.schema import Release, ReleaseStatus, SourceRef, Tier


class Gated(Protocol):
    id: str
    name: str
    release: Release
    source: SourceRef


@dataclass
class GateReport:
    kept: list = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (id, reason)
    unverified: list[str] = field(default_factory=list)  # kept, but not cross-checked yet


def normalise_name(name: str) -> str:
    """Comparison key for names across sources: ignores case, accents, punctuation, spacing."""
    text = unicodedata.normalize("NFKD", name).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def check(record: Gated, now: datetime, blocklist: set[str]) -> str | None:
    """Return a drop reason, or None if the record may be served."""
    if record.id in blocklist:
        return "blocklisted"
    status = record.release.status
    if status == ReleaseStatus.UNKNOWN:
        return "release status unknown"
    if status == ReleaseStatus.RELEASED:
        released_at = record.release.released_at
        if released_at is not None and released_at > now:
            return f"release date {released_at:%Y-%m-%d} is in the future"
        return None
    if status == ReleaseStatus.ANNOUNCED:
        # Upcoming content is allowed only from official announcements.
        return None if record.source.tier == Tier.OFFICIAL else "announced but not official"
    return f"unhandled status {status}"


def gate_linked_docs(
    docs: Iterable, released_characters: set[str] | None
) -> tuple[list, list[tuple[str, str]], list[str]]:
    """Drop guide docs that are linked to a character who is not released in the live game.

    Third-party guides (e.g. KQM) carry no release data of their own, so a doc linked to
    `character/<slug>` is only served if that character passed the gate from official data.
    Returns (kept, dropped, unverified); without official data every linked doc is unverified.
    """
    kept, dropped, unverified = [], [], []
    for doc in docs:
        eid = doc.entity_id or ""
        if not eid.startswith("character/"):
            kept.append(doc)
            continue
        if released_characters is None:
            unverified.append(doc.doc_id)
            kept.append(doc)
            continue
        if eid in released_characters:
            kept.append(doc)
        else:
            dropped.append((doc.doc_id, f"linked character {eid} is not released"))
    return kept, dropped, unverified


def gate(
    records: Iterable[Gated],
    now: datetime,
    blocklist: set[str] | None = None,
    official_names: set[str] | None = None,
) -> GateReport:
    """Filter records. `official_names` (from HoYoWiki) confirms undated records."""
    report = GateReport()
    official = {normalise_name(n) for n in official_names} if official_names is not None else None
    for record in records:
        reason = check(record, now, blocklist or set())
        if reason:
            report.dropped.append((record.id, reason))
            continue
        undated = record.release.released_at is None
        if undated and official is not None and normalise_name(record.name) not in official:
            report.dropped.append((record.id, "not listed on official HoYoWiki"))
            continue
        if undated and official is None:
            report.unverified.append(record.id)
        report.kept.append(record)
    return report
