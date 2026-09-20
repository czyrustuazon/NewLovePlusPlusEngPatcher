# Azahar a/b test workflow

Dual isolated Azahar user dirs so you can A/B patches without fighting roaming
`%AppData%\Azahar`. Title ID: `00040000000F4E00`.

Call from **repo root** (shim) or directly:

```powershell
.\make.ps1 help
.\ab_test\make.ps1 help
```

## One-time setup

1. Copy `ab_test/paths.local.ps1.example` → `ab_test/paths.local.ps1` and set
   `AzaharExe` / `VanillaDump` for this machine.
2. Build Azahar if needed: `.\make.ps1 build-azahar`
3. Create instances + launch bats:

```powershell
.\make.ps1 instances
.\make.ps1 seed-a    # optional; deploy-a also seeds if missing
.\make.ps1 seed-b
```

Instance roots (gitignored under `out/`):

```
out/azahar_instances/a/user/
out/azahar_instances/b/user/
```

Each has its own `load/mods/00040000000F4E00/` LayeredFS tree and
`Launch-a.bat` / `Launch-b.bat`.

## Everyday loop

| Goal | Command |
|------|---------|
| Deploy current default stack → A | `.\make.ps1 deploy-a` |
| Same → B | `.\make.ps1 deploy-b` |
| Launch A / B | `.\make.ps1 launch-a` / `launch-b` |
| Roll back default stack on A | `.\make.ps1 restore-a` |
| Fresh A from scratch | `.\make.ps1 all-a` |

**Default `deploy-*` / `restore-*` today** wire the Profile name-input stack
(`tools/deploy_name_input_en.py` + kanji TRB) on whatever img is already in the
instance (usually vanilla from `seed-*`).

**CESA thank-you gold bake A/B** (A = `logo_white` blurb, B = English CESA only / blank right pane):

```powershell
.\make.ps1 instances
.\make.ps1 cesa-ab
.\make.ps1 launch-a
.\make.ps1 launch-b
```

**Local Nene title save** (Checkpoint/Azahar `savedata*` pack in gitignored `ab_test/saves/nene/`):

```powershell
.\make.ps1 save-nene      # A and B
.\make.ps1 save-nene-a    # one instance
```

This overwrites the playable SD slot (`sdmc/.../title/00040000/000f4e00/data/00000001/`). The previous title save is snapshotted under `out/extdata_backup/`. Extra data / DLC caches stay put. Script: `tools/import_azahar_save.py`.

**TalkWindow Message Speed A/B** (A = ÷4 table + voice/script cap, B = ÷4 table only; Options 14/8/2/0 on both):

```powershell
.\make.ps1 talk-speed-ab
.\make.ps1 launch-a
.\make.ps1 launch-b
```

Compare a **heroine date line** vs a player line. Script: `tools/ab_talk_speed.py`.

**Combine Bleeding-Edge bake + name-input:**

```powershell
.\make.ps1 combine-a    # bake img + name_input_code.bin + name-kanji TRB → A
.\make.ps1 combine      # same → roaming AppData
```

Script: `tools/deploy_bleeding_edge_name_input.py`. That is bake **UI** plus the
verified ExeFS/TRB name-input pieces — not “bake TRB alone.”

## Point any script at instance A or B

Deploy / patch scripts that honor `NLPP_AZAHAR_USER_DIR` (or `AZAHAR_USER_DIR`)
write into that instance instead of roaming AppData:

```powershell
$env:NLPP_AZAHAR_USER_DIR = (Resolve-Path out\azahar_instances\a\user)
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
| `ab_test/make.ps1` | Targets: instances, seed, deploy, restore, launch, build-azahar |
| `ab_test/setup_azahar_instances.ps1` | Copies azahar.exe + ICU DLLs; writes Launch-*.bat |
| `ab_test/paths.local.ps1` | Machine paths (gitignored) |
| `ab_test/saves/nene/` | Local Nene title-save pack (`.\make.ps1 save-nene`; gitignored) |
| `out/azahar_instances/{a,b}/` | Isolated user dirs + local azahar copy |
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

## Communications loading hang

Not extra data, not pkg 5237. Local Azahar must **clone** `OpenLinkFile`
handles (same offset/size/subfile) and must **not Close the backend** while
the clone is still live. Patch: `ab_test/patches/azahar-openlinkfile.patch`.
`.\make.ps1 build-azahar` applies it and copies `azahar.exe` into the instance
folders. See `technical.md` **§10.1**.

## Game Start hang (reset continues)

Same extra-data smash, different handle: Game Start `OpenLinkFile`s the
**parent** archive (`size≈1.62 GiB`, `subfile=false`). The clone patch cannot
shrink that. Not hardware; do not restore extra data. See `technical.md` **§10.2**.

## Verify a code.bin patch landed

```powershell
$env:NLPP_AZAHAR_USER_DIR = (Resolve-Path out\azahar_instances\a\user)
python -c "from pathlib import Path; import os; p=Path(os.environ['NLPP_AZAHAR_USER_DIR'])/'load/mods/00040000000F4E00/exefs/code.bin'; d=p.read_bytes(); print(d[FILE_OFF:FILE_OFF+4].hex())"
```

Replace `FILE_OFF` with the file offset you care about (Ghidra image base 0;
runtime VA ≈ file + `0x100000`). Compare against vanilla / expected bytes.

## Agent prefs (hard)

- Do **not** tell the user to “fully quit Azahar” between tests — they already do.
- Feature-specific RE (addresses, bans, verified stacks) lives in `technical.md`,
  not here. Keep this file about **how to run a/b**, not what was last patched.
