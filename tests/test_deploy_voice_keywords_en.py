"""Love Plus mode voice-hint bubbles read in romaji (Keyword pkg 4073)."""

from __future__ import annotations

import re

import pytest

from conftest import TOOLS, load_module

vk = load_module("deploy_voice_keywords_en", TOOLS / "deploy_voice_keywords_en.py")


def _sjis(rows: list[str]) -> bytes:
    return b"".join(r.encode("cp932") + b"\0" for r in rows)


def _utf8(rows: list[str]) -> bytes:
    return b"".join(r.encode("utf-8") + b"\0" for r in rows)


@pytest.mark.parametrize(
    ("kana", "romaji"),
    [
        ("ヒマダネ", "himadane"),
        ("マーナカ", "maanaka"),  # ー repeats the vowel
        ("アソボウ", "asobou"),  # long vowels stay spelled out
        ("ドッチ", "dotchi"),  # ッ before ch
        ("ショッピング", "shoppingu"),
        ("キンイロ", "kin'iro"),  # ン before a vowel
        ("ジュンアイ", "jun'ai"),
        ("コメディ", "komedi"),  # small vowel: stem table
        ("ファミレス", "famiresu"),  # small vowel: consonant stem
        ("ジェイポップ", "jeipoppu"),
        ("ネェ", "nee"),  # same vowel: long
        ("オァ", "oa"),  # vowel-only base
        ("ァ", "a"),
        ("ー", ""),
        ("アッ", "a"),  # trailing ッ
        ("アッア", "aa"),  # ッ before a vowel
        ("キャ", "kya"),
        ("チョ", "cho"),
    ],
)
def test_romanize(kana, romaji):
    assert vk.romanize(kana) == romaji


def test_romanize_rejects_non_katakana():
    with pytest.raises(ValueError, match="not katakana"):
        vk.romanize("ひま")


def test_spells_reading_allows_particles_only():
    assert vk.spells_reading("aki wa suki", "アキハスキ")
    assert vk.spells_reading("koucha-ha", "コウチャハ")
    assert vk.spells_reading("hon o yomu", "ホンヲヨム")
    assert vk.spells_reading("Ima, nanji", "イマナンジ")
    assert not vk.spells_reading("aki ga suki", "アキハスキ")
    assert not vk.spells_reading("akiwasuki", "アキハスキ")  # wa only as a word


def test_romaji_table_spells_every_reading():
    table = vk.load_romaji()
    assert table["readings"], "empty romaji table"
    for kana, romaji in table["readings"].items():
        assert vk.spells_reading(romaji, kana), (kana, romaji)
    for romaji in [*table["readings"].values(), *table["category"].values()]:
        # bubble_text adds the bubble's own punctuation; ASCII keeps the
        # game's UTF-8 walker (no 4-byte case) and the bubble font safe.
        assert romaji == romaji.strip() and not re.search(r"[?!~♪]$", romaji), romaji
        assert romaji.isascii(), romaji


def test_bubble_text_keeps_punctuation():
    assert vk.bubble_text("好きですか？", "suki desu ka") == "Suki desu ka?"
    assert vk.bubble_text("春だね♪", "haru da ne") == "Haru da ne♪"
    assert vk.bubble_text("そりゃまぁ……", "sorya maa") == "Sorya maa..."
    assert vk.bubble_text("コラ！", "kora") == "Kora!"
    assert vk.bubble_text("ヒマだね", "hima da ne") == "Hima da ne"


def test_heroine_table_keeps_rows_and_length():
    shown = ["", "ヒマだね", "NULL", "I LOVE YOU", "Ｊ", "好きですか？", ""]
    heard = ["ネエ", "ヒマダネ", "ヒマ", "アイラブユー", "ジェイ", "スキデスカ", "スキ"]
    stringu = _utf8(shown)
    out = vk.build_heroine_table(stringu, _sjis(heard), {"ヒマダネ": "hima da ne", "スキデスカ": "suki desu ka"}, "t")
    assert len(out) == len(stringu)
    rows = vk._split(out, "utf-8")
    assert rows[: len(shown)] == ["", "Hima da ne", "NULL", "I LOVE YOU", "J", "Suki desu ka?", ""]
    # Saved bytes go into one spaces row past the last real row.
    assert len(rows) == len(shown) + 1 and rows[-1].strip() == ""


