"""Questions in other languages: translated for routing, answered in the player's language."""

import json

from test_engine import FakeIndex, store

from irminsul.engine.engine import Engine
from irminsul.engine.language import looks_foreign, translate
from irminsul.engine.llm import Completion


class FakeTranslator:
    """A model that translates (JSON), localizes (prefix 'ES:') and answers RAG questions."""

    def __init__(self, english="What are Raiden Shogun's base stats?", language="Spanish"):
        self.english, self.language, self.calls = english, language, []

    def _reply(self, messages):
        system = messages[0]["content"]
        if system.startswith("You translate Genshin Impact questions"):
            self.calls.append("translate")
            return json.dumps({"language": self.language, "english": self.english})
        if system.startswith("Translate this Genshin Impact answer"):
            self.calls.append("localize")
            return "ES: " + messages[1]["content"]
        self.calls.append("answer")
        return "Respuesta en español. [1]"

    def complete(self, messages, max_tokens=1024):
        return Completion(self._reply(messages), "fake", "fake-model", 10, 10)

    def stream(self, messages, max_tokens=1024):
        text = self._reply(messages)
        yield text
        yield Completion(text, "fake", "fake-model", 10, 10)


def test_detects_other_languages_but_not_english():
    for q in (
        "胡桃的最佳武器是什么？",
        "¿Cuál es la mejor arma para Hu Tao?",
        "Qual é a melhor arma para a Furina?",
        "雷電将軍のおすすめ武器は？",
        "누구를 뽑아야 하나요?",
    ):
        assert looks_foreign(q), q
    for q in ("What is the best weapon for Hu Tao?", "raiden c2", "Is Escoffier good?"):
        assert not looks_foreign(q), q


def test_exact_answers_are_routed_in_english_and_translated_back():
    llm = FakeTranslator()
    engine = Engine(store(), FakeIndex(), llm)
    a = engine.ask("¿Cuáles son las estadísticas base de Raiden Shogun?")
    assert a.route == "exact" and a.text.startswith("ES: ")
    assert a.trace["language"] == "Spanish" and llm.calls == ["translate", "localize"]
    assert a.follow_ups == []  # suggestions are English templates


def test_ai_answers_are_written_in_the_players_language():
    llm = FakeTranslator(english="Is Raiden Shogun good in teams?")
    engine = Engine(store(), FakeIndex(), llm)
    a = engine.ask("¿Es buena Raiden Shogun en equipos?")
    assert a.route == "rag" and llm.calls == ["translate", "answer"]
    events = list(engine.ask_stream("¿Es buena Raiden Shogun en equipos?"))
    done = events[-1][1]
    assert done["trace"]["language"] == "Spanish" and done["follow_ups"] == []


def test_translated_answers_never_enter_the_english_cache():
    llm = FakeTranslator()
    engine = Engine(store(), FakeIndex(), llm)
    engine.ask("¿Cuáles son las estadísticas base de Raiden Shogun?")
    english = engine.ask("What are Raiden Shogun's base stats?")
    assert not english.text.startswith("ES: ")


def test_personal_data_is_checked_on_the_original_words():
    engine = Engine(store(), FakeIndex(), FakeTranslator())
    a = engine.ask("Mi correo es alguien@example.com, ¿qué arma para Raiden Shogun?")
    assert a.route == "refuse_privacy"


def test_translation_failures_fall_back_to_english():
    class Broken:
        def complete(self, messages, max_tokens=1024):
            raise RuntimeError("down")

    assert translate(Broken(), "¿Cuál es la mejor arma?") is None
    engine = Engine(store(), FakeIndex(), Broken())
    assert engine.is_free("¿Cuál es la mejor arma para Raiden Shogun?") is False
