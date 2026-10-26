"""Repository hygiene checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_control_characters_in_source():
    # A shell heredoc once turned regex "\b" into a literal backspace (0x08) twice in one
    # night, silently breaking the pattern. Catch that class of bug at the source.
    bad = []
    for path in [*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("tests").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, f"control characters found in {bad}"
