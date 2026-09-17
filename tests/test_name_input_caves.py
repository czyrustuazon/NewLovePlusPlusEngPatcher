"""Name-input caves must sit in .text RX pages (real 3DS NX)."""

from __future__ import annotations

from conftest import SRC, load_module

cave_map = load_module("patch_input_cave_map", SRC / "patch_input_cave_map.py")
romaji = load_module("patch_input_romaji", SRC / "patch_input_romaji.py")
cand = load_module(
    "patch_input_candidate_nullguard", SRC / "patch_input_candidate_nullguard.py"
)
pane = load_module(
    "patch_input_pane_registry_nullguard",
    SRC / "patch_input_pane_registry_nullguard.py",
)
fill = load_module(
    "patch_input_candmode_fillflag_reset",
    SRC / "patch_input_candmode_fillflag_reset.py",
)
ascii_dakuten = load_module(
    "patch_input_skip_ascii_dakuten",
    SRC / "patch_input_skip_ascii_dakuten.py",
)
strcat_raw = load_module("patch_input_strcat_raw", SRC / "patch_input_strcat_raw.py")


def test_name_input_caves_are_inside_text_rx():
    """Regression: Luma prefetch abort PC 0x007E6A78 was the old .rodata pad."""
    end = cave_map.TEXT_PAGE_END
    assert cave_map.ADDR_SHARED_PAD < end
    assert cave_map.ADDR_ROMAJI_CAVE < end
    assert cand.CAVE1 < end and cand.CAVE2 + 0x18 <= end
    assert pane.CAVE + pane.CAVE_LEN <= end
    assert fill.CAVE + fill.CAVE_LEN <= end
    blob = romaji.build_romaji_blob()
    assert romaji.ADDR_CAVE + len(blob) <= end
    sc = strcat_raw.cave_addr()
    assert sc + len(strcat_raw.build_blob(base=sc)) <= end
    assert cave_map.OLD_RODATA_SHARED_PAD >= end
    assert cave_map.OLD_RODATA_ROMAJI_CAVE >= end


def test_name_input_caves_do_not_overlap():
    ranges = [
        (cand.CAVE1, cand.CAVE1 + 0x18),
        (cand.CAVE2, cand.CAVE2 + 0x18),
        (pane.CAVE, pane.CAVE + pane.CAVE_LEN),
        (fill.CAVE, fill.CAVE + fill.CAVE_LEN),
        (romaji.ADDR_CAVE, romaji.ADDR_CAVE + len(romaji.build_romaji_blob())),
        (
            strcat_raw.cave_addr(),
            strcat_raw.cave_addr() + len(strcat_raw.build_blob(base=strcat_raw.cave_addr())),
        ),
    ]
    for i, (a0, a1) in enumerate(ranges):
        for b0, b1 in ranges[i + 1 :]:
            assert a1 <= b0 or b1 <= a0, hex(a0)


def _arm_bl_targets(blob: bytes, base: int) -> list[tuple[int, int]]:
    import struct

    out: list[tuple[int, int]] = []
    for i in range(0, len(blob) - 3, 4):
        w = struct.unpack_from("<I", blob, i)[0]
        if (w >> 24) != 0xEB:
            continue
        off = w & 0xFFFFFF
        if off & 0x800000:
            off -= 0x1000000
        out.append((i, base + i + 8 + (off << 2)))
    return out


def _arm_blx_targets(blob: bytes, base: int) -> list[tuple[int, int]]:
    import struct

    out: list[tuple[int, int]] = []
    for i in range(0, len(blob) - 3, 4):
        w = struct.unpack_from("<I", blob, i)[0]
        if (w >> 25) != 0x7D:  # 1111 101x BLX imm
            continue
        h = (w >> 24) & 1
        off = w & 0xFFFFFF
        if off & 0x800000:
            off -= 0x1000000
        out.append((i, base + i + 8 + (off << 2) + (h << 1)))
    return out


def test_romaji_table_ka_ke_ku_are_two_letters():
    """Hepburn か/け/く must be KA/KE/KU — KKE here is the KAKKE bug."""
    tab = b"".join(
        romaji._pad4(romaji._romaji_cell(romaji.HIRA_ROMAJI.get(cp, "")))
        for cp in range(0x3041, 0x3041 + 0x56)
    )
    for kana, want in (("か", b"KA\0\0"), ("け", b"KE\0\0"), ("く", b"KU\0\0")):
        i = ord(kana) - 0x3041
        assert tab[i * 4 : i * 4 + 4] == want, (kana, tab[i * 4 : i * 4 + 4])


def test_romaji_copies_insert_before_makestr():
    blob = romaji.build_romaji_blob()
    targets = _arm_bl_targets(blob, romaji.ADDR_CAVE)
    memcpy_offs = [off for off, tgt in targets if tgt == romaji.ADDR_MEMCPY7]
    makestr_offs = [off for off, tgt in targets if tgt == romaji.ADDR_MAKE_STR]
    assert memcpy_offs, "DrawCell must strncpy the insert slot"
    assert makestr_offs, "DrawCell must MakeStr for labels"
    assert memcpy_offs[0] < makestr_offs[0]


def test_skip_ascii_dakuten_is_inplace_strcat_branch():
    assert ascii_dakuten.PATCHED_SITE != ascii_dakuten.EXPECT_SITE
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    if data[ascii_dakuten.SITE : ascii_dakuten.SITE + 4] != ascii_dakuten.EXPECT_SITE:
        return
    ascii_dakuten.apply_patch(data)
    assert ascii_dakuten.is_patched(data)
    assert data[ascii_dakuten.SITE_CONVERT : ascii_dakuten.SITE_CONVERT + 4] == (
        ascii_dakuten.PATCHED_CONVERT
    )
    assert data[ascii_dakuten.OLD_CAVE : ascii_dakuten.OLD_CAVE + ascii_dakuten.OLD_CAVE_LEN] == (
        b"\x00" * ascii_dakuten.OLD_CAVE_LEN
    )


def test_strcat_raw_replaces_makestr_join():
    cave = strcat_raw.cave_addr()
    blob = strcat_raw.build_blob(base=cave)
    assert cave + len(blob) <= cave_map.TEXT_PAGE_END
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    if data[strcat_raw.ADDR : strcat_raw.ADDR + 8] != strcat_raw.VANILLA_HEAD:
        return
    strcat_raw.apply_patch(data)
    assert strcat_raw.is_patched(data)
    assert bytes(data[cave : cave + len(blob)]) == blob
    # FUN_00000b1c is Thumb — ARM BL would crash on first tap.
    blx_offs = [
        off
        for off, tgt in _arm_blx_targets(blob, cave)
        if tgt == strcat_raw.ADDR_STRCAT
    ]
    assert blx_offs, "strcat cave must BLX Thumb FUN_00000b1c"
    # Hardcoded 8 glyphs after strncpy (caller r3 is not kept).
    assert bytes.fromhex("0870a0e3") in blob  # mov r7, #8
    hi = [
        off
        for off in range(0, len(blob), 4)
        if blob[off + 3] == 0x8A  # bhi
    ]
    assert hi, "strcat cave must bhi-skip when dest+pending > 8 glyphs"
