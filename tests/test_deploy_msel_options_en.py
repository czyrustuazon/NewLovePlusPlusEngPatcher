"""Options / clock title chrome @ NCommonMSel pkg 5245 (exact-zlib splice)."""

from __future__ import annotations

import random
from pathlib import Path

import fake_img as fi
from conftest import TOOLS, load_module
from darcutil import DarcArchive

msel = load_module("deploy_msel_options_en", TOOLS / "deploy_msel_options_en.py")
NOTE = b"untouched note"
# splice_arc verifies every ARC against the patched stream — only one ARC.
SIBLING = "sibling.bin"


def _stems() -> list[str]:
    stems = [Path(base).stem for base, _en in msel.LABELS]
    stems.append(Path(msel.PLATE_PASSWORD).stem)
    return stems


def _options_pkg() -> bytes:
    rng = random.Random(5245)
    files = {}
    for stem in _stems():
        # A8 (fmt 1): 1 bpp on pot canvas; noise keeps zlib roomy.
        pix = rng.randbytes(64 * 64)
        files[f"timg/{stem}.bclim"] = fi.bclim(8, 8, 1, pixels=pix)
    return fi.package(
        [
            ("NCommonMSel.arc", fi.darc(files)),
            (SIBLING, NOTE, b"TXT ", False),
        ]
    )


def _bclims(img: Path, tmp: Path) -> dict[str, bytes]:
    arc = DarcArchive(
        fi.read_element(fi.read_package(img, msel.PKG), "NCommonMSel.arc", tmp)
    )
    return {f.name: arc.extract_file(f) for f in arc.files}


def test_labels_cover_options_and_clock_titles():
    texts = [en for _base, en in msel.LABELS]
    assert "Options" in texts
    assert "3DS System Clock" in texts
    assert msel.PKG == 5245


def test_main_splices_options_pkg(tmp_path: Path, monkeypatch):
    fi.use_paths(monkeypatch, tmp_path, msel)
    img = tmp_path / "img.bin"
    img.write_bytes(fi.img({msel.PKG: _options_pkg()}))
    monkeypatch.setattr(msel, "MOD_IMG", img)
    monkeypatch.setattr(msel, "VANILLA", img)
    monkeypatch.setattr(msel, "IMG_DATA", tmp_path / "img_data")
    monkeypatch.setattr(msel, "AZAHAR_INSTANCES", tmp_path / "azahar_instances")
    monkeypatch.setattr(msel.sys, "argv", ["deploy_msel_options_en.py"])

    before = _bclims(img, tmp_path)
    before_sibling = fi.read_element(fi.read_package(img, msel.PKG), SIBLING, tmp_path)
    target = f"timg/{Path(msel.LABELS[0][0]).stem}.bclim"
    marker = b"\x5a" * 32

    def _patch_arc(vanilla_arc: bytes, tmp: Path, cmp_len: int) -> bytes:
        darc = DarcArchive(bytearray(vanilla_arc))
        ent = darc.find(target) or darc.find(Path(target).name)
        assert ent is not None
        raw = bytearray(darc.extract_file(ent))
        raw[0 : len(marker)] = marker
        darc.replace_same_size(ent, bytes(raw))
        return bytes(darc.data)

    monkeypatch.setattr(msel, "patch_arc", _patch_arc)
    monkeypatch.setattr(msel, "add_password_input_plate", lambda arc, tmp, cmp_len: arc)

    msel.main()

    after = _bclims(img, tmp_path)
    assert after[target] != before[target]
    assert after[target].startswith(marker)
    assert (
        fi.read_element(fi.read_package(img, msel.PKG), SIBLING, tmp_path)
        == before_sibling
    )
