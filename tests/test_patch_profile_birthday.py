"""Confirm-sheet birthday prints "June 23" without touching shared 月/日 tokens."""

from __future__ import annotations

import struct

from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

from conftest import SRC, load_module

bday = load_module("patch_profile_birthday", SRC / "patch_profile_birthday.py")

VA = 0x100000


def _image() -> bytearray:
    table = bday.ADDR_BIRTHDAY_MONTHS
    data = bytearray(table + len(bday.build_month_table()))
    data[bday.SITE : bday.SITE + bday.WINDOW] = bday.VANILLA_WINDOW
    return data


def test_month_table_fits_the_spotpass_pad_tail():
    table = bday.build_month_table()
    assert len(table) == 12 * 12
    assert table[5 * 12 : 5 * 12 + 5] == b"June\x00"
    assert table[8 * 12 : 8 * 12 + 10] == b"September\x00"
    end = bday.ADDR_BIRTHDAY_MONTHS + len(table)
    pad_end = bday.ADDR_SPOTPASS_PAYLOAD + bday.SPOTPASS_PAYLOAD_MAX
    assert bday.ADDR_BIRTHDAY_MONTHS >= bday.ADDR_SPOTPASS_PAYLOAD + 0x914
    assert end <= pad_end


def test_month_table_guards_bad_inputs(monkeypatch):
    monkeypatch.setattr(bday, "MONTHS", ("Jan",))
    try:
        bday.build_month_table()
    except ValueError as exc:
        assert "months" in str(exc)
    else:
        raise AssertionError("short MONTHS was accepted")
    monkeypatch.setattr(bday, "MONTHS", tuple(["X" * 20] * 12))
    try:
        bday.build_month_table()
    except ValueError as exc:
        assert "stride" in str(exc)
    else:
        raise AssertionError("oversized month was accepted")
    monkeypatch.setattr(bday, "MONTHS", tuple(f"M{i}" for i in range(12)))
    monkeypatch.setattr(bday, "SPOTPASS_PAYLOAD_MAX", 0x10)
    try:
        bday.build_month_table()
    except ValueError as exc:
        assert "past the SpotPass pad" in str(exc)
    else:
        raise AssertionError("table past pad was accepted")


def test_window_replaces_the_unit_concat_and_draws():
    window = bday.build_window()
    assert len(window) == bday.WINDOW
    assert len(bday.VANILLA_WINDOW) == bday.WINDOW
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    insns = list(md.disasm(window, bday.SITE))
    text = {i.address: (i.mnemonic, i.op_str) for i in insns}
    assert text[bday.SITE] == ("ldrb", "r0, [r4, #0x80]")
    assert text[bday.SITE + 12] == ("bhi", f"#{bday.SKIP:#x}")
    assert text[bday.SITE + 0x20] == ("ldrb", "r0, [r1], #1")
    assert text[bday.SITE + 0x74] == ("b", f"#{bday.DRAW:#x}")
    # The two nops and the name-table literal sit between that branch and the draw.
    assert window.endswith(bytes.fromhex("0000a0e1" * 2))


def test_apply_is_idempotent_and_guards_both_ranges():
    data = _image()
    assert bday.apply_patch(data) is True
    assert bday.is_patched(data)
    assert data[bday.ADDR_BIRTHDAY_MONTHS : bday.ADDR_BIRTHDAY_MONTHS + 5] == b"Janua"
    assert bday.apply_patch(data) is False

    bad_code = _image()
    bad_code[bday.SITE] ^= 0xA5
    try:
        bday.apply_patch(bad_code)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupted site was patched")
    assert bad_code[bday.SITE : bday.SITE + 4] != bday.build_window()[:4]

    bad_table = _image()
    bad_table[bday.ADDR_BIRTHDAY_MONTHS] ^= 0xA5
    try:
        bday.apply_patch(bad_table)
    except ValueError:
        pass
    else:
        raise AssertionError("corrupted month table was patched")
    assert bad_table[bday.SITE : bday.SITE + 4] == bday.VANILLA_WINDOW[:4]


