"""Scroll the SysPopup message box over a 1024-tall text texture.

The message box (``Lyt_C_Com_Win01`` in pkg 5259, class ctor ``0x001D9BAC``)
does not clip long text with its stencil mask. Once the text runs past 8
lines (14 px each), ``FUN_001d92f8`` windows the text pic every frame:

* texture V = (scroll + 67) * 1/256, clamped to 1.0, for the visible slice;
* pane scale Y = window height * 1/255, so the 256-tall pane shrinks to the
  window.

Both constants assume a 256-tall ``Tex_Sentence``. ``deploy_ui_buttons_en``
makes that pane (and so its texture) ``TEXT_H`` tall for the localization
credits, so without this the slice clamps to the whole texture and the pane
draws four times the window height over the screen.

V uses 1/TEXT_H (same pixel slice as vanilla). Scale uses
256 / (255 * TEXT_H), the vanilla on-screen height. Both literals sit in
``FUN_001d92f8``'s own pool; Win02 (``0x00227364``) keeps 256 and its own
code. The map's own ``Lyt_C_Com_Win01`` (pkg 4183 ``Common.arc``; pkg 4074
``map_layout.arc`` has a 136-tall copy) is built by factory ``0x0018E378``
into a different class (vtable ``0x0080D738``) that shares none of this code.

Progress boxes (modes 3 / 4) draw their text from the top of the texture at a
fixed pane position, so the taller pane hid it; see ``ADDR_PROGRESS_MODE3``.
"""
from __future__ import annotations

import struct

TEXT_H = 1024

# File addresses (runtime VA = +0x100000) of FUN_001d92f8's float pool.
ADDR_V_PER_PIXEL = 0x001D94B8
ADDR_SCALE_PER_PIXEL = 0x001D94C0

# Box modes 3 and 4 of the text setup (FUN_001d94d0, jump table 0x1D9668) are
# the progress boxes: they clear the pic's +0x181 (draw the text from the top
# of the texture, not centred) and park the centre-origin pane at y = -67, so
# its top edge sits under the header at -67 + 256/2. With a TEXT_H-tall pane
# that edge went to -67 + TEXT_H/2 and "Creating extra data on the SD card."
# drew off screen. They now store y = -67 - (TEXT_H - 256)/2 instead.
# x and z are already 0 from the setup's own reset at 0x1D9554 / 0x1D955C.
ADDR_PROGRESS_MODE3 = 0x001D96E4
ADDR_PROGRESS_MODE4 = 0x001D975C
TOP_TEXT_Y = -67 - (TEXT_H - 256) / 2
assert struct.pack("<f", TOP_TEXT_Y) == struct.pack("<I", 0xC3000000 | 0xE10000 | 0x8000)


def _words(*words: int) -> bytes:
    return struct.pack(f"<{len(words)}I", *words)


def _progress_vanilla(r2: int) -> bytes:
    return _words(
        0xE3A00000,  # mov   r0, #0
        0xE5C60181,  # strb  r0, [r6, #0x181]
        0xE2860028,  # add   r0, r6, #0x28
        0xE3A03000,  # mov   r3, #0
        0xEC808A02,  # vstmia r0, {s16, s17}   ; x = 0, y = -67
        0xE3A02000 | r2,  # mov r2, #r2
        0xED868A0C,  # vstr  s16, [r6, #0x30]  ; z = 0
    )


def _progress_patched(r2: int) -> bytes:
    return _words(
        0xE3A03000,  # mov   r3, #0
        0xE5C63181,  # strb  r3, [r6, #0x181]
        0xE3A004C3,  # mov   r0, #0xC3000000
        0xE38008E1,  # orr   r0, r0, #0xE10000
        0xE3800C80,  # orr   r0, r0, #0x8000   ; TOP_TEXT_Y
        0xE586002C,  # str   r0, [r6, #0x2c]
        0xE3A02000 | r2,  # mov r2, #r2
    )


_VANILLA = {
    ADDR_V_PER_PIXEL: struct.pack("<f", 1 / 256),
    ADDR_SCALE_PER_PIXEL: struct.pack("<f", 1 / 255),
    ADDR_PROGRESS_MODE3: _progress_vanilla(8),
    ADDR_PROGRESS_MODE4: _progress_vanilla(4),
}
_PATCHED = {
    ADDR_V_PER_PIXEL: struct.pack("<f", 1 / TEXT_H),
    ADDR_SCALE_PER_PIXEL: struct.pack("<f", 256 / (255 * TEXT_H)),
    ADDR_PROGRESS_MODE3: _progress_patched(8),
    ADDR_PROGRESS_MODE4: _progress_patched(4),
}


def is_patched(data: bytes) -> bool:
    return all(bytes(data[a : a + len(v)]) == v for a, v in _PATCHED.items())


def apply_patch(data: bytearray) -> bool:
    """Patch each site that is still vanilla. A code.bin from before the
    progress-box fix has only the scroll pool and gets the rest."""
    if is_patched(data):
        print(f"[syspopup-tall] message box already scrolls a {TEXT_H}-tall text")
        return False
    todo = []
    for addr, want in _VANILLA.items():
        got = bytes(data[addr : addr + len(want)])
        if got == _PATCHED[addr]:
            continue
        if got != want:
            raise ValueError(f"SysPopup message box @ {addr:#x}: {got.hex()}, expected {want.hex()}")
        todo.append(addr)
    for addr in todo:
        data[addr : addr + len(_PATCHED[addr])] = _PATCHED[addr]
    print(f"[syspopup-tall] message box text texture 256 -> {TEXT_H} tall")
    return True
