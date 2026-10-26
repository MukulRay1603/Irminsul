from irminsul.text import clean, fill_params, format_param


def test_clean_strips_markup_and_newlines():
    raw = "<color=#FFD780FF>Normal Attack</color>\\nPerforms up to 5 <i>strikes</i>."
    assert clean(raw) == "Normal Attack\nPerforms up to 5 strikes."


def test_clean_variants():
    assert clean("{LAYOUT_MOBILE#Tap}{LAYOUT_PC#Press}{LAYOUT_PS#Press} the button") == (
        "Press the button"
    )
    assert clean("{F#She}{M#He} smiles at {NICKNAME}") == "She smiles at Traveler"
    assert clean("{LINK#N123}Resolve{/LINK} stacks") == "Resolve stacks"
    assert clean(None) == ""


def test_format_param_codes():
    assert format_param(0.39646, "F1P") == "39.6%"
    assert format_param(1.27837, "P") == "128%"
    assert format_param(25, "F1") == "25.0"
    assert format_param(3.6, "I") == "4"


def test_fill_params():
    assert fill_params("{param1:F1P}+{param2:F1P}", [0.28982, 0.28982]) == "29.0%+29.0%"
    assert fill_params("{param9:P}", [0.1]) == "?"
