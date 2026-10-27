"""Official news: recent articles and the latest update notices, as official-tier docs."""

from datetime import UTC, datetime

from irminsul.schema import Tier
from irminsul.sources.notices import NoticesSource, fetch_notices, plain_text, published

NOW = datetime(2026, 10, 27, tzinfo=UTC)


class FakeClient:
    def __init__(self, lists: dict[str, list[dict]], contents: dict[str, str]):
        self.lists, self.contents, self.calls = lists, contents, []

    def get_json(self, url, params=None):
        self.calls.append(params)
        if url.endswith("getContentList"):
            return {"data": {"list": self.lists.get(str(params["iChanId"]), [])}}
        info = str(params["iInfoId"])
        if info == "999":
            raise RuntimeError("broken article")
        return {"data": {"sContent": self.contents.get(info, "")}}


def item(info_id, title, when):
    return {"iInfoId": info_id, "sTitle": title, "dtStartTime": when}


def test_recent_articles_and_latest_update_notices_become_official_docs():
    lists = {
        "397": [
            item("2", "Version 7.1 Update Details", "2026-09-23 07:00:00"),
            item("1", "Version 7.0 Update Details", "2026-05-12 07:00:00"),  # old, but kept
            item("0", "Version 6.8 Update Details", "2026-03-12 07:00:00"),  # old: dropped
        ],
        "398": [
            item("3", "Event Now Available - Patrol", "2026-09-24 10:00:00"),
            item("4", "October Calendar Wallpapers", "2026-09-30 11:00:00"),  # skipped
            item("5", "Future article", "2026-11-30 11:00:00"),  # not published yet
            item("999", "Broken article", "2026-10-01 10:00:00"),
        ],
        "396": [item("3", "Event Now Available - Patrol", "2026-09-24 10:00:00")],  # repeat
    }
    contents = {
        "1": "<p>7.0 notes</p>",
        "2": "<p>New in 7.1</p>",
        "3": "<p>Redemption Code: <b>VesnaOnPatrol</b> valid until October 22, 2026</p>"
        '<p>Redeem here <a href="https://hoyo.link/x">https://hoyo.link/x</a></p>',
    }
    docs = fetch_notices(NoticesSource(FakeClient(lists, contents)), NOW, "7.1")
    assert [d.doc_id for d in docs] == ["notice/2", "notice/1", "notice/3"]
    event = docs[2]
    assert event.source.tier == Tier.OFFICIAL
    assert event.source.url == "https://genshin.hoyoverse.com/en/news/detail/3"
    assert "VesnaOnPatrol" in event.text and "hoyo.link" not in event.text
    assert "published by HoYoverse on 2026-09-24" in event.text
    assert event.revealed_in == "7.1"


def test_html_to_text_and_beijing_time():
    assert plain_text("<p>A &amp; B</p><p>C<br>D</p>") == "A & B\nC\nD"
    when = published(item("1", "x", "2026-09-24 10:00:00"))
    assert when == datetime(2026, 9, 24, 2, 0, tzinfo=UTC)
    assert published(item("1", "x", "soon")) is None
