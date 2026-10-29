"""Tapping the Eng Patch badge on the Main Menu shows the localization credits.

The credits are one scrolling INFORMATION box with one OK. Paging is kept:
with ``PAGE_LINES`` > 0 they become a run of boxes and OK on one opens the next
(``CREDIT_PAGES``; see docs/technical.md "Credits paging").

The badge (``Pic_EngPatch`` in ``Pts_Copyright``, ``deploy_title_engpatch_en``)
is a picture, not a button, so the tap is read straight from HID shared memory
and tested against the badge's rectangle on the touch screen.

Tap (``ldr r0, [r5, #0x70]`` @ ``0x002C6018``): the title operator's per-frame
tick (``FUN_002C5E90``, r4 = operator, r5 = hub ``Lyt_Tit02``) reaches this
load only while it waits for a Main Menu choice and no dialog of its own is
pending. ``hub+0x70`` is the chosen row, -1 while none. The cave returns that
word unchanged when a row was chosen. Otherwise it reads the latest touch
entry (``*(HID+0xC)`` is the touch section at shared memory ``+0xA8``: ``+0x10``
latest index, entries at ``+0x20``, 8 bytes each: x, y, bit 0 = touched) and
tracks one press in a ``.data`` cell: armed when the finger lands on the badge,
disarmed if it slides off, and the box opens on release. It then returns -1
(nothing chosen) every frame, so the operator keeps waiting.

The box is ``FUN_00195FA4(*0x008BFA7C, layout, mode, 1, 2, 0, 0, 0, 0, 0)``:
``r3 = 1`` is the OK-only button set, and window style 2 shows the
``C_Com_Win01_t02`` header (INFORMATION; t01 COMMUNICATION, t03 ERROR, …).
``mode`` is ``DIALOG_MODE + page``. While a box is up the cell's open flag is
set, and each tick asks ``FUN_00196F88(_, handle)``, the same "closed yet?"
check the operator uses for its own title dialogs (``0x002C5FF8``); when it
closes, the next page opens, until the last. Their wait path is not reused: on close
it calls ``0x001EED80(hub, 1)``, which replays the hub's intro animation.

Hub taps while the box is up: the hub's touch-down handler (vtable ``+0x28``
``0x002BE0EC`` VA) records the pressed row only while ``+0x70 == -1``. Its
vtable slot (VA ``0x0080AEF0``) points at a guard that returns 0 while the box
is open, so a row cannot be picked behind it.

The badge rectangle depends on how the console is held. The hub keeps the hold
angle in ``+0x64`` (vtable ``+0x38`` setter ``0x001BE628``, the same one the
Copyright Parts uses to pick ``Pos_Copyright_{H,VR,VL}``): 0 = H at
(0, -95); -90 = VR at (-152, 0) rotated -90; 90 = VL at (152, 0) rotated 90.
``Pic_EngPatch`` spans x -109..109, y 4..30 inside ``Nul_Copyright``. Touch
pixels are ``x = 160 + X``, ``y = 120 - Y`` for layout X/Y; each box below is
that rectangle plus 2 px.

Stale state: the hub-enter path of the same tick (``str r8, [r4, #0x58]`` @
``0x002C5FB0``, r8 = 0) also clears the cell, so a box torn down without
closing (soft reset back to the title) cannot leave the Main Menu locked.

Room: the tap, press tracking and enter hook sit in the rest of
``FUN_000EA964``'s dead body (``patch_spotpass_skip`` stubs its entry;
``patch_camera_defaults_reset`` has the first part). Opening and polling the
boxes and the touch-down guard sit in the dead body of ``CecCheckEula`` (``0x00632534``),
which ``patch_eula_agreed`` stubs to ``mov r0, #0; bx lr``.

The pages are pack ``0x1901`` layout 53 modes 4.. = slots 502.., right after
the camera confirm's slot 501. ``append_info_message`` adds them to the TRB
(``tools/deploy_name_kanji_trb.py``).
"""
from __future__ import annotations

