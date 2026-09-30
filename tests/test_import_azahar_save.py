"""Import Checkpoint/Azahar NLPP title saves (tools/import_azahar_save.py)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from conftest import ROOT, TOOLS, load_module

mod = load_module("import_azahar_save", TOOLS / "import_azahar_save.py")

ID0 = "a" * 32
ID1 = "b" * 32


def _pack(root: Path, name: str = "nene") -> Path:
    pack = root / name
    slot = pack / "00000001"
    slot.mkdir(parents=True)
    (slot / "savedata0").write_bytes(b"LP2H-nene")
    (slot / "savedata1").write_bytes(b"slot-b")
    (slot / "savedata18.bak").write_bytes(b"ignore-me")
    (pack / "00000001.metadata").write_bytes(b"M" * 16)
    (pack / "manifest.json").write_text(
        '{"id":"%s","heroine":"Nene"}\n' % name, encoding="utf-8"
    )
    return pack


def _user(root: Path) -> Path:
    user = root / "Azahar"
    (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "extdata"
        / "00000000"
        / "00000f4e"
        / "user"
    ).mkdir(parents=True)
    return user


def test_list_and_install_named_pack(tmp_path: Path):
    saves = tmp_path / "saves"
    _pack(saves)
    user = _user(tmp_path)
    dest_slot = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "title"
        / "00040000"
        / "000f4e00"
        / "data"
        / "00000001"
    )
    dest_slot.mkdir(parents=True)
    (dest_slot / "savedata0").write_bytes(b"old-save")

    assert mod.main(["--list", "--saves-root", str(saves)]) == 0
    assert (
        mod.main(
            [
                "--pack",
                "nene",
                "--saves-root",
                str(saves),
                "--user-dir",
                str(user),
                "--backup-root",
                str(tmp_path / "backups"),
            ]
        )
        == 0
    )
    assert (dest_slot / "savedata0").read_bytes() == b"LP2H-nene"
    assert (dest_slot / "savedata1").read_bytes() == b"slot-b"
    assert not (dest_slot / "savedata18.bak").exists()
    meta = dest_slot.parent / "00000001.metadata"
    assert meta.read_bytes() == b"M" * 16
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / dest_slot.relative_to(user) / "savedata0").read_bytes() == (
        b"old-save"
    )


def test_import_zip_creates_zero_id_tree(tmp_path: Path):
    zpath = tmp_path / "nene savefile!(1).zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("nene savefile!/00000001/savedata0", b"from-zip")
    user = tmp_path / "empty-user"
    user.mkdir()
    assert (
        mod.main(
            [
                "--zip",
                str(zpath),
                "--user-dir",
                str(user),
                "--no-backup",
            ]
        )
        == 0
    )
    dest = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ("0" * 32)
        / ("0" * 32)
        / "title"
        / "00040000"
        / "000f4e00"
        / "data"
        / "00000001"
        / "savedata0"
    )
    assert dest.read_bytes() == b"from-zip"


def test_two_user_dirs_do_not_collide_on_backup(tmp_path: Path):
    saves = tmp_path / "saves"
    _pack(saves)
    backups = tmp_path / "backups"
    users = []
    for name in ("a", "b"):
        user = _user(tmp_path / name)
        slot = (
            user
            / "sdmc"
            / "Nintendo 3DS"
            / ID0
            / ID1
            / "title"
            / "00040000"
            / "000f4e00"
            / "data"
            / "00000001"
        )
        slot.mkdir(parents=True)
        (slot / "savedata0").write_bytes(name.encode())
        users.append((user, slot))
    for user, _slot in users:
        assert (
            mod.main(
                [
                    "--pack",
                    "nene",
                    "--saves-root",
                    str(saves),
                    "--user-dir",
                    str(user),
                    "--backup-root",
                    str(backups),
                ]
            )
            == 0
        )
    assert len(list(backups.iterdir())) == 2
    for inst, slot in users:
        assert (slot / "savedata0").read_bytes() == b"LP2H-nene"


def test_repo_nene_pack_has_lp2h_header():
    pack = ROOT / "ab_test" / "saves" / "nene"
    if not pack.is_dir():
        pytest.skip("local ab_test/saves/nene pack is gitignored")
    slot = mod.find_save_slot(pack)
    files = mod.iter_savedata_files(slot)
    assert len(files) == 81
    magic = (slot / "savedata0").read_bytes()[:4]
    assert magic == b"LP2H"
    meta = pack / "00000001.metadata"
    assert meta.is_file() and meta.stat().st_size == 16
