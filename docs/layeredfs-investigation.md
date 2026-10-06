# LayeredFS on real hardware: investigation notes (2026-10-03 / 04)

**Status: unresolved. Ship the CIA.** Drop CIA no longer builds a LayeredFS folder.
This file records what was tried so the next session does not repeat it.

## Symptom

With a Luma LayeredFS drop on a real 3DS (Luma v10.3 and v13):

- CESA warnings draw.
- The top screen draws the heroine and the music plays.
- The bottom (touch) screen stays white. The title menu never appears.

The same files installed as a CIA boot fine. In Azahar, LayeredFS boots fine too,
including the Chinese pack below with our `code.bin`.

## Evidence

### Hardware bisect (Luma title folder contents, console running the unmodified CIA)

| Card contents | Result |
|---|---|
| nothing (pure vanilla) | title shows |
| our `code.bin` only | title shows (Japanese) |
| `code.bin` + our full romfs | white screen |
| `code.bin` + vanilla `img.bin` only | white screen |
| `code.bin` + bake `img.bin` with the Title archive reverted to vanilla size | white screen |
| `code.bin` + a single script file | white (v10.3); real faults (v13), then silent white after guards |
| romfs only, no `code.bin` | **not tested** (our English assets need `code.bin`) |

Later, with the patched CIA installed on the console (so the running code is ours
either way):

| Card contents | Result |
|---|---|
| NLPP_CHN_2.2.2_r4_LayeredFS romfs + our `code.bin` (v13) | CESA in Chinese, heroine on top, bottom white |

So a romfs override **does** take effect on this console. The failure is the title
scene's bottom screen.

### Ruled out

- Our bake content: the same bake boots as a CIA.
- Title archive growth (+9 KB): the variant with the vanilla-size Title archive fails too.
- Archive structure on disk: the card's Title archive is a valid DARC (75 nodes, valid name offsets, matching sizes). Only archive 5261 differs in structure from vanilla; the other changed archives (for example 5189) have identical layout and only pixel data changed.
- Our `code.bin` versus their assets: Azahar boots the Chinese pack plus our `code.bin` to a normal title.
- Reads past 512 MiB: CESA lives at about the same offset as Title and loads fine.
- The CIA's exheader: `patch_cia.py` does not change it.
- Luma version alone: v13 changed the failure from silent to faulting, not to working.

### What the dumps show

All dumps are ARM11 on the `nlpp` process. Addresses are VAs; file offset = VA - 0x100000.
Fixtures are in `tests/fixtures/` (see `tests/test_title_save_fault.py` for the parser).

- Null pane in the title menu update: `ldrb r0,[r6,#0x5f]` at VA `0x3C6070`, `r6 == 0`.
  The only way in is the `beq` at `0x3C5FCC`. The three panes come from the slot-table getter at
  `0x6C5CB0`, called near `0x3C5F00`–`0x3C5F70`.
- Latest all-traps dump (`crash_dump_00000011`, not saved as a fixture): trapped in the pane-flag cave
  (LR `0x6AEC14`) with `r4 = 0x86210f0` (scene object) and `r5 = r6 = r7 = 0`. All three panes are null,
  so the scene registered none of them.
- The same bind loop later (v13) saw a null `this` (`ldr r2,[r6,#0xb2c]` at `0x6C60C4`), then a
  non-null `this` whose `[this+0xB2C]` was the float `1.0` (`0x3F800000`). The object type is wrong.
- Name walk (`0x644D78`, dump 2026-10-03 02:42): resolving the path component `blyt` in an archive whose
  in-memory node table reads as text (`Tit\0` where a name offset belongs) from entry 4 on. A DARC on disk is fine,
  so this looks like a buffer that was never fully filled, or was overwritten.
- Null texture-release lists (`0x6E96DC`) are benign and happen in normal runs. Do not trap on them.

### Structure comparison with the Chinese pack

|  | Vanilla | Ours | NLPP_CHN_2.2.2_r4 |
|---|---|---|---|
| `img.bin` bytes | 712,744,960 | 712,744,960 | 713,013,248 |
| packages with a different size | none | none | 72 (+270 KB total) |
| packages whose offset moved | none | none | 5,614 |

We keep every package in its original slot (exact-size recompression). They rebuilt the image and rewrote
the index. Their notes mention a white screen after repacking images, fixed by an alignment correction
(BCLIM 128-byte alignment). Their README says r4 still needs real-hardware testing.

## Hypotheses (untested)

1. **Short or partial reads.** A LayeredFS file read might return fewer bytes than asked, and the game does not check.
   That would leave stale heap text in a buffer, matching the `Tit\0` table.
2. **Load timing.** The title scene might assume a load takes as long as it does through the CIA path.
   LayeredFS reads straight from the SD file.
3. **File-handle semantics.** Our Azahar build needs an `OpenLinkFile` clone-offset patch for this game.
   Luma's redirect might not handle a linked or cloned handle the way retail FS does.
4. **Heap state.** Allocation order or free space differs, and the title scene fails when it cannot allocate.
5. **Console state.** A game update or other title data installed for this title might confuse the RomFS mount.
   Luma v13.3.3 notes mention update RomFS mount detection.

## What to try next, in order

1. **Baseline on a clean console state.** Reinstall the unmodified CIA, then test the Chinese pack alone
   (vanilla code, no `code.bin`). That proves the mechanism on this console without our code in the picture.
   Then add our `code.bin`, then our own romfs. The console currently has our patched CIA installed, which
   confounds every LayeredFS test.
2. **Check for an installed update or DLC** for this title (System Settings, Data Management).
3. **Trace the title scene on the console.** Put an `UDF` at the title scene init and at the pane-registration
   setter (near `0x6C5D18`), one boot per step. A Luma dump then shows whether each was reached. Narrow it down.
4. **Look for short reads.** Find the file-read wrapper (the `FSFILE_Read` caller), and compare bytes returned with
   bytes requested. A trap on a mismatch, or a retry loop in `code.bin`, would both confirm and fix hypothesis 1
   without changing Luma.
5. **IPS delivery.** `tools/make_code_ips.py` writes a `code.ips` (9,183 bytes for the current `code.bin`).
   It carries the same bytes, so I expect the same result, but it is one boot to rule out.
6. **Ask the Chinese team** whether any 2.2.x LayeredFS build was tested on a real console, and on which Luma.

## Tools in the tree

- `NLPP_DIAG_TRAP=1`: build `code.bin` with each guard's fail branch as a `bl` to a UDF at `0x5D1944`.
  The Luma dump's LR (minus `0x100000`) names the guard. Applied with
  `NLPP_DIAG_TRAP=1 python -c "import patch_chunk_walk_guard as g; ..."` over `release/name_input_code.bin`.
- `NLPP_DIAG_ALL=1` (with the above): also trap the null-object exits (field getter, pane flag).
  The texture-release exits never trap.
- `tools/make_code_ips.py`: vanilla to patched `code.ips`.
- Azahar hooks documented in `ab_test/README.md`: `NLPP_EMU_NAME_WALK_ABORT`, `NLPP_EMU_MENU_VT`, `NLPP_EMU_PANE_FLAG`.
- The crash guards are in `src/patch_chunk_walk_guard.py`. They came from LayeredFS runs and also ship in
  `name_input_code.bin` (the CIA boots with them in place; no CIA without them has been tested).