import hashlib
import struct

from patch_camera_defaults_reset import (
    ADDR_STUB,
    CAVE_END as CAMERA_CAVE_END,
    STUB_PATCHED,
    append_message_slot,
    b,
    bl,
)
from patch_eula_agreed import SITES as EULA_SITES

NOP = bytes.fromhex("00f020e3")

# Rest of FUN_000EA964's dead body, after the camera cave.
CAVE_A_START = CAMERA_CAVE_END  # 0x000EAA60
CAVE_A_END = 0x000EAB80
CAVE_A_VANILLA_SHA256 = "b09c0e77b16c0dbe905966dae25d450f1a7a9f9b9da9c2b698f439785c6a1017"
# CecCheckEula after its two-word stub, up to the end of its literal pool.
CEC_STUB = 0x00632534
CEC_STUB_PATCHED = next(p for s, _v, p, _l in EULA_SITES if s == CEC_STUB)
CAVE_B_START = 0x0063253C
CAVE_B_END = 0x00632604
CAVE_B_VANILLA_SHA256 = "dd13aa73d7ef00eaaa5d3de352f5dbf9399d9ae13954dd06c16da8c0758f5de0"

HOOK_TAP = 0x002C6018
HOOK_TAP_VANILLA = bytes.fromhex("700095e5")  # ldr r0, [r5, #0x70]
HOOK_ENTER = 0x002C5FB0
HOOK_ENTER_VANILLA = bytes.fromhex("588084e5")  # str r8, [r4, #0x58]

# Hub (Lyt_Tit02) vtable VA 0x0080AEC8, slot +0x28 = touch-down handler.
HUB_TOUCH_SLOT = 0x0070AEF0
HUB_TOUCH_DOWN = 0x001BE0EC
HUB_TOUCH_SLOT_VANILLA = struct.pack("<I", HUB_TOUCH_DOWN + 0x100000)

ADDR_OPEN_DIALOG = 0x00195FA4
ADDR_DIALOG_CLOSED = 0x00196F88
DIALOG_MGR_PTR = 0x008BFA7C  # VA; *ptr is FUN_00195FA4's r0
HID_TOUCH_PTR = 0x009A1404  # VA of HID object (0x009A13F8) + 0xC

# .data, VA. +0 was touched, +1 armed, +2 box open, +3 page, +4 handle.
# ADDR_MENU_CELL (patch_spotpass_embed) uses 0x008A5100..0x008A5124.
CELL = 0x008A5180

