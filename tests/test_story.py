"""Story-safe mode: revealed_in from official data, the version gate in search, the engine's
"past your story point" guard, the API field and the per-story-point cache."""

import json
from datetime import UTC, datetime

import pytest
from conftest import FETCHED_AT, load_yatta
from fastapi.testclient import TestClient
from test_engine import FakeLLM
from test_retrieval import FakeEmbedder, doc

from irminsul import story
from irminsul.api.app import create_app
from irminsul.api.limits import Limits
from irminsul.engine.engine import Engine
from irminsul.engine.entities import EntityStore
from irminsul.evals import Category, load
from irminsul.pipeline.build import fetch_lore, stamp_revealed
from irminsul.pipeline.render import book_docs, character_docs, story_docs
from irminsul.retrieval.chunking import Chunk, chunk_docs
from irminsul.retrieval.index import Hit, HybridIndex
from irminsul.schema import Character, Release, ReleaseStatus, SourceRef, Tier
from irminsul.sources.yatta import parse_character, parse_stories, parse_weapon


def raiden() -> Character:
    c = parse_character(
        load_yatta("avatar_10000052"), load_yatta("avatarCurve"), FETCHED_AT, "71F2"
    )
    c.revealed_in = "2.1"
    return c


def changelog() -> story.Changelog:
    return story.Changelog(load_yatta("changelog"))


# ---- story points and versions -----------------------------------------------------------
def test_versions_parse_and_compare():
    assert story.parse_version("7.1") == (7, 1) and story.parse_version("10.0") == (10, 0)
    assert story.parse_version("71F2") is None and story.parse_version(None) is None
    assert story.later("2.1", "1.6") and not story.later("1.6", "1.6")
    assert not story.later(None, "1.0") and not story.later("2.1", None)  # unknown never hides


def test_story_points_follow_the_archon_quest_in_order():
    keys = [p.key for p in story.STORY_POINTS]
    assert keys[:3] == ["mondstadt", "liyue", "inazuma"] and keys[-1] == "nod-krai"
    versions = [story.parse_version(p.until) for p in story.STORY_POINTS]
    assert all(v is not None for v in versions) and versions == sorted(versions)
    assert story.point(None) is None and story.point("") is None
    with pytest.raises(ValueError):
        story.point("teyvat")


def test_hides_only_later_content():
    liyue = story.point("liyue")
    assert story.hides(liyue, "2.1") and not story.hides(liyue, "1.6")
    assert not story.hides(liyue, None) and not story.hides(None, "7.1")


# ---- revealed_in from official data --------------------------------------------------------
def test_changelog_first_listing_and_untracked_ceiling():
    cl = changelog()
    assert cl.version_of("avatar", "10000067") == "3.0"  # Collei
    assert cl.version_of("book", "1074") == "7.0" and cl.version_of("book", "nope") is None
    assert cl.first_tracked["book"] == "4.0"
    # A book the changelog never lists predates tracking: the last version before it.
    assert cl.untracked_ceiling("book") == "3.0" and cl.latest() == "7.1"


def test_character_versions_from_release_time_and_changelog():
    cl = story.Changelog(
        {
            "30": {"version": "3.0", "items": {"avatar": ["10000067", "10000005-dendro"]}},
            "62": {"version": "6.2", "items": {"avatar": ["10000022"]}},  # Venti re-listed
        }
    )

    def at(day: str) -> datetime:
        return datetime.fromisoformat(day).replace(tzinfo=UTC)

    reveal = story.character_revealed_in
    assert reveal("10000052", at("2021-08-31T21:00"), cl, "7.1") == "2.1"  # Raiden: eve of 2.1
    assert reveal("10000038", at("2020-12-21"), cl, "7.1") == "1.2"  # Albedo: 2 days early
    assert reveal("10000022", at("2020-09-27"), cl, "7.1") == "1.0"  # a re-list doesn't count
    assert reveal("10000067", at("2022-08-23"), cl, "7.1") == "3.0"
    # Dated 2.8 but first listed in 3.0: ambiguous, so the later (safer) version wins.
    assert reveal("10000005-dendro", at("2022-07-12"), cl, "7.1") == "3.0"
    assert reveal("99999999", None, cl, "7.1") == "7.1"  # unproven: hidden everywhere


