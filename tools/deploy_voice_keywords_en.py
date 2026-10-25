#!/usr/bin/env python3
"""Love Plus mode voice-hint bubbles read in romaji (Keyword pkg 4073).

The bubbles that float around the heroine while the mic is open (ヒマだね,
遊ぼう, あのさ, お話しよう…) are not TRB text. They are NUL-separated UTF-8
lists in img.bin package **4073**:

  keyword_stringu_{0,1,2}.lmb   bubble text, Manaka / Rinko / Nene
  keyword_strings_{0,1,2}.lmb   Shift-JIS katakana the recognizer listens for
  keyword_category_stringu.lmb  answer-hint bubbles (not index-parallel)

``stringu_N[i]`` is the bubble for ``strings_N[i]``. The recognizer only hears
Japanese, so each bubble becomes the romaji of its own row's reading
(``assets/voice_keywords/romaji.json``) plus the bubble's punctuation: what to
say, not what it means. ``""`` and ``NULL`` rows (alternate readings with no
bubble) and Latin bubbles (``I LOVE YOU``, ``RPG``) are kept.

Loaders ``0x1F98F0`` (stringu) and ``0x1F9D58`` (category) count NULs over
the whole resource, allocate that many pointers, then index by ordinal. The
count is not stored. Rows keep their order; the bytes romaji saves go into
one spaces row after the last, so each table keeps its vanilla length: no
dec_len, package layout or idx change. The UTF-8 walker has no 4-byte case
(a lead byte >= 0xF0 never advances), so text stays below U+10000.

  python tools/deploy_voice_keywords_en.py
"""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from exact_zlib import compress_exact_empty_blocks  # noqa: E402
from img import FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    iter_deploy_targets,
    maybe_backup_img,
    resolve_img_paths,
)

MOD_IMG, _VANILLA = resolve_img_paths()

PKG = 4073
HEROINE_TABLES = {
    f"keyword_stringu_{n}.lmb": f"keyword_strings_{n}.lmb" for n in range(3)
}
CATEGORY_TABLE = "keyword_category_stringu.lmb"
ROMAJI_JSON = ROOT / "assets" / "voice_keywords" / "romaji.json"
OUT = ROOT / "out" / "voice_keywords_en"
NO_BUBBLE = ("", "NULL")

_KANA = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヰ": "i", "ヱ": "e", "ヲ": "o", "ン": "n", "ヴ": "vu",
}
_SMALL_Y = {"ャ": "a", "ュ": "u", "ョ": "o"}
_SMALL_V = {"ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o"}
# Consonant a small vowel attaches to: ティ -> ti, ウィ -> wi, イェ -> ye.
_SMALL_V_STEM = {"ウ": "w", "イ": "y", "ヴ": "v", "テ": "t", "デ": "d", "ト": "t", "ド": "d"}

# Bubble punctuation carried onto the romaji (trailing run only).
_PUNCT = {"？": "?", "！": "!", "♪": "♪", "…": "...", "。": ".", "～": "~"}
_FULLWIDTH = str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)})
_JP = re.compile(r"[぀-ヿ㐀-鿿]")


def romanize(kana: str) -> str:
    """Katakana reading -> lowercase romaji, no spaces. ー repeats the vowel
    (マーナカ -> maanaka), ッ doubles the next consonant, ン before a vowel
    or y is n'. Long vowels stay spelled out (ou, ei) so they read aloud."""
    syl: list[str] = []
    i = 0
    while i < len(kana):
        c = kana[i]
        nxt = kana[i + 1] if i + 1 < len(kana) else ""
        if c in ("ッ", "ー"):
            syl.append(c)
        elif c in _KANA and nxt in _SMALL_Y and c not in "アイウエオヤユヨワン":
            stem = _KANA[c][:-1]  # キ -> k, シ -> sh, チ -> ch, ジ -> j
            syl.append(stem + ("" if stem.endswith(("sh", "ch", "j")) else "y") + _SMALL_Y[nxt])
            i += 1
        elif c in _KANA and nxt in _SMALL_V:
            base = _KANA[c]
            if base[-1] == _SMALL_V[nxt]:
                syl.append(base + _SMALL_V[nxt])  # ネェ -> nee
            else:
                stem = _SMALL_V_STEM.get(c, base[:-1] if len(base) > 1 else base)
                syl.append(stem + _SMALL_V[nxt])  # ファ -> fa, シェ -> she
            i += 1
        elif c in _SMALL_V:
            syl.append(_SMALL_V[c])
        elif c in _KANA:
            syl.append(_KANA[c])
        else:
            raise ValueError(f"not katakana: {kana!r}")
        i += 1
    out = ""
    for k, part in enumerate(syl):
        if part == "ー":
            out += next((ch for ch in reversed(out) if ch in "aiueo"), "")
        elif part == "ッ":
            nxt = next((p for p in syl[k + 1 :] if p not in ("ッ", "ー")), "")
            if nxt[:1] and nxt[0] not in "aiueon":
                out += "t" if nxt.startswith("ch") else nxt[0]
        else:
            if out.endswith("n") and syl[k - 1] == "n" and part[0] in "aiueoy":
                out += "'"
            out += part
    return out


