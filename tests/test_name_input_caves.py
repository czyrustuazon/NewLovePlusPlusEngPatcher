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
lyt_null = load_module("patch_lyt_null_pane", SRC / "patch_lyt_null_pane.py")
ascii_dakuten = load_module(
    "patch_input_skip_ascii_dakuten",
    SRC / "patch_input_skip_ascii_dakuten.py",
)
strcat_raw = load_module("patch_input_strcat_raw", SRC / "patch_input_strcat_raw.py")
call_romaji = load_module("patch_input_call_romaji", SRC / "patch_input_call_romaji.py")


def test_name_input_caves_are_inside_text_rx():
    """Regression: Luma prefetch abort PC 0x007E6A78 was the old .rodata pad."""
    end = cave_map.TEXT_PAGE_END
    assert cave_map.ADDR_SHARED_PAD < end
    assert cave_map.ADDR_TALK_CAP_CAVE + cave_map.TALK_CAP_CAVE_LEN <= end
    assert cave_map.ADDR_TALK_CAP_CAVE + cave_map.TALK_CAP_CAVE_LEN <= cand.CAVE1
    assert cave_map.ADDR_ROMAJI_CAVE < end
    assert cand.CAVE1 < end and cand.CAVE2 + 0x18 <= end
    assert pane.CAVE + pane.CAVE_LEN <= end
    assert fill.CAVE + fill.CAVE_LEN <= end
    assert lyt_null.ATTACH_CAVE + lyt_null.ATTACH_CAVE_LEN <= end
    assert lyt_null.FIND_CAVE + lyt_null.FIND_CAVE_LEN <= end
    assert lyt_null.ATTACH_CAVE + lyt_null.ATTACH_CAVE_LEN <= cand.CAVE1
    assert pane.CAVE + pane.CAVE_LEN <= lyt_null.FIND_CAVE
    assert lyt_null.FIND_CAVE + lyt_null.FIND_CAVE_LEN <= fill.CAVE
    blob = romaji.build_romaji_blob()
    assert romaji.ADDR_CAVE + len(blob) <= end
    sc = strcat_raw.cave_addr()
    assert sc + len(strcat_raw.build_blob(base=sc)) <= end
    cr = call_romaji.cave_addr()
    assert cr + len(call_romaji.build_blob()[0]) <= end
    assert cave_map.OLD_RODATA_SHARED_PAD >= end
    assert cave_map.OLD_RODATA_ROMAJI_CAVE >= end


