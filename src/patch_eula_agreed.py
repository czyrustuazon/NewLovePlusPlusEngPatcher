"""Let StreetPass turn on without the Nintendo terms-of-use (EULA) check.

Options > Communication Settings > StreetPass asks "Do you want to register
StreetPass for NEW Love Plus on this system?" (``0x002043B4``). Yes passes
three EULA checks, and any of them shows pack ``0x1901`` slot ``0x60``: "To use this
service, you must agree to the latest terms of use..." OK retries and fails
the same way.

1. ``IsEulaAgreed`` @ ``0x004FD248`` (VA ``0x005FD248``), called by the
   registration state machine at ``0x00204418``. It reads the agreed version
   from CFG block ``0x000D0000``, loads the latest version from the system
   EULA archive (``0x005EADCC``) and returns 1 only when the load succeeds and
   agreed >= latest. On 0 the machine queues error 9 (``0x006FE780``).
2. ``CecCheckEula`` @ ``0x00632534`` (VA ``0x00732534``), the CEC library's own
   copy, called from the mailbox setup gate ``0x005FA754``. It does the same
   compare and returns CEC result ``0xE0A1086C`` (module 66, desc 108). The
   result mapper ``0x006F83AC`` turns that into error kind 9, and
   ``0x006F82B8`` shows it as dialog code ``0x2E`` (the same slot ``0x60``).
3. Before check 2 the same gate asks cecd ``ReadData`` info type 2 (EULA
   agreed) and returns ``0xE0A1086C`` when the byte is 0 (``beq`` @
   ``0x004FA79C``). Azahar answers 1; hardware with stale terms would not.
   That ``beq`` is NOP'd. The parental-control query (type 3) stays.

The only way to agree is System Settings > Internet Settings > Review Terms
of Use, which downloads the terms from Nintendo's servers, and those are
offline. Azahar already stores agreed = 0x7F7F; there the archive load is
what fails.

Checks 1 and 2 become "pass" stubs and check 3's branch is a NOP. In
place, no cave. Check 1 also gates the game's online services (SpotPass /
web); those still fail with their own connection errors.

``patch_spotpass_embed`` used to force check 1's failure branch
(``0x0010441C``, "MagList command 9"), which showed this error whatever the
checks returned. It leaves that branch vanilla now.
"""
from __future__ import annotations

# (site, vanilla head, patched head, label)
SITES: tuple[tuple[int, bytes, bytes, str], ...] = (
    (
        0x004FD248,
        bytes.fromhex("38402de9" "0d28a0e3"),  # push {r3-r5,lr}; mov r2,#0xd0000
        bytes.fromhex("0100a0e3" "1eff2fe1"),  # mov r0,#1 (agreed); bx lr
        "IsEulaAgreed",
    ),
    (
        0x00632534,
        bytes.fromhex("70402de9" "10d04de2"),  # push {r4-r6,lr}; sub sp,sp,#0x10
        bytes.fromhex("0000a0e3" "1eff2fe1"),  # mov r0,#0 (ResultSuccess); bx lr
        "CecCheckEula",
    ),
    (
        0x004FA79C,
        bytes.fromhex("1e00000a"),  # beq 0x5fa81c (cecd "EULA agreed" byte == 0)
        bytes.fromhex("00f020e3"),  # nop
        "CecGateEulaFlag",
    ),
)


def is_patched(data: bytes) -> bool:
    return all(bytes(data[s : s + len(p)]) == p for s, _v, p, _l in SITES)


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[eula-agreed] already patched")
        return False
    for site, vanilla, patched, label in SITES:
        cur = bytes(data[site : site + len(vanilla)])
        if cur not in (vanilla, patched):
            raise ValueError(f"unexpected {label} head @{site:#x}: {cur.hex()}")
    for site, _vanilla, patched, label in SITES:
        data[site : site + len(patched)] = patched
        print(f"[eula-agreed] {label} @{site:#x} -> pass")
    return True
