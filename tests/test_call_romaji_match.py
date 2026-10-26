"""Romaji Called-name lookup blob (src/call_romaji_match.c), run in unicorn.

The compiled pieces are mapped at their real VAs. The TRB getter
(FUN_005c0d4c), the ID range table and the mode-1 exclusion table are faked,
so these tests need no game data. The local_data test runs the real romaji
dictionary from release/.
"""

from __future__ import annotations

import faulthandler
import hashlib
import shutil
import struct
import subprocess
import sys

import pytest

from conftest import ROOT, SRC, TOOLS, load_module

blob = load_module("call_romaji_match_blob", SRC / "call_romaji_match_blob.py")
unicorn = pytest.importorskip("unicorn")
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc  # noqa: E402
from unicorn.arm_const import (  # noqa: E402
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
)

VA = 0x100000
GET_STR = 0x006C0D4C
RANGES_VA = 0x007A484E
EXCLUDED_VA = 0x007A4986
STRINGS = 0x10000000
STACK_TOP = 0x20010000
OUT = 0x30000000
NAME = 0x30001000
RETURN = 0x40000000
REAL_RANGES = [(0, 957), (968, 1365), (1438, 2938), (2955, 3180), (4718, 4875), (4876, 4969), (5064, 5125)]


def _first_map(uc, address: int, size: int) -> None:
    """uc.mem_map with faulthandler paused.

    On Windows, unicorn 2.x's first mem_map on a new Uc starts the engine, which
    raises an access violation and catches it itself. faulthandler still dumps a
    "Windows fatal exception" stack for it, even though the test passes.
    """
    was_on = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        uc.mem_map(address, size)
    finally:
        if was_on:
            faulthandler.enable(file=sys.__stderr__)


class Matcher:
    """The blob in unicorn, with pack 0x7200 = readings (id -> str)."""

    def __init__(self, readings: dict[int, str], ranges=None, excluded=()):
        ranges = ranges or [(0, 99), (200, 210), (300, 300), (400, 400), (500, 500), (600, 600), (700, 700)]
        assert len(ranges) == 7
        excl = list(excluded) + [0xFFFF] * (23 - len(excluded))
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        _first_map(uc, 0x147000 + VA, 0x3000)
        for start, data in blob.PIECES:
            uc.mem_write(start + VA, data)
        uc.mem_map(0x7A4000, 0x1000)
        uc.mem_write(RANGES_VA, b"".join(struct.pack("<HH", lo, hi) for lo, hi in ranges))
        uc.mem_write(EXCLUDED_VA, struct.pack(f"<{len(excl)}H", *excl))
        uc.mem_map(GET_STR & ~0xFFF, 0x1000)
        uc.mem_write(GET_STR, bytes.fromhex("1eff2fe1"))  # bx lr
        uc.mem_map(STRINGS, 0x100000)
        self.ptr = {}
        at = STRINGS
        for sid, text in readings.items():
            raw = text.encode("utf-8") + b"\0"
            uc.mem_write(at, raw)
            self.ptr[sid] = at
            at += (len(raw) + 3) & ~3
        uc.mem_map(STACK_TOP - 0x10000, 0x10000)
        uc.mem_map(OUT, 0x2000)
        uc.mem_map(RETURN, 0x1000)
        self.calls = 0
        uc.hook_add(UC_HOOK_CODE, self._get_str, begin=GET_STR, end=GET_STR)

    def _get_str(self, uc, _addr, _size, _data):
        pack, slot, one = (uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        assert pack == 0x7200 and one == 1
        self.calls += 1
        uc.reg_write(UC_ARM_REG_R0, self.ptr.get(slot, 0))

    def _run(self, entry: str, name: str | bytes, regs: list[int]) -> int:
        uc = self.uc
        raw = name if isinstance(name, bytes) else name.encode("utf-8")
        uc.mem_write(NAME, raw + b"\0")
        uc.mem_write(OUT, b"\xAA" * 0x104)
        for reg, val in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), regs):
            uc.reg_write(reg, val & 0xFFFFFFFF)
        uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        uc.reg_write(UC_ARM_REG_LR, RETURN)
        uc.emu_start(blob.SYMBOLS[entry] + VA, RETURN, count=20_000_000)
        assert uc.reg_read(UC_ARM_REG_PC) == RETURN
        assert uc.reg_read(UC_ARM_REG_SP) == STACK_TOP
        return uc.reg_read(UC_ARM_REG_R0)

    def out(self) -> tuple[int, list[int]]:
        words = struct.unpack("<65i", self.uc.mem_read(OUT, 0x104))
        return words[0], list(words[1 : 1 + max(words[0], 1)])

    def exact(self, name, mode: int = 0) -> tuple[int, tuple[int, list[int]]]:
        ret = self._run("nlpp_call_exact", name, [NAME, mode, OUT])
        return ret, self.out()

    def suggest(self, name, mode: int = 0, flag: int = 0) -> list[int]:
        self._run("nlpp_call_list", name, [NAME, mode, flag, OUT])
        count, ids = self.out()
        return ids[:count]


