"""Per-line sources for contributor scripts (tools/line_credits.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from line_credits import classify  # noqa: E402


def test_the_contributors_wording_is_credited_even_with_new_punctuation():
    assert classify("Huh? Geez, this is hard...", "えぇっ？", "Eh！？ Hard.", "Eh！？ Hard.",
                    ["Huh？ Geez, this is hard..."]) == "c"


def test_a_line_the_contributor_left_alone_keeps_its_source():
    # Gemini kept the community line: community. A punctuation-only "edit" is no credit.
    assert classify("Not really...", "あんまり", "Not really...", "Not really...", ["Not really…"]) == "n"
    assert classify("Not really...", "あんまり", "Not really...", "Nope.", ["Not really..."]) == "g"


def test_review_edits_are_marked():
    # Close to the contributor's wording: their line, edited.
    assert classify("I don't think it's a good idea this time.", "ナシかな", "It's not good.", None,
                    ["I don't think it's good idea this time."]) == "c+"
    # Rewritten from the source line, not the contributor's: improved source.
    assert classify("Shh...", "黙って……", "Stop speaking...", "Stop speaking...", []) == "n+"
    assert classify("Hush.", "黙って", "Stop it.", "Stop.", ["Be quiet you."], reviewed=True) == "g+"


def test_nameplates_and_placeholders_get_no_label():
    assert classify("Anegasaki", "姉ヶ崎", "Anegasaki", "Anegasaki", []) == ""
    assert classify("○○○○○○○○", "○○○○○○○○", "○○○○○○○○", None, []) == ""