def test_story_docs_carry_the_character_version():
    stories = parse_stories(load_yatta("avatarFetter_10000052"))
    assert stories[0][0] == "Character Details" and "\\n" not in stories[0][1]
    docs = story_docs(raiden(), stories)
    assert [d.kind for d in docs] == ["lore_story"] * len(stories)
    assert docs[1].doc_id == "character/raiden-shogun#lore-character-story-1"
    assert all(d.revealed_in == "2.1" and d.source.tier == Tier.OFFICIAL for d in docs)
    assert "Revealed in version 2.1" in docs[0].text
    assert all(d.revealed_in == "2.1" for d in character_docs(raiden()))


def test_book_docs_one_per_volume():
    book = load_yatta("book_1")
    texts = [load_yatta(f"readable_Book{v['storyId']}") for v in book["volume"]]
    source = SourceRef(source="yatta", url="u", tier=Tier.OFFICIAL, fetched_at=FETCHED_AT)
    docs = book_docs(
        book,
        [(v, t, "3.1") for v, t in zip(book["volume"], texts, strict=True)],
        Release(status=ReleaseStatus.RELEASED),
        source,
    )
    assert [d.doc_id for d in docs] == [
        "book/1#the-fox-in-the-dandelion-sea-i",
        "book/1#the-fox-in-the-dandelion-sea-ii",
    ]
    assert all(d.kind == "lore_book" and d.revealed_in == "3.1" for d in docs)
    assert "Dandelion" in docs[0].text


class FakeLoreSource:
    def __init__(self):
        self.asked: list[str] = []

    def character_stories(self, game_id):
        self.asked.append(game_id)
        return [("Character Story 1", f"Story of {game_id}.")]

    def books(self):
        book = {"id": 9, "name": "Future Book"}
        yield book, [({"id": 1, "name": "Future Book (I)"}, "text")]


def test_fetch_lore_is_leak_safe():
    def character(cid, game_id, status, revealed_in):
        return Character(
            id=cid,
            game_id=game_id,
            name=cid,
            rarity=5,
            element="Cryo",
            weapon_type="Sword",
            release=Release(status=status),
            source=SourceRef(source="t", url="u", tier=Tier.OFFICIAL, fetched_at=FETCHED_AT),
            revealed_in=revealed_in,
        )

    chars = [
        character("character/a", "1", ReleaseStatus.RELEASED, "2.1"),
        character("character/announced", "hoyowiki:1", ReleaseStatus.ANNOUNCED, "7.1"),
        character("character/traveler-cryo", "5-cryo", ReleaseStatus.RELEASED, "7.0"),
        character("character/traveler-anemo", "5-anemo", ReleaseStatus.RELEASED, "1.0"),
        character("character/future", "3", ReleaseStatus.RELEASED, "7.2"),
    ]
    source = FakeLoreSource()
    cl = story.Changelog({"72": {"version": "7.2", "items": {"book": ["9"]}}})
    docs, dropped, counts = fetch_lore(source, chars, cl, "7.1", FETCHED_AT, set(), True, None)
    # Never asked for the announced character; the Traveler profile is fetched once, by base id.
    assert sorted(source.asked) == ["1", "3", "5"]
    ids = {d.doc_id for d in docs}
    assert "character/traveler-anemo#lore-character-story-1" in ids
    assert not any("announced" in i or "traveler-cryo" in i for i in ids)
    # Anything revealed after the live version is dropped: a future character and book.
    assert {i for i, _ in dropped} == {
        "character/future#lore-character-story-1",
        "book/9#future-book-i",
    }
    assert counts == {"stories": 3, "books": 1, "book_volumes": 1}


def test_stamp_revealed_dates_entity_docs_and_guides():
    weapon = parse_weapon(load_yatta("weapon_11403"), load_yatta("weaponCurve"), FETCHED_AT, "x")
    r = raiden()
    guide = doc("kqm/raiden#1", "Raiden guide")
    guide.entity_id = r.id
    loose = doc("kqm/pity#1", "Pity rules")
    docs = [*character_docs(r), guide, loose]
    boss = doc("kqm/the-shogun#intro", "The Raiden Shogun's weekly boss fight.")
    old_lore = doc("kqm/ei#1", "Ei kept the sword.")  # a short name players use
    docs += [boss, old_lore]
    stamp_revealed(docs, {"characters": [r], "weapons": [weapon]}, changelog())
    assert guide.revealed_in == "2.1" and loose.revealed_in is None
    # Undated pages that name a character are dated by that character.
    assert boss.revealed_in == "2.1" and old_lore.revealed_in == "2.1"


