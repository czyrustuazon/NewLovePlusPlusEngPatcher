"""Coverage for img_pack_cache, script_inject, and the Restore Default /
Eng Patch info code caves (vanilla body hashes monkeypatched to synthetic bytes).
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

import img_pack_cache as ipc
import patch_camera_defaults_reset as rst
import patch_title_engpatch_info as info
import script_inject as si

# ---------------------------------------------------------------------------
# img_pack_cache
# ---------------------------------------------------------------------------


def test_atomic_write_cleans_up_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "d" / "blob"

    def fail_replace(self, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        ipc._atomic_write(target, b"x")
    assert list(target.parent.iterdir()) == []

    real_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(OSError, match="replace failed"):
        ipc._atomic_write(target, b"x")
    monkeypatch.setattr(Path, "unlink", real_unlink)


def test_bclim_cache_hit_miss_and_bad_length(tmp_path, monkeypatch):
    cache = ipc.ImgPackCache(tmp_path / "c")
    assert cache.get_bclim(b"png", b"orig") is None
    cache.put_bclim(b"png", b"orig", b"toolong")  # wrong length: not stored
    cache.put_bclim(b"png", b"orig", b"ENCD")
    assert cache.get_bclim(b"png", b"orig") == b"ENCD"
    # A stale blob of the wrong length is dropped.
    path = cache._blob_path("bclim", cache.bclim_key(b"png", b"orig"))
    path.write_bytes(b"xx")
    assert cache.get_bclim(b"png", b"orig") is None
    assert not path.exists()
    path.write_bytes(b"xx")
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(OSError("busy")))
    assert cache.get_bclim(b"png", b"orig") is None
    assert cache.stats.bclim_hit == 1 and cache.stats.bclim_miss == 3
    assert "bclim hit/miss=1/3" in cache.stats.summary()


def test_zlib_cache_and_cached_compress(tmp_path, monkeypatch, capsys):
    cache = ipc.ImgPackCache(tmp_path / "c")
    data = b"hello" * 20
    slot = zlib.compress(data, 9)
    assert cache.get_zlib(data, len(slot), fine_tune=False) is None
    cache.put_zlib(data, len(slot) + 1, slot, fine_tune=False)  # wrong length
    cache.put_zlib(data, len(slot), b"\x00" * len(slot), fine_tune=False)  # not zlib
    cache.put_zlib(data, len(slot), slot, fine_tune=False)
    assert cache.get_zlib(data, len(slot), fine_tune=False) == slot

    path = cache._blob_path("zlib", cache.zlib_key(data, len(slot), fine_tune=False))
    path.write_bytes(slot + b"!")  # trailing data / wrong length
    assert cache.get_zlib(data, len(slot), fine_tune=False) is None
    path.write_bytes(slot[:-1] + b"!")
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(OSError("busy")))
    assert cache.get_zlib(data, len(slot), fine_tune=False) is None
    monkeypatch.undo()

    assert ipc._zlib_slot_ok(zlib.compress(b"ab") + b"tail", 2) is False
    assert ipc._zlib_slot_ok(zlib.compress(b"ab")[:-3], 2) is False
    assert ipc._zlib_slot_ok(zlib.compress(b"ab"), 3) is False

    import exact_zlib

    monkeypatch.setattr(exact_zlib, "compress_to_exact_slot", lambda d, n, fine_tune=False: slot)
    fresh = ipc.ImgPackCache(tmp_path / "c2")
    assert ipc.compress_to_exact_slot_cached(data, len(slot), cache=fresh) == slot
    assert ipc.compress_to_exact_slot_cached(data, len(slot), cache=fresh) == slot
    assert "cache hit" in capsys.readouterr().out
    assert ipc.compress_to_exact_slot_cached(data, len(slot)) == slot


# ---------------------------------------------------------------------------
# script_inject
# ---------------------------------------------------------------------------


@pytest.fixture
def si_paths(tmp_path, monkeypatch):
    p = {
        "COMMUNITY_MANIFEST": tmp_path / "nlppatch" / "stems.json",
        "GEMINI_NENE_ROOT": tmp_path / "gem",
        "GEMINI_NENE_DBIN": tmp_path / "gem" / "dbin2",
        "GEMINI_NENE_MANIFEST": tmp_path / "gem" / "stems.json",
        "CONTRIB_DBIN": tmp_path / "contrib",
        "LEGACY_NLPPATCH_SCRIPT": tmp_path / "vendor" / "script",
        "ROOT": tmp_path / "root",
    }
    for k, v in p.items():
        monkeypatch.setattr(si, k, v)
    monkeypatch.setattr(si, "_community_stems", None)
    monkeypatch.setattr(si, "_gemini_nene_stems", None)
    monkeypatch.delenv("NLPP_INCLUDE_GEMINI_NENE", raising=False)
    return p


def _put(path: Path, data: bytes = b"EN") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_stem_lists_without_any_source(si_paths):
    assert si.gemini_nene_stems() == set()
    assert si.community_stems() == set()
    assert si.nlppatch_script_dir() is None


def test_stem_lists_from_dirs_and_legacy_vendor(si_paths):
    _put(si_paths["GEMINI_NENE_DBIN"] / "script" / "a001.dbin2")
    _put(si_paths["GEMINI_NENE_ROOT"] / "xml" / "k002.xml")
    assert si.gemini_nene_stems() == {"a001", "k002"}
    _put(si_paths["LEGACY_NLPPATCH_SCRIPT"] / "a777.dbin2")
    assert si.community_stems() == {"a777"}
    assert si.nlppatch_script_dir() == si_paths["LEGACY_NLPPATCH_SCRIPT"]


def test_resolve_falls_back_to_legacy_vendor_and_prefix(si_paths, tmp_path, monkeypatch):
    eng = tmp_path / "eng"
    _put(eng / "script" / "a100.dbin2")
    # No manifest: an a*/k* file left in rebuild counts as community.
    assert si.resolve_script_source("script", "a100", eng)[1] == "nlppatch"
    _put(si_paths["LEGACY_NLPPATCH_SCRIPT"] / "a200.dbin2")
    got, tag = si.resolve_script_source("script", "a200", eng)
    assert tag == "nlppatch" and got.parent == si_paths["LEGACY_NLPPATCH_SCRIPT"]
    assert si.resolve_script_source("script", "a300", eng) == (None, "jp")


def test_coverage_summary_counts_contrib_and_gemini(si_paths, tmp_path, monkeypatch):
    eng = tmp_path / "eng"  # no script dir at all
    _put(si_paths["CONTRIB_DBIN"] / "script" / "a010.dbin2")
    _put(si_paths["GEMINI_NENE_DBIN"] / "script" / "k020.dbin2")
    monkeypatch.setenv("NLPP_INCLUDE_GEMINI_NENE", "1")
    s = si.coverage_summary(eng)
    assert s["contrib"] == 1 and s["gemini_nene"] == 1 and s["gemini_nene_enabled"] is True


def test_inject_errors_and_marker_note(si_paths, tmp_path, monkeypatch, capsys):
    eng = tmp_path / "eng"
    with pytest.raises(si.ScriptInjectError, match="missing packed scripts"):
        si.inject_scripts(tmp_path / "romfs", eng, create_dirs=True)

    for pack in si.PACKS:
        _put(eng / pack / "t001.dbin2")
    monkeypatch.setattr(si, "apply_nene_marker_to_romfs", lambda romfs, vanilla: 2)
    assert si.inject_scripts(tmp_path / "romfs", eng, create_dirs=True) == 3
    assert "nickname markers updated in 2" in capsys.readouterr().out


def test_apply_marker_skips_overlaid_and_missing_dest_root(si_paths, tmp_path, monkeypatch):
    vanilla = tmp_path / "vanilla"
    _put(vanilla / "script" / "a001.dbin2", b"JP")
    romfs = tmp_path / "romfs"
    monkeypatch.setattr(si, "_rewrite_base_script", lambda raw, stem="": raw + b"!")
    # No script/bin yet: nothing rewritten in place, vanilla file copied in.
    assert si.apply_nene_marker_to_romfs(romfs, vanilla) == 1
    # Now it is overlaid: the in-place pass rewrites it, the vanilla pass skips it.
    assert si.apply_nene_marker_to_romfs(romfs, vanilla) == 1


def test_main(si_paths, tmp_path, monkeypatch, capsys):
    calls = []

    def fake_inject(romfs, dbin, *, create_dirs, vanilla_bin):
        calls.append((romfs, dbin, create_dirs, vanilla_bin))
        return 7

    monkeypatch.setattr(si, "inject_scripts", fake_inject)
    assert si.main(["--layeredfs", str(tmp_path / "lfs"), "--include-gemini-nene"]) == 0
    assert si.include_gemini_nene()
    import os

    os.environ.pop("NLPP_INCLUDE_GEMINI_NENE", None)
    assert calls[-1][2] is True and calls[-1][3] is None
    assert "layeredfs OK (7" in capsys.readouterr().out

    vanilla = si_paths["ROOT"] / "cache" / "vanilla_from_rom" / "romfs" / "script" / "bin"
    vanilla.mkdir(parents=True)
    assert si.main(["--layeredfs", str(tmp_path / "lfs")]) == 0
    assert calls[-1][3] == vanilla

    def broken(*a, **k):
        raise si.ScriptInjectError("nope")

    monkeypatch.setattr(si, "inject_scripts", broken)
    assert si.main(["--layeredfs", str(tmp_path / "lfs")]) == 1
    assert "nope" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# patch_camera_defaults_reset / patch_title_engpatch_info caves
# ---------------------------------------------------------------------------

CODE_LEN = info.HUB_TOUCH_SLOT + 0x100


def _layout(data: bytearray, base: int) -> None:
    struct.pack_into("<H", data, rst.ADDR_LAYOUT_TABLE + 2 * rst.DIALOG_LAYOUT, base)


def _camera_vanilla(monkeypatch) -> bytearray:
    data = bytearray(CODE_LEN)
    data[rst.ADDR_STUB : rst.ADDR_STUB + 4] = rst.STUB_PATCHED
    body = bytes(range(256)) * 2
    data[rst.CAVE_START : rst.CAVE_END] = body[: rst.CAVE_END - rst.CAVE_START]
    monkeypatch.setattr(rst, "CAVE_VANILLA_SHA256", hashlib.sha256(data[rst.CAVE_START : rst.CAVE_END]).hexdigest())
    data[rst.HOOK_PRESS : rst.HOOK_PRESS + 4] = rst.HOOK_PRESS_VANILLA
    data[rst.HOOK_POLL : rst.HOOK_POLL + 4] = rst.HOOK_POLL_VANILLA
    _layout(data, rst.DIALOG_LAYOUT_BASE)
    return data


def test_camera_reset_apply(monkeypatch, capsys):
    data = _camera_vanilla(monkeypatch)
    assert rst.apply_patch(data) is True
    assert rst.is_patched(data)
    assert rst.apply_patch(data) is False
    assert "already applied" in capsys.readouterr().out


@pytest.mark.parametrize(
    "breakit, msg",
    [
        (lambda d: d.__setitem__(slice(rst.ADDR_STUB, rst.ADDR_STUB + 4), b"\0" * 4), "not bx lr"),
        (lambda d: d.__setitem__(rst.CAVE_START, 0xFF), "is not vanilla"),
        (lambda d: d.__setitem__(rst.HOOK_POLL, 0), "unexpected insn"),
        (lambda d: _layout(d, 7), "starts at slot 7"),
    ],
)
def test_camera_reset_rejects(monkeypatch, breakit, msg):
    data = _camera_vanilla(monkeypatch)
    breakit(data)
    with pytest.raises(ValueError, match=msg):
        rst.apply_patch(data)


def test_camera_reset_region_too_big(monkeypatch):
    monkeypatch.setattr(rst, "CAVE_END", rst.CAVE_START + 8)
    with pytest.raises(ValueError, match="camera reset cave"):
        rst.build_region()


def _info_vanilla(monkeypatch, *, nop_a: bool = False) -> bytearray:
    data = bytearray(CODE_LEN)
    data[info.ADDR_STUB : info.ADDR_STUB + 4] = info.STUB_PATCHED
    data[info.CEC_STUB : info.CEC_STUB + len(info.CEC_STUB_PATCHED)] = info.CEC_STUB_PATCHED
    a_len = info.CAVE_A_END - info.CAVE_A_START
    data[info.CAVE_A_START : info.CAVE_A_END] = info.NOP * (a_len // 4) if nop_a else bytes([7]) * a_len
    data[info.CAVE_B_START : info.CAVE_B_END] = bytes([9]) * (info.CAVE_B_END - info.CAVE_B_START)
    monkeypatch.setattr(info, "CAVE_A_VANILLA_SHA256", hashlib.sha256(bytes([7]) * a_len).hexdigest())
    monkeypatch.setattr(
        info, "CAVE_B_VANILLA_SHA256", hashlib.sha256(data[info.CAVE_B_START : info.CAVE_B_END]).hexdigest()
    )
    data[info.HOOK_TAP : info.HOOK_TAP + 4] = info.HOOK_TAP_VANILLA
    data[info.HOOK_ENTER : info.HOOK_ENTER + 4] = info.HOOK_ENTER_VANILLA
    data[info.HUB_TOUCH_SLOT : info.HUB_TOUCH_SLOT + 4] = info.HUB_TOUCH_SLOT_VANILLA
    _layout(data, info.DIALOG_LAYOUT_BASE)
    return data


@pytest.mark.parametrize("nop_a", [False, True])
def test_engpatch_info_apply(monkeypatch, capsys, nop_a):
    data = _info_vanilla(monkeypatch, nop_a=nop_a)
    assert info.apply_patch(data) is True
    assert info.is_patched(data)
    assert info.apply_patch(data) is False
    assert "already applied" in capsys.readouterr().out


@pytest.mark.parametrize(
    "breakit, msg",
    [
        (lambda d: d.__setitem__(info.ADDR_STUB, 0), "not bx lr"),
        (lambda d: d.__setitem__(info.CEC_STUB, d[info.CEC_STUB] ^ 0xFF), "CecCheckEula stub"),
        (lambda d: d.__setitem__(info.CAVE_A_START, 0), "neither vanilla nor NOP"),
        (lambda d: d.__setitem__(info.CAVE_B_START, 0), "body .* is not vanilla"),
        (lambda d: d.__setitem__(info.HOOK_ENTER, 0), "unexpected bytes"),
        (lambda d: _layout(d, 3), "starts at slot 3"),
    ],
)
def test_engpatch_info_rejects(monkeypatch, breakit, msg):
    data = _info_vanilla(monkeypatch)
    breakit(data)
    with pytest.raises(ValueError, match=msg):
        info.apply_patch(data)


def test_engpatch_info_build_limits(monkeypatch):
    with pytest.raises(ValueError, match="cave X 8 > 4"):
        info._pad(b"\0" * 8, 0, 4, "X")
    real_finish = info._Asm.finish

    def bloated(self):
        out = real_finish(self)
        return out + bytes(0x400) if self.base == info.CAVE_A_START else out

    monkeypatch.setattr(info._Asm, "finish", bloated)
    with pytest.raises(ValueError, match="add-immediate range"):
        info.build_caves()


def test_engpatch_credit_pages_split(monkeypatch):
    monkeypatch.setattr(info, "PAGE_LINES", 6)
    monkeypatch.setattr(info, "BLANK_BETWEEN_ROLES", True)
    pages = info._credit_pages()
    assert len(pages) > 1


def test_append_message_slot_rejects_other_text():
    from test_patch_camera_defaults_reset import _fake_trb

    with pytest.raises(ValueError, match="holds other text"):
        rst.append_confirm_message(_fake_trb([3, rst.MSG_VANILLA_SLOTS + 1, 2]))


def test_inject_into_existing_dirs_and_empty_pack(si_paths, tmp_path):
    eng = tmp_path / "eng"
    romfs = tmp_path / "romfs"
    for pack in si.PACKS:
        _put(eng / pack / "t001.dbin2")
        (romfs / "script" / "bin" / pack).mkdir(parents=True)
    assert si.inject_scripts(romfs, eng) == 3
    (eng / "script" / "t001.dbin2").unlink()
    with pytest.raises(si.ScriptInjectError, match="no .dbin2 files"):
        si.inject_scripts(romfs, eng)


def test_resolve_and_summary_edges(si_paths, tmp_path):
    eng = tmp_path / "eng"
    _put(si_paths["COMMUNITY_MANIFEST"], json.dumps({"stems": ["a001"]}).encode())
    _put(eng / "script" / "a002.dbin2")  # in rebuild, not on the allowlist
    _put(eng / "script" / "z003.dbin2")  # no layer claims z*
    _put(eng / "script" / "t004.dbin2")
    assert si.resolve_script_source("script", "a002", eng) == (None, "jp")
    s = si.coverage_summary(eng)
    assert s["manaka"] == 1 and s["gemini_nene_enabled"] is False


def test_resolve_without_manifest_ignores_other_prefixes(si_paths, tmp_path):
    eng = tmp_path / "eng"
    _put(eng / "script" / "z005.dbin2")
    assert si.resolve_script_source("script", "z005", eng) == (None, "jp")