def test_join_exact_fit_adds_no_row():
    assert vk._join(["ab"], 3, "t") == b"ab\0"


def test_table_errors():
    with pytest.raises(ValueError, match="does not end in NUL"):
        vk._split(b"abc", "utf-8")
    with pytest.raises(ValueError, match="bubbles vs"):
        vk.build_heroine_table(_utf8(["ア"]), _sjis(["ア", "イ"]), {}, "t")
    with pytest.raises(KeyError, match="no romaji"):
        vk.build_heroine_table(_utf8(["ア"]), _sjis(["ア"]), {}, "t")
    with pytest.raises(ValueError, match="> vanilla"):
        vk.build_heroine_table(_utf8(["ア"]), _sjis(["ア"]), {"ア": "aaaaa"}, "t")
    with pytest.raises(ValueError, match="4-byte"):
        vk._join(["\U0001f600"], 10, "t")
    with pytest.raises(KeyError, match="no romaji"):
        vk.build_category_table(_utf8(["はい"]), {})


def test_category_table():
    out = vk.build_category_table(_utf8(["はい", "NULL", "10", "楽しみ♪"]), {"はい": "hai", "楽しみ♪": "tanoshimi"})
    assert vk._split(out, "utf-8")[:4] == ["Hai", "NULL", "10", "Tanoshimi♪"]


def _tables() -> dict[str, bytes]:
    """Vanilla-shaped pkg 4073 contents. EXTRA real readings (shown as their
    katakana) make the tables compress like the game's, so each zlib slot
    has room for an empty-block stream."""
    table = vk.load_romaji()
    extra = list(table["readings"])[:EXTRA]
    tables = {
        "conditionvoice_0.lmb": b"\x01\x02\x03",
        CATEGORY: _utf8(["はい", "NULL", "そうだね", *table["category"]]),
    }
    for n, (u, s) in enumerate(vk.HEROINE_TABLES.items()):
        tables[s] = _sjis(["ネエ", "ヒマダネ", "オハナシシヨウ", "スキンシップハスキ", *extra])
        tables[u] = _utf8(["", "ヒマだね", "お話しよう" + "♪" * n, "スキンシップは好き？", *extra])
    return tables


EXTRA = 200


CATEGORY = vk.CATEGORY_TABLE


def _env(tmp_path, monkeypatch, *, tables=None):
    import fake_img as fi

    fi.use_paths(monkeypatch, tmp_path, vk)
    monkeypatch.setattr(vk, "OUT", tmp_path / "out")
    tables = tables or _tables()
    pkg = fi.package([(name, data, b"LMB ", True) for name, data in tables.items()])
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(fi.img({vk.PKG: pkg}))
    mod = tmp_path / "release" / "bake_img.bin"
    mod.parent.mkdir(parents=True)
    mod.write_bytes(vanilla.read_bytes())
    monkeypatch.setattr(vk, "MOD_IMG", mod)
    monkeypatch.setattr(vk, "_VANILLA", vanilla)
    return vanilla, mod


def test_main_writes_romaji_into_the_package(tmp_path, monkeypatch):
    import fake_img as fi

    _vanilla, mod = _env(tmp_path, monkeypatch)
    vk.main()
    pkg = fi.read_package(mod, vk.PKG)
    for n, u in enumerate(vk.HEROINE_TABLES):
        rows = vk._split(fi.read_element(pkg, u, tmp_path), "utf-8")
        assert rows[:4] == ["", "Hima da ne", "Ohanashi shiyou" + "♪" * n, "Sukinshippu wa suki?"]
        assert len(rows) == 4 + EXTRA + 1 and set(rows[-1]) <= {" ", "-"}
    cat = vk._split(fi.read_element(pkg, CATEGORY, tmp_path), "utf-8")
    assert cat[:3] == ["Hai", "NULL", "Sou da ne"]
    assert fi.read_element(pkg, "conditionvoice_0.lmb", tmp_path) == b"\x01\x02\x03"
    # Re-running over its own output is a no-op.
    before = mod.read_bytes()
    vk.main()
    assert mod.read_bytes() == before