DIALOG_LAYOUT = 53
DIALOG_LAYOUT_BASE = 498
DIALOG_MODE = 4
DIALOG_BUTTONS_OK = 1
DIALOG_STYLE_INFORMATION = 2
MSG_SLOT = DIALOG_LAYOUT_BASE + DIALOG_MODE  # 502, first page
# One box per page; OK opens the next. Vanilla boxes in this layout run to
# 14 lines (they scroll) and 36 characters; pages stay within that.
CREDITS_TITLE = "Localization Credits"
PAGE_LINES = 0  # lines per box, title included; 0 = everything in one scrolling box
# Changing the page count needs both rebuilds: code.bin (cmp #pages) and the TRB (slots).
# One box draws at most 64 lines: vanilla DrawTextToPane (0x0054B880) only
# kept 32 lines in its stack table; patch_drawtext_64_lines packs it to 64.
# The text texture is pane-sized (deploy_ui_buttons_en makes Tex_Sentence
# 1024 tall); vanilla's 256 held ~16 lines.
MAX_BOX_LINES = 64
BLANK_BETWEEN_ROLES = False  # a blank line before every role costs ~20 lines
LINE_WIDTH = 26  # lines are centred; ~30 (● counted twice) ran past the box edges
BULLET = ""  # names line prefix; the game's "● " bullet looked busy
# (role, names); names None = a team heading line; ("", None) = one blank line.
CREDITS: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ("== 2026 Team ==", None),
    ("[Developers]", ("zaccken", "Cetaceaqua")),
    (" ", None),
    ("[UI Texture Overhaul]", ("Zhoumaru",)),
    (" ", None),
    ("[QA & Proofreading]", ("Dragios", "D.", "THE DRIZZLE", "Lieutenant Dan")),
    (" ", None),
    ("[Special Thanks]", ("anon","lolipop221", "i need help here...", "2Soulz the sheep", "gamebrew.org", "LovePlusProject", "gbatemp.net")),
    ("== Pioneer Legacy Team ==", None),
    ("[Project Coordination]", ("Dgrin", "Makein")),
    (" ", None),
    ("[Original Love Plus (DS)]", ("TLWiki group", "jjjewel & team")),
    (" ", None),
    # Translation, proofreading, text & strings, new script, and later passes.
    (
        "[Translation & Editing]",
        (
            "Mayne", "DDMeisterX", "Shakkolvan", "Scarymonsters", "Kai", "Oli",
            "Bango", "Incolbum", "Jaslyn", "Cozy Translations", "k7ra", "rinkohot1337",
        ),
    ),
    (" ", None),
    # Hacking & tools plus script integration.
    (
        "[Hacking & Tools]",
        (
            "gdkchan", "Demonslayerx8", "MGDanon", "deaknaew", "froid_san", "kiwiz", "Chulio",
            "Nagato", "Makein", "Zander1995", "Asia81", "internetakias", "ofan", "NCDyson",
            "Aikin-Ai", "impeio92", "Keimeow",
        ),
    ),
    (" ", None),
    # Graphics translation and graphics editing.
    (
        "[Graphics]",
        ("eyenight", "Jaslyn", "Karuta", "Bango", "Kaizerscythe", "Shakkolvan", "Yuuyuun", "bigcookie"),
    ),
)


def _width(line: str) -> int:
    # The box centres each line; ● draws about two letters wide.
    return len(line) + line.count("●")


def _name_lines(names: tuple[str, ...]) -> list[str]:
    """BULLET + "name, name, ..." wrapped at LINE_WIDTH without splitting a name."""
    lines = [BULLET.rstrip()]
    for i, name in enumerate(names):
        item = name + ("," if i < len(names) - 1 else "")
        if lines[-1] == BULLET.rstrip():
            lines[-1] = (lines[-1] + " " + item).lstrip()
        elif _width(lines[-1]) + 1 + len(item) <= LINE_WIDTH:
            lines[-1] += " " + item
        else:
            lines.append(item)
    return lines


def _credit_pages() -> tuple[str, ...]:
    pages: list[list[str]] = [[]]
    for role, names in CREDITS:
        if not role.strip():  # ("", None): one blank line, nothing else
            pages[-1].append("")
            continue
        block = [role] if names is None else [role, *_name_lines(names)]
        if PAGE_LINES and pages[-1] and len(pages[-1]) + 1 + len(block) > PAGE_LINES - 1:
            pages.append([])
        if pages[-1] and (BLANK_BETWEEN_ROLES or names is None):
            pages[-1].append("")
        pages[-1] += block
    n = len(pages)
    title = [CREDITS_TITLE, ""] if n == 1 else []
    return tuple(
        "\n".join([*(title or [f"{CREDITS_TITLE} ({i}/{n})"]), *p]) for i, p in enumerate(pages, 1)
    )


CREDIT_PAGES = _credit_pages()

ANGLE_H, ANGLE_VR, ANGLE_VL = 0, -90, 90
# Touch pixels (x0, x1, y0, y1), inclusive, in ANGLE_H / VR / VL order.
BADGE_RECTS = (
    (49, 271, 183, 213),
    (10, 40, 9, 231),
    (280, 310, 9, 231),
)


def _u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


