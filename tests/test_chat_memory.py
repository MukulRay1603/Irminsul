"""The chat is the input: players tell it things, and it remembers them on their device."""

from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.players import Showcase, line
from irminsul.engine import guards, pulls
from irminsul.engine.engine import Engine

UID = "618285856"


def fake_enka(uid):
    s = store()
    raiden = s.by_id["character/raiden-shogun"].entity
    weapon = next(m.entity for m in s.by_id.values() if m.kind == "weapon")
    return {
        "ttl": 60,
        "playerInfo": {"nickname": "SECRET-NAME", "signature": "SECRET-BIO"},
        "avatarInfoList": [
            {
                "avatarId": int(raiden.game_id),
                "talentIdList": [1, 2],
                "propMap": {"4001": {"val": "90"}},
                "equipList": [{"itemId": int(weapon.game_id), "weapon": {"affixMap": {"1": 4}}}],
            },
            {"avatarId": 99999999, "talentIdList": []},  # unknown: skipped
        ],
    }


def engine(llm=None, fetch=fake_enka):
    s = store()
    return Engine(s, FakeIndex(), llm or FakeLLM(), players=Showcase(s, fetch=fetch))


def test_telling_the_chat_is_enough():
    a = engine().ask("I'm at 40 pity with 8000 primos and 20 fates")
    assert a.route == "exact" and "70 wishes" in a.text
    assert a.trace["stash"] == {"primos": 8000, "fates": 20, "pity": 40, "guaranteed": False}


def test_what_the_player_said_is_used_later():
    llm = FakeLLM()
    saved = {"primos": 8000, "fates": 20, "pity": 40, "guaranteed": True}
    a = engine(llm).ask("What are my chances?", stash=saved)
    assert a.route == "exact" and "70 wishes" in a.text and llm.calls == 0


def test_wish_results_update_the_tracker():
    a = engine().ask("I lost my 50/50 at 72")
    assert a.trace["stash"] == {"pity": 0, "guaranteed": True}
    b = engine().ask("I won the 50/50!")
    assert b.trace["stash"] == {"pity": 0, "guaranteed": False}


def test_a_uid_is_not_personal_data_but_other_long_numbers_are():
    assert not guards.has_personal_data(f"my UID is {UID}")
    assert guards.has_personal_data(f"my phone is {UID}")


def test_a_uid_reads_the_public_showcase_only():
    a = engine().ask(f"my UID is {UID}")
    assert a.route == "exact" and a.trace["uid"] == UID
    assert "Raiden Shogun C2" in a.text and "R5" in a.text
    assert "SECRET" not in a.text


def test_a_closed_showcase_says_so_and_never_breaks():
    a = engine(fetch=lambda uid: None).ask(f"my uid: {UID}")
    assert a.route == "exact" and "couldn't read" in a.text

    def down(uid):
        raise RuntimeError("timeout")

    assert "couldn't read" in engine(fetch=down).ask(f"uid {UID}").text


def test_showcase_is_cached_for_enkas_ttl():
    calls = []

    def counted(uid):
        calls.append(uid)
        return fake_enka(uid)

    now = [1000.0]
    c = Showcase(store(), fetch=counted, clock=lambda: now[0])
    c.characters(UID)
    c.characters(UID)
    assert len(calls) == 1
    now[0] += 61
    c.characters(UID)
    assert len(calls) == 2
    assert (
        line({"name": "Furina", "constellation": 2, "level": 90, "weapon": None})
        == "Furina C2 Lv.90"
    )


def test_my_account_questions_carry_the_showcase():
    e = engine()
    q = e.with_context("Who should I build next?", None, None, UID)
    assert "Raiden Shogun C2" in q
    # A question about the game in general stays as it is
    assert e.with_context("How does Bloom work?", None, None, UID) == "How does Bloom work?"


def test_income_counts_everything_and_shows_the_floor():
    from datetime import date

    est = pulls.income(date(2026, 11, 5), date(2026, 12, 17))
    assert est.likely > est.primos and est.likely_wishes > est.wishes
    text = pulls.income_text(date(2026, 11, 5), (7, 3), 1)
    assert "At least" in text and "Events, quests, exploration and achievements" in text


def test_a_story_about_pulls_is_not_a_stash():
    q = "My friend got C6 Arlecchino in under 100 pulls while I got one Mona. How is that possible?"
    assert not pulls.is_odds_question(q)
