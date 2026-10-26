"""The per-sentence source check, and the examples its threshold was tuned on."""

import time

import pytest
from test_engine import FakeIndex, store

from irminsul.engine.engine import Engine
from irminsul.engine.grounding import MIN_OVERLAP, _check, check, split
from irminsul.engine.llm import Completion

# Excerpts of real index chunks (the text the model is given for each numbered source).
AYAKA = (
    "# Kamisato Ayaka — Frostflake Heron\n5★ Cryo Sword character from Inazuma. Released: "
    "2021-07-20. Base stats at Lv. 90: HP 12858, ATK 342, DEF 784, CRIT DMG 38.4% (ascension "
    "stat). Talents: Normal Attack: Kamisato Art: Kabuki; Elemental Skill: Kamisato Art: Hyouka; "
    "Elemental Burst: Kamisato Art: Soumetsu."
)
SOUMETSU = (
    "# Kamisato Ayaka — Elemental Burst: Kamisato Art: Soumetsu\nSummons forth a snowstorm with "
    "flawless poise, unleashing a Frostflake Seki no To that moves forward continuously. A storm "
    "of whirling icy winds that slashes repeatedly at every enemy it touches, dealing Cryo DMG. "
    "The snowstorm explodes after its duration ends, dealing AoE Cryo DMG. | Attribute | Lv1 | "
    "Lv10 | | Cutting DMG | 112% | 202% | | Duration | 5.0s | 5.0s | | CD | 20.0s | 20.0s | "
    "| Energy Cost | 80 | 80 |"
)
EMBLEM = (
    "# Emblem of Severed Fate (artifact set) Available rarities: 4★/5★. 2-Piece Bonus: Energy "
    "Recharge +20% 4-Piece Bonus: Increases Elemental Burst DMG by 25% of Energy Recharge. A "
    "maximum of 75% bonus DMG can be obtained in this way."
)
MISTSPLITTER = (
    "# Mistsplitter Reforged 5★ Sword. Max level stats: Base ATK 674, CRIT DMG 44.1%. Passive: "
    "Mistsplitter's Edge R1: Gain a 12% Elemental DMG Bonus for all elements and receive the "
    "might of the Mistsplitter's Emblem. At stack levels 1/2/3, the Mistsplitter's Emblem "
    "provides a 8/16/28% Elemental DMG Bonus for the character's Elemental Type."
)
GAUGE = (
    "# Elemental Gauge Theory ## Aura Application Aura application has a 0.8x modifier. This is "
    "also referred to as **Aura Tax**. Kaeya's E applies 2U * 0.8 = 1.6U Cryo aura and the "
    "decay rate is 7.5s per unit. In addition, neither Anemo nor Geo may be applied as an aura."
)

# (sentence, source, backed?) The supported ones are paraphrases a model actually writes; the
# unsupported ones cite a real source for a claim it does not make.
CASES = [
    ("Ayaka is a 5-star Cryo sword user from Inazuma.", AYAKA, True),
    ("Her base ATK at level 90 is 342.", AYAKA, True),
    ("Her ascension stat is CRIT DMG, reaching 38.4% at Lv. 90.", AYAKA, True),
    ("Her Elemental Burst, Kamisato Art: Soumetsu, costs 80 Energy.", SOUMETSU, True),
    ("Soumetsu summons a snowstorm that deals Cryo DMG to every enemy it touches.", SOUMETSU, True),
    ("The burst lasts 5 seconds and has a 20s cooldown.", SOUMETSU, True),
    ("The snowstorm explodes at the end, dealing AoE Cryo DMG.", SOUMETSU, True),
    ("The 2-piece bonus gives +20% Energy Recharge.", EMBLEM, True),
    ("The 4-piece bonus increases Burst DMG by 25% of Energy Recharge, up to 75%.", EMBLEM, True),
    ("Mistsplitter Reforged gives a 12% Elemental DMG Bonus for all elements.", MISTSPLITTER, True),
    ("Its emblem stacks give 8/16/28% Elemental DMG Bonus.", MISTSPLITTER, True),
    ("Aura application has a 0.8x modifier, known as aura tax.", GAUGE, True),
    ("Anemo and Geo can't be applied as an aura.", GAUGE, True),
    # wrong numbers
    ("Her Elemental Burst costs 60 Energy.", SOUMETSU, False),
    ("The 2-piece bonus gives +30% Energy Recharge.", EMBLEM, False),
    ("Mistsplitter Reforged has a base ATK of 608.", MISTSPLITTER, False),
    ("Aura application has a 0.5x modifier.", GAUGE, False),
    # right source, claim it does not make
    ("Ayaka is best played with Shenhe and Kazuha in a freeze team.", AYAKA, False),
    ("The set is best on supports who need to fund their bursts quickly.", EMBLEM, False),
    ("Mistsplitter Reforged is the signature weapon of Kamisato Ayaka.", MISTSPLITTER, False),
    ("Swirl spreads the absorbed element to nearby enemies.", GAUGE, False),
    ("Ayaka's dash, Senho, infuses her attacks with Cryo and restores stamina.", SOUMETSU, False),
]


@pytest.mark.parametrize(("sentence", "source", "backed"), CASES)
def test_tuned_examples(sentence, source, backed):
    ok, reason, overlap, _ = _check(sentence, source)
    assert ok is backed, f"overlap {overlap:.2f}, reason {reason}"


