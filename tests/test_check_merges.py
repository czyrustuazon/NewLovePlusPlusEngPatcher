"""check_merges stops a merge that threw away one side's dialogue."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import ROOT, load_module

check = load_module("check_merges", ROOT / "dev" / "check_merges.py")

DIALOGUE = "assets/gemini_heroines/translations.json"
TEXT = "a\nb\nc\nd\ne\nf\ng\n"
SIDE_FIX = TEXT.replace("a", "A")


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", rel)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """``main`` and ``side`` both moved on from the same first commit."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    monkeypatch.setattr(check, "ROOT", root)
    _commit(root, DIALOGUE, TEXT)
    _git(root, "checkout", "-q", "-b", "side")
    _commit(root, DIALOGUE, SIDE_FIX)
    _git(root, "checkout", "-q", "main")
    _git(root, "branch", "upstream")
    return root


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


def test_a_clean_merge_passes(repo, capsys):
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "side")
    assert check.main(["--upstream", "upstream"]) == 0
    assert "1 merge(s) kept both sides" in capsys.readouterr().out


def test_keeping_ours_on_dialogue_fails(repo, capsys):
    _git(repo, "merge", "-q", "-s", "ours", "-m", "merge", "side")
    assert check.main(["--upstream", "upstream"]) == 1
    out = capsys.readouterr().out
    assert DIALOGUE in out
    assert "merge_gemini_lines" in out


def test_taking_theirs_over_our_change_fails_too(repo):
    _commit(repo, DIALOGUE, TEXT.replace("a", "ours"))
    _git(repo, "merge", "-q", "-X", "theirs", "-m", "merge", "side")
    assert check.main(["--upstream", "upstream"]) == 1


def test_a_long_list_is_cut_short(repo, capsys):
    _git(repo, "checkout", "-q", "side")
    for n in range(12):
        _commit(repo, f"rebuild_dbin2/script/t{n:03}.dbin2", "x")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "-s", "ours", "-m", "merge", "side")
    assert check.main(["--upstream", "upstream"]) == 1
    assert "... 3 more" in capsys.readouterr().out


def test_a_repaired_merge_is_not_flagged_again(repo, monkeypatch):
    _git(repo, "merge", "-q", "-s", "ours", "-m", "merge", "side")
    monkeypatch.setattr(check, "REPAIRED", {_head(repo)})
    assert check.main(["--upstream", "upstream"]) == 0


def test_code_files_are_not_watched(repo):
    _git(repo, "checkout", "-q", "side")
    _commit(repo, "src/x.py", "side\n")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "src/x.py", "main\n")
    _git(repo, "merge", "-q", "-X", "ours", "-m", "merge", "side")
    assert check.check_merge(_head(repo)) == []


def test_a_clean_merge_of_overlapping_edits_passes(repo):
    """One side's edits contain the other's, so git lands on that side's exact copy."""
    _commit(repo, DIALOGUE, SIDE_FIX)
    _git(repo, "checkout", "-q", "side")
    _commit(repo, DIALOGUE, SIDE_FIX.replace("g", "G"))
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "-m", "merge", "side")
    assert check.check_merge(_head(repo)) == []


def test_a_merge_of_unrelated_histories_is_skipped(repo):
    _git(repo, "checkout", "-q", "--orphan", "other")
    _commit(repo, "other.txt", "x\n")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--allow-unrelated-histories", "-m", "merge", "other")
    assert check.check_merge(_head(repo)) == []


def test_a_plain_commit_is_not_a_merge(repo):
    assert check.check_merge(_head(repo)) == []


def test_no_upstream_skips_the_check(repo, capsys):
    assert check.main(["--upstream", "missing"]) == 0
    assert "not found; skipped" in capsys.readouterr().out


def test_the_pre_push_hook_runs_this_check():
    text = (ROOT / "dev" / "hooks" / "pre-push").read_text(encoding="utf-8")
    assert "dev/check_merges.py" in text
    assert text.index("dev/check_merges.py") < text.index("dev/ci_local.py")


def test_the_merge_that_lost_lines_stays_listed():
    assert "1bd0b64db19014e15fe402940a9d8acebd1f3686" in check.REPAIRED
