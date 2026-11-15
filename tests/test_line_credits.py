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


# --- build / credits file / CLI -------------------------------------------

import json  # noqa: E402

import pytest  # noqa: E402

import line_credits as lc  # noqa: E402
from patch_names import DbinEntry, SDL2Data, build_dbin2  # noqa: E402


def _dbin(folder: Path, stem: str, lines: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    blob = build_dbin2(1, 0, [DbinEntry(0, 0, SDL2Data(1, [], list(lines)))])
    (folder / f"{stem}.dbin2").write_bytes(blob)


@pytest.fixture
def roots(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    paths = {
        "contrib": tmp_path / "contrib",
        "gemini": tmp_path / "gemini",
        "community": tmp_path / "community",
        "vanilla": tmp_path / "vanilla",
    }
    monkeypatch.setattr(lc, "CONTRIB", paths["contrib"])
    monkeypatch.setattr(lc, "GEMINI", paths["gemini"])
    monkeypatch.setattr(lc, "COMMUNITY", paths["community"])
    monkeypatch.setattr(lc, "CREDITS", tmp_path / "line_credits.json")
    monkeypatch.setattr(lc, "find_vanilla_script_dir", lambda: None)
    _dbin(paths["contrib"], "k007", ["Anegasaki", "Huh? Geez."])
    _dbin(paths["gemini"], "k007", ["Anegasaki", "Eh!? Hard."])
    return paths


def test_an_edited_line_with_no_match_is_still_the_contributors():
    assert classify("Totally new.", "え", "Eh.", None, [], edited=True) == "c+"


def test_build_needs_matching_contrib_and_gemini_scripts(roots):
    with pytest.raises(SystemExit, match="same length"):
        lc.build("a001", [])
    _dbin(roots["gemini"], "k007", ["only one"])
    with pytest.raises(SystemExit, match="same length"):
        lc.build("k007", [])


def test_build_refuses_a_pack_of_the_wrong_length(roots):
    with pytest.raises(SystemExit, match="a pack has 1 lines"):
        lc.build("k007", [["x"]])


def test_build_uses_the_given_japanese(roots):
    codes = lc.build("k007", [["Anegasaki", "Huh? Geez."]], jp=["姉ヶ崎", "えぇっ"])
    assert codes == ["", "c"]


def test_build_falls_back_to_blank_japanese_without_a_dump(roots):
    # No nameplate label without the Japanese; a short community script is ignored.
    _dbin(roots["community"], "k007", ["one"])
    assert lc.build("k007", [], edited={1}) == ["g", "c+"]


def test_build_reads_the_vanilla_japanese(roots, monkeypatch):
    monkeypatch.setattr(lc, "find_vanilla_script_dir", lambda: roots["vanilla"])
    _dbin(roots["vanilla"], "k007", ["姉ヶ崎", "えぇっ"])
    _dbin(roots["community"], "k007", ["Anegasaki", "Eh!? Hard."])
    assert lc.build("k007", [], reviewed={1}) == ["", "n+"]
    _dbin(roots["vanilla"], "k007", ["姉ヶ崎"])
    assert lc.build("k007", []) == ["n", "n+"]


def test_credits_file_round_trips(roots):
    assert lc.load_credits() == {}
    lc.save_credits({"k007": {"name": "Dnnz.Cstr", "lines": ["", "c"]},
                     "a002": {"name": "Ármando", "lines": ["g"]}})
    text = lc.CREDITS.read_text(encoding="utf-8")
    assert text.index('"a002"') < text.index('"k007"')
    assert "Ármando" in text
    assert lc.load_credits()["k007"] == {"name": "Dnnz.Cstr", "lines": ["", "c"]}


def test_pack_lines_finds_the_stem(tmp_path: Path):
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"items": [
        {"stem": "a001", "dialogs": ["x"]},
        {"stem": "k007", "dialogs": ["a", "b"], "baseline_dialogs": ["あ", "い"]},
    ]}), encoding="utf-8")
    assert lc._pack_lines(pack, "k007") == (["a", "b"], ["あ", "い"])
    assert lc._pack_lines(pack, "a001") == (["x"], [])
    with pytest.raises(SystemExit, match="no item for z999"):
        lc._pack_lines(pack, "z999")


def test_main_writes_the_stems_credits(roots, tmp_path: Path, capsys):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps({"items": [{"stem": "k007", "dialogs": ["Anegasaki", "Huh?"],
                                          "baseline_dialogs": ["姉ヶ崎", "えぇっ"]}]}), encoding="utf-8")
    new.write_text(json.dumps({"items": [{"stem": "k007", "dialogs": ["Anegasaki", "Huh? Geez."]}]}),
                   encoding="utf-8")
    argv = ["k007", "--name", "Dnnz.Cstr", "--pack", str(old), "--pack", str(new),
            "--edited", "1, ,", "--reviewed", ""]
    assert lc.main(argv) == 0
    assert lc.load_credits() == {"k007": {"name": "Dnnz.Cstr", "lines": ["", "c+"]}}
    assert "[line-credits] k007 Dnnz.Cstr: {'-': 1, 'c+': 1}" in capsys.readouterr().out