def _exec(month: int, day: int) -> tuple[str, int]:
    """Run the cave. Returns the sp+8 string and the file PC it stopped on."""
    window = bday.build_window()
    table = bday.build_month_table()
    mem = bytearray(bday.ADDR_BIRTHDAY_MONTHS + len(table) + 16)
    mem[bday.SITE : bday.SITE + len(window)] = window
    mem[bday.ADDR_BIRTHDAY_MONTHS : bday.ADDR_BIRTHDAY_MONTHS + len(table)] = table
    obj = 0x1000
    stack = 0x2000
    mem[obj + 0x80] = month & 0xFF
    mem[obj + 0x81] = day & 0xFF
    reg = [0] * 16
    reg[4] = obj + VA
    reg[13] = stack + VA
    pc = bday.SITE
    flags = {"z": False, "c": False}

    def va_to_file(addr: int) -> int:
        return addr - VA

    for _ in range(400):
        if pc in (bday.DRAW, bday.SKIP):
            break
        word = struct.unpack_from("<I", mem, pc)[0]
        next_pc = pc + 4
        cond = word >> 28
        take = True
        if cond == 0x0:
            take = flags["z"]
        elif cond == 0x2:
            take = flags["c"]
        elif cond == 0x3:
            take = not flags["c"]
        elif cond == 0x8:
            take = flags["c"] and not flags["z"]
        elif cond != 0xE:
            raise AssertionError(f"unhandled cond {cond:#x} @{pc:#x}")
        op = (word >> 25) & 7
        if op == 5 and take:
            imm = word & 0xFFFFFF
            if imm & 0x800000:
                imm -= 0x1000000
            next_pc = pc + 8 + (imm << 2)
        elif op == 5:
            pass
        elif op == 2 and (word & 0x0C000000) == 0x04000000:
            # single data transfer
            rn = (word >> 16) & 0xF
            rd = (word >> 12) & 0xF
            imm = word & 0xFFF
            pre = (word >> 24) & 1
            up = (word >> 23) & 1
            byte = (word >> 22) & 1
            writeback = (word >> 21) & 1
            load = (word >> 20) & 1
            base = (pc + VA + 8) if rn == 15 else reg[rn]
            off = imm if up else -imm
            addr = (base + off) if pre else base
            file_addr = va_to_file(addr)
            if not byte or (word >> 26) & 1 == 0 and not byte:
                pass
            if load and not byte:
                reg[rd] = struct.unpack_from("<I", mem, file_addr)[0]
            elif load and byte:
                reg[rd] = mem[file_addr]
            elif byte:
                mem[file_addr] = reg[rd] & 0xFF
            else:
                raise AssertionError(f"word store @{pc:#x}")
            if not pre:
                reg[rn] = (base + off) & 0xFFFFFFFF
            elif writeback:
                reg[rn] = addr & 0xFFFFFFFF
        elif (word >> 26) & 3 == 0:
            # data processing (imm or reg)
            opcode = (word >> 21) & 0xF
            s = (word >> 20) & 1
            rn = (word >> 16) & 0xF
            rd = (word >> 12) & 0xF
            if (word >> 25) & 1:
                imm = word & 0xFF
                rot = ((word >> 8) & 0xF) * 2
                operand = ((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF if rot else imm
            else:
                rm = word & 0xF
                shift = (word >> 7) & 0x1F
                kind = (word >> 5) & 3
                val = reg[rm]
                if kind == 0:
                    operand = (val << shift) & 0xFFFFFFFF
                else:
                    raise AssertionError(f"shift kind {kind} @{pc:#x}")
            a = reg[rn]
            if opcode == 0x2:  # sub
                result = (a - operand) & 0xFFFFFFFF
            elif opcode == 0x4:  # add
                result = (a + operand) & 0xFFFFFFFF
            elif opcode == 0xA:  # cmp
                result = (a - operand) & 0xFFFFFFFF
                s = 1
            elif opcode == 0xD:  # mov
                result = operand
            else:
                raise AssertionError(f"opcode {opcode:#x} @{pc:#x} {word:08x}")
            if s and opcode != 0xD:
                flags["z"] = result == 0
                flags["c"] = a >= operand if opcode in (0x2, 0xA) else (a + operand) > 0xFFFFFFFF
            if opcode != 0xA:
                reg[rd] = result
        else:
            raise AssertionError(f"unhandled @{pc:#x} {word:08x}")
        pc = next_pc
    else:
        raise AssertionError("cave did not finish")
    raw = bytes(mem[stack + 8 : stack + 8 + 24])
    return raw.split(b"\x00", 1)[0].decode("ascii"), pc


def test_cave_writes_june_23_and_keeps_r4():
    assert bday.format_birthday(6, 23) == "June 23"
    assert bday.format_birthday(9, 23) == "September 23"
    assert bday.format_birthday(0, 23) is None
    samples = {
        (6, 23): "June 23",
        (9, 23): "September 23",
        (1, 1): "January 1",
        (12, 31): "December 31",
        (5, 9): "May 9",
        (10, 10): "October 10",
    }
    for (month, day), text in samples.items():
        got, pc = _exec(month, day)
        assert got == text, (month, day, got)
        assert pc == bday.DRAW
    blank, pc = _exec(13, 2)
    assert blank == ""
    assert pc == bday.SKIP
