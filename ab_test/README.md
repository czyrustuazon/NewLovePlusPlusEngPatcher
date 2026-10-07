# Azahar a/b test workflow

Dual isolated Azahar user dirs so you can A/B patches without fighting roaming
`%AppData%\Azahar`. Title ID: `00040000000F4E00`.

From the repo root:

```powershell
.\ab_test\make.ps1 help
```

## One-time setup

1. Paths are found automatically when
   [azahar-3ds-accurate](https://github.com/czyrustuazon/azahar-3ds-accurate) is
   checked out next to this repo (`..\azahar-3ds-accurate`, built in `build\`) and
   MSYS2 is at `C:\msys64`. Otherwise copy
   `ab_test/paths.local.ps1.example` → `ab_test/paths.local.ps1` and uncomment what
   differs, or set `NLPP_AZAHAR_SRC` / `NLPP_AZAHAR_EXE` / `NLPP_MSYS_BIN` /
   `NLPP_ROM` / `NLPP_PYTHON`. `.\ab_test\make.ps1 paths` shows what it resolved.
2. Build Azahar if needed: `.\ab_test\make.ps1 build-azahar`
   That configures `build\` on the first run (MSYS2 clang64 + Ninja), builds
   `citra_meta`, and copies `azahar.exe` into `ab_test/azahar_instances/{a,b}/`.
   The fork already has the NLPP changes (OpenLinkFile clone, `NLPP_EMU_*`
   replays). Pointed at a plain upstream Azahar instead, it applies
   `ab_test/patches/azahar-*.patch` first.
3. Create instances + launch bats:

```powershell
.\ab_test\make.ps1 instances
.\ab_test\make.ps1 seed-a    # copies release\ bake into A; deploy-a does the same
.\ab_test\make.ps1 seed-b
```

`seed-*` and `deploy-*` copy the existing post-bake tree. They do not build a
bake and they do not seed vanilla `img.bin`. If `release\bake_img.bin`,
`release\name_input_code.bin`, or `release\romfs_overlay` is missing, the
command stops and prompts: a bake should be done first (Drop CIA, or
`rebuild_bake_img.py --skip-pack` when a bake already exists).

Instance roots (gitignored, outside `out/` so a CIA build does not delete them):

```
ab_test/azahar_instances/a/user/
ab_test/azahar_instances/b/user/
```

Each has its own `load/mods/00040000000F4E00/` LayeredFS tree and
`Launch-a.bat` / `Launch-b.bat`.

Azahar treats the sibling `user/` folder as its portable user root. When
`RomPath` is set, each launcher passes that ROM as Azahar's final positional
argument.

## Smoke boot (automated crash check)

Double-click **`ab_test\Run Safety Checks.bat`** for a menu: code.bin checks,
smoke boot, or the full test suite (`make.ps1 checks` / `smoke` / `test`).

`tools/smoke_boot_azahar.py` boots `release/` in a throwaway copy of instance A
and fails on a data abort. `--inject` turns on the NLPP_EMU_* hardware-crash
replays from [azahar-3ds-accurate](https://github.com/czyrustuazon/azahar-3ds-accurate)
(`..\azahar-3ds-accurate`, branch `main`; exported here as `ab_test/patches/azahar-*.patch`
by `tools/export_azahar_patches.py`). A guarded build passes; restoring a vanilla
instruction at a guarded site fails within seconds. Changes to the emulator go
to the fork first: see `CLAUDE.md`.

```powershell
python tools\smoke_boot_azahar.py --azahar ab_test\azahar_instances\a\azahar.exe `
  --dll-dir C:\msys64\clang64\bin --rom $env:NLPP_ROM `
  --seed-user ab_test\azahar_instances\a\user --inject name-walk,pane-flag,menu-vt
```

`--seed-user` copies that instance's title save; without one the game waits on
its create-save prompt and never reaches the crash sites. The gold-maker runner
runs the same check after each published bake (nlpp-gold-maker `smoke.yml`).

## Everyday loop

| Goal | Command |
|------|---------|
| Deploy current post-bake stack → A | `.\ab_test\make.ps1 deploy-a` |
| Same → B | `.\ab_test\make.ps1 deploy-b` |
| Launch A / B | `.\ab_test\make.ps1 launch-a` / `launch-b` |

`NLPP_EMU_NAME_WALK_ABORT=1` before launch makes Azahar force the 2026-10-01 18:36
directory offset (`0x746954`) and data-abort the vanilla `ldrh` at `0x644D78`.
The name-walk cave replaces that load, so the guarded `code.bin` returns not-found
instead. Rebuild with `.\ab_test\make.ps1 build-azahar` after that emulator change.

`NLPP_EMU_PANE_FLAG=1` before launch nulls `r6` once at the `beq` at `0x3C5FCC`
(first time `[r4+0x50]` is 0), matching the 2026-10-03 00:50 dump: vanilla
`ldrb r0, [r6, #0x5f]` at `0x3C6070` data-aborts with FAR `0x5F`. The guarded
`code.bin` branches to a null check and takes the menu-update epilogue.
| Shared Nene title save → A and B | `.\ab_test\make.ps1 save-nene` |
| Roll back name-input baseline on A | `.\ab_test\make.ps1 restore-a` |
| Instances + post-bake copy onto A | `.\ab_test\make.ps1 all-a` |

**`seed-*` / `deploy-*`** copy what a finished bake already wrote:

| Instance file | Source |
|---------------|--------|
| `romfs/img.bin` | `release/bake_img.bin` |
| `exefs/code.bin` and mod-root `code.bin` | `release/name_input_code.bin` |
| `romfs/**` | `release/romfs_overlay/` |
| `romfs/script/bin/*/*.dbin2` | `rebuild_dbin2/` (same English layers as the CIA) |

**Combine Bleeding-Edge bake + name-input:**

```powershell
.\ab_test\make.ps1 combine-a    # bake img + name_input_code.bin + name-kanji TRB → A
.\ab_test\make.ps1 combine      # same → roaming AppData
```

Script: `tools/deploy_bleeding_edge_name_input.py`. That is bake **UI** plus the
verified ExeFS/TRB name-input pieces — not “bake TRB alone.”

## Point any script at instance A or B

Deploy / patch scripts that honor `NLPP_AZAHAR_USER_DIR` (or `AZAHAR_USER_DIR`)
write into that instance instead of roaming AppData:

```powershell
$env:NLPP_AZAHAR_USER_DIR = (Resolve-Path ab_test\azahar_instances\a\user)
# example — any EngPatcher deploy that uses nlpp_paths:
python tools/deploy_msel_options_en.py
python tools/deploy_name_input_en.py --dry-run
Remove-Item Env:NLPP_AZAHAR_USER_DIR
```

Or set the env inside a small wrapper the same way `ab_test/make.ps1` does
(`Set-DeployEnv`).

## What lives where

| Path | Role |
|------|------|
| `ab_test/make.ps1` | Targets: instances, seed, deploy, restore, launch, build-azahar, save-nene |
| `ab_test/patches/azahar-openlinkfile.patch` | Vendored Azahar `OpenLinkFile` clone fix (`build-azahar` applies it) |
| `ab_test/setup_azahar_instances.ps1` | Copies azahar.exe + ICU DLLs; writes Launch-*.bat |
| `ab_test/paths.local.ps1` | Machine paths (gitignored) |
| `ab_test/azahar_instances/{a,b}/` | Isolated user dirs + local azahar copy |
| `ab_test/saves/nene/` | Local Nene title save (gitignored). `save-nene` installs it |
| `src/nlpp_paths.py` | Resolves Azahar mod paths from env |

## LayeredFS notes

- If `load/mods/00040000000F4E00/` exists under the instance user dir, mods apply
  on launch (no separate “enable mods” toggle).
- Log markers when a patch is live:

```
load/mods/00040000000F4E00/exefs/code.bin overriding built-in ExeFS file
LayeredFS replacement file in use for /img.bin
```

- Prefer instance A for the “new” experiment and B for baseline / previous
  known-good, then swap by redeploying.

## Verify a code.bin patch landed

```powershell
$env:NLPP_AZAHAR_USER_DIR = (Resolve-Path ab_test\azahar_instances\a\user)
python -c "from pathlib import Path; import os; p=Path(os.environ['NLPP_AZAHAR_USER_DIR'])/'load/mods/00040000000F4E00/exefs/code.bin'; d=p.read_bytes(); print(d[FILE_OFF:FILE_OFF+4].hex())"
```

Replace `FILE_OFF` with the file offset you care about (Ghidra image base 0;
runtime VA ≈ file + `0x100000`). Compare against vanilla / expected bytes.

## MCP server

`tools/ab_mcp_server.py` (registered in the repo-root `.mcp.json`, needs `pip install mcp`)
exposes this workflow to agents: `ab_make` (allow-listed `make.ps1` targets; not
`progress`, which POSTs), `ab_status`, `ab_diff` (A vs B mod tree), `ab_read_bytes`,
`ab_log_tail`, `ab_log_search`, `ab_log_markers`, `ab_stop` (kills that instance's
azahar.exe only).

## Agent prefs (hard)

- Do **not** tell the user to “fully quit Azahar” between tests — they already do.
- Feature-specific RE (addresses, bans, verified stacks) lives in `docs/technical.md`,
  not here. Keep this file about **how to run a/b**, not what was last patched.
