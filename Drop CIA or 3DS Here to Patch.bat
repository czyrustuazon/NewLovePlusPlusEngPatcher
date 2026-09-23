@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM Drag a New Love Plus+ .cia / .3ds / .cci onto this file, or double-click for a drop window.
title New Love Plus+ - Drop ROM to Patch
set "SRC=%~dp0src"

if not "%~1"=="" goto :run_patch

where powershell >nul 2>&1
if errorlevel 1 (
  echo Double-click opens a drop window ^(needs PowerShell^).
  echo Or drag a .cia / .3ds / .cci file onto this bat.
  echo.
  set /p "CIA=ROM path: "
  if "%CIA%"=="" exit /b 1
  call "%~f0" "%CIA%"
  exit /b %ERRORLEVEL%
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%\drop_zone.ps1"
exit /b %ERRORLEVEL%

:run_patch
REM Stage dump path via PowerShell first. Names with Japanese glyphs or parentheses
REM (e.g. piratelegit "NEWラブプラス＋ (CTR-P-BLPJ) (v0.2.0)...") break cmd parsing
REM if we expand %~1 / %~nx1 inside IF blocks.
REM Read the result from a temp file — never for /f over powershell stdout
REM (error text like "Copy-Item" can leak into the captured path).
set "NLPP_ROM=%~1"
set "NLPP_DROP_PATH_FILE=%TEMP%\nlpp_drop_path.txt"
if exist "%NLPP_DROP_PATH_FILE%" del /f /q "%NLPP_DROP_PATH_FILE%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\short_path.ps1"
set "NLPP_ROM="
set "CIA="
if exist "%NLPP_DROP_PATH_FILE%" (
  set /p CIA=<"%NLPP_DROP_PATH_FILE%"
  del /f /q "%NLPP_DROP_PATH_FILE%" >nul 2>&1
)
set "NLPP_DROP_PATH_FILE="
if not defined CIA (
  echo [!] Could not resolve dump path.
  pause
  exit /b 1
)
for %%I in ("%CIA%") do (
  set "EXT=%%~xI"
  set "CIA_NAME=%%~nxI"
)

if /i not "%EXT%"==".cia" if /i not "%EXT%"==".3ds" if /i not "%EXT%"==".cci" (
  echo.
  echo [!] Drop a .cia / .3ds / .cci file ^(got: !CIA_NAME!^)
  echo.
  pause
  exit /b 1
)

if not exist "%CIA%" (
  echo [!] File not found:
  echo     "%CIA%"
  pause
  exit /b 1
)

REM Resolve a real Python (not the Microsoft Store stub). Prefer PATH, then py launcher,
REM then common install folders — new installs often only get "py" or miss PATH.
call :find_python
if not defined PYTHON (
  echo.
  echo [!] Python 3.10+ not found.
  echo.
  echo     Fix ^(pick one^):
  echo       1. Install from https://www.python.org/downloads/
  echo          and CHECK "Add python.exe to PATH"
  echo       2. Or install from Microsoft Store: "Python 3.12"
  echo.
  echo     If you disabled "App execution aliases" for python.exe:
  echo     that only helps after a real install is on PATH / via py.
  echo     Try opening a NEW Command Prompt and running:  py -3 --version
  echo.
  pause
  exit /b 1
)

echo.
echo  ============================================
echo   New Love Plus+ English Patcher
echo  ============================================
echo.
echo  Dropped:
echo    "%CIA%"
echo  Using:
echo    %PYTHON%
echo.

REM Do not use FOR /F around '"%PYTHON%" -c "import ...' — cmd treats
REM 'C:\...\python.exe" -c "import' as the executable name (quote pairing).
REM Write the unix stamp to a temp file instead (same pattern as SHA-1).
set "NLPP_T0="
set "NLPP_T0_FILE=%TEMP%\nlpp_t0.txt"
if exist "%NLPP_T0_FILE%" del /f /q "%NLPP_T0_FILE%" >nul 2>&1
"%PYTHON%" "%SRC%\run_timer.py" --now > "%NLPP_T0_FILE%"
if exist "%NLPP_T0_FILE%" (
  set /p NLPP_T0=<"%NLPP_T0_FILE%"
  del /f /q "%NLPP_T0_FILE%" >nul 2>&1
)
set "NLPP_T0_FILE="
if defined NLPP_T0 echo [timer] Drop CIA started
REM Pass Drop start into patch_cia.py so PATCH SUMMARY elapsed includes bake.
set "STARTED_UNIX="
if defined NLPP_T0 set STARTED_UNIX=--started-unix !NLPP_T0!

echo Installing Python deps from requirements.txt ...
"%PYTHON%" -m pip install -q -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo [!] pip install failed. Try: %PYTHON% -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo.
echo Fetching / checking CIA tools ^(3dstool, ctrtool, makerom, seeddb^) ...
echo Decrypt your dump yourself first - this patcher does not include decrypt.exe.
"%PYTHON%" "%SRC%\setup_tools.py"
if errorlevel 1 (
  echo [!] Tool setup failed.
  pause
  exit /b 1
)

REM SHA-1 gate: known dumps pass; unknown dumps ask before continuing with --skip-hash.
set "SKIP_HASH="
echo.
echo Checking dump SHA-1 ^(this may take a minute on large .3ds files^)...
"%PYTHON%" -c "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from patch_cia import sha1_file, ALLOWED_DUMP_SHA1; p=Path(sys.argv[2]); d=sha1_file(p); print(d); raise SystemExit(0 if d.lower() in ALLOWED_DUMP_SHA1 else 2)" "%SRC%" "%CIA%" > "%TEMP%\nlpp_sha1.txt" 2>nul
set HASH_ERR=!ERRORLEVEL!
set "GOT_SHA1="
if exist "%TEMP%\nlpp_sha1.txt" (
  set /p GOT_SHA1=<"%TEMP%\nlpp_sha1.txt"
  del "%TEMP%\nlpp_sha1.txt" >nul 2>&1
)

if "!HASH_ERR!"=="0" (
  echo [hash] OK — known dump
  echo         !GOT_SHA1!
  REM Already verified here; skip the second full-file hash inside patch_cia.py.
  set "SKIP_HASH=--skip-hash"
) else if "!HASH_ERR!"=="2" (
  echo.
  echo [!] SHA-1 is not in the known-dump allowlist.
  echo     got: !GOT_SHA1!
  echo.
  echo     This may still be a valid dump ^(e.g. a decrypted CIA with a
  echo     different hash^), but it was not verified against the list.
  echo.
  set /p "CONT=Continue patching anyway? [y/N]: "
  if /i not "!CONT!"=="y" if /i not "!CONT!"=="yes" (
    echo Aborted.
    pause
    exit /b 1
  )
  echo [hash] continuing with --skip-hash
  set "SKIP_HASH=--skip-hash"
) else (
  echo [!] Could not compute SHA-1 ^(exit !HASH_ERR!^).
  set /p "CONT=Continue without hash check? [y/N]: "
  if /i not "!CONT!"=="y" if /i not "!CONT!"=="yes" (
    echo Aborted.
    pause
    exit /b 1
  )
  set "SKIP_HASH=--skip-hash"
)

echo.
echo Wiping out\ and release\ before this build...
echo Previous CIA, logs, Azahar copies, extra-data backups, gold bake,
echo TRB overlay, and name-input code.bin in those folders are deleted.
echo cache\ is left as-is. Close anything using files under out\ or release\.
"%PYTHON%" "%SRC%\scratch_cleanup.py" --wipe-cia-build
if errorlevel 1 (
  echo [!] Could not wipe out\ and release\.
  echo     Close programs that have files open in those folders, then drop again.
  pause
  exit /b 1
)
echo.

echo Injecting scripts + UI / rebuilding CIA...
echo Requires a decrypted .cia or .3ds/.cci ^(decrypt yourself first^).
echo This can take several minutes and needs a few GB free disk.
echo.

REM Use an extracted RomFS as a *source copy* only — never --in-place-romfs
REM (in-place previously overwrote img.bin with a bad UI pack).
set "EXTRA_ROMFS="
set "SIBLING_ROMFS=%~dp0..\New Love Plus Plus\extracted\romfs"
set "CACHE_ROMFS=%~dp0cache\vanilla_from_rom\romfs"
if exist "%SIBLING_ROMFS%\script\bin\script" (
  echo Using RomFS template from sibling extracted ^(copied, not in-place^)
  REM Keep quotes inside the value so paths with spaces survive expansion.
  set EXTRA_ROMFS=--romfs "%SIBLING_ROMFS%"
) else if exist "%CACHE_ROMFS%\script\bin\script" (
  echo Using RomFS template from cache\vanilla_from_rom ^(copied, not in-place^)
  set EXTRA_ROMFS=--romfs "%CACHE_ROMFS%"
)

REM UI ON by default. out\ and release\ were wiped above; this run fills them again.
REM   release\bake_img.bin     — gold bake (built locally; gitignored)
REM   release\romfs_overlay\   — TRB overlays (auto-applied when present)
REM Optional PNG scratch:
REM   cache\new_img.bin        — PNG pack only (incomplete vs gold; NLPP_REPACK_IMAGES=1)
REM Opt out: set NLPP_WITH_IMAGES=0
REM Force PNG scratch rebuild: set NLPP_REPACK_IMAGES=1
REM Bake was just deleted, so the stamp check fails and this run packs locally.
REM   NLPP_REUSE_BAKE=1  skips that stamp check and may poll GitHub first
REM   NLPP_SKIP_GOLD_FETCH=1  offline — skip CI poll, build locally only
if not exist "%~dp0cache" mkdir "%~dp0cache"
REM Keep quotes inside the value so paths with spaces survive expansion
REM (e.g. E:\zip game\... GitHub unzip folders).
REM LayeredFS is written next to the CIA. code.bin is name_input_code.bin
REM so English graphics load. Install the CIA or this folder, not both.
set LAYEREDFS=--layeredfs-out "%~dp0out\1_[Either use this-LayerFS]\luma"
set "PACKED_IMG=%~dp0release\bake_img.bin"
if exist "%~dp0release\bake_img.bin" (
  echo Using gold bake: release\bake_img.bin
) else if exist "%~dp0cache\bake_img.bin" (
  REM legacy path during transition
  set "PACKED_IMG=%~dp0cache\bake_img.bin"
  echo Using legacy bake: cache\bake_img.bin ^(move to release\^)
)
if exist "%~dp0release\romfs_overlay\SystemData" (
  echo TRB overlay will auto-apply from release\romfs_overlay
) else if exist "%~dp0cache\romfs_overlay\SystemData" (
  echo TRB overlay will auto-apply from cache\romfs_overlay ^(legacy^)
)
set "INJECT_CODE="
REM Profile name-input is required for a complete Drop (built by rebuild_bake_img).
if exist "%~dp0release\name_input_code.bin" (
  set INJECT_CODE=--inject-code "%~dp0release\name_input_code.bin"
  echo Including Profile name-input code.bin from release\name_input_code.bin
)
if /i "%NLPP_WITH_IMAGES%"=="0" (
  echo.
  echo [!] NLPP_WITH_IMAGES=0 is not allowed — incomplete patches are disabled.
  echo     Drop always builds a full CIA ^(UI gold bake + Eng Patch + name-input^).
  echo.
  pause
  exit /b 1
)
if /i "%NLPP_REPACK_IMAGES%"=="1" (
  echo UI packing — rebuilding cache\new_img.bin from assets\images ^(not gold bake^)
  if not defined INJECT_CODE (
    echo [!] release\name_input_code.bin required. Run rebuild_bake_img.py --rom first.
    pause
    exit /b 1
  )
  "%PYTHON%" "%SRC%\patch_cia.py" --cia "%CIA%" --out "%~dp0out\2_[Or this]\NewLovePlusPlus-EN.cia" --packed-img "%~dp0cache\new_img.bin" --repack-images !EXTRA_ROMFS! %SKIP_HASH% !LAYEREDFS! !INJECT_CODE! !STARTED_UNIX!
) else (
  REM RC: leftover bake from an older unzip is ignored unless bake_stamp matches.
  set "BAKE_STALE="
  if /i not "%NLPP_REUSE_BAKE%"=="1" (
    "%PYTHON%" "%SRC%\patcher_version.py"
    if errorlevel 1 set "BAKE_STALE=1"
  )
  if defined BAKE_STALE (
    echo.
    echo RC: bake stamp missing, other release, or UI PNGs changed — packing from this tree.
    echo Leftover release\bake_img.bin will be overwritten ^(from scratch^).
    echo Set NLPP_REUSE_BAKE=1 to inject the existing bake anyway.
    echo.
  )
  set "NEED_REBUILD="
  if defined BAKE_STALE set "NEED_REBUILD=1"
  if not exist "%~dp0release\bake_img.bin" if not exist "%~dp0cache\bake_img.bin" set "NEED_REBUILD=1"
  set "PACK_CACHE="
  if /i "%NLPP_USE_PACK_CACHE%"=="1" set "PACK_CACHE=--use-cache"
  if defined NEED_REBUILD (
    REM Gold bake required. CI fetch only when reusing an unstamped-missing bake
    REM ^(NLPP_REUSE_BAKE=1^). RC from-scratch skips fetch so an old gold zip
    REM cannot mask this tree's assets.
    if not defined BAKE_STALE if /i not "%NLPP_SKIP_GOLD_FETCH%"=="1" (
      echo.
      echo No gold bake at release\bake_img.bin — polling GitHub Release tag gold...
      echo ^(set NLPP_GITHUB_REPO=OWNER/nlpp-gold-maker if auto-detect fails^)
      echo.
      "%PYTHON%" "%~dp0tools\fetch_release_bake.py" --best-effort
      if errorlevel 1 (
        echo [fetch] No published gold bake — will build locally from assets.
      )
    )
    if not exist "%~dp0release\bake_img.bin" if not exist "%~dp0cache\bake_img.bin" (
      echo.
      echo No gold bake at release\bake_img.bin — running tools\rebuild_bake_img.py
      echo This builds bake + textresource TRBs from assets\ ^(PNG pack + deploy chrome^).
      echo Vanilla img.bin comes from the dropped ROM if no sibling extracted\ exists.
      echo RC from-scratch pack ignores cache\img_pack. Leave this window open.
      echo.
      "%PYTHON%" "%~dp0tools\rebuild_bake_img.py" --rom "%CIA%" !PACK_CACHE!
      if errorlevel 1 (
        echo [!] rebuild_bake_img.py failed — see traceback above.
        echo     Common fixes:
        echo       pip install -r requirements.txt
        echo       ^(needs Pillow numpy zopfli etcpak PyYAML^)
        echo       Or set NLPP_VANILLA_IMG if vanilla extract failed.
        pause
        exit /b 1
      )
      REM Rebuild may have just filled cache\vanilla_from_rom — prefer it as RomFS template.
      if not defined EXTRA_ROMFS if exist "%CACHE_ROMFS%\script\bin\script" (
        echo Using RomFS template from cache\vanilla_from_rom ^(copied, not in-place^)
        set EXTRA_ROMFS=--romfs "%CACHE_ROMFS%"
      )
    ) else if defined BAKE_STALE (
      echo.
      echo Overwriting leftover gold bake — running tools\rebuild_bake_img.py
      echo RC from-scratch pack ignores cache\img_pack. Leave this window open.
      echo.
      "%PYTHON%" "%~dp0tools\rebuild_bake_img.py" --rom "%CIA%" !PACK_CACHE!
      if errorlevel 1 (
        echo [!] rebuild_bake_img.py failed — see traceback above.
        echo     Common fixes:
        echo       pip install -r requirements.txt
        echo       ^(needs Pillow numpy zopfli etcpak PyYAML^)
        echo       Or set NLPP_VANILLA_IMG if vanilla extract failed.
        pause
        exit /b 1
      )
      if not defined EXTRA_ROMFS if exist "%CACHE_ROMFS%\script\bin\script" (
        echo Using RomFS template from cache\vanilla_from_rom ^(copied, not in-place^)
        set EXTRA_ROMFS=--romfs "%CACHE_ROMFS%"
      )
    )
    if not exist "%~dp0release\bake_img.bin" if not exist "%~dp0cache\bake_img.bin" (
      echo.
      echo [!] No gold bake available. English menus need release\bake_img.bin.
      echo     Run: python tools\rebuild_bake_img.py --rom your.cia
      echo     ^(must finish — first run is often ~16 hours^)
      echo     Or scripts-only: set NLPP_WITH_IMAGES=0
      pause
      exit /b 1
    )
    if exist "%~dp0release\bake_img.bin" (
      set "PACKED_IMG=%~dp0release\bake_img.bin"
    ) else (
      set "PACKED_IMG=%~dp0cache\bake_img.bin"
    )
    echo Using gold bake: !PACKED_IMG!
  )
  if not exist "!PACKED_IMG!" (
    echo [!] Gold bake path missing: !PACKED_IMG!
    pause
    exit /b 1
  )
  REM Incomplete gold artifacts: finish rebuild (keeps PNG pack) until Eng_Patch
  REM and name_input_code.bin both exist — never inject a partial CIA.
  set "NEED_FINISH="
  "%PYTHON%" -c "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from patch_cia import _title_pkg_has_eng_patch; raise SystemExit(0 if _title_pkg_has_eng_patch(Path(sys.argv[2])) else 2)" "%SRC%" "!PACKED_IMG!" >nul 2>&1
  if errorlevel 2 set "NEED_FINISH=1"
  if not exist "%~dp0release\name_input_code.bin" set "NEED_FINISH=1"
  if defined NEED_FINISH (
    echo.
    echo Gold artifacts incomplete ^(Eng Patch and/or name_input_code.bin missing^).
    echo Finishing with rebuild_bake_img.py --skip-pack ^(retries; no soft skips^)...
    echo.
    "%PYTHON%" "%~dp0tools\rebuild_bake_img.py" --rom "%CIA%" --skip-pack
    if errorlevel 1 (
      echo [!] rebuild_bake_img.py --skip-pack failed — see traceback above.
      echo     Re-run Drop after fixing the error; incomplete CIAs are not emitted.
      pause
      exit /b 1
    )
    if exist "%~dp0release\bake_img.bin" (
      set "PACKED_IMG=%~dp0release\bake_img.bin"
    )
    if not defined EXTRA_ROMFS if exist "%CACHE_ROMFS%\script\bin\script" (
      echo Using RomFS template from cache\vanilla_from_rom ^(copied, not in-place^)
      set EXTRA_ROMFS=--romfs "%CACHE_ROMFS%"
    )
  )
  if not exist "%~dp0release\name_input_code.bin" (
    echo [!] release\name_input_code.bin still missing after rebuild — aborting.
    pause
    exit /b 1
  )
  set INJECT_CODE=--inject-code "%~dp0release\name_input_code.bin"
  echo Including Profile name-input code.bin from release\name_input_code.bin
  echo Injecting gold bake: !PACKED_IMG!
  "%PYTHON%" "%SRC%\patch_cia.py" --cia "%CIA%" --out "%~dp0out\2_[Or this]\NewLovePlusPlus-EN.cia" --packed-img "!PACKED_IMG!" !EXTRA_ROMFS! %SKIP_HASH% !LAYEREDFS! !INJECT_CODE! !STARTED_UNIX!
)
set ERR=%ERRORLEVEL%

echo.
if not "%ERR%"=="0" (
  echo.
  echo [!] Patch failed ^(exit %ERR%^).
  pause
  exit /b %ERR%
)

echo [+] Patched CIA:
echo     %~dp0out\2_[Or this]\NewLovePlusPlus-EN.cia
echo [+] LayeredFS ^(use this or the CIA, not both^):
echo     %~dp0out\1_[Either use this-LayerFS]\luma\00040000000F4E00
echo     Copy that folder to SD:/luma/titles/ and enable game patching.
echo     code.bin is included so English graphics load.
echo.
if defined NLPP_T0 (
  set "NLPP_ELAPSED="
  set "NLPP_ELAPSED_FILE=%TEMP%\nlpp_elapsed.txt"
  if exist "!NLPP_ELAPSED_FILE!" del /f /q "!NLPP_ELAPSED_FILE!" >nul 2>&1
  "%PYTHON%" "%SRC%\run_timer.py" !NLPP_T0! > "!NLPP_ELAPSED_FILE!"
  if exist "!NLPP_ELAPSED_FILE!" (
    set /p NLPP_ELAPSED=<"!NLPP_ELAPSED_FILE!"
    del /f /q "!NLPP_ELAPSED_FILE!" >nul 2>&1
  )
  set "NLPP_ELAPSED_FILE="
  if defined NLPP_ELAPSED (
    echo [+] Time to finish: !NLPP_ELAPSED!
    echo.
  )
)
echo [+] Scroll up for PATCH SUMMARY ^([OK] lines — incomplete patches abort^).
echo [+] Patch log ^(same summary^):
echo     %~dp0out\logs\latest.txt
echo     ^(timestamped copies stay in out\logs\^)
echo.
echo [+] Install over the existing title in FBI/Azahar. Do NOT delete the title first
echo     ^(that orphans extra data^). CIA title version is CIA_TITLE_VERSION for this RC
echo     ^(src\patcher_version.py^). Bump that number when merging an RC into main.
echo.
echo [+] Azahar extra data backup/restore:
echo     python tools\restore_azahar_extdata.py backup
echo     python tools\restore_azahar_extdata.py restore
echo.
echo [+] out\ cleaned ^(scratch removed; kept the CIA folder + logs + extdata_backup^).
echo     SpotPass ^(optional^): python tools\build_spotpass_inject.py
echo.

REM Soft-update companion site script-text progress bar (optional .env /
REM NLPP_PROGRESS_*). Missing config or network must never fail the patch.
echo Reporting script-text progress ^(optional^)...
"%PYTHON%" "%SRC%\report_progress.py" --best-effort
if errorlevel 1 echo [progress] optional update skipped ^(patch still OK^)
echo.
pause
exit /b 0

:find_python
set "PYTHON="
REM 1) python on PATH — skip the zero-byte Microsoft Store alias stub
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON call :try_python "%%P"
  )
)
if defined PYTHON exit /b 0

