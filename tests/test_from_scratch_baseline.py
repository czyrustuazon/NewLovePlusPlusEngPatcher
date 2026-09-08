"""Working from-scratch Drop baseline (Sep 2026).

Locks the contract that a clean clone + dropped ROM can finish a full CIA:
  extract vanilla (img + TRB + code.bin)
  → gold bake with Eng_Patch (Title pkg 5261)
  → release/name_input_code.bin
  → Drop inject (no soft-skips / no incomplete CIAs)

These are unit/contract tests — no 680MB bake or live ROM required.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import nlpp_paths as paths
from conftest import ROOT, SRC, TOOLS, load_module

patch_cia = load_module("patch_cia", SRC / "patch_cia.py")
extract = load_module("extract_vanilla_from_rom", SRC / "extract_vanilla_from_rom.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
name_kanji = load_module("deploy_name_kanji_trb", TOOLS / "deploy_name_kanji_trb.py")

BAT = ROOT / "Drop CIA or 3DS Here to Patch.bat"


def _bat() -> str:
    return BAT.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Drop bat — complete-CIA gate
# ---------------------------------------------------------------------------


def test_baseline_drop_requires_full_artifact_set():
    """Drop must not inject until Eng_Patch + name_input exist; no scripts-only."""
    text = _bat()
    assert "NLPP_WITH_IMAGES=0 is not allowed" in text
    assert "Scripts-only patch" not in text
    assert "NEED_FINISH" in text
    assert "_title_pkg_has_eng_patch" in text
    assert "name_input_code.bin" in text
    assert "--skip-pack" in text
    assert 'INJECT_CODE=--inject-code %~dp0release\\name_input_code.bin' in text
    # Finish incomplete artifacts before inject.
    assert text.index("NEED_FINISH") < text.index("Injecting gold bake")
    assert text.index("name_input_code.bin still missing") < text.index(
        "Injecting gold bake"
    )


def test_baseline_drop_rebuilds_from_rom_when_bake_missing():
    text = _bat()
    assert "rebuild_bake_img.py" in text
    assert '--rom "%CIA%"' in text
    assert "fetch_release_bake.py" in text
    assert text.index("fetch_release_bake.py") < text.index(
        "running tools\\rebuild_bake_img.py"
    )


# ---------------------------------------------------------------------------
# Vanilla extract — code.bin required + retries
# ---------------------------------------------------------------------------


def test_baseline_vanilla_cache_requires_code_bin(tmp_path: Path, monkeypatch):
    img = tmp_path / "img.bin"
    trb = tmp_path / "textresource_jpn.trb"
    code = tmp_path / "code.bin"
    img.write_bytes(b"img")
    trb.write_bytes(b"trb")
    monkeypatch.setattr(extract, "VANILLA_IMG", img)
    monkeypatch.setattr(extract, "VANILLA_MAIN_TRB", trb)
    monkeypatch.setattr(extract, "VANILLA_CODE", code)
    monkeypatch.setattr(extract, "MARKER", tmp_path / ".source_rom.txt")

    assert extract.vanilla_cache_ready() is False
    code.write_bytes(b"code")
    assert extract.vanilla_cache_ready() is True


def test_baseline_retry_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise extract.PatchError("transient")
        return "ok"

    assert extract._retry(flaky, attempts=3, delay_s=0.01, what="test") == "ok"
    assert calls["n"] == 3


def test_baseline_retry_raises_after_exhausted_attempts(monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda *_a, **_k: None)

    def always_fail():
        raise extract.PatchError("nope")

    with pytest.raises(extract.PatchError, match="failed after 3 attempts"):
        extract._retry(always_fail, attempts=3, delay_s=0.01, what="test")


def test_baseline_extract_source_has_no_code_soft_skip():
    text = (SRC / "extract_vanilla_from_rom.py").read_text(encoding="utf-8")
    assert "warning: code.bin extract failed" not in text
    assert "_retry(" in text
    assert "ExeFS code.bin extract" in text


# ---------------------------------------------------------------------------
# Name-kanji TRB — from-scratch resolver (no sibling-dump hardcode)
# ---------------------------------------------------------------------------


def test_baseline_name_kanji_resolves_via_env(tmp_path: Path, monkeypatch):
    trb = tmp_path / "textresource_jpn.trb"
    cfg = tmp_path / "textresource_config.trb"
    trb.write_bytes(b"trb")
    cfg.write_bytes(b"cfg")
    monkeypatch.setenv("NLPP_VANILLA_TRB", str(trb))
    got_trb, got_cfg = name_kanji.resolve_vanilla_trb_and_cfg()
    assert got_trb == trb.resolve()
    assert got_cfg == cfg.resolve()


def test_baseline_name_kanji_resolves_cache_vanilla_from_rom(
    tmp_path: Path, monkeypatch
):
    cache_trb = (
        tmp_path
        / "vanilla_from_rom"
        / "romfs"
        / "SystemData"
        / "TextResource"
        / "textresource_jpn.trb"
    )
    cache_trb.parent.mkdir(parents=True)
    cache_trb.write_bytes(b"trb")
    (cache_trb.parent / "textresource_config.trb").write_bytes(b"cfg")
    monkeypatch.delenv("NLPP_VANILLA_TRB", raising=False)
    monkeypatch.setattr(paths, "DEFAULT_VANILLA_MAIN_TRB", tmp_path / "missing.trb")
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "CACHE_VANILLA_MAIN_TRB", cache_trb)
    assert paths.find_vanilla_main_trb() == cache_trb.resolve()
    monkeypatch.setattr(name_kanji, "find_vanilla_main_trb", paths.find_vanilla_main_trb)
    got_trb, got_cfg = name_kanji.resolve_vanilla_trb_and_cfg()
    assert got_trb == cache_trb.resolve()
    assert got_cfg.name == "textresource_config.trb"


def test_baseline_name_kanji_no_hardcoded_sibling_path():
    text = (TOOLS / "deploy_name_kanji_trb.py").read_text(encoding="utf-8")
    assert 'ROOT.parents[0]' not in text
    assert "New Love Plus Plus" not in text
    assert "find_vanilla_main_trb" in text


def test_baseline_name_kanji_filter_keeps_ui_allowlist():
    mapping = {
        "冬": "Winter",
        "あ": "A",
        "芽": "Bud",
        "Options": "Options",
    }
    out = name_kanji.filter_mapping(mapping)
    assert out["冬"] == "Winter"
    assert out["Options"] == "Options"
    assert "あ" not in out
    assert "芽" not in out


# ---------------------------------------------------------------------------
# Rebuild — Eng_Patch deploy + required name_input
# ---------------------------------------------------------------------------


def test_baseline_rebuild_deploys_title_engpatch_not_labels_only():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_title_engpatch_en.py" in scripts
    assert "deploy_title_main_menu_en.py" not in scripts


def test_baseline_rebuild_name_input_hard_fails_without_vanilla_code(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(rebuild.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(rebuild, "find_vanilla_code", lambda: None)
    monkeypatch.setattr(rebuild, "RELEASE", tmp_path / "release")
    monkeypatch.setattr(rebuild, "NAME_INPUT_CODE", tmp_path / "release" / "name.bin")

    with pytest.raises(SystemExit, match="name_input_code.bin failed after 3 attempts"):
        rebuild.build_name_input_code(rom=None)


def test_baseline_rebuild_name_input_writes_artifact(monkeypatch, tmp_path: Path):
    src_code = tmp_path / "vanilla_code.bin"
    src_code.write_bytes(b"vanilla-code")
    out = tmp_path / "release" / "name_input_code.bin"
    monkeypatch.setattr(rebuild, "find_vanilla_code", lambda: src_code)
    monkeypatch.setattr(rebuild, "RELEASE", tmp_path / "release")
    monkeypatch.setattr(rebuild, "NAME_INPUT_CODE", out)
    monkeypatch.setattr(rebuild.time, "sleep", lambda *_a, **_k: None)

    def fake_run(cmd, *, env=None):
        # deploy_name_input_en.py --src … --out …
        out_idx = cmd.index("--out") + 1
        Path(cmd[out_idx]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[out_idx]).write_bytes(b"patched-code")

    monkeypatch.setattr(rebuild, "run", fake_run)
    got = rebuild.build_name_input_code(rom=None)
    assert got == out
    assert out.read_bytes() == b"patched-code"


# ---------------------------------------------------------------------------
# patch_cia — Eng_Patch + name-input gates
# ---------------------------------------------------------------------------


def test_baseline_require_name_input_ok_and_fail(tmp_path: Path):
    code = tmp_path / "name_input_code.bin"
    code.write_bytes(b"x")
    patch_cia._require_name_input_for_ui(
        argparse.Namespace(inject_code=str(code), patch_code=False)
    )
    with pytest.raises(patch_cia.PatchError, match="required for a full UI patch"):
        patch_cia._require_name_input_for_ui(
            argparse.Namespace(inject_code=None, patch_code=False)
        )
    with pytest.raises(patch_cia.PatchError, match="Profile name-input missing"):
        patch_cia._require_name_input_for_ui(
            argparse.Namespace(
                inject_code=str(tmp_path / "missing.bin"), patch_code=False
            )
        )


def test_baseline_summary_matches_successful_full_cia(tmp_path: Path, monkeypatch):
    """Mirrors the working PATCH SUMMARY shape from a successful Drop."""
    bake = tmp_path / "release" / "bake_img.bin"
    bake.parent.mkdir(parents=True)
    bake.write_bytes(b"gold")
    code = tmp_path / "release" / "name_input_code.bin"
    code.write_bytes(b"code")
    overlay = tmp_path / "release" / "romfs_overlay"
    overlay.mkdir(parents=True)
    out = tmp_path / "out" / "NewLovePlusPlus-EN.cia"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"cia" * 100)
    luma = tmp_path / "out" / "luma" / "00040000000F4E00"
    luma.mkdir(parents=True)
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", bake)

    lines = patch_cia.build_patch_summary(
        out_cia=out,
        packed_img=bake,
        layered_img=bake,
        layeredfs_out=luma.parent,
        romfs_overlay=overlay,
        args=argparse.Namespace(
            no_images=False,
            with_images=True,
            inject_code=str(code),
            patch_code=False,
            skip_name_patches=False,
            skip_hash=True,
        ),
        eng_patch=True,
        elapsed="3m05s",
        started_at="2026-09-08 00:12:03",
    )
    text = "\n".join(lines)
    assert "[OK]" in text and "Dialog scripts" in text
    assert "[OK]" in text and "UI img.bin" in text and "gold bake" in text
    assert "[OK]" in text and "Eng Patch title badge" in text
    assert "[OK]" in text and "Profile name-input code.bin" in text
    assert "[OK]" in text and "RomFS overlay" in text
    assert "[OK]" in text and "Heroine name table patches" in text
    assert "[OK]" in text and "Output CIA" in text
    assert "[SKIPPED]" in text and "Input CIA SHA-1" in text  # bat pre-checked
    assert "no --inject-code" not in text
    assert "[OK]" in text and "Time to finish: 3m05s" in text