DICT = {
    1: "Aki",
    2: "Akiko",
    3: "Akio",
    4: "Akira",
    5: "Akihiko",
    6: "Hōjō",
    7: "Shin'ichi",
    8: "Bob",
    9: "Kanako",
    10: "Nanako",
    200: "Aki",  # same reading under a second ID (582 / 3186 in pack 0x7200)
    300: "Manaka",
}


@pytest.fixture(scope="module")
def m() -> Matcher:
    return Matcher(DICT)


def test_exact_is_case_insensitive(m):
    assert m.exact("akiko") == (1, (1, [2]))
    assert m.exact("AKIKO") == (1, (1, [2]))


def test_exact_folds_macrons_and_drops_punctuation(m):
    assert m.exact("Hojo")[1] == (1, [6])
    assert m.exact("Shinichi")[1] == (1, [7])
    assert m.exact("shin-ichi")[1] == (1, [7])


def test_exact_miss_leaves_vanilla_out(m):
    assert m.exact("Zack") == (0, (0, [-1]))


def test_exact_mode_3_never_matches(m):
    assert m.exact("Akiko", mode=3) == (0, (0, [-1]))


def test_mode_1_rejects_excluded_ids():
    mm = Matcher(DICT, excluded=(300,))
    assert mm.exact("Manaka", mode=1)[0] == 0
    assert mm.exact("Manaka", mode=0)[1] == (1, [300])
    assert 300 not in mm.suggest("Manak", mode=1)


def test_non_ascii_name_matches_nothing(m):
    assert m.exact("あきこ") == (0, (0, [-1]))
    assert m.suggest("あきこ") == []
    assert m.suggest("") == []


def test_prefix_suggestions_rank_shorter_completions_first(m):
    # "Aki" itself is the exact match (drawn by the caller), not a suggestion.
    assert m.suggest("Aki") == [3, 2, 4, 5]


def test_typo_suggestions(m):
    # Swapped letters count as one slip; Akiko ranks above the deletion.
    assert m.suggest("Akkio")[:2] == [2, 3]
    # Kanaco -> Nanako is two slips; six letters allow one.
    assert m.suggest("Kanaco") == [9]


def test_duplicate_readings_listed_once(m):
    assert m.suggest("Ak").count(1) + m.suggest("Ak").count(200) == 1


def test_flag_lists_exact_only(m):
    assert m.suggest("akiko", flag=1) == [2]
    assert m.suggest("Akk", flag=1) == []


def test_short_query_has_no_typo_matches(m):
    assert m.suggest("Bab") == []


def test_list_caps_at_ten():
    many = {i: "Ta" + chr(ord("a") + i) * 2 for i in range(20)}
    assert len(Matcher(many).suggest("Ta")) == 10


def test_unknown_name_lists_nothing(m):
    """No reading and no suggestion: the Called list stays empty."""
    assert m.suggest("Zack") == []


def test_long_vowel_spelling_is_a_suggestion():
    # Yuji is one letter from Yuuji: listed, not an exact match.
    m = Matcher({20: "Yuuji", 22: "Ono", 23: "Oono"})
    assert m.exact("Yuji")[0] == 0
    assert m.suggest("Yuji") == [20]


def test_blob_is_built_from_current_source():
    src = (SRC / "call_romaji_match.c").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(src).hexdigest() == blob.SOURCE_SHA256, (
        "src/call_romaji_match.c changed: run python tools/build_call_romaji_match.py"
    )


def test_blob_matches_a_rebuild_with_the_same_clang():
    if not shutil.which("clang"):
        pytest.skip("no clang")
    build = load_module("build_call_romaji_match", TOOLS / "build_call_romaji_match.py")
    if build.clang_version() != blob.CLANG_VERSION:
        pytest.skip(f"clang differs from the blob's ({blob.CLANG_VERSION})")
    assert subprocess.run([sys.executable, str(TOOLS / "build_call_romaji_match.py"), "--check"]).returncode == 0


@pytest.mark.local_data
def test_real_dictionary_akiko():
    """Akiko is reading 4780 in the shipped TRB; typos still find it."""
    sys.path.insert(0, str(TOOLS))
    from patch_password_serials import _sub_u16_off
    from patch_textresource import LOOKUP_PATH, decode_entry, iter_entries, load_lookup, parse_chunks

    trb = ROOT / "release" / "romfs_overlay" / "SystemData" / "TextResource" / "textresource_jpn.trb"
    if not trb.is_file():
        pytest.skip("no release TRB")
    chunks = parse_chunks(trb.read_bytes())
    lookup = load_lookup(LOOKUP_PATH)
    entries = list(iter_entries(chunks["STRI"]))
    off, count = _sub_u16_off(chunks["INDX"], 0x72, 0)
    readings = {}
    for i in range(count):
        _i, _o, stringindex, _bl, flag = entries[struct.unpack_from("<H", chunks["INDX"], off + 2 * i)[0]]
        if flag != 2:
            readings[i] = decode_entry(chunks["STRB"], stringindex, flag, lookup)[0]
    mm = Matcher(readings, ranges=REAL_RANGES)
    assert readings[4780] == "Akiko"
    assert mm.exact("Akiko", mode=1)[1] == (1, [4780])
    assert 4780 in mm.suggest("Akko", mode=1)
    assert 4780 in mm.suggest("Akikko", mode=1)
    assert mm.calls > 0