class _Asm:
    """One cave region; branches may name labels in either region."""

    def __init__(self, base: int, labels: dict[str, int]) -> None:
        self.base = base
        self.code = bytearray()
        self.labels = labels
        self.fixups: list[tuple[int, str, int]] = []  # (offset, label, cond)
        self.lits: list[tuple[int, int, int]] = []  # (offset, rd, value)

    def here(self) -> int:
        return self.base + len(self.code)

    def label(self, name: str) -> None:
        self.labels[name] = self.here()

    def op(self, word: int) -> None:
        self.code.extend(_u32(word))

    def call(self, target: int) -> None:
        self.code.extend(bl(self.here(), target))

    def jump(self, target: int, cond: int = 0xE) -> None:
        self.code.extend(b(self.here(), target, cond))

    def jump_label(self, name: str, cond: int = 0xE) -> None:
        self.fixups.append((len(self.code), name, cond))
        self.op(0)

    def ldr_lit(self, rd: int, value: int) -> None:
        self.lits.append((len(self.code), rd, value))
        self.op(0)

    def finish(self) -> bytes:
        pool: dict[int, int] = {}
        for _at, _rd, value in self.lits:
            if value not in pool:
                pool[value] = len(self.code)
                self.op(value)
        for at, rd, value in self.lits:
            self.code[at : at + 4] = _u32(0xE59F0000 | (rd << 12) | (pool[value] - at - 8))
        for at, name, cond in self.fixups:
            self.code[at : at + 4] = b(self.base + at, self.labels[name], cond)
        return bytes(self.code)


