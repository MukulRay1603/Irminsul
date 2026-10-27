"""Official HoYoverse news: update notices, events (with their redemption codes) and news.

The same feed genshin.hoyoverse.com/en/news reads, from HoYoverse's public content API.
These answer what game data can't: "which codes are active?", "when does this event end?",
"what's in the 7.1 update?". Each article becomes one official-tier Doc linking to its page.

Kept: articles from the last MAX_AGE_DAYS, plus the latest update notices whatever their age
(they describe the live version). Calendar wallpapers and similar are skipped. Story-safe
mode treats every notice as revealed in the live version, so a player who hasn't caught up
doesn't see event or chapter names from it.
"""

import html
import logging
import re
from datetime import UTC, datetime, timedelta

from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier
from irminsul.sources.http import PoliteClient

log = logging.getLogger("irminsul.notices")

API = "https://sg-public-api.hoyoverse.com/content_v2_user/app/a1b1f9d3315447cc"
PAGE = "https://genshin.hoyoverse.com/en/news/detail/{id}"
CHANNELS = {"397": "Update notice", "398": "Event", "396": "News"}
MAX_AGE_DAYS = 75
PER_CHANNEL = 30
UPDATE_NOTICES_ALWAYS = 2  # the live and previous versions' "Update Details"
_SKIP = re.compile(r"wallpaper|career test", re.I)
_TAG = re.compile(r"<(?:br|/p|/div|/li|/h\d)\s*/?>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")
UTC8 = timedelta(hours=8)  # the API's times are Beijing time


def plain_text(content: str) -> str:
    """Article HTML to readable text: paragraph breaks kept, tags and bare links dropped."""
    text = _ANY_TAG.sub(" ", _TAG.sub("\n", content or ""))
    text = _URL.sub("", html.unescape(text))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def published(item: dict) -> datetime | None:
    try:
        local = datetime.strptime(item.get("dtStartTime", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return (local - UTC8).replace(tzinfo=UTC)


class NoticesSource:
    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    def listing(self, channel: str) -> list[dict]:
        data = self.client.get_json(
            f"{API}/getContentList",
            {
                "iAppId": 32,
                "iChanId": channel,
                "iPageSize": PER_CHANNEL,
                "iPage": 1,
                "sLangKey": "en-us",
            },
        )
        return (data or {}).get("data", {}).get("list", []) or []

    def content(self, info_id: str) -> dict:
        data = self.client.get_json(
            f"{API}/getContent", {"iAppId": 32, "iInfoId": info_id, "sLangKey": "en-us"}
        )
        return (data or {}).get("data", {}) or {}

    def articles(self, now: datetime) -> list[tuple[str, dict]]:
        """(channel, list item) for every article worth keeping, newest first, no repeats."""
        seen: set[str] = set()
        chosen: list[tuple[str, dict]] = []
        for channel in CHANNELS:
            for i, item in enumerate(self.listing(channel)):
                info_id, when = str(item.get("iInfoId", "")), published(item)
                if not info_id.isdigit() or info_id in seen or when is None or when > now:
                    continue
                if _SKIP.search(item.get("sTitle", "")):
                    continue
                recent = now - when <= timedelta(days=MAX_AGE_DAYS)
                if recent or (channel == "397" and i < UPDATE_NOTICES_ALWAYS):
                    seen.add(info_id)
                    chosen.append((channel, item))
        return chosen


def notice_doc(
    channel: str, item: dict, content: str, fetched_at: datetime, live: str | None
) -> Doc | None:
    text = plain_text(content)
    when = published(item)
    if not text or when is None:
        return None
    info_id = str(item["iInfoId"])
    title = html.unescape(item.get("sTitle", "")).strip()
    day = when.date().isoformat()
    kind = CHANNELS[channel]
    return Doc(
        doc_id=f"notice/{info_id}",
        entity_id=None,
        kind="official_notice",
        title=f"{title} ({kind.lower()}, {day})",
        text=f"# {title}\n{kind} published by HoYoverse on {day}.\n{text}",
        release=Release(status=ReleaseStatus.RELEASED),
        source=SourceRef(
            source="hoyoverse_news",
            url=PAGE.format(id=info_id),
            tier=Tier.OFFICIAL,
            fetched_at=fetched_at,
            game_version=live,
        ),
        revealed_in=live,
    )


def fetch_notices(source: NoticesSource, now: datetime, live: str | None) -> list[Doc]:
    docs = []
    for channel, item in source.articles(now):
        try:
            content = source.content(str(item["iInfoId"])).get("sContent", "")
        except Exception as e:  # one broken article never stops the build
            log.warning("notice %s failed: %s", item.get("iInfoId"), e)
            continue
        if doc := notice_doc(channel, item, content, now, live):
            docs.append(doc)
    return docs
