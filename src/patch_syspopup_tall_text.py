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
``FUN_001d92f8``'s own pool; Win02 (``0x00227364``) and the pkg 4183 / 4074
copies of the layout keep 256 and their own code.
"""
from __future__ import annotations

import struct

TEXT_H = 1024

# File addresses (runtime VA = +0x100000) of FUN_001d92f8's float pool.
ADDR_V_PER_PIXEL = 0x001D94B8
ADDR_SCALE_PER_PIXEL = 0x001D94C0

_VANILLA = {
    ADDR_V_PER_PIXEL: struct.pack("<f", 1 / 256),
    ADDR_SCALE_PER_PIXEL: struct.pack("<f", 1 / 255),
}
_PATCHED = {
    ADDR_V_PER_PIXEL: struct.pack("<f", 1 / TEXT_H),
    ADDR_SCALE_PER_PIXEL: struct.pack("<f", 256 / (255 * TEXT_H)),
}


def is_patched(data: bytes) -> bool:
    return all(bytes(data[a : a + 4]) == v for a, v in _PATCHED.items())


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print(f"[syspopup-tall] message box already scrolls a {TEXT_H}-tall text")
        return False
    for addr, want in _VANILLA.items():
        got = bytes(data[addr : addr + 4])
        if got != want:
            raise ValueError(f"SysPopup scroll pool @ {addr:#x}: {got.hex()}, expected {want.hex()}")
    for addr, new in _PATCHED.items():
        data[addr : addr + 4] = new
    print(f"[syspopup-tall] message box scroll: text texture 256 -> {TEXT_H} tall")
    return True
