"""Tests for companion-site progress reporting."""

from __future__ import annotations

from pathlib import Path

from conftest import SRC, load_module

report = load_module("report_progress", SRC / "report_progress.py")


def test_progress_skipped_env(monkeypatch):
    monkeypatch.setenv("NLPP_PROGRESS_SKIP", "1")
    assert report._progress_skipped() is True
    monkeypatch.setenv("NLPP_PROGRESS_SKIP", "yes")
    assert report._progress_skipped() is True
    monkeypatch.setenv("NLPP_PROGRESS_SKIP", "0")
    assert report._progress_skipped() is False


def test_from_env_or_dotenv_reads_env_first(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("NLPP_PROGRESS_TOKEN", "from-env")
    monkeypatch.setattr(report.paths, "ROOT", tmp_path)
    assert report._from_env_or_dotenv("NLPP_PROGRESS_TOKEN") == "from-env"


def test_from_env_or_dotenv_reads_dotenv(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("NLPP_PROGRESS_TOKEN", raising=False)
    monkeypatch.setattr(report.paths, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        'NLPP_PROGRESS_TOKEN="from-dotenv"\n',
        encoding="utf-8",
    )
    assert report._from_env_or_dotenv("NLPP_PROGRESS_TOKEN") == "from-dotenv"


def test_try_report_progress_skips_without_credentials(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("NLPP_PROGRESS_ENDPOINT", raising=False)
    monkeypatch.delenv("NLPP_PROGRESS_TOKEN", raising=False)
    monkeypatch.setattr(report.paths, "ROOT", tmp_path)
    assert report.try_report_progress() is False
