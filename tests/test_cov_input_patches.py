"""Coverage for the Name Input / password / layout code.bin patches.

Each patch runs on a zero bytearray the size of code.bin with only the bytes
its site checks. No vanilla code.bin. ``--deploy-azahar`` writes under a fake
home or a monkeypatched Azahar mod dir in tmp_path.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

import nlpp_paths
import patch_input_candidate_nullguard as cand
import patch_input_candmode_fillflag_reset as fill
import patch_input_kana_direct_insert as kana
import patch_input_pane_registry_nullguard as pane
import patch_input_romaji as romaji
import patch_input_skip_ascii_dakuten as dakuten
import patch_input_strcat_raw as strcat
import patch_lyt_null_pane as lyt
import patch_password_serials as serials
import patch_password_uribo as uribo

CODE_LEN = 0x6C0000


def _code(**sites: bytes) -> bytearray:
    data = bytearray(CODE_LEN)
    for addr, blob in sites.items():
        a = int(addr, 16)
        data[a : a + len(blob)] = blob
    return data


def _put(data: bytearray, addr: int, blob: bytes) -> bytearray:
    data[addr : addr + len(blob)] = blob
    return data


# ---------------------------------------------------------------------------
# Shared main(): --dry-run / missing flag / deploy to ~/AppData/.../code.bin
# ---------------------------------------------------------------------------

HOME_DEPLOY = (dakuten, pane, fill, cand, lyt)


@pytest.mark.parametrize("mod", HOME_DEPLOY, ids=lambda m: m.__name__)
def test_home_deploy_main(mod, monkeypatch, tmp_path, capsys):
    assert mod.main(["--dry-run"]) == 0
    with pytest.raises(SystemExit, match="--deploy-azahar"):
        mod.main([])

    monkeypatch.setattr(mod.Path, "home", classmethod(lambda cls: tmp_path))
    dest = tmp_path / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    with pytest.raises(SystemExit, match="missing"):
        mod.main(["--deploy-azahar"])

    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"vanilla")
    calls = []

    def fake_apply(data: bytearray) -> None:
        calls.append(bytes(data))
        data[:] = b"patched"

    monkeypatch.setattr(mod, "apply_patch", fake_apply)
    assert mod.main(["--deploy-azahar"]) == 0
    assert (dest.parent.parent / "code.bin").read_bytes() == b"patched"
    baks = list(dest.parent.glob("code.bin.bak_pre_*"))
    assert len(baks) == 1 and baks[0].read_bytes() == b"vanilla"
    # Second deploy keeps the first backup.
    assert mod.main(["--deploy-azahar"]) == 0
    assert baks[0].read_bytes() == b"vanilla"
    assert calls == [b"vanilla", b"patched"]
    assert "backup" in capsys.readouterr().out


@pytest.mark.parametrize("mod", (kana, uribo), ids=lambda m: m.__name__)
def test_mod_code_deploy_main(mod, monkeypatch, tmp_path, capsys):
    assert mod.main(["--dry-run"]) == 0
    with pytest.raises(SystemExit, match="--deploy-azahar"):
        mod.main([])
    root = tmp_path / "mods"
    dest = root / "exefs" / "code.bin"
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_CODE", dest)
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_ROOT", root)
    with pytest.raises(SystemExit, match="missing"):
        mod.main(["--deploy-azahar"])

    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"v")
    seen = []
    monkeypatch.setattr(mod, "apply_patch", lambda data: seen.append("apply"))
    monkeypatch.setattr(mod, "revert_patch", lambda data: seen.append("revert"))
    if mod is kana:
        monkeypatch.setattr(mod, "restore_bind_sites", lambda data: seen.append("bind"))
    assert mod.main(["--deploy-azahar"]) == 0
    assert mod.main(["--deploy-azahar", "--revert"]) == 0
    assert seen[-1] == "revert" and "apply" in seen
    assert (root / "code.bin").read_bytes() == b"v"
    assert len(list(dest.parent.glob("*.bak_pre_*"))) == 1
    assert "backup" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# apply_patch per module
# ---------------------------------------------------------------------------


def test_skip_ascii_dakuten_apply(capsys):
    data = _put(_code(), dakuten.SITE, dakuten.EXPECT_SITE)
    _put(data, dakuten.SITE_CONVERT, dakuten.EXPECT_CONVERT)
    _put(data, dakuten.OLD_CAVE, b"\xff" * dakuten.OLD_CAVE_LEN)
    assert not dakuten.is_patched(data)
    dakuten.apply_patch(data)
    assert dakuten.is_patched(data)
    assert not any(data[dakuten.OLD_CAVE : dakuten.OLD_CAVE + dakuten.OLD_CAVE_LEN])
    dakuten.apply_patch(data)
    assert "already patched" in capsys.readouterr().out

    with pytest.raises(ValueError, match="unexpected bytes at site"):
        dakuten.apply_patch(_code())
    bad_conv = _put(_code(), dakuten.SITE, bytes.fromhex("0de410ea"))  # old cave hook
    with pytest.raises(ValueError, match="unexpected bytes at convert"):
        dakuten.apply_patch(bad_conv)


def test_pane_registry_nullguard_apply(capsys):
    data = _put(_code(), pane.SITE, pane.EXPECT_SITE)
    pane.apply_patch(data)
    assert data[pane.SITE : pane.SITE + 4] == pane.b_ins(pane.SITE, pane.CAVE)
    assert data[pane.CAVE : pane.CAVE + pane.CAVE_LEN] == pane.build_cave()
    assert "pane-registry-nullguard" in capsys.readouterr().out
    with pytest.raises(ValueError, match="unexpected bytes"):
        pane.apply_patch(data)
    busy = _put(_put(_code(), pane.SITE, pane.EXPECT_SITE), pane.CAVE, b"\x01")
    with pytest.raises(ValueError, match="not empty"):
        pane.apply_patch(busy)


def test_candmode_fillflag_apply(monkeypatch, capsys):
    data = _put(_code(), fill.SITE, fill.EXPECT_SITE)
    fill.apply_patch(data)
    fill.apply_patch(data)  # re-deploy over its own cave
    assert data[fill.CAVE : fill.CAVE + fill.CAVE_LEN] == fill.build_cave()
    assert "clamp +0x30" in capsys.readouterr().out
    with pytest.raises(ValueError, match="unexpected bytes"):
        fill.apply_patch(_code())
    busy = _put(_put(_code(), fill.SITE, fill.EXPECT_SITE), fill.CAVE + 4, b"\x01")
    with pytest.raises(ValueError, match="not empty"):
        fill.apply_patch(busy)
    monkeypatch.setattr(fill, "CAVE_LEN", 8)
    with pytest.raises(SystemExit, match="fillflag cave"):
        fill.build_cave()


def test_candidate_nullguard_apply(capsys):
    data = _put(_put(_code(), cand.SITE1, cand.EXPECT_SITE), cand.SITE2, cand.EXPECT_SITE)
    cand.apply_patch(data)
    assert data[cand.SITE1 : cand.SITE1 + 4] == cand.b_ins(cand.SITE1, cand.CAVE1)
    assert "fillcand-nullguard" in capsys.readouterr().out
    with pytest.raises(ValueError, match="site1"):
        cand.apply_patch(_code())
    with pytest.raises(ValueError, match="site2"):
        cand.apply_patch(_put(_code(), cand.SITE1, cand.EXPECT_SITE))
    busy = _put(_put(_code(), cand.SITE1, cand.EXPECT_SITE), cand.SITE2, cand.EXPECT_SITE)
    _put(busy, cand.CAVE2, b"\x01")
    with pytest.raises(ValueError, match="cave2"):
        cand.apply_patch(busy)


def test_kana_direct_apply_revert_and_bind_sites(capsys):
    assert kana.u32(-1) == b"\xff" * 4
    data = _put(_code(), kana.SITE, kana.VANILLA)
    assert not kana.is_patched(data)
    kana.apply_patch(data)
    assert kana.is_patched(data)
    kana.apply_patch(data)
    kana.revert_patch(data)
    kana.revert_patch(data)
    out = capsys.readouterr().out
    assert "already patched" in out and "already vanilla" in out
    with pytest.raises(ValueError, match="want vanilla"):
        kana.apply_patch(_code())
    with pytest.raises(ValueError, match="unexpected bytes"):
        kana.revert_patch(_code())

    _put(data, kana.SITE_BIND_KBD, kana.VANILLA_BL_KBD)
    kana.restore_bind_sites(data)
    assert data[kana.SITE_BIND_CAND : kana.SITE_BIND_CAND + 4] == kana.VANILLA_BL_CAND
    assert "restored BindGrid BL (cand)" in capsys.readouterr().out


def test_strcat_raw_apply(monkeypatch, capsys):
    assert strcat.main(["--dry-run"]) == 0
    with pytest.raises(SystemExit, match="deploy_name_input_en"):
        strcat.main([])

    data = _put(_code(), strcat.ADDR, strcat.VANILLA_HEAD)
    assert not strcat.is_patched(data)
    strcat.apply_patch(data)
    assert strcat.is_patched(data)
    strcat.apply_patch(data)  # refresh own cave
    assert "strcat-raw" in capsys.readouterr().out
    # A branch somewhere else is not "patched".
    other = _put(_code(), strcat.ADDR, strcat.b_ins(strcat.ADDR, strcat.ADDR - 0x100))
    assert not strcat.is_patched(other)

    with pytest.raises(ValueError, match="unexpected FUN_002573ac head"):
        strcat.apply_patch(_code())
    busy = _put(_code(), strcat.ADDR, strcat.VANILLA_HEAD)
    _put(busy, strcat.cave_addr() + 4, b"\x01")
    with pytest.raises(ValueError, match="not empty pad"):
        strcat.apply_patch(busy)

    # The guard sits right after the hook today; a later guard NOPs the gap.
    monkeypatch.setattr(strcat, "ADDR_CHUNK_WALK_CAVE", strcat.ADDR + 12)
    gap = _put(_code(), strcat.ADDR, strcat.VANILLA_HEAD)
    strcat.apply_patch(gap)
    assert gap[strcat.ADDR + 4 : strcat.ADDR + 12] == strcat.NOP * 2

    monkeypatch.setattr(strcat, "ADDR_CHUNK_WALK_CAVE", strcat.ADDR + strcat.SIZE + 4)
    with pytest.raises(ValueError, match="outside"):
        strcat.apply_patch(_put(_code(), strcat.ADDR, strcat.VANILLA_HEAD))

    monkeypatch.setattr(strcat, "ADDR_COMMU_HEADER_CAVE", strcat.cave_addr())
    with pytest.raises(ValueError, match="overlaps commu header"):
        strcat.apply_patch(_code())


def test_lyt_null_pane_apply(monkeypatch, capsys):
    data = _put(_code(), lyt.ATTACH_SITE, lyt.ATTACH_EXPECT)
    _put(data, lyt.FIND_SITE, lyt.FIND_EXPECT)
    assert not lyt.is_patched(data)
    lyt.apply_patch(data)
    assert lyt.is_patched(data)
    lyt.apply_patch(data)
    assert "lyt-null-pane" in capsys.readouterr().out
    assert not lyt.is_patched(_put(_code(), lyt.ATTACH_SITE, lyt.b_ins(lyt.ATTACH_SITE, lyt.ATTACH_CAVE)))

    with pytest.raises(ValueError, match="unexpected bytes"):
        lyt.apply_patch(_code())
    busy = _put(_code(), lyt.ATTACH_SITE, lyt.ATTACH_EXPECT)
    _put(busy, lyt.ATTACH_CAVE, b"\x01")
    with pytest.raises(ValueError, match="not empty"):
        lyt.apply_patch(busy)

    monkeypatch.setattr(lyt, "ATTACH_CAVE_LEN", 4)
    with pytest.raises(ValueError, match="attach cave"):
        lyt.build_attach_cave()
    monkeypatch.setattr(lyt, "FIND_CAVE_LEN", 4)
    with pytest.raises(ValueError, match="find cave"):
        lyt.build_find_cave()


# ---------------------------------------------------------------------------
# patch_input_romaji leftovers
# ---------------------------------------------------------------------------


def test_romaji_blob_pads_odd_assembly(monkeypatch):
    real = romaji._assemble
    monkeypatch.setattr(romaji, "_assemble", lambda base, stream: real(base, stream) + b"\x01")
    blob = romaji.build_romaji_blob()
    assert len(blob) % 4 == 0


def test_romaji_main_patches_given_code_bin(monkeypatch, tmp_path, capsys):
    src = tmp_path / "code.bin"
    src.write_bytes(b"x" * 16)
    seen = []
    patch_code_bin = romaji.patch_code_bin_romaji
    monkeypatch.setattr(romaji, "patch_code_bin_romaji", lambda p, force=False: seen.append((p, force)))
    assert romaji.main([str(src), "--force"]) == 0
    assert seen == [(src.resolve(), True)]

    path = tmp_path / "c2.bin"
    path.write_bytes(b"y")
    (tmp_path / "c2.bin.bak_pre_input_romaji").write_bytes(b"old")
    monkeypatch.setattr(romaji, "patch_input_romaji", lambda data, force=False: False)
    assert patch_code_bin(path) is False
    assert "already patched" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# patch_password_serials
# ---------------------------------------------------------------------------


def _trb(*, slots: int = 48, entries: list[tuple[int, int, int]] | None = None,
         strb: bytes = b"", cat_off: int | None = None, sub_count: int = 1,
         tail: bytes = b"") -> bytes:
    indx = bytearray(0x400 + 4 + 4 + 4 + slots * 2)
    off = 0x400 if cat_off is None else cat_off
    struct.pack_into("<I", indx, serials.PASSWORD_CAT * 4, off)
    if off and off < len(indx):
        struct.pack_into("<I", indx, 0x400, sub_count)
        struct.pack_into("<I", indx, 0x404, 8)  # sub 0 at cat_off + 8
        struct.pack_into("<I", indx, 0x408, slots)
    stri = b"".join(struct.pack("<IHH", *e) for e in (entries or []))
    return serials._pack_trb(
        {"_order": ["STRI", "STRB", "INDX"], "STRI": stri, "STRB": strb, "INDX": bytes(indx), "_tail": tail}
    )


def test_password_serials_appends_codes_then_is_idempotent():
    data = _trb(entries=[(0, 3, 1)], strb=b"abc\x00\xc9\xc9\xc9\xc9", tail=b"\x00\x00")
    patched, logs = serials.apply_shared_serial_passwords(data)
    assert patched != data and len(logs) == len(serials.SHARED_SERIALS)
    again, logs2 = serials.apply_shared_serial_passwords(patched)
    assert again == patched
    assert all("already" in line for line in logs2)

    # STRB already 4-aligned after the append; no _tail chunk.
    chunks = serials.parse_chunks(_trb(entries=[(0, 1, 1)], strb=b"a\x00"))
    chunks.pop("_tail", None)
    out, _logs = serials.apply_shared_serial_passwords(serials._pack_trb(chunks))
    assert len(serials.parse_chunks(out)["STRB"]) % 4 == 0


def test_password_serials_errors_and_helpers():
    with pytest.raises(ValueError, match="too small"):
        serials._sub_u16_off(b"\x00" * 16, 1, 0)
    with pytest.raises(ValueError, match="missing"):
        serials.apply_shared_serial_passwords(_trb(cat_off=0))
    with pytest.raises(ValueError, match="has no sub"):
        serials.apply_shared_serial_passwords(_trb(sub_count=0))
    with pytest.raises(ValueError, match="password slot"):
        serials.apply_shared_serial_passwords(_trb(slots=30))

    assert serials._strb_used(b"", b"") == 0
    assert serials._strb_used(struct.pack("<IHH", 7, 0, 2), b"x" * 20) == 7
    stri = struct.pack("<IHH", 0, 3, 1) + struct.pack("<IHH", 0, 0, 2)
    assert serials._slot_text(stri, b"abc", 9) == (-1, "")
    assert serials._slot_text(stri, b"abc", 1) == (2, "")
    assert serials._slot_text(stri, b"abc", 0) == (1, "abc")  # no NUL: runs to the end


# ---------------------------------------------------------------------------
# patch_password_uribo
# ---------------------------------------------------------------------------


def _uribo_vanilla() -> bytearray:
    data = bytearray(uribo.ADDR_TABLE + uribo.N_SLOTS * 4)
    data[uribo.ADDR_SLOT_THRESH : uribo.ADDR_SLOT_THRESH + 8] = uribo.VANILLA_CMP + uribo.VANILLA_BGE
    uribo._put_s32(data, uribo._table_off(0), uribo.GLOVE_MANAKA)
    uribo._put_s32(data, uribo._table_off(24), uribo.SENTINEL_VISA)
    for s in uribo.URIBO_SLOTS:
        uribo._put_s32(data, uribo._table_off(s), uribo.SENTINEL_INTERNAL)
    return data


def test_password_uribo_apply_revert(capsys):
    data = _uribo_vanilla()
    assert uribo.is_vanilla(data) and not uribo.is_patched(data)
    assert uribo.apply_patch(data) is True
    assert uribo.is_patched(data)
    assert uribo.apply_patch(data) is False
    assert uribo.revert_patch(data) is True
    assert uribo.revert_patch(data) is False
    out = capsys.readouterr().out
    assert "already patched" in out and "already vanilla" in out

    with pytest.raises(ValueError, match="out of range"):
        uribo._table_off(uribo.N_SLOTS)
    with pytest.raises(ValueError, match="unexpected password grant table"):
        uribo.apply_patch(bytearray(16))
    with pytest.raises(ValueError, match="cannot revert"):
        uribo.revert_patch(bytearray(16))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.__setitem__(slice(uribo.ADDR_SLOT_THRESH, uribo.ADDR_SLOT_THRESH + 4), b"\0" * 4),
        lambda d: d.__setitem__(slice(uribo.ADDR_SLOT_THRESH + 4, uribo.ADDR_SLOT_THRESH + 8), b"\0" * 4),
        lambda d: uribo._put_s32(d, uribo._table_off(0), 1),
        lambda d: uribo._put_s32(d, uribo._table_off(24), 1),
    ],
)
def test_password_uribo_is_vanilla_checks(mutate):
    data = _uribo_vanilla()
    mutate(data)
    assert not uribo.is_vanilla(data)


def test_password_uribo_adds_src_to_path(monkeypatch):
    from conftest import SRC, load_module

    monkeypatch.setattr("sys.path", [p for p in __import__("sys").path if Path(p).resolve() != SRC])
    mod = load_module("patch_password_uribo_fresh", SRC / "patch_password_uribo.py")
    assert str(SRC) in __import__("sys").path
    assert mod.N_SLOTS == uribo.N_SLOTS


def test_password_uribo_is_patched_checks():
    data = _uribo_vanilla()
    uribo.apply_patch(data)
    bge = data[uribo.ADDR_SLOT_THRESH + 4 : uribo.ADDR_SLOT_THRESH + 8]
    data[uribo.ADDR_SLOT_THRESH + 4 : uribo.ADDR_SLOT_THRESH + 8] = b"\0" * 4
    assert not uribo.is_patched(data)
    data[uribo.ADDR_SLOT_THRESH + 4 : uribo.ADDR_SLOT_THRESH + 8] = bge
    assert uribo.is_patched(data)
    assert not uribo.is_patched(bytearray(16))
