"""Trip-mode voice-hint bubbles read in romaji (pkgs 5398 / 5438)."""

from __future__ import annotations

import struct

import pytest
from conftest import TOOLS, load_module

tk = load_module("deploy_trip_keywords_en", TOOLS / "deploy_trip_keywords_en.py")
vk = tk.vk

EXTRA = 120  # real readings, so the tables compress like the game's


def _rows(readings: list[str], bubbles: list[str]) -> tuple[bytes, bytes]:
    return (b"".join(r.encode("cp932") + b"\0" for r in readings),
            b"".join(b.encode("utf-8") + b"\0" for b in bubbles))


def day_trip(readings: list[str], bubbles: list[str], count: int | None = None) -> bytes:
    heard, shown = _rows(readings, bubbles)
    body = b"\x07" * 40  # stands in for the record sections
    heard_at = 4 + 12 * 4 + len(body)
    fields = [12, 1, 2, 2, 3, len(readings) if count is None else count, 52, 52, 52, 52, 52,
              heard_at, heard_at + len(heard)]
    return struct.pack("<13I", *fields) + body + heard + shown


def overnight(readings: list[str], bubbles: list[str]) -> bytes:
    heard, shown = _rows(readings, bubbles)
    return struct.pack("<6HI", len(readings), 38, 16, 14, 16, 0, 16 + len(heard)) + heard + shown


def _extra() -> tuple[list[str], list[str]]:
    readings = list(vk.load_romaji()["readings"])[:EXTRA]
    return readings, list(readings)  # katakana bubbles, like the overnight lists


def _tables() -> dict[str, bytes]:
    er, eb = _extra()
    tables = {}
    for n, name in enumerate(tk.DAY_TRIP):
        tables[name] = day_trip(["ネエネエ", "オハヨウ", "", "オーケー", *er],
                                ["ねえねえ", "おはよう" + "♪" * (n % 2), "", "ＯＫ", *eb])
    for name in tk.OVERNIGHT:
        tables[name] = overnight(["ネネサン", "アネガサキセンパイ", *er], ["ネネサン", "アネガサキセンパイ", *eb])
    return tables


def _packages(tables: dict[str, bytes]) -> dict[int, bytes]:
    import fake_img as fi

    day = [(n, b"", b"    ", False) for n in ("tripmode_keyword_atami.tmb",)]
    day += [("trip_00_OFF.texi", b"\x01" * 82, b"TEXI", False), ("trip_00_OFF.texi", b"\x02" * 64, b"TEX ", True)]
    day += [("tripmode_home_atami_ang.tmb", b"home", b"TMB ", True)]
    day += [(n, tables[n], b"TMB ", True) for n in tk.DAY_TRIP]
    night = [(n, tables[n], b"TMB ", True) for n in tk.OVERNIGHT]
    night += [("tripmode_overnight_voice.tmb", b"voice", b"TMB ", True)]
    return {5398: fi.package(day), 5438: fi.package(night)}


def _env(tmp_path, monkeypatch, tables=None):
    import fake_img as fi

    fi.use_paths(monkeypatch, tmp_path, tk)
    monkeypatch.setattr(tk, "OUT", tmp_path / "out")
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(fi.img(_packages(tables or _tables())))
    mod = tmp_path / "release" / "bake_img.bin"
    mod.parent.mkdir(parents=True)
    mod.write_bytes(vanilla.read_bytes())
    monkeypatch.setattr(tk, "MOD_IMG", mod)
    monkeypatch.setattr(tk, "_VANILLA", vanilla)
    return vanilla, mod


def test_layouts_and_rows():
    blob = day_trip(["ネエ", "オウ"], ["ねえ", "おう"])
    assert tk.layout(blob)[0] == 2
    assert tk.split_rows(blob, "d") == (["ネエ", "オウ"], ["ねえ", "おう"])
    night = overnight(["ネネ"], ["ネネ"])
    assert tk.layout(night) == (1, 16, 16 + len("ネネ".encode("cp932")) + 1)
    assert tk.split_rows(night + b"   -\0", "n") == (["ネネ"], ["ネネ"])  # spare row
    with pytest.raises(ValueError, match="header says 3"):
        tk.split_rows(day_trip(["ネエ"], ["ねえ"], count=3), "d")
    with pytest.raises(ValueError, match="2 bubbles"):
        tk.split_rows(night + b"x\0", "n")  # an extra row that is not filler


def test_build_table_keeps_length_and_rows():
    blob = day_trip(["ネエネエ", "", "オーケー", "オハヨウ"], ["ねえねえ", "", "ＯＫ", "おはよう♪"])
    readings = {"ネエネエ": "nee nee", "オハヨウ": "ohayou"}
    built = tk.build_table(blob, readings, "d")
    assert len(built) == len(blob)
    shown = tk.split_rows(built, "d")[1]
    assert shown == ["Nee nee", "", "OK", "Ohayou♪"]
    with pytest.raises(KeyError, match="no romaji for オハヨウ"):
        tk.build_table(blob, {"ネエネエ": "nee nee"}, "d")