def test_name_input_caves_do_not_overlap():
    ranges = [
        (
            cave_map.ADDR_TALK_CAP_CAVE,
            cave_map.ADDR_TALK_CAP_CAVE + cave_map.TALK_CAP_CAVE_LEN,
        ),
        (cand.CAVE1, cand.CAVE1 + 0x18),
        (cand.CAVE2, cand.CAVE2 + 0x18),
        (pane.CAVE, pane.CAVE + pane.CAVE_LEN),
        (fill.CAVE, fill.CAVE + fill.CAVE_LEN),
        (lyt_null.ATTACH_CAVE, lyt_null.ATTACH_CAVE + lyt_null.ATTACH_CAVE_LEN),
        (lyt_null.FIND_CAVE, lyt_null.FIND_CAVE + lyt_null.FIND_CAVE_LEN),
        (romaji.ADDR_CAVE, romaji.ADDR_CAVE + len(romaji.build_romaji_blob())),
        (
            strcat_raw.cave_addr(),
            strcat_raw.cave_addr() + len(strcat_raw.build_blob(base=strcat_raw.cave_addr())),
        ),
        (
            call_romaji.cave_addr(),
            call_romaji.cave_addr() + len(call_romaji.build_blob()[0]),
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


def test_fullwidth_latin_to_ascii_abc_pack():
    """ABC TRB pack 0x7004 is U+FF01..U+FF5E; GetCharWidthCells=2 until ASCII."""
    assert romaji.fullwidth_latin_to_ascii("ＡＢＣ") == "ABC"
    assert romaji.fullwidth_latin_to_ascii("ａｚ") == "az"
    assert romaji.fullwidth_latin_to_ascii("！～") == "!~"
    assert romaji.fullwidth_latin_to_ascii("あＡKA") == "あAKA"
    for cp in range(0xFF01, 0xFF5F):
        assert romaji.fullwidth_latin_to_ascii(chr(cp)) == chr(cp - 0xFEE0)


def test_romaji_cave_converts_fullwidth_utf8():
    """kana_to_romaji k_fw: EF BC 81..BF → ASCII-0x60, EF BD 80..9E → ASCII-0x20."""
    blob = romaji.build_romaji_blob()
    assert bytes.fromhex("ef0050e3") in blob  # cmp r0, #0xEF
    assert bytes.fromhex("bc0051e3") in blob  # cmp r1, #0xBC
    assert bytes.fromhex("bd0051e3") in blob  # cmp r1, #0xBD
    assert bytes.fromhex("600042e2") in blob  # sub r0, r2, #0x60
    assert bytes.fromhex("200042e2") in blob  # sub r0, r2, #0x20
    a_utf8 = "Ａ".encode("utf-8")
    assert a_utf8 == bytes([0xEF, 0xBC, 0xA1])
    assert chr(a_utf8[2] - 0x60) == "A"
    z_utf8 = "ｚ".encode("utf-8")
    assert z_utf8 == bytes([0xEF, 0xBD, 0x9A])
    assert chr(z_utf8[2] - 0x20) == "z"


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


def test_call_romaji_caves_assemble_and_hook_vanilla():
    """Called-list *3 walk + ASCII fallback stay in .text RX after strcat."""
    cave = call_romaji.cave_addr()
    blob, labs = call_romaji.build_blob(base=cave)
    assert cave + len(blob) <= cave_map.TEXT_PAGE_END
    assert labs["utf8_off"] == cave
    assert "call01" in labs and "call02" in labs
    assert bytes.fromhex("00c00fe1") in blob  # mrs r12, cpsr (preserve +3 loop flags)
    assert bytes.fromhex("0cf028e1") in blob  # msr cpsr_f, r12
    assert bytes.fromhex("0190a0e3") in blob  # mov r9, #1 before ASCII DrawText jump
    bls = _arm_bl_targets(blob, cave)
    assert any(tgt == call_romaji.ADDR_UTF8_LEN for _, tgt in bls)
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    if data[call_romaji.SITE_INDEX_MUL3 : call_romaji.SITE_INDEX_MUL3 + 4] != (
        call_romaji.ORIG_INDEX_MUL3
    ):
        return
    if data[strcat_raw.ADDR : strcat_raw.ADDR + 8] == strcat_raw.VANILLA_HEAD:
        strcat_raw.apply_patch(data)
    call_romaji.apply_patch(data)
    assert call_romaji.is_patched(data)
    assert bytes(data[cave : cave + len(blob)]) == blob


def test_lyt_null_pane_caves_assemble_and_hook_vanilla():
    attach = lyt_null.build_attach_cave()
    find = lyt_null.build_find_cave()
    assert len(attach) == lyt_null.ATTACH_CAVE_LEN
    assert len(find) == lyt_null.FIND_CAVE_LEN
    assert attach[4:8] == bytes.fromhex("1eff2f01")  # bxeq lr
    assert bytes.fromhex("33ff2fe1") in find  # BLX r3
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    if data[lyt_null.ATTACH_SITE : lyt_null.ATTACH_SITE + 4] != lyt_null.ATTACH_EXPECT:
        return
    if data[lyt_null.FIND_SITE : lyt_null.FIND_SITE + 4] != lyt_null.FIND_EXPECT:
        return
    lyt_null.apply_patch(data)
    assert lyt_null.is_patched(data)
    assert bytes(data[lyt_null.ATTACH_CAVE : lyt_null.ATTACH_CAVE + len(attach)]) == attach
    assert bytes(data[lyt_null.FIND_CAVE : lyt_null.FIND_CAVE + len(find)]) == find