REM 2) Windows Python launcher (survives missing PATH / disabled aliases)
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable) if sys.version_info >= (3,10) else None" 2^>nul') do (
    if not defined PYTHON if exist "%%P" call :try_python "%%P"
  )
)
if defined PYTHON exit /b 0

REM 3) Common install locations when PATH was never set
for %%V in (314 313 312 311 310) do (
  if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
    call :try_python "%LocalAppData%\Programs\Python\Python%%V\python.exe"
  )
)
if defined PYTHON exit /b 0
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
  if not defined PYTHON if exist "%ProgramFiles%\Python%%V\python.exe" (
    call :try_python "%ProgramFiles%\Python%%V\python.exe"
  )
)
if defined PYTHON exit /b 0
if exist "%LocalAppData%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python*\python.exe" (
  for /d %%D in ("%LocalAppData%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python*") do (
    if not defined PYTHON if exist "%%D\python.exe" call :try_python "%%D\python.exe"
  )
)
exit /b 0

:try_python
REM Reject Store stub (opens Store / tiny file) and require 3.10+
set "CAND=%~1"
if not exist "%CAND%" exit /b 1
for %%A in ("%CAND%") do if %%~zA LSS 1024 exit /b 1
REM Bare WindowsApps\python.exe is the Store alias stub; real Store Python is under PythonSoftwareFoundation.*
set "CAND_DIR=%~dp1"
echo "%CAND_DIR%" | findstr /i /c:"\WindowsApps\" >nul
if not errorlevel 1 (
  echo "%CAND_DIR%" | findstr /i /c:"PythonSoftwareFoundation" >nul
  if errorlevel 1 exit /b 1
)
"%CAND%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PYTHON=%CAND%"
exit /b 0