def test_exact_slot_prefers_zopfli_then_salting(monkeypatch):
    monkeypatch.setattr(tk, "try_compress_to_slot", lambda data, n: b"z" * n)
    assert tk.exact_slot(b"Ab\0  \0", 4) == (b"Ab\0  \0", b"zzzz")
    monkeypatch.setattr(tk, "try_compress_to_slot", lambda data, n: None)
    monkeypatch.setattr(vk, "exact_slot", lambda data, n: (b"salted", b"slot"))
    assert tk.exact_slot(b"Ab\0  \0", 4) == (b"salted", b"slot")


def test_main_writes_romaji_into_both_packages(tmp_path, monkeypatch):
    import fake_img as fi

    _vanilla, mod = _env(tmp_path, monkeypatch)
    tk.main()
    day = fi.read_package(mod, 5398)
    for n, name in enumerate(tk.DAY_TRIP):
        shown = tk.split_rows(fi.read_element(day, name, tmp_path), name)[1]
        assert shown[:4] == ["Nee nee", "Ohayou" + "♪" * (n % 2), "", "OK"]
        assert not any(vk._JP.search(s) for s in shown)
    assert fi.read_element(day, "tripmode_home_atami_ang.tmb", tmp_path) == b"home"
    night = fi.read_package(mod, 5438)
    for name in tk.OVERNIGHT:
        shown = tk.split_rows(fi.read_element(night, name, tmp_path), name)[1]
        assert shown[:2] == ["Nene-san", "Anegasaki-senpai"]
    assert fi.read_element(night, "tripmode_overnight_voice.tmb", tmp_path) == b"voice"
    before = mod.read_bytes()
    tk.main()  # re-running over its own output is a no-op
    assert mod.read_bytes() == before


def test_main_errors(tmp_path, monkeypatch):
    import fake_img as fi

    _vanilla, mod = _env(tmp_path, monkeypatch)

    def fail(*_a):
        raise tk.PackError("grew")

    monkeypatch.setattr(tk, "splice_packages_into_img", fail)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        tk.main()

    real = tk.splice
    monkeypatch.setattr(tk, "splice", lambda raw, built, path: raw)
    with pytest.raises(SystemExit, match="round-trip mismatch"):
        tk.main()
    monkeypatch.setattr(tk, "splice", real)

    tables = _tables()
    pkgs = _packages(tables)
    night = [(n, tables[n], b"TMB ", True) for n in tk.OVERNIGHT] + [("tripmode_overnight_voice.tmb", b"edited", b"TMB ", True)]
    mod.write_bytes(fi.img({5398: pkgs[5398], 5438: fi.package(night)}))
    with pytest.raises(SystemExit, match="tripmode_overnight_voice.tmb is not vanilla"):
        tk.main()

    mod.write_bytes(fi.img({5398: pkgs[5398], 5438: fi.package(night[:-1])}))
    with pytest.raises(SystemExit, match="entries differ"):
        tk.main()

    mod.write_bytes(fi.img({5398: pkgs[5398]}, count=5439))
    with pytest.raises(SystemExit, match="pkg 5438 missing in"):
        tk.main()

    monkeypatch.setattr(tk, "_VANILLA", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing vanilla"):
        tk.main()
    monkeypatch.setattr(tk, "MOD_IMG", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing"):
        tk.main()


def test_splice_rejects_stored_entries(tmp_path):
    import fake_img as fi

    raw = fi.package([("a.tmb", b"a\0", b"TMB ", False), ("b.tmb", b"b\0", b"TMB ", True)])
    path = tmp_path / "p.pkg"
    path.write_bytes(raw)
    with pytest.raises(SystemExit, match="cmp=0"):
        tk.splice(raw, {"a.tmb": b"x\0"}, path)


def test_bake_runs_trip_keywords_deploy():
    rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_trip_keywords_en.py" in scripts
    assert scripts.index("deploy_trip_keywords_en.py") < scripts.index("deploy_cesa_en.py")


@pytest.mark.local_data
def test_vanilla_trip_tables_all_have_romaji(tmp_path):
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    romaji = vk.load_romaji()["readings"]
    for pkg, names in tk.PKGS.items():
        path = tmp_path / f"{pkg}.pkg"
        path.write_bytes(tk._pkg_bytes(vanilla, pkg))
        entries = tk._entries(path)
        for name in names:
            built = tk.build_table(entries[name], romaji, name)
            assert len(built) == len(entries[name])
            assert not any(vk._JP.search(s) for s in tk.split_rows(built, name)[1])