def test_threshold_has_margin():
    """The tuned threshold sits in the gap between backed and unbacked word overlap."""
    backed = [_check(s, src)[2] for s, src, ok in CASES if ok]
    wordy = [_check(s, src) for s, src, ok in CASES if not ok]
    unbacked = [o for _, reason, o, _ in wordy if reason == "words"]
    assert min(backed) >= MIN_OVERLAP + 0.05
    assert max(unbacked) <= MIN_OVERLAP - 0.05


def test_supported_answer():
    answer = (
        "**Ayaka's burst costs 80 Energy [2].**\n\n"
        "- She is a 5★ Cryo Sword character from Inazuma [1].\n"
        "- The snowstorm lasts **5s** and the cooldown is **20s** [2]."
    )
    g = check(answer, {1: AYAKA, 2: SOUMETSU})
    assert g["checked"] == 3
    assert g["unsupported"] == [] and g["uncited"] == []
    assert [s["status"] for s in g["sentences"]] == ["supported"] * 3
    assert g["sentences"][0]["text"] == "Ayaka's burst costs 80 Energy ."


def test_unsupported_number_and_claim():
    answer = (
        "Her burst costs 60 Energy [2]. It is the best burst in the game [2]. "
        "She comes from Inazuma [1]."
    )
    g = check(answer, {1: AYAKA, 2: SOUMETSU})
    assert g["checked"] == 3
    assert g["unsupported"] == [0, 1]
    first, second, third = g["sentences"]
    assert first["reason"] == "number" and first["missing_numbers"] == ["60"]
    assert second["reason"] == "words"
    assert third["status"] == "supported"


def test_number_only_in_another_source_is_unsupported():
    g = check("The 4-piece bonus caps at 75% [1].", {1: AYAKA, 2: EMBLEM})
    assert g["unsupported"] == [0]


def test_number_formats_match():
    assert _check("It deals 1,200 DMG over 5 seconds.", "deals 1200 DMG for 5.0s")[0]
    assert _check("Energy Recharge rises by 20 percent.", "Energy Recharge +20.0%")[0]


def test_missing_citation():
    answer = (
        "Ayaka pairs well with Shenhe, Kazuha and Kokomi in freeze teams. "
        "Her burst costs 80 Energy [2]."
    )
    g = check(answer, {2: SOUMETSU})
    assert g["checked"] == 1
    assert g["uncited"] == [0]
    assert g["sentences"][0]["reason"] == "no_citation"


def test_uncited_restatement_of_sources_is_fine():
    # A bold summary line with its citations on the bullets below is backed by those sources.
    g = check("**Soumetsu costs 80 Energy.**\n- Energy cost: 80 [1].", {1: SOUMETSU})
    assert g["uncited"] == [] and g["sentences"][0]["status"] == "supported"


def test_non_claims_are_skipped():
    g = check("I don't have verified information on that yet.\n\n### Summary\nThanks!", {})
    assert g["checked"] == 0 and g["uncited"] == []
    assert all(s["status"] == "skip" for s in g["sentences"])


def test_split_handles_abbreviations_decimals_tables():
    answer = (
        "### Stats\n"
        "At Lv. 90 her CRIT DMG is 38.4% [1]. She is from Inazuma [1].\n"
        "| Level | ATK |\n|---|---|\n| 90 | 342 [1] |\n"
        "1. First step, e.g. Hyouka [1].\n"
    )
    parts = split(answer)
    assert [p[0] for p in parts] == [
        "At Lv. 90 her CRIT DMG is 38.4% [1].",
        "She is from Inazuma [1].",
        "90 342 [1]",
        "First step, e.g. Hyouka [1].",
    ]
    assert all(p[1] == [1] for p in parts)


def test_multi_citations():
    g = check(
        "Ayaka's burst costs 80 Energy and she is from Inazuma [1, 2].", {1: AYAKA, 2: SOUMETSU}
    )
    assert g["sentences"][0]["cites"] == [1, 2] and g["unsupported"] == []
    g = check(
        "Ayaka's burst costs 80 Energy and she is from Inazuma [1][2].", {1: AYAKA, 2: SOUMETSU}
    )
    assert g["sentences"][0]["cites"] == [1, 2] and g["unsupported"] == []


def test_fast():
    answer = "\n".join(
        f"- Ayaka's burst costs 80 Energy and lasts 5s [{n % 2 + 1}]." for n in range(20)
    )
    start = time.perf_counter()
    check(answer, {1: AYAKA, 2: SOUMETSU})
    assert (time.perf_counter() - start) * 1000 < 20


class FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, messages):
        return Completion(self.text, "fake", "fake-1", 100, 20)

    def stream(self, messages):
        yield self.text
        yield self.complete(messages)


ANSWER = "Raiden needs 200-220% ER in National teams [1]. Solo, she needs 300% ER [1]."


def test_engine_adds_grounding_to_stream_and_ask():
    q = "How much ER does Raiden need in National teams?"
    done = list(Engine(store(), FakeIndex(), FakeLLM(ANSWER)).ask_stream(q))[-1][1]
    g = done["trace"]["grounding"]
    assert g["checked"] == 2 and g["unsupported"] == [1]
    assert g["sentences"][1]["missing_numbers"] == ["300"]
    assert Engine(store(), FakeIndex(), FakeLLM(ANSWER)).ask(q).trace["grounding"] == g