def build_caves() -> tuple[bytes, bytes, dict[str, int]]:
    """Return (cave A, cave B, entry labels: tap / enter / guard)."""
    labels: dict[str, int] = {}
    a = _Asm(CAVE_A_START, labels)
    bb = _Asm(CAVE_B_START, labels)

    # Tap: replaces ldr r0, [r5, #0x70]; a chosen row passes straight through.
    a.label("tap")
    a.op(0xE5950070)  # ldr r0, [r5, #0x70]
    a.op(0xE3700001)  # cmn r0, #1
    a.op(0x112FFF1E)  # bxne lr
    a.op(0xE92D4040)  # push {r6, lr}
    a.op(0xE3A02000)  # mov r2, #0  (touched)
    a.op(0xE3A03000)  # mov r3, #0  (on the badge)
    a.ldr_lit(1, HID_TOUCH_PTR)  # ldr r1, =HID+0xC
    a.op(0xE5911000)  # ldr r1, [r1]  (touch section)
    a.op(0xE3510000)  # cmp r1, #0
    a.jump_label("track", cond=0x0)  # beq track
    a.op(0xE5910010)  # ldr r0, [r1, #0x10]  (latest entry)
    a.op(0xE2000007)  # and r0, r0, #7
    a.op(0xE0811180)  # add r1, r1, r0, lsl #3
    a.op(0xE5912024)  # ldr r2, [r1, #0x24]
    a.op(0xE2122001)  # ands r2, r2, #1
    a.jump_label("track", cond=0x0)  # beq track  (lifted: no position)
    a.op(0xE1D102B0)  # ldrh r0, [r1, #0x20]  (x)
    a.op(0xE1D112B2)  # ldrh r1, [r1, #0x22]  (y)
    a.op(0xE5956064)  # ldr r6, [r5, #0x64]  (hold angle)
    adr_at = len(a.code)
    a.op(0)  # add ip, pc, #rects (patched below)
    a.op(0xE3560000 | ANGLE_H)  # cmp r6, #0
    a.jump_label("rect", cond=0x0)
    a.op(0xE28CC008)  # add ip, ip, #8
    a.op(0xE3760000 | -ANGLE_VR)  # cmn r6, #90
    a.jump_label("rect", cond=0x0)
    a.op(0xE28CC008)  # add ip, ip, #8
    a.op(0xE3560000 | ANGLE_VL)  # cmp r6, #90
    a.jump_label("track", cond=0x1)  # bne track
    a.label("rect")
    a.op(0xE1DC60B0)  # ldrh r6, [ip]
    a.op(0xE1500006)  # cmp r0, r6
    a.jump_label("track", cond=0x3)  # blo
    a.op(0xE1DC60B2)  # ldrh r6, [ip, #2]
    a.op(0xE1500006)  # cmp r0, r6
    a.jump_label("track", cond=0x8)  # bhi
    a.op(0xE1DC60B4)  # ldrh r6, [ip, #4]
    a.op(0xE1510006)  # cmp r1, r6
    a.jump_label("track", cond=0x3)  # blo
    a.op(0xE1DC60B6)  # ldrh r6, [ip, #6]
    a.op(0xE1510006)  # cmp r1, r6
    a.op(0x93A03001)  # movls r3, #1

    # r2 = touched, r3 = on the badge.
    a.label("track")
    a.ldr_lit(12, CELL)  # ldr ip, =CELL
    a.op(0xE5DC0000)  # ldrb r0, [ip]  (was touched)
    a.op(0xE5DC1001)  # ldrb r1, [ip, #1]  (armed)
    a.op(0xE5CC2000)  # strb r2, [ip]
    a.op(0xE5DC6002)  # ldrb r6, [ip, #2]  (box open)
    a.op(0xE3560000)  # cmp r6, #0
    a.op(0x13A01000)  # movne r1, #0
    a.op(0x15CC1001)  # strbne r1, [ip, #1]  (box open: no arming)
    a.jump_label("poll", cond=0x1)  # bne poll
    a.op(0xE3520000)  # cmp r2, #0
    a.op(0x05CC2001)  # strbeq r2, [ip, #1]  (lifted: disarm)
    a.jump_label("lift", cond=0x0)  # beq lift
    a.op(0xE3500000)  # cmp r0, #0
    a.op(0x01A01003)  # moveq r1, r3  (new press: armed on the badge)
    a.op(0x10011003)  # andne r1, r1, r3  (held: off the badge disarms)
    a.op(0xE5CC1001)  # strb r1, [ip, #1]
    a.jump_label("idle")

    # Hub enter: replaces str r8, [r4, #0x58] (r8 = 0); forget any old box.
    a.label("enter")
    a.op(0xE5848058)  # str r8, [r4, #0x58]
    a.ldr_lit(12, CELL)  # ldr ip, =CELL
    a.op(0xE58C8000)  # str r8, [ip]
    a.op(0xE12FFF1E)  # bx lr

    # Lifted: open page 0 if this press was armed the whole way.
    bb.label("lift")
    bb.op(0xE3500000)  # cmp r0, #0
    bb.op(0x13510000)  # cmpne r1, #0
    bb.jump_label("idle", cond=0x0)  # beq idle
    bb.op(0xE3A00000)  # mov r0, #0  (page)
    # r0 = page, ip = CELL.
    bb.label("open")
    bb.op(0xE5CC0003)  # strb r0, [ip, #3]
    bb.op(0xE2806000 | DIALOG_MODE)  # add r6, r0, #mode
    bb.op(0xE3A01000)  # mov r1, #0
    bb.op(0xE52D1004)  # str r1, [sp, #-4]!  (alt-table flag = 0)
    bb.op(0xE3A00000 | DIALOG_STYLE_INFORMATION)  # mov r0, #style
    bb.op(0xE3A02000)  # mov r2, #0
    bb.op(0xE3A03000)  # mov r3, #0
    bb.op(0xE3A0C000)  # mov ip, #0
    bb.op(0xE92D100F)  # push {r0-r3, ip}  (style, then four empty params)
    bb.ldr_lit(0, DIALOG_MGR_PTR)  # ldr r0, =DIALOG_MGR_PTR
    bb.op(0xE5900000)  # ldr r0, [r0]
    bb.op(0xE3A01000 | DIALOG_LAYOUT)  # mov r1, #layout
    bb.op(0xE1A02006)  # mov r2, r6  (mode of this page)
    bb.op(0xE3A03000 | DIALOG_BUTTONS_OK)  # mov r3, #1
    bb.call(ADDR_OPEN_DIALOG)
    bb.op(0xE28DD018)  # add sp, sp, #0x18
    bb.op(0xE3500000)  # cmp r0, #0
    bb.jump_label("idle", cond=0x0)  # beq idle  (nothing queued)
    bb.ldr_lit(12, CELL)  # ldr ip, =CELL
    bb.op(0xE58C0004)  # str r0, [ip, #4]  (handle)
    bb.op(0xE3A00001)  # mov r0, #1
    bb.op(0xE5CC0002)  # strb r0, [ip, #2]
    bb.jump_label("idle")

    # Box open. Once it reports closed, open the next page.
    bb.label("poll")
    bb.op(0xE59C1004)  # ldr r1, [ip, #4]  (handle)
    bb.ldr_lit(0, DIALOG_MGR_PTR)  # ldr r0, =DIALOG_MGR_PTR
    bb.op(0xE5900000)  # ldr r0, [r0]
    bb.call(ADDR_DIALOG_CLOSED)
    bb.op(0xE3500000)  # cmp r0, #0
    bb.jump_label("idle", cond=0x0)  # beq idle  (still open)
    bb.ldr_lit(12, CELL)  # ldr ip, =CELL
    bb.op(0xE3A00000)  # mov r0, #0
    bb.op(0xE5CC0002)  # strb r0, [ip, #2]
    bb.op(0xE5DC0003)  # ldrb r0, [ip, #3]  (page)
    bb.op(0xE2800001)  # add r0, r0, #1
    bb.op(0xE3500000 | len(CREDIT_PAGES))  # cmp r0, #pages
    bb.jump_label("open", cond=0x3)  # blo open

    bb.label("idle")
    bb.op(0xE3E00000)  # mvn r0, #0  (no row chosen)
    bb.op(0xE8BD8040)  # pop {r6, pc}

    # Hub touch-down (vtable +0x28): ignored while the box is open.
    bb.label("guard")
    bb.ldr_lit(12, CELL)  # ldr ip, =CELL
    bb.op(0xE5DCC002)  # ldrb ip, [ip, #2]
    bb.op(0xE35C0000)  # cmp ip, #0
    bb.op(0x13A00000)  # movne r0, #0
    bb.op(0x112FFF1E)  # bxne lr
    bb.jump(HUB_TOUCH_DOWN)

    blob_b = bb.finish()
    blob_a = a.finish()
    rects = len(blob_a)
    blob_a += b"".join(struct.pack("<4H", *r) for r in BADGE_RECTS)
    off = rects - adr_at - 8
    if not 0 <= off <= 0xFF:
        raise ValueError(f"rect table {off:#x} out of add-immediate range")
    blob_a = blob_a[:adr_at] + _u32(0xE28FC000 | off) + blob_a[adr_at + 4 :]  # add ip, pc, #off
    return blob_a, blob_b, {k: labels[k] for k in ("tap", "enter", "guard")}