# ---- search: the version gate ------------------------------------------------------------
def gated_index() -> HybridIndex:
    lore = doc("raiden-lore", "# Raiden lore\nRaiden Electro twin sister story.")
    lore.revealed_in = "2.1"
    early = doc("early-lore", "# Early lore\nElectro Raiden energy before Inazuma.")
    early.revealed_in = "1.0"
    rules = doc("pity", "# Pity\nThe banner has a pity of 90 wishes. Electro raiden.")
    return HybridIndex.build(chunk_docs([lore, early, rules]), embedder=FakeEmbedder())


def test_search_hides_chunks_revealed_after_the_story_point():
    index = gated_index()
    everything = {h.chunk.doc_id for h in index.search("raiden electro", k=5)}
    assert "raiden-lore" in everything
    report: dict = {}
    hits = index.search("raiden electro", k=5, max_revealed="1.6", report=report)
    assert {h.chunk.doc_id for h in hits} == {"early-lore", "pity"}
    assert report == {"hidden": 1}
    assert {h.chunk.doc_id for h in index.search("raiden", k=5, max_revealed="2.1")} >= {
        "raiden-lore"
    }


def test_hidden_chunks_never_reach_the_reranker():
    index = gated_index()
    seen: list[str] = []

    class Rerank:
        def rerank(self, query, passages):
            seen.extend(passages)
            return [1.0] * len(passages)

    index._rerank = Rerank()
    index.search("raiden electro", k=5, rerank=True, max_revealed="1.6")
    assert seen and not any("twin sister" in p for p in seen)


# ---- engine: the story-point guard, the filter and the cache -------------------------------
class StoryIndex:
    """Records the filter it gets; returns one chunk past Liyue and one before it."""

    def __init__(self):
        self.calls: list[dict] = []

    def search(self, question, k=6, mode="hybrid", rerank=False, exclude_tiers=frozenset(), **kw):
        self.calls.append(kw)
        if "report" in kw:
            kw["report"]["hidden"] = 3

        def chunk(doc_id, revealed_in):
            return Chunk(
                chunk_id=f"{doc_id}::0",
                doc_id=doc_id,
                entity_id=None,
                title=doc_id,
                text="Lore text.",
                tier="official",
                release_status="released",
                source_url="https://example.org",
                revealed_in=revealed_in,
            )

        # Ignores the filter on purpose: the engine must drop the late chunk itself as well.
        return [Hit(chunk("late-lore", "2.1"), 0.9, 0), Hit(chunk("early-lore", "1.0"), 0.8, 1)]


def engine(llm=None, index=None) -> Engine:
    return Engine(EntityStore([raiden()], [], []), index or StoryIndex(), llm or FakeLLM())


def test_exact_answers_past_the_story_point_get_a_gentle_stop():
    e = engine()
    stop = e.ask("What are Raiden Shogun's base stats?", story_until="liyue")
    assert stop.route == "spoiler" and "story point" in stop.text and "337" not in stop.text
    assert stop.citations == [] and stop.follow_ups == [] and "entity" not in stop.trace
    assert stop.trace["spoiler_filter"]["until"] == "liyue"
    assert e.is_free("What are Raiden Shogun's base stats?", "liyue")
    # Once the player has finished Inazuma (2.8), Raiden (2.1) is fair game.
    ok = e.ask("What are Raiden Shogun's base stats?", story_until="inazuma")
    assert ok.route == "exact" and "337" in ok.text
    assert ok.trace["spoiler_filter"] == {
        "until": "inazuma",
        "label": "Inazuma",
        "max_version": "2.8",
        "hidden": 0,
    }
    plain = e.ask("What are Raiden Shogun's base stats?")
    assert plain.route == "exact" and "spoiler_filter" not in plain.trace


