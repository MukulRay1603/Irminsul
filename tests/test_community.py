"""Community build guides: post-release only, leak-filtered, cached, quota-capped."""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_engine import store

from irminsul.api.community import SEARCHES_PER_DAY, CommunityVideos, add_community, seconds


class FakeYouTube:
    def __init__(self, titles: dict[str, str], durations: dict[str, str] | None = None):
        self.titles = titles  # video id -> title
        self.durations = durations or {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, endpoint: str, params: dict) -> dict:
        self.calls.append((endpoint, params))
        if endpoint == "search":
            return {
                "items": [
                    {
                        "id": {"videoId": vid},
                        "snippet": {
                            "title": t,
                            "channelTitle": "A Creator",
                            "publishedAt": "2026-10-01T00:00:00Z",
                        },
                    }
                    for vid, t in self.titles.items()
                ]
            }
        ids = params["id"].split(",")
        return {
            "items": [
                {
                    "id": vid,
                    "statistics": {"viewCount": str(1000 * (i + 1))},
                    "contentDetails": {"duration": self.durations.get(vid, "PT12M3S")},
                }
                for i, vid in enumerate(ids)
            ]
        }


RAIDEN = "character/raiden-shogun"


def make(yt, clock=lambda: 1_800_000_000.0):
    return CommunityVideos(store(), "test-key", (7, 1), fetch=yt, clock=clock)


def test_only_safe_full_guides_after_release_are_kept():
    yt = FakeYouTube(
        {
            "a": "Raiden Shogun Build Guide &amp; Best Teams",
            "b": "Raiden Shogun 7.3 LEAKS kit changes",
            "c": "Raiden Shogun beta kit test",
            "d": "Raiden Shogun 7.4 build",
            "e": "Best Furina teams",  # doesn't name the character
            "f": "Raiden Shogun build in 30s",
        },
        durations={"f": "PT30S"},
    )
    vids = make(yt).for_character(RAIDEN)
    assert [v["youtube_id"] for v in vids] == ["a"]
    assert vids[0]["title"] == "Raiden Shogun Build Guide & Best Teams"  # unescaped
    search = yt.calls[0][1]
    released = store().by_id[RAIDEN].entity.release.released_at
    assert search["publishedAfter"] == released.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert search["safeSearch"] == "strict"


def test_top_three_by_views_and_cached_for_a_day():
    now = [1_800_000_000.0]
    yt = FakeYouTube({str(i): f"Raiden Shogun guide part {i}" for i in range(5)})
    c = make(yt, clock=lambda: now[0])
    first = c.for_character(RAIDEN)
    assert len(first) == 3 and first[0]["views"] > first[-1]["views"]
    c.for_character(RAIDEN)
    assert sum(1 for e, _ in yt.calls if e == "search") == 1
    now[0] += 25 * 3600
    c.for_character(RAIDEN)
    assert sum(1 for e, _ in yt.calls if e == "search") == 2


def test_daily_search_cap_and_errors_never_break_the_page():
    yt = FakeYouTube({"a": "Raiden Shogun guide"})
    c = make(yt)
    c._searches, c._day = (
        SEARCHES_PER_DAY,
        datetime.fromtimestamp(1_800_000_000, UTC).strftime("%Y-%m-%d"),
    )
    assert c.for_character(RAIDEN) == [] and yt.calls == []

    def broken(endpoint, params):
        raise RuntimeError("quota exceeded")

    assert make(broken).for_character(RAIDEN) == []


def test_endpoint_lists_videos_for_a_versions_characters():
    yt = FakeYouTube({"a": "Raiden Shogun guide"})
    notes = {"versions": [{"version": "7.1", "characters": [{"id": RAIDEN}]}]}
    app = FastAPI()
    add_community(app, make(yt), notes)
    c = TestClient(app)
    body = c.get("/api/community-videos", params={"version": "7.1"}).json()
    assert [v["youtube_id"] for v in body["videos"]] == ["a"]
    assert c.get("/api/community-videos", params={"version": "9.9"}).status_code == 404
    off = FastAPI()
    add_community(off, None, notes)
    assert (
        TestClient(off).get("/api/community-videos", params={"version": "7.1"}).status_code == 404
    )


def test_iso_durations():
    assert seconds("PT1H2M3S") == 3723 and seconds("PT45S") == 45 and seconds("bad") == 0


def test_endpoint_only_serves_recent_versions_and_limits_each_client():
    from irminsul.api.community import PER_CLIENT_PER_HOUR

    yt = FakeYouTube({"a": "Raiden Shogun guide"})
    notes = {
        "versions": [
            {"version": v, "characters": [{"id": RAIDEN}]} for v in ("7.1", "7.0", "6.8", "6.0")
        ]
    }
    app = FastAPI()
    add_community(app, make(yt), notes)
    c = TestClient(app)
    assert c.get("/api/community-videos", params={"version": "6.0"}).status_code == 404
    codes = [
        c.get("/api/community-videos", params={"version": "7.1"}).status_code
        for _ in range(PER_CLIENT_PER_HOUR + 1)
    ]
    assert codes[:-1] == [200] * PER_CLIENT_PER_HOUR and codes[-1] == 429


def test_a_failed_search_is_not_retried_at_once():
    calls = []

    def broken(endpoint, params):
        calls.append(endpoint)
        raise RuntimeError("quota exceeded")

    c = make(broken)
    assert c.for_character(RAIDEN) == [] and c.for_character(RAIDEN) == []
    assert calls == ["search"]