def _letters(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def spells_reading(romaji: str, kana: str) -> bool:
    """True if ``romaji`` spells ``kana`` letter for letter, allowing the
    particles wa / e / o for ハ / ヘ / ヲ written as their own word."""
    want = _letters(romanize(kana))
    words = re.findall(r"[A-Za-z']+|[^A-Za-z']+", romaji)
    swaps = {"wa": "ha", "e": "he"}
    idx = [i for i, w in enumerate(words) if w.lower() in swaps]
    for mask in range(1 << len(idx)):
        trial = list(words)
        for bit, i in enumerate(idx):
            if mask >> bit & 1:
                trial[i] = swaps[trial[i].lower()]
        if _letters("".join(trial)) == want:
            return True
    return False


def bubble_text(display: str, romaji: str) -> str:
    """Sentence-case romaji plus the bubble's trailing punctuation."""
    tail = re.search(r"[？！♪…。～]*$", display).group()
    suffix = re.sub(r"(\.\.\.)+", "...", "".join(_PUNCT[c] for c in tail))
    return romaji[:1].upper() + romaji[1:] + suffix


def _split(blob: bytes, encoding: str) -> list[str]:
    rows = blob.split(b"\0")
    if rows[-1] != b"":
        raise ValueError("table does not end in NUL")
    return [r.decode(encoding) for r in rows[:-1]]


def _join(rows: list[str], size: int, name: str) -> bytes:
    body = b"".join(r.encode("utf-8") + b"\0" for r in rows)
    if len(body) > size:
        raise ValueError(f"{name}: {len(body)} bytes > vanilla {size}")
    if any(b >= 0xF0 for b in body):
        raise ValueError(f"{name}: 4-byte UTF-8 hangs the game's walker")
    pad = size - len(body)
    # One spaces row past the last real row, NUL-ended: the walker would
    # store a pointer past its array for bytes after the final NUL.
    return body + (b" " * (pad - 1) + b"\0" if pad else b"")


def load_romaji(path: Path = ROMAJI_JSON) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_heroine_table(stringu: bytes, strings: bytes, readings: dict[str, str], name: str) -> bytes:
    shown = _split(stringu, "utf-8")
    heard = _split(strings, "cp932")
    if len(shown) != len(heard):
        raise ValueError(f"{name}: {len(shown)} bubbles vs {len(heard)} readings")
    out = []
    for display, kana in zip(shown, heard):
        if display in NO_BUBBLE or not _JP.search(display):
            out.append(display.translate(_FULLWIDTH))
            continue
        if kana not in readings:
            raise KeyError(f"{name}: no romaji for {kana} ({display})")
        out.append(bubble_text(display, readings[kana]))
    return _join(out, len(stringu), name)


def build_category_table(stringu: bytes, category: dict[str, str]) -> bytes:
    out = []
    for display in _split(stringu, "utf-8"):
        if display in NO_BUBBLE or not _JP.search(display):
            out.append(display.translate(_FULLWIDTH))
            continue
        if display not in category:
            raise KeyError(f"{CATEGORY_TABLE}: no romaji for {display}")
        out.append(bubble_text(display, category[display]))
    return _join(out, len(stringu), CATEGORY_TABLE)


def build_tables(entries: dict[str, bytes], romaji: dict[str, dict[str, str]]) -> dict[str, bytes]:
    """Vanilla LMB blobs by name -> romaji LMB blobs (same lengths)."""
    built = {
        u: build_heroine_table(entries[u], entries[s], romaji["readings"], u)
        for u, s in HEROINE_TABLES.items()
    }
    built[CATEGORY_TABLE] = build_category_table(entries[CATEGORY_TABLE], romaji["category"])
    return built


def _pkg_bytes(img_path: Path) -> bytes:
    img = ImgBin(str(img_path))
    try:
        img.parse(False)
        ent = img.entries[PKG]
        if ent is None:
            raise SystemExit(f"pkg {PKG} missing in {img_path}")
        return ent.fw.read()
    finally:
        img.fh.close()


def _entries(pkg_path: Path) -> dict[str, bytes]:
    pkg = Package(FileWindow(str(pkg_path)), 0)
    pkg.parse(False)
    return {e.fn: e.read() for e in pkg.entries}


def exact_slot(data: bytes, slot_len: int) -> tuple[bytes, bytes]:
    """``(table, zlib stream of exactly slot_len)``.

    Empty-block padding only reaches some lengths, and the shared gap-tune
    rewrites zero runs, which here are rows. Instead turn trailing spaces of
    the spare row into ``-`` until a stream lands on the slot.
    """
    m = re.search(rb" *\0\Z", data)
    keep = m.end() - 1
    for salt in range(keep - m.start() + 1):
        table = data[: keep - salt] + b"-" * salt + b"\0"
        slot = compress_exact_empty_blocks(table, slot_len)
        if slot is not None:
            return table, slot
    raise SystemExit(f"no exact zlib stream of {slot_len} bytes")


def splice_tables(pkg_raw: bytes, built: dict[str, bytes], names: list[str]) -> bytes:
    """Recompress each table into its own vanilla zlib slot. ``built`` gets
    the tables as stored (spare-row filler may change)."""
    blob = bytearray(pkg_raw)
    cnt = struct.unpack_from("=6sH", blob, 0)[1]
    for i, name in enumerate(names[:cnt]):
        if name not in built:
            continue
        off = Package.ENTRY_SIZE + i * Package.ENTRY_SIZE
        _typ, dec_len, _do, _fl, is_cmp, cmp_len, cmp_off = Package.parse_entry(
            bytes(blob[off : off + Package.ENTRY_SIZE])
        )
        data = built[name]
        if not is_cmp or len(data) != dec_len:
            raise SystemExit(f"{name}: cmp={is_cmp} dec {len(data)}/{dec_len}")
        built[name], slot = exact_slot(data, cmp_len)
        blob[cmp_off : cmp_off + cmp_len] = slot
        print(f"  {name}: slot {cmp_len}", flush=True)
    return bytes(blob)


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    if not _VANILLA.is_file():
        raise SystemExit(f"missing vanilla {_VANILLA}")
    bak = maybe_backup_img(MOD_IMG, "voice_keywords")
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    vanilla_pkg = pkg_dir / f"vanilla_{PKG:04d}"
    vanilla_pkg.write_bytes(_pkg_bytes(_VANILLA))
    vanilla = _entries(vanilla_pkg)
    built = build_tables(vanilla, load_romaji())

    src = pkg_dir / f"{PKG:04d}"
    src.write_bytes(_pkg_bytes(MOD_IMG))
    current = _entries(src)
    if list(current) != list(vanilla):
        raise SystemExit(f"pkg {PKG} entries differ from vanilla")
    for name, data in current.items():
        if name not in built and data != vanilla[name]:
            raise SystemExit(f"pkg {PKG} {name} is not vanilla")

    new_pkg = pkg_dir / f"new_{PKG:04d}"
    new_pkg.write_bytes(splice_tables(src.read_bytes(), built, list(vanilla)))
    after = _entries(new_pkg)
    for name, data in after.items():
        if data != built.get(name, vanilla[name]):
            raise SystemExit(f"round-trip mismatch {name}")

    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print("spliced", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed romaji voice-hint bubbles ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