def test_element_words_do_not_stop_a_question():
    electro = Character(
        id="character/traveler-electro",
        game_id="10000005-electro",
        name="Traveler (Electro)",
        rarity=5,
        element="Electro",
        weapon_type="Sword",
        release=Release(status=ReleaseStatus.RELEASED),
        source=SourceRef(source="t", url="u", tier=Tier.OFFICIAL, fetched_at=FETCHED_AT),
        revealed_in="2.0",
    )
    e = Engine(EntityStore([raiden(), electro], [], []), StoryIndex(), FakeLLM(text="Lore. [1]"))
    # "Electro" alone matches the Electro Traveler: that must not count as naming a character.
    answer = e.ask("Who was the Electro Archon's twin sister?", story_until="liyue")
    assert answer.route == "rag"


def test_rag_filters_before_the_llm_and_reports_hidden_passages():
    index, llm = StoryIndex(), FakeLLM(text="Early lore. [1]")
    answer = engine(llm, index).ask("Tell me the story of the Electro Archon", story_until="liyue")
    assert index.calls[-1]["max_revealed"] == "1.6"
    assert [c.doc_id for c in answer.citations] == ["early-lore"]
    assert [r["doc_id"] for r in answer.trace["retrieval"]] == ["early-lore"]
    assert answer.trace["spoiler_filter"]["hidden"] == 3
    unfiltered = engine(llm, StoryIndex()).ask("Tell me the story of the Electro Archon")
    assert len(unfiltered.citations) >= 1 and "spoiler_filter" not in unfiltered.trace


def test_cache_never_crosses_story_points():
    llm = FakeLLM(text="Lore. [1]")
    e = engine(llm)
    q = "Tell me the story of the Electro Archon"
    e.ask(q, story_until="liyue")
    assert e.ask(q, story_until="liyue").trace.get("cache") == "hit" and llm.calls == 1
    assert e.ask(q, story_until="inazuma").trace.get("cache") is None and llm.calls == 2
    assert e.ask(q).trace.get("cache") is None and llm.calls == 3
    assert {k.split("|")[0] for k in e._cache} == {"liyue", "inazuma", "*"}


def test_streaming_applies_the_story_point():
    events = list(engine().ask_stream("Raiden Shogun's base stats?", story_until="mondstadt"))
    done = events[-1][1]
    assert done["route"] == "spoiler" and done["follow_ups"] == []
    assert done["trace"]["spoiler_filter"]["label"] == "Mondstadt"


# ---- API ----------------------------------------------------------------------------------
def client() -> TestClient:
    return TestClient(create_app(engine(), Limits()))


def test_api_validates_story_until():
    c = client()
    q = "What are Raiden Shogun's base stats?"
    assert c.post("/ask", json={"question": q, "story_until": "teyvat"}).status_code == 422
    assert c.post("/ask", json={"question": q, "story_until": "x" * 100}).status_code == 422
    assert c.post("/ask", json={"question": q, "story_until": None}).json()["route"] == "exact"
    stop = c.post("/ask", json={"question": q, "story_until": "liyue"}).json()
    assert stop["route"] == "spoiler" and stop["trace"]["spoiler_filter"]["max_version"] == "1.6"


def test_api_stream_passes_story_until():
    with client().stream(
        "POST", "/ask/stream", json={"question": "Raiden Shogun stats", "story_until": "liyue"}
    ) as r:
        body = "".join(r.iter_text())
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n\n")[0])
    assert done["route"] == "spoiler"


def test_api_lists_story_points_in_order():
    points = client().get("/api/story").json()["points"]
    assert [p["key"] for p in points] == [p.key for p in story.STORY_POINTS]
    inazuma = {"key": "inazuma", "label": "Inazuma", "chapter": "Chapter II", "until": "2.8"}
    assert points[2] == inazuma


# ---- golden evals ------------------------------------------------------------------------
def test_golden_set_proves_the_gate_both_ways():
    items = [i for i in load() if i.category == Category.SPOILER]
    assert all(i.story_until for i in items)
    # At least one question answerable only past the cutoff, and one answerable before it.
    assert any(i.expect == "refuse" for i in items)
    assert any(i.expect == "answer" and i.gold_doc_ids for i in items)
