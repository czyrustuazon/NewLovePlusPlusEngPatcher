# Azahar a/b test workflow

Dual isolated Azahar user dirs so you can A/B patches without fighting roaming
`%AppData%\Azahar`. Title ID: `00040000000F4E00`.

From the repo root:

```powershell
.\ab_test\make.ps1 help
```

## One-time setup

1. Copy `ab_test/paths.local.ps1.example` → `ab_test/paths.local.ps1` and set
   `AzaharExe`, `VanillaDump`, and optional `RomPath` for this machine.
2. Build Azahar if needed: `.\ab_test\make.ps1 build-azahar`
   That applies `ab_test/patches/azahar-openlinkfile.patch` when `file.cpp` still stubs `OpenLinkFile` (log line `clone offset=`), rebuilds `citra_meta`, and copies `azahar.exe` into `ab_test/azahar_instances/{a,b}/`.
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