def test_main_errors(tmp_path, monkeypatch):
    import fake_img as fi

    vanilla, mod = _env(tmp_path, monkeypatch)

    def fail(*_a):
        raise vk.PackError("grew")

    monkeypatch.setattr(vk, "splice_packages_into_img", fail)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        vk.main()

    real_splice = vk.splice_tables
    monkeypatch.setattr(vk, "splice_tables", lambda raw, built, names: raw)
    with pytest.raises(SystemExit, match="round-trip mismatch"):
        vk.main()
    monkeypatch.setattr(vk, "splice_tables", real_splice)

    other = _tables()
    other["conditionvoice_0.lmb"] = b"\x09"
    mod.write_bytes(fi.img({vk.PKG: fi.package([(k, v, b"LMB ", True) for k, v in other.items()])}))
    with pytest.raises(SystemExit, match="conditionvoice_0.lmb is not vanilla"):
        vk.main()

    del other["conditionvoice_0.lmb"]
    mod.write_bytes(fi.img({vk.PKG: fi.package([(k, v, b"LMB ", True) for k, v in other.items()])}))
    with pytest.raises(SystemExit, match="entries differ"):
        vk.main()

    mod.write_bytes(fi.img({vk.PKG - 1: fi.package([("x.lmb", b"x", b"LMB ", True)])}, count=vk.PKG + 1))
    with pytest.raises(SystemExit, match="missing in"):
        vk.main()

    monkeypatch.setattr(vk, "_VANILLA", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing vanilla"):
        vk.main()
    monkeypatch.setattr(vk, "MOD_IMG", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing"):
        vk.main()


def test_splice_tables_rejects_stored_entries():
    import fake_img as fi

    raw = fi.package([("a.lmb", b"a\0", b"LMB ", False), ("b.lmb", b"b\0", b"LMB ", True)])
    with pytest.raises(SystemExit, match="cmp=0"):
        vk.splice_tables(raw, {"a.lmb": b"x\0"}, ["a.lmb", "b.lmb", "extra.lmb"])


def test_exact_slot_salts_only_the_spare_row(monkeypatch):
    tried = []

    def empty_blocks(table, n):
        tried.append(table)
        return b"slot" if len(tried) == 3 else None

    monkeypatch.setattr(vk, "compress_exact_empty_blocks", empty_blocks)
    assert vk.exact_slot(b"Ab\0   \0", 9) == (b"Ab\0 --\0", b"slot")
    assert tried == [b"Ab\0   \0", b"Ab\0  -\0", b"Ab\0 --\0"]

    monkeypatch.setattr(vk, "compress_exact_empty_blocks", lambda table, n: None)
    with pytest.raises(SystemExit, match="no exact zlib stream of 9 bytes"):
        vk.exact_slot(b"Ab\0", 9)


def test_bake_runs_voice_keywords_deploy():
    rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
    assert "deploy_voice_keywords_en.py" in rebuild.DEPLOY_SCRIPTS
    for name in rebuild.DEPLOY_SCRIPTS:
        if name == "deploy_voice_keywords_en.py":
            continue
        text = (TOOLS / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*PKG\s*=\s*4073\b", text, re.MULTILINE), name


def _pkg4073(img_path) -> dict[str, bytes]:
    import fake_img as fi

    pkg = fi.read_package(img_path, vk.PKG)
    from img import FileWindow, Package
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pkg"
        path.write_bytes(pkg)
        p = Package(FileWindow(str(path)), 0)
        p.parse(False)
        return {e.fn: e.read() for e in p.entries}


@pytest.mark.local_data
def test_vanilla_tables_all_have_romaji():
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    entries = _pkg4073(vanilla)
    built = vk.build_tables(entries, vk.load_romaji())
    for name, blob in built.items():
        assert len(blob) == len(entries[name])
        old, new = vk._split(entries[name], "utf-8"), vk._split(blob, "utf-8")
        assert len(new) - len(old) in (0, 1)
        assert not any(vk._JP.search(r) for r in new), name


@pytest.mark.local_data
def test_release_bake_has_romaji_bubbles():
    """Stale-bake guard: deploy-a ships release/bake_img.bin."""
    from nlpp_paths import BAKE_IMG

    if not BAKE_IMG.is_file():
        pytest.skip("no release/bake_img.bin")
    rows = vk._split(_pkg4073(BAKE_IMG)["keyword_stringu_0.lmb"], "utf-8")
    assert "Hima da ne" in rows and "ヒマだね" not in rows
