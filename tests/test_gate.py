from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from irminsul.pipeline.gate import gate
from irminsul.schema import Release, ReleaseStatus, SourceRef, Tier

NOW = datetime(2026, 10, 26, tzinfo=UTC)


@dataclass
class Rec:
    id: str
    name: str
    release: Release
    source: SourceRef


def rec(name, status, released_at=None, tier=Tier.OFFICIAL):
    return Rec(
        id=f"x/{name.lower()}",
        name=name,
        release=Release(status=status, released_at=released_at),
        source=SourceRef(source="t", url="https://example.org", tier=tier, fetched_at=NOW),
    )


def test_released_past_is_kept():
    r = gate([rec("A", ReleaseStatus.RELEASED, NOW - timedelta(days=1))], NOW)
    assert [x.name for x in r.kept] == ["A"] and not r.dropped


def test_future_release_date_is_dropped():
    r = gate([rec("B", ReleaseStatus.RELEASED, NOW + timedelta(days=9))], NOW)
    assert not r.kept and "future" in r.dropped[0][1]


def test_unknown_is_dropped():
    assert gate([rec("C", ReleaseStatus.UNKNOWN)], NOW).dropped[0][1] == "release status unknown"


def test_announced_needs_official_source():
    ok = gate([rec("D", ReleaseStatus.ANNOUNCED)], NOW)
    bad = gate([rec("E", ReleaseStatus.ANNOUNCED, tier=Tier.KQM)], NOW)
    assert len(ok.kept) == 1 and not bad.kept


def test_blocklist_wins():
    r = gate([rec("F", ReleaseStatus.RELEASED, NOW)], NOW, blocklist={"x/f"})
    assert r.dropped == [("x/f", "blocklisted")]


def test_undated_records_need_official_confirmation():
    undated = rec("G", ReleaseStatus.RELEASED)
    assert gate([undated], NOW).unverified == ["x/g"]
    assert gate([undated], NOW, official_names={"G"}).kept
    assert gate([undated], NOW, official_names={"Other"}).dropped[0][1] == (
        "not listed on official HoYoWiki"
    )
