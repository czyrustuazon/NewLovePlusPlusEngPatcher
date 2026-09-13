"""HOME-menu SMDH / NCCH product-code helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

from conftest import SRC, load_module

smdh = load_module("smdh_meta", SRC / "smdh_meta.py")
patch_cia = load_module("patch_cia", SRC / "patch_cia.py")


def _blank_smdh() -> bytearray:
    buf = bytearray(smdh.SMDH_SIZE)
    buf[0:4] = smdh.SMDH_MAGIC
    # Japanese short title: ニューラブプラス＋
    jp = "ニューラブプラス＋".encode("utf-16le").ljust(smdh.SHORT_LEN, b"\x00")
    buf[smdh.TITLES_OFF : smdh.TITLES_OFF + smdh.SHORT_LEN] = jp
    buf[smdh.REGION_LOCK_OFF : smdh.REGION_LOCK_OFF + 4] = smdh.REGION_JAPAN.to_bytes(
        4, "little"
    )
    return buf


def _ncch_header(product: str = "CTR-P-BLPJ") -> bytes:
    buf = bytearray(0x200)
    buf[0x100:0x104] = b"NCCH"
    blob = product.encode("ascii").ljust(16, b"\x00")
    buf[0x150:0x160] = blob
    return bytes(buf)


def test_patch_smdh_english_titles_and_usa_region():
    patched = smdh.patch_smdh(bytes(_blank_smdh()), region_lock=smdh.REGION_USA)
    assert patched[:4] == smdh.SMDH_MAGIC
    assert smdh.smdh_short_title(patched, lang=0) == "New Love Plus+"
    assert smdh.smdh_short_title(patched, lang=1) == "New Love Plus+"
    assert smdh.smdh_region_lock(patched) == smdh.REGION_USA
    # icons / trailing bytes preserved (we only filled titles + region)
    assert patched[0x2060:] == bytes(_blank_smdh())[0x2060:]


def test_utf16_field_null_pads_and_truncates():
    field = smdh.utf16_field("New Love Plus+", 0x80)
    assert len(field) == 0x80
    assert field.startswith("New Love Plus+".encode("utf-16le"))
    assert field.endswith(b"\x00\x00")
    long = smdh.utf16_field("A" * 80, 8)
    assert len(long) == 8
    assert long == ("A" * 3).encode("utf-16le") + b"\x00\x00"


def test_ncch_product_code_j_to_e():
    raw = _ncch_header()
    assert smdh.read_ncch_product_code(raw) == "CTR-P-BLPJ"
    out = smdh.patch_ncch_product_code(raw, "CTR-P-BLPE")
    assert smdh.read_ncch_product_code(out) == "CTR-P-BLPE"
    assert out[0x100:0x104] == b"NCCH"


def test_ncch_header_without_rsa_prefix():
    buf = bytearray(0x100)
    buf[0:4] = b"NCCH"
    buf[0x50:0x60] = b"CTR-P-BLPJ".ljust(16, b"\x00")
    out = smdh.patch_ncch_product_code(bytes(buf), "CTR-P-BLPE")
    assert smdh.read_ncch_product_code(out) == "CTR-P-BLPE"


def test_resolve_region_aliases():
    lock, code, label = smdh.resolve_region("usa")
    assert lock == smdh.REGION_USA
    assert code == "CTR-P-BLPE"
    assert "North America" in label
    assert smdh.resolve_region("na")[0] == smdh.REGION_USA
    assert smdh.resolve_region("free")[0] == smdh.REGION_FREE
    assert smdh.resolve_region("europe")[1] == "CTR-P-BLPP"


def test_patch_icon_file(tmp_path: Path):
    icon = tmp_path / "icon.bin"
    icon.write_bytes(_blank_smdh())
    smdh.patch_icon_file(icon, region_lock=smdh.REGION_FREE)
    data = icon.read_bytes()
    assert smdh.smdh_short_title(data, 1) == "New Love Plus+"
    assert smdh.smdh_region_lock(data) == smdh.REGION_FREE


def test_find_exefs_icon_prefers_icon_bin(tmp_path: Path):
    (tmp_path / "icon.bin").write_bytes(b"x")
    assert smdh.find_exefs_icon(tmp_path).name == "icon.bin"


def test_summary_cia_meta_ok_by_default(tmp_path: Path, monkeypatch):
    bake = tmp_path / "bake.bin"
    bake.write_bytes(b"gold")
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", bake)
    lines = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=bake,
        layered_img=bake,
        layeredfs_out=None,
        romfs_overlay=None,
        args=argparse.Namespace(
            no_images=False,
            with_images=True,
            inject_code=None,
            patch_code=False,
            skip_name_patches=False,
            skip_hash=False,
            cia_region="usa",
        ),
        eng_patch=True,
    )
    text = "\n".join(lines)
    assert "[OK]" in text and "CIA HOME-menu metadata" in text
    assert "New Love Plus+" in text
    assert "USA (North America)" in text
    assert "CTR-P-BLPE" in text


def test_summary_cia_meta_skipped(tmp_path: Path, monkeypatch):
    bake = tmp_path / "bake.bin"
    bake.write_bytes(b"gold")
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", bake)
    lines = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=bake,
        layered_img=bake,
        layeredfs_out=None,
        romfs_overlay=None,
        args=argparse.Namespace(
            no_images=False,
            with_images=True,
            inject_code=None,
            patch_code=False,
            skip_name_patches=False,
            skip_hash=False,
            skip_cia_meta=True,
        ),
        eng_patch=True,
        layeredfs_only=False,
    )
    text = "\n".join(lines)
    assert "[SKIPPED]" in text and "--skip-cia-meta" in text


def test_parser_cia_region_defaults_to_usa():
    args = patch_cia.build_parser().parse_args(["--cia", "game.cia"])
    assert args.cia_region == "usa"
    assert args.skip_cia_meta is False
    args = patch_cia.build_parser().parse_args(
        ["--cia", "game.cia", "--cia-region", "free"]
    )
    assert args.cia_region == "free"