def _pad(blob: bytes, start: int, end: int, name: str) -> bytes:
    size = end - start
    if len(blob) > size:
        raise ValueError(f"Eng Patch info cave {name} {len(blob)} > {size}")
    return blob + NOP * ((size - len(blob)) // 4)


def build_regions() -> tuple[bytes, bytes, dict[str, int]]:
    """Both caves NOP-padded to their dead bodies."""
    blob_a, blob_b, entries = build_caves()
    return (
        _pad(blob_a, CAVE_A_START, CAVE_A_END, "A"),
        _pad(blob_b, CAVE_B_START, CAVE_B_END, "B"),
        entries,
    )


def _guard_slot(guard: int) -> bytes:
    return _u32(guard + 0x100000)


def is_patched(data: bytes) -> bool:
    region_a, region_b, e = build_regions()
    return (
        data[CAVE_A_START:CAVE_A_END] == region_a
        and data[CAVE_B_START:CAVE_B_END] == region_b
        and data[HOOK_TAP : HOOK_TAP + 4] == bl(HOOK_TAP, e["tap"])
        and data[HOOK_ENTER : HOOK_ENTER + 4] == bl(HOOK_ENTER, e["enter"])
        and data[HUB_TOUCH_SLOT : HUB_TOUCH_SLOT + 4] == _guard_slot(e["guard"])
    )


def apply_patch(data: bytearray) -> bool:
    region_a, region_b, e = build_regions()
    if is_patched(data):
        print(f"[engpatch-info] already applied @{CAVE_A_START:#x} / {CAVE_B_START:#x}")
        return False
    if data[ADDR_STUB : ADDR_STUB + 4] != STUB_PATCHED:
        raise ValueError(f"{ADDR_STUB:#x} is not bx lr; apply patch_spotpass_skip first")
    if data[CEC_STUB : CEC_STUB + len(CEC_STUB_PATCHED)] != CEC_STUB_PATCHED:
        raise ValueError(f"{CEC_STUB:#x} is not the CecCheckEula stub; apply patch_eula_agreed first")
    body_a = bytes(data[CAVE_A_START:CAVE_A_END])
    # The camera cave used to NOP-pad the whole dead body, this range included.
    if hashlib.sha256(body_a).hexdigest() != CAVE_A_VANILLA_SHA256 and body_a != NOP * (len(body_a) // 4):
        raise ValueError(f"dead body @{CAVE_A_START:#x} is neither vanilla nor NOP padding")
    if hashlib.sha256(bytes(data[CAVE_B_START:CAVE_B_END])).hexdigest() != CAVE_B_VANILLA_SHA256:
        raise ValueError(f"CecCheckEula body @{CAVE_B_START:#x} is not vanilla")
    for addr, vanilla in (
        (HOOK_TAP, HOOK_TAP_VANILLA),
        (HOOK_ENTER, HOOK_ENTER_VANILLA),
        (HUB_TOUCH_SLOT, HUB_TOUCH_SLOT_VANILLA),
    ):
        if data[addr : addr + 4] != vanilla:
            raise ValueError(f"unexpected bytes @{addr:#x}: {data[addr:addr+4].hex()}")
    base = struct.unpack_from("<H", data, 0x006C6F5C + 2 * DIALOG_LAYOUT)[0]
    if base != DIALOG_LAYOUT_BASE:
        raise ValueError(f"dialog layout {DIALOG_LAYOUT} starts at slot {base}, not {DIALOG_LAYOUT_BASE}")
    data[CAVE_A_START:CAVE_A_END] = region_a
    data[CAVE_B_START:CAVE_B_END] = region_b
    data[HOOK_TAP : HOOK_TAP + 4] = bl(HOOK_TAP, e["tap"])
    data[HOOK_ENTER : HOOK_ENTER + 4] = bl(HOOK_ENTER, e["enter"])
    data[HUB_TOUCH_SLOT : HUB_TOUCH_SLOT + 4] = _guard_slot(e["guard"])
    print(
        f"[engpatch-info] badge tap @{HOOK_TAP:#x} -> {e['tap']:#x}, "
        f"enter @{HOOK_ENTER:#x} -> {e['enter']:#x}, hub touch-down guard {e['guard']:#x}"
    )
    return True


def append_info_message(data: bytes) -> tuple[bytes, list[str]]:
    """Add pack 0x1901 slots 502.. (one per credits page); slot 501 must already exist."""
    logs: list[str] = []
    for page, text in enumerate(CREDIT_PAGES):
        data, page_logs = append_message_slot(data, MSG_SLOT + page, text, f"credits {page + 1}")
        logs += page_logs
    return data, logs
