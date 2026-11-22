"""Facts that come from data, not from code: re-checked facts, topic tags, the official
calendar, and words and nicknames learned from the corpus and feedback."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from irminsul.engine import pulls
from irminsul.engine.entities import EntityStore
from irminsul.engine.guards import on_topic
from irminsul.pipeline import freshness
from irminsul.pipeline.recheck import CHANGED, OK, UNREADABLE, UNSURE, recheck, verdict
from irminsul.pipeline.vocab import nicknames, proper_nouns
from irminsul.sources.http import FetchError
from irminsul.sources.team_facts import fact_lines, parse_facts

NOW = datetime(2026, 11, 22, 12, tzinfo=UTC)
URL = "https://game8.co/games/Genshin-Impact/archives/1"
FILE = (
    "## Wishes\n"
    f"- Either Fate can be bought for 160 Primogems. | {URL} | 2026-10-26 | 7.1\n"
    f"- Every 3-star item from a wish gives 15 Masterless Stardust. #fates | {URL} | "
    "2026-10-26 | 7.1\n"
    f"- Pity is 90 wishes. | {URL} | 2026-10-26 | 7.1\n"
)
PAGE = (
    "Wishes cost one Intertwined Fate; buy Fates for 160 Primogems in the shop. Every 3-star "
    "gives 15 Masterless Stardust. " * 20
)


class FakeClient:
    def __init__(self, pages):
        self.pages, self.calls = pages, 0

    def get_page(self, url):
        self.calls += 1
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        return page


# ---- B1: facts re-check themselves ------------------------------------------------------
def test_a_page_that_still_says_it_confirms_the_line():
    assert verdict("Either Fate can be bought for 160 Primogems.", PAGE, URL) == (OK, [])


def test_a_number_the_page_no_longer_shows_hides_the_line():
    status, missing = verdict("Either Fate can be bought for 180 Primogems.", PAGE, URL)
    assert status == CHANGED and "180" in missing


def test_reworded_names_alone_only_ask_for_a_look():
    status, _ = verdict("The Starfall Exchange sells Fates for 160 Primogems.", PAGE, URL)
    assert status == UNSURE


def test_numbers_with_commas_stay_whole():
    page = "The Benefits Overview lists 1,600 Primogems. " * 20
    assert verdict("It lists 1,600 Primogems.", page, URL)[0] == OK


def test_a_clause_credited_to_another_source_is_not_this_pages_to_confirm():
    fact = "KQM names Song of Broken Pines, a six-way tie at 741 in Yatta's weapon data."
    page = "Song of Broken Pines is Eula's best claymore. " * 20
    assert verdict(fact, page, "https://keqingmains.com/q/eula")[0] == OK


def lines():
    return fact_lines(FILE)


def test_only_lines_behind_the_live_version_are_fetched_and_each_page_once():
    client = FakeClient({URL: PAGE})
    checks = recheck(lines(), {}, (7, 2), NOW, client)
    assert client.calls == 1 and checks["live"] == "7.2"
    assert [f["status"] for f in checks["facts"].values()] == [OK, OK, CHANGED]
    again = recheck(lines(), checks, (7, 2), NOW, FakeClient({}))
    assert again["facts"] == checks["facts"]  # a verdict for this version is not re-fetched
    assert recheck(lines(), {}, (7, 1), NOW, client)["facts"] == {}  # nothing is behind


def test_an_unreadable_page_keeps_the_line_and_tries_again():
    checks = recheck(lines(), {}, (7, 2), NOW, FakeClient({URL: FetchError("down")}))
    assert {f["status"] for f in checks["facts"].values()} == {UNREADABLE}
    client = FakeClient({URL: PAGE})
    assert recheck(lines(), checks, (7, 2), NOW, client)["counts"][OK] == 2
    assert client.calls == 1


def test_confirmed_lines_are_restamped_and_changed_ones_hidden():
    checks = recheck(lines(), {}, (7, 2), NOW, FakeClient({URL: PAGE}))
    result = parse_facts(FILE, NOW, (7, 2), checks=checks)
    text = result.docs[0].text
    assert "(checked 2026-11-22 by machine; applies to 7.2" in text
    assert "Pity is 90" not in text and result.dropped[0][1].startswith("its source")
    assert result.docs[0].source.game_version == "7.2"


def test_a_newer_hand_check_wins_over_the_machine():
    checks = recheck(lines(), {}, (7, 2), NOW, FakeClient({URL: PAGE}))
    rechecked = FILE.replace(
        "Pity is 90 wishes. | " + URL + " | 2026-10-26",
        "Pity is 90 wishes. | " + URL + " | 2026-11-23",
    )
    assert "Pity is 90" in parse_facts(rechecked, NOW, (7, 2), checks=checks).docs[0].text


def test_hidden_facts_raise_one_freshness_problem_naming_only_pages(tmp_path):
    checks = recheck(lines(), {}, (7, 2), NOW, FakeClient({URL: PAGE}))
    (tmp_path / "fact_checks.json").write_text(json.dumps(checks))
    (problem,) = freshness.fact_problems(tmp_path, NOW)
    assert "1 team fact lines are hidden" in problem and URL in problem and "Pity" not in problem


# ---- B2: topic tags instead of doc ids ----------------------------------------------------
RULES = [{"topic": "fates", "section": "Wishes", "match": "160 Primogems"}]


def test_tags_come_from_the_file_and_from_the_rules():
    text = parse_facts(FILE, NOW, (7, 1), topics=RULES).docs[0].text
    assert "160 Primogems. (checked 2026-10-26; applies to 7.1; topics: fates)" in text
    assert "15 Masterless Stardust. (checked 2026-10-26; applies to 7.1; topics: fates)" in text
    assert "Pity is 90 wishes. (checked 2026-10-26; applies to 7.1)" in text
    assert "#fates" not in text


def test_a_tagged_line_feeds_the_fates_answer_wherever_it_sits():
    from types import SimpleNamespace

    from irminsul.engine.engine import Engine

    moved = "## Odds and ends\n" + FILE.split("\n", 1)[1]
    docs = parse_facts(moved, NOW, (7, 1), topics=[{"topic": "fates", "match": "160 Prim"}]).docs
    docs += parse_facts(FILE.replace(URL, URL + "2"), NOW, (7, 1)).docs
    engine = Engine.__new__(Engine)
    engine.index = SimpleNamespace(
        chunks=[
            SimpleNamespace(
                doc_id=d.doc_id,
                title=d.title,
                source_url=d.source.url,
                tier="community",
                text=d.text,
            )
            for d in docs
        ]
    )
    answer = engine._fates_answer("How do I get more Fates?")
    assert "160 Primogems. [1]" in answer.text and "15 Masterless Stardust. [2]" in answer.text


def test_the_topic_rules_file_parses():
    import tomllib

    rules = tomllib.loads(Path("config/fact_topics.toml").read_text("utf-8"))["rule"]
    assert {r["topic"] for r in rules} == {"fates"}


# ---- B3: one calendar from the official notices ------------------------------------------
@pytest.fixture
def calendar():
    yield pulls.use_calendar
    pulls.use_calendar(None)


def test_official_dates_beat_the_cadence(calendar):
    feed = {
        "versions": {"7.2": "2026-11-04", "7.3": "2026-12-17"},
        "banners": [{"version": "7.3", "phase": 2, "start": "2027-01-06"}],
    }
    calendar(feed)
    assert pulls.version_start((7, 3)) == date(2026, 12, 17)  # a day later than the cadence
    assert pulls.version_start((7, 3), 2) == date(2027, 1, 6)
    assert pulls.version_start((7, 4)) == date(2027, 1, 28)  # 42 days from the newest notice
    assert pulls.anchor() == ((7, 3), date(2026, 12, 17))


def test_without_the_calendar_the_last_known_date_counts_on(calendar):
    calendar(None)
    assert pulls.version_start((7, 3)) == date(2026, 12, 16)


def test_income_figures_ask_for_a_look_once_a_newer_version_is_live(tmp_path):
    wish = {
        "version": "7.3",
        "kind": "character",
        "start": "2026-11-20",
        "end": "2026-12-10",
        "five_stars": [],
        "four_stars": [],
        "name": "w",
        "phase": 1,
        "source": "",
    }
    feed = {"versions": {"7.3": "2026-11-20"}, "banners": [wish]}
    (tmp_path / "banners.json").write_text(json.dumps(feed))
    (tmp_path / "characters.jsonl").write_text("")
    manifest = {"deep_at": NOW.isoformat(), "sources": {"yatta": {"game_version": "73F1"}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert any("free-Primogem figures" in p for p in freshness.check(tmp_path, NOW))


# ---- B4: words and nicknames learned from the data ---------------------------------------
TEXTS = [
    "The leader of the Hexenzirkel was seen near the lake, and the Hexenzirkel met there. "
    "Only the Hexenzirkel knew, said a member of the Hexenzirkel, before the water rose. "
    "She drank water, then more water and water again. A Sonata of the Shores played."
] * 2


def test_proper_nouns_come_from_the_corpus():
    words = proper_nouns(TEXTS)
    assert "hexenzirkel" in words and "water" not in words and "sonata" not in words


def test_a_corpus_word_counts_as_on_topic_but_never_beats_an_offtopic_sign():
    vocab = frozenset({"pohjola"})
    assert on_topic("Tell me about Pohjola", False, vocab)
    assert not on_topic("Tell me about Pohjola", False)
    assert not on_topic("Write python code for Pohjola", False, vocab)


def store(tmp_path, vocabulary=None):
    row = {
        "id": "character/furina",
        "game_id": "10000089",
        "name": "Furina",
        "rarity": 5,
        "element": "Hydro",
        "weapon_type": "Sword",
        "release": {"status": "released"},
        "source": {
            "source": "yatta",
            "url": "https://gi.yatta.moe/en/archive/avatar/Furina",
            "tier": "official",
            "fetched_at": "2026-11-21T00:00:00Z",
        },
    }
    (tmp_path / "characters.jsonl").write_text(json.dumps(row) + "\n")
    if vocabulary:
        (tmp_path / "vocabulary.json").write_text(json.dumps(vocabulary))
    return EntityStore.load(tmp_path)


def feedback(question, rating="up", docs=("character/furina#overview",)):
    return {"kind": "answer", "rating": rating, "question": question, "doc_ids": list(docs)}


def test_a_nickname_is_learned_from_helpful_answers_about_one_character(tmp_path):
    s = store(tmp_path)
    records = [feedback(q) for q in ("furi build?", "best furi team", "is furi good")]
    assert nicknames(records, s, set()) == {"furi": "character/furina"}
    assert nicknames(records[:2], s, set()) == {}  # not enough uses yet
    unhelpful = [feedback(r["question"], "down") for r in records]
    assert nicknames(unhelpful, s, set()) == {}
    elsewhere = records + [feedback("furi lore", docs=("lore/fontaine#1",))]
    assert nicknames(elsewhere, s, set()) == {}  # it led somewhere else too: not sure yet


def test_a_learned_nickname_finds_the_character_but_never_replaces_a_name(tmp_path):
    s = store(tmp_path, {"words": ["hexenzirkel"], "nicknames": {"furi": "character/furina"}})
    assert [m.entity.id for m in s.find("furi build")] == ["character/furina"]
    assert "hexenzirkel" in s.vocabulary
