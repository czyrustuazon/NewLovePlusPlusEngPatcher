"""Azahar extra-data backup / restore (tools/restore_azahar_extdata.py)."""

from __future__ import annotations

from pathlib import Path

from conftest import TOOLS, load_module

mod = load_module("restore_azahar_extdata", TOOLS / "restore_azahar_extdata.py")

ID0 = "a" * 32
ID1 = "b" * 32


def _fake_azahar(root: Path) -> Path:
    user = root / "Azahar"
    ext = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "extdata"
        / "00000000"
        / "00000f4e"
        / "user"
    )
    ext.mkdir(parents=True)
    (ext / "save.bin").write_bytes(b"life-data")
    boss = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "extdata"
        / "00000000"
        / "00000321"
        / "boss"
    )
    boss.mkdir(parents=True)
    (boss / "info.dat").write_bytes(b"spotpass")
    sd_save = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "title"
        / "00040000"
        / "000f4e00"
        / "data"
    )
    (sd_save / "00000001").mkdir(parents=True)
    (sd_save / "00000001.metadata").write_bytes(b"meta" * 4)
    (sd_save / "00000001" / "savedata0").write_bytes(b"sd-save")
    save = user / "nand" / "data" / ID0 / "title" / "00040000" / "000f4e00" / "data"
    save.mkdir(parents=True)
    (save / "00000001.sav").write_bytes(b"nand-save")
    other = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "extdata"
        / "00000000"
        / "0000abcd"
        / "user"
    )
    other.mkdir(parents=True)
    (other / "ignore.bin").write_bytes(b"not-nlpp")
    return user


def test_extdata_id_from_title():
    assert "00000f4e" in mod.EXTDATA_IDS
    assert "00000321" in mod.EXTDATA_IDS
    assert mod.UNIQUE_ID == 0xF4E


def test_discover_finds_nlpp_trees_only(tmp_path: Path):
    user = _fake_azahar(tmp_path)
    trees = mod.discover_nlpp_trees(user)
    rels = {p.relative_to(user).as_posix().lower() for p in trees}
    assert any(r.endswith("00000f4e") or "/00000f4e/" in r + "/" for r in rels)
    joined = " ".join(rels)
    assert "00000f4e" in joined
    assert "00000321" in joined
    assert "000f4e00" in joined
    assert any(r.endswith("title/00040000/000f4e00/data") for r in rels)
    assert "0000abcd" not in joined


def test_backup_and_restore_roundtrip(tmp_path: Path):
    user = _fake_azahar(tmp_path)
    dest = tmp_path / "snap"
    manifest = mod.backup_trees(user, dest)
    assert manifest["title_id"] == "00040000000F4E00"
    assert len(manifest["files"]) == 5

    save = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "extdata"
        / "00000000"
        / "00000f4e"
        / "user"
        / "save.bin"
    )
    save.write_bytes(b"wiped")
    nand = (
        user / "nand" / "data" / ID0 / "title" / "00040000" / "000f4e00" / "data"
        / "00000001.sav"
    )
    nand.unlink()

    n = mod.restore_trees(dest, user)
    assert n == 5
    assert save.read_bytes() == b"life-data"
    assert nand.read_bytes() == b"nand-save"
    sd = (
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
        / "savedata0"
    )
    assert sd.read_bytes() == b"sd-save"


def test_latest_backup_picks_newest_stamp(tmp_path: Path):
    root = tmp_path / "backups"
    older = root / "20260101_010101"
    newer = root / "20260913_120000"
    for folder in (older, newer):
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "not-a-backup").mkdir()
    assert mod.latest_backup(root) == newer


def test_backup_errors_when_nothing_found(tmp_path: Path):
    empty = tmp_path / "empty-azahar"
    empty.mkdir()
    try:
        mod.backup_trees(empty, tmp_path / "snap")
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "No NLPP extra data" in str(exc)


def test_cli_backup_restore(tmp_path: Path):
    user = _fake_azahar(tmp_path)
    root = tmp_path / "backups"
    assert (
        mod.main(
            [
                "backup",
                "--user-dir",
                str(user),
                "--backup-root",
                str(root),
                "--stamp",
                "t1",
            ]
        )
        == 0
    )
    save = (
        user
        / "sdmc"
        / "Nintendo 3DS"
        / ID0
        / ID1
        / "extdata"
        / "00000000"
        / "00000f4e"
        / "user"
        / "save.bin"
    )
    save.write_bytes(b"broken")
    assert (
        mod.main(
            [
                "restore",
                "--user-dir",
                str(user),
                "--backup-root",
                str(root),
            ]
        )
        == 0
    )
    assert save.read_bytes() == b"life-data"
