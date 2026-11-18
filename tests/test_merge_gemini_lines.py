"""merge_gemini_lines keeps both sides of a conflict git cannot merge."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import SRC, TOOLS, load_module
from patch_names import DbinEntry, SDL2Data, build_dbin2

merge = load_module("merge_gemini_lines", TOOLS / "merge_gemini_lines.py")

GEM = "assets/gemini_heroines"


def _blob(lines: list[str]) -> bytes:
    return build_dbin2(1, 0, [DbinEntry(0, 0, SDL2Data(1, [], lines))])


def _xml(lines: list[str]) -> bytes:
    return ("".join(f"<Dialog>{line}</Dialog>\n" for line in lines)).encode("utf-8")


def _table(table: dict) -> str:
    return json.dumps({"translations": table}, ensure_ascii=False, indent=2) + "\n"


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, bytes | str], message: str) -> str:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> dict:
    """base, then theirs, then this branch from base with its own edits."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    monkeypatch.setattr(merge, "ROOT", root)
    base = _commit(
        root,
        {
            f"{GEM}/dbin2/script/a001.dbin2": _blob(["one", "two", "three"]),
            f"{GEM}/xml/a001.xml": _xml(["one", "two", "three"]),
            f"{GEM}/translations.json": _table({"一": "one", "二": "two"}),
        },
        "base",
    )
    theirs = _commit(
        root,
        {
            f"{GEM}/dbin2/script/a001.dbin2": _blob(["ONE", "two", "three"]),
            f"{GEM}/xml/a001.xml": _xml(["ONE", "two", "three"]),
            f"{GEM}/translations.json": _table({"一": "ONE", "二": "two"}),
        },
        "theirs",
    )
    _git(root, "checkout", "-q", base)
    _commit(
        root,
        {
            f"{GEM}/dbin2/script/a001.dbin2": _blob(["one", "two", "three..."]),
            f"{GEM}/xml/a001.xml": _xml(["one", "two", "three..."]),
            f"{GEM}/translations.json": _table({"一": "one", "二": "TWO"}),
        },
        "ours",
    )
    return {"root": root, "base": base, "theirs": theirs}


def _args(repo: dict, *extra: str) -> list[str]:
    return ["--base", repo["base"], "--theirs", repo["theirs"], *extra]


def _lines(root: Path, rel: str) -> list[str]:
    return merge.lines_of(rel, (root / rel).read_bytes())


def test_importing_puts_src_and_tools_on_the_path(monkeypatch):
    keep = {str(SRC), str(TOOLS)}
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p not in keep])
    load_module("merge_gemini_lines_path", TOOLS / "merge_gemini_lines.py")
    assert keep <= set(sys.path)


def test_merged_lines_keep_both_sides():
    merged, taken, conflicts = merge.merge_lines(
        ["same", "old", "old", "old", "old"],
        ["same", "main", "old", "main", "same fix"],
        ["same", "old", "mine", "mine", "same fix"],
    )
    assert merged == ["same", "main", "mine", "mine", "same fix"]
    assert taken == 1
    assert conflicts == 1


def test_dry_run_reports_and_writes_nothing(repo, capsys):
    rel = f"{GEM}/dbin2/script/a001.dbin2"
    before = (repo["root"] / rel).read_bytes()
    assert merge.main(_args(repo)) == 0
    assert "would take 2 line(s) in 2 file(s) and 1 phrase-map key(s)" in capsys.readouterr().out
    assert (repo["root"] / rel).read_bytes() == before


def test_apply_takes_their_fix_and_keeps_this_branchs_edit(repo, capsys):
    root = repo["root"]
    assert merge.main(_args(repo, "--apply")) == 0
    assert "took 2 line(s)" in capsys.readouterr().out
    want = ["ONE", "two", "three..."]
    assert _lines(root, f"{GEM}/dbin2/script/a001.dbin2") == want
    assert _lines(root, f"{GEM}/xml/a001.xml") == want
    saved = json.loads((root / f"{GEM}/translations.json").read_text(encoding="utf-8"))
    assert saved["translations"] == {"一": "ONE", "二": "TWO"}


def test_a_line_both_sides_changed_is_reported(repo, capsys):
    root = repo["root"]
    rel = f"{GEM}/dbin2/script/a001.dbin2"
    (root / rel).write_bytes(_blob(["mine", "two", "three"]))
    assert merge.main(_args(repo)) == 1
    assert "1 line(s) changed on both sides" in capsys.readouterr().out


def test_a_different_line_count_needs_a_person(repo, capsys):
    root = repo["root"]
    rel = f"{GEM}/dbin2/script/a001.dbin2"
    (root / rel).write_bytes(_blob(["only one"]))
    assert merge.main(_args(repo, "--apply")) == 1
    assert "line count differs" in capsys.readouterr().out
    assert _lines(root, rel) == ["only one"]


def test_a_file_missing_here_needs_a_person(repo, capsys):
    (repo["root"] / f"{GEM}/xml/a001.xml").unlink()
    assert merge.main(_args(repo)) == 1
    assert "a side lacks this file" in capsys.readouterr().out


def test_a_phrase_both_sides_changed_is_kept_and_reported(repo, capsys):
    path = repo["root"] / f"{GEM}/translations.json"
    path.write_text(_table({"一": "mine", "二": "TWO"}), encoding="utf-8")
    assert merge.main(_args(repo, "--apply")) == 1
    assert "phrase map '一': kept 'mine' over 'ONE'" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))["translations"]["一"] == "mine"


def test_a_file_both_sides_agree_on_is_left_alone(repo):
    root = repo["root"]
    rel = f"{GEM}/dbin2/script/a001.dbin2"
    (root / rel).write_bytes(_blob(["ONE", "two", "three"]))
    assert merge.merge_file(rel, repo["base"], repo["theirs"], apply=True) == (0, None)


def test_a_missing_rev_reads_as_no_file(repo):
    assert merge.blob(repo["base"], "not/here.xml") is None
    assert merge.lines_of("not/here.xml", None) is None
