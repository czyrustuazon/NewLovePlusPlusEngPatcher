# NLPP a/b Azahar workflow. From the repo root: .\ab_test\make.ps1 help
param(
    [Parameter(Position = 0)]
    [string]$Target = "help"
)

$ErrorActionPreference = "Stop"
$AbTest = $PSScriptRoot
$EngPatcher = Split-Path -Parent $AbTest
$Parent = Split-Path -Parent $EngPatcher

# --- paths ---
# Empty entries are filled in below. Override with NLPP_AZAHAR_SRC /
# NLPP_AZAHAR_EXE / NLPP_MSYS_BIN / NLPP_ROM / NLPP_PYTHON, or in
# ab_test/paths.local.ps1 (copy paths.local.ps1.example).
$Paths = @{
    AzaharSrc    = $env:NLPP_AZAHAR_SRC
    AzaharBuild  = ""
    AzaharExe    = $env:NLPP_AZAHAR_EXE
    MsysBin      = $env:NLPP_MSYS_BIN
    VanillaDump  = Join-Path $EngPatcher "cache\vanilla_from_rom"
    RomPath      = $env:NLPP_ROM
    PythonExe    = $env:NLPP_PYTHON
    Instances    = Join-Path $AbTest "azahar_instances"
    TitleId      = "00040000000F4E00"
}

$LocalPaths = Join-Path $AbTest "paths.local.ps1"
if (Test-Path $LocalPaths) { . $LocalPaths }

# Default: the azahar-3ds-accurate fork next to this repo (CLAUDE.md), else a
# plain Azahar checkout (..\azahar) that build-azahar patches. Built in build\.
if (-not $Paths.AzaharSrc) {
    $fork = Join-Path $Parent "azahar-3ds-accurate"
    $Paths.AzaharSrc = if (Test-Path (Join-Path $fork "NLPP.md")) { $fork } else { Join-Path $Parent "azahar" }
}
if (-not $Paths.AzaharBuild) { $Paths.AzaharBuild = Join-Path $Paths.AzaharSrc "build" }
if (-not $Paths.AzaharExe) {
    $Paths.AzaharExe = Join-Path $Paths.AzaharBuild "bin\Release\azahar.exe"
    $flat = Join-Path $Paths.AzaharBuild "bin\azahar.exe"
    if (-not (Test-Path $Paths.AzaharExe) -and (Test-Path $flat)) { $Paths.AzaharExe = $flat }
}
# MSYS2's default install location; set MsysBin if yours lives elsewhere.
if (-not $Paths.MsysBin) { $Paths.MsysBin = "C:\msys64\clang64\bin" }

function Get-InstanceUser([string]$Id) {
    Join-Path $Paths.Instances "$Id\user"
}

function Set-DeployEnv([string]$InstanceId) {
    $user = Get-InstanceUser $InstanceId
    $env:NLPP_AZAHAR_USER_DIR = $user
    $env:AZAHAR_USER_DIR = $user
    return $user
}

function Clear-DeployEnv {
    Remove-Item Env:NLPP_AZAHAR_USER_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:AZAHAR_USER_DIR -ErrorAction SilentlyContinue
}

function Invoke-Python([string[]]$PythonArgv) {
    $py = $Paths.PythonExe
    if (-not $py -or -not (Test-Path $py)) {
        $py310 = "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
        if (Test-Path $py310) { $py = $py310 } else { $py = "python" }
    }
    Push-Location $EngPatcher
    try {
        & $py @PythonArgv
        if ($LASTEXITCODE -ne 0) { throw "python failed: $PythonArgv" }
    } finally {
        Pop-Location
    }
}

function Show-Paths {
    Write-Host "EngPatcher:  $EngPatcher"
    Write-Host "Azahar src:  $($Paths.AzaharSrc)"
    Write-Host "Azahar exe:  $($Paths.AzaharExe)"
    Write-Host "MSYS2 bin:   $($Paths.MsysBin)"
    Write-Host "Vanilla dump:$($Paths.VanillaDump)"
    Write-Host "Test ROM:    $($Paths.RomPath)"
    Write-Host "Instances:   $($Paths.Instances)"
    Write-Host "  instance a: $(Get-InstanceUser a)"
    Write-Host "  instance b: $(Get-InstanceUser b)"
    Write-Host "Roaming mod: $env:APPDATA\Azahar\load\mods\$($Paths.TitleId)"
}

function Test-AzaharFork {
    Test-Path (Join-Path $Paths.AzaharSrc "NLPP.md")
}

# The fork already has the NLPP changes as commits. A plain upstream checkout
# gets ab_test\patches\azahar-*.patch (exports of the fork) applied once.
function Ensure-AzaharNlppChanges {
    if (-not (Test-Path (Join-Path $Paths.AzaharSrc "src\core"))) {
        throw "Azahar source missing: $($Paths.AzaharSrc)"
    }
    if (Test-AzaharFork) {
        Write-Host "azahar-3ds-accurate checkout ($($Paths.AzaharSrc)); NLPP changes are commits, nothing to patch"
        return
    }
    Write-Warning "$($Paths.AzaharSrc) is not azahar-3ds-accurate; applying the exported patches"
    Push-Location $Paths.AzaharSrc
    try {
        foreach ($name in @("azahar-openlinkfile.patch", "azahar-nlpp-emu.patch")) {
            $patch = Join-Path $AbTest "patches\$name"
            git apply --reverse --check $patch 2>$null
            if ($LASTEXITCODE -eq 0) { Write-Host "already applied: $name"; continue }
            git apply $patch
            if ($LASTEXITCODE -ne 0) { throw "git apply failed: $patch" }
            Write-Host "applied: $name"
        }
    } finally {
        Pop-Location
    }
}

# Same options as the original ..\azahar\build (MSYS2 clang64 + Ninja).
function Initialize-AzaharBuild([string]$Build) {
    $gen = Join-Path $Paths.MsysBin "ninja.exe"
    if (-not (Test-Path $gen)) { throw "ninja not found in $($Paths.MsysBin) (pacman -S mingw-w64-clang-x86_64-ninja)" }
    git -C $Paths.AzaharSrc submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw "submodule update failed" }
    cmake -S $Paths.AzaharSrc -B $Build -G Ninja `
        -DCMAKE_BUILD_TYPE=Release `
        "-DCMAKE_C_COMPILER=$($Paths.MsysBin)/cc.exe" `
        "-DCMAKE_CXX_COMPILER=$($Paths.MsysBin)/c++.exe" `
        -DENABLE_QT_UPDATE_CHECKER=OFF -DENABLE_DISCORD_RPC=OFF -DENABLE_VULKAN=OFF `
        -DENABLE_LTO=ON -DENABLE_TESTS=ON
    if ($LASTEXITCODE -ne 0) { throw "cmake configure failed" }
}

function Copy-AzaharRuntimeDlls([string]$DestDir) {
    # ICU was always copied next to the exe. Qt6Multimedia is also a hard
    # load at startup; without it, double-clicking azahar.exe (or a PATH
    # that lacks msys64\clang64\bin) shows "Qt6Multimedia.dll was not found".
    $msysBin = $Paths.MsysBin
    if (-not (Test-Path $msysBin)) {
        Write-Warning "MSYS2 bin not found at $msysBin - set MsysBin in paths.local.ps1 or NLPP_MSYS_BIN"
        return
    }
    # ICU's major version follows the MSYS2 package, so match any libicu*.
    $icu = @(Get-ChildItem -Path $msysBin -Filter "libicu*.dll" | ForEach-Object { $_.Name })
    $dlls = $icu + @("Qt6Multimedia.dll", "Qt6MultimediaWidgets.dll", "Qt6MultimediaQuick.dll")
    foreach ($dll in $dlls) {
        $src = Join-Path $msysBin $dll
        if (Test-Path $src) {
            Copy-Item $src (Join-Path $DestDir $dll) -Force
        }
    }
}

function Copy-AzaharToInstances {
    $exe = $Paths.AzaharExe
    if (-not (Test-Path $exe)) { return }
    foreach ($id in @("a", "b")) {
        $destDir = Join-Path $Paths.Instances $id
        if (-not (Test-Path $destDir)) { continue }
        Copy-Item $exe (Join-Path $destDir "azahar.exe") -Force
        Copy-AzaharRuntimeDlls $destDir
        Write-Host "Copied azahar.exe + runtime DLLs -> $destDir"
    }
}

function Build-Azahar {
    $build = $Paths.AzaharBuild
    Ensure-AzaharNlppChanges
    $msysBin = $Paths.MsysBin
    # clang64\bin -> msys64 root -> usr\bin (make, sh, ...).
    $msysUsr = Join-Path (Split-Path -Parent (Split-Path -Parent $msysBin)) "usr\bin"
    $env:PATH = "$msysBin;$msysUsr;" + $env:PATH
    if (-not (Test-Path (Join-Path $build "CMakeCache.txt"))) {
        Write-Host "Configuring a new build in $build (first build of this checkout is slow)"
        Initialize-AzaharBuild $build
    }
    Push-Location $build
    try {
        cmake .
        if ($LASTEXITCODE -ne 0) { throw "cmake failed" }
        ninja citra_meta
        if ($LASTEXITCODE -ne 0) { throw "ninja failed" }
        $release = Split-Path -Parent $Paths.AzaharExe
        Copy-AzaharRuntimeDlls $release
        Write-Host "Built: $($Paths.AzaharExe)"
        Copy-AzaharToInstances
    } finally {
        Pop-Location
    }
}

function Setup-Instances {
    $setupArgs = @{
        AzaharExe = $Paths.AzaharExe
        OutRoot   = $Paths.Instances
        MsysBin   = $Paths.MsysBin
    }
    if ($Paths.RomPath) { $setupArgs.RomPath = $Paths.RomPath }
    & (Join-Path $AbTest "setup_azahar_instances.ps1") @setupArgs
}

function Require-PostBake {
    $release = Join-Path $EngPatcher "release"
    $need = @(
        @{ Path = (Join-Path $release "bake_img.bin"); Label = "release\bake_img.bin" },
        @{ Path = (Join-Path $release "name_input_code.bin"); Label = "release\name_input_code.bin" },
        @{ Path = (Join-Path $release "romfs_overlay"); Label = "release\romfs_overlay" }
    )
    $missing = @($need | Where-Object { -not (Test-Path $_.Path) } | ForEach-Object { $_.Label })
    if ($missing.Count -eq 0) { return }

    Write-Host ""
    Write-Host "A bake should be done first."
    Write-Host "A/B uses the existing post-bake files. This step does not build them."
    Write-Host "Missing:"
    foreach ($item in $missing) { Write-Host "  $item" }
    Write-Host ""
    Write-Host "Drop a decrypted .cia / .3ds / .cci on:"
    Write-Host "  Drop CIA or 3DS Here to Patch.bat"
    Write-Host "or, when a bake already exists and only code/TRB changed:"
    Write-Host "  python tools\rebuild_bake_img.py --skip-pack"
    Write-Host ""
    $interactive = $true
    try { $interactive = -not [Console]::IsInputRedirected } catch { $interactive = $true }
    if ($interactive) { Read-Host "Press Enter" }
    exit 1
}

function Install-PostBake([string]$Id) {
    Require-PostBake
    $release = Join-Path $EngPatcher "release"
    $mod = Join-Path (Get-InstanceUser $Id) "load\mods\$($Paths.TitleId)"
    $exefs = Join-Path $mod "exefs"
    $romfs = Join-Path $mod "romfs"
    New-Item -ItemType Directory -Force -Path $exefs | Out-Null
    New-Item -ItemType Directory -Force -Path $romfs | Out-Null

    $bake = Join-Path $release "bake_img.bin"
    $code = Join-Path $release "name_input_code.bin"
    Copy-Item $bake (Join-Path $romfs "img.bin") -Force
    Copy-Item $code (Join-Path $exefs "code.bin") -Force
    Copy-Item $code (Join-Path $mod "code.bin") -Force
    Copy-Item (Join-Path $release "romfs_overlay\*") $romfs -Recurse -Force
    Invoke-Python @("src\script_inject.py", "--layeredfs", $romfs)
    Write-Host "Installed post-bake LayeredFS -> $mod"
    Write-Host "  img.bin  <- release\bake_img.bin"
    Write-Host "  code.bin <- release\name_input_code.bin"
    Write-Host "  romfs    <- release\romfs_overlay"
    Write-Host "  dialog   <- rebuild_dbin2 (.dbin2, same layers as the CIA)"

    $roamingConfig = Join-Path $env:APPDATA "Azahar\config\qt-config.ini"
    $instConfigDir = Join-Path (Get-InstanceUser $Id) "config"
    $instConfig = Join-Path $instConfigDir "qt-config.ini"
    if ((Test-Path $roamingConfig) -and -not (Test-Path $instConfig)) {
        New-Item -ItemType Directory -Force -Path $instConfigDir | Out-Null
        Copy-Item $roamingConfig $instConfig
        Write-Host "Seeded $instConfig from roaming Azahar"
    }
}

function Restore-NameInput([string]$InstanceId) {
    if ($InstanceId) {
        $user = Set-DeployEnv $InstanceId
        Write-Host "Restore target: $user"
    } else {
        Clear-DeployEnv
        Write-Host "Restore target: roaming Azahar (default)"
    }
    try {
        Invoke-Python @("tools\restore_name_input_baseline.py")
    } finally {
        if ($InstanceId) { Clear-DeployEnv }
    }
}

function Deploy-NameInput([string]$InstanceId) {
    if (-not $InstanceId) {
        Write-Host ""
        Write-Host "Use deploy-a or deploy-b."
        Write-Host "Roaming AppData is not an a/b instance."
        Write-Host ""
        $interactive = $true
        try { $interactive = -not [Console]::IsInputRedirected } catch { $interactive = $true }
        if ($interactive) { Read-Host "Press Enter" }
        exit 1
    }
    $user = Set-DeployEnv $InstanceId
    Write-Host "Deploy target: $user"
    try {
        Install-PostBake $InstanceId
    } finally {
        Clear-DeployEnv
    }
}

function Deploy-Combined([string]$InstanceId) {
    if ($InstanceId) {
        $user = Set-DeployEnv $InstanceId
        Write-Host "Combine deploy target: $user"
        Require-PostBake
    } else {
        Clear-DeployEnv
        Write-Host "Combine deploy target: roaming Azahar (default)"
        Require-PostBake
    }
    try {
        Invoke-Python @("tools\deploy_bleeding_edge_name_input.py")
        Write-Host "Done. Bake UI + name-input code + name-kanji TRB."
    } finally {
        if ($InstanceId) { Clear-DeployEnv }
    }
}

function Import-SavePack([string]$InstanceId, [string]$Pack) {
    if ($InstanceId) {
        $user = Set-DeployEnv $InstanceId
        if (-not (Test-Path $user)) {
            throw "Instance $InstanceId missing. Run .\ab_test\make.ps1 instances first. ($user)"
        }
        Write-Host "Save target: $user"
    } else {
        Clear-DeployEnv
        Write-Host "Save target: roaming Azahar (default)"
    }
    try {
        Invoke-Python @("tools\import_azahar_save.py", "--pack", $Pack)
    } finally {
        if ($InstanceId) { Clear-DeployEnv }
    }
}

function Move-LayeredFsBackups([string]$Id) {
    # LayeredFS maps every file under romfs/, including img.bin.bak_* sidecars.
    $mod = Join-Path (Get-InstanceUser $Id) "load\mods\$($Paths.TitleId)"
    $stash = Join-Path $mod "_bak"
    foreach ($sub in @("romfs", "exefs")) {
        $root = Join-Path $mod $sub
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem $root -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '\.bak' } |
            ForEach-Object {
                $rel = $_.FullName.Substring($root.Length).TrimStart('\')
                $dest = Join-Path $stash (Join-Path $sub $rel)
                New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
                Move-Item -LiteralPath $_.FullName -Destination $dest -Force
                Write-Host "LayeredFS: moved $sub\$rel -> _bak\"
            }
    }
}

function Launch-Instance([string]$Id) {
    Move-LayeredFsBackups $Id
    if ($env:NLPP_EMU_NAME_WALK_ABORT -eq "1") {
        Write-Host "NLPP_EMU_NAME_WALK_ABORT=1 (name-walk load emulates the 2026-10-01 18:36 data abort)"
    }
    if ($env:NLPP_EMU_PANE_FLAG -eq "1") {
        Write-Host "NLPP_EMU_PANE_FLAG=1 (menu update gets one null pane in r6, the 2026-10-03 00:50 dump)"
    }
    $bat = Join-Path $Paths.Instances "$Id\Launch-$Id.bat"
    if (Test-Path $bat) {
        Start-Process $bat
    } else {
        throw "Run '.\ab_test\make.ps1 instances' first. Missing $bat"
    }
}

function Invoke-CodeChecks {
    # Same gate the gold runner uses: no vanilla = fail, not skip.
    $env:NLPP_REQUIRE_CODE_CHECKS = "1"
    $vanilla = Join-Path $Paths.VanillaDump "exefs\code.bin"
    if (Test-Path $vanilla) { $env:NLPP_VANILLA_CODE = $vanilla }
    Invoke-Python @("-m", "pytest", "tests/test_code_patch_map.py",
        "tests/test_patch_blob_snapshots.py", "-q", "-rs", "-p", "no:cacheprovider")
    $code = Join-Path $EngPatcher "release\name_input_code.bin"
    if (Test-Path $code) {
        Write-Host "Checking release\name_input_code.bin against the snapshot (stale after a patch change until you rebake)"
        Invoke-Python @("tools\verify_name_input_code.py")
    }
}

function Invoke-Smoke([string]$Inject) {
    $exe = Join-Path $Paths.Instances "a\azahar.exe"
    if (-not (Test-Path $exe)) {
        throw "Missing $exe. Run '.\ab_test\make.ps1 build-azahar' and 'instances' first."
    }
    if (-not $Paths.RomPath -or -not (Test-Path $Paths.RomPath)) {
        throw "ROM not found. Set `$Paths.RomPath in ab_test\paths.local.ps1 or NLPP_ROM."
    }
    Require-PostBake
    $argv = @("tools\smoke_boot_azahar.py", "--azahar", $exe, "--dll-dir", $Paths.MsysBin,
        "--rom", $Paths.RomPath, "--seed-user", (Get-InstanceUser "a"))
    if ($Inject) { $argv += @("--inject", $Inject) }
    Invoke-Python $argv
}

$handlers = @{
    "help" = {
        @"
NLPP a/b Azahar workflow (.\ab_test\make.ps1 [target])
See ab_test\README.md

  paths          Show resolved folder paths
  build-azahar   Build azahar-3ds-accurate (..\azahar-3ds-accurate; configures build\ on first run), then copy azahar.exe into instances.
                 A plain upstream checkout gets ab_test\patches\azahar-*.patch applied first
  instances      Create dual test instances + Launch-a/b.bat
  seed-a / seed-b  Copy post-bake LayeredFS + EN dialog into instance mod
  deploy-a/b     Same post-bake copy + EN .dbin2 -> instance A/B
  combine-a/b    Post-bake img + name-input code, name-kanji TRB -> A/B
  combine        Same combine stack -> roaming Azahar

  If release\bake_img.bin is missing, these stop and ask for a bake first.
  restore-a/b    Restore default-stack baseline in instance
  restore        Restore baseline in roaming Azahar

  save-nene-a/b  Install the local Nene title-save pack -> instance A/B
  save-nene      Same pack -> A and B (shared a/b slot; pack is gitignored)

  checks         code.bin checks vs vanilla + release\name_input_code.bin vs snapshot
  smoke          Boot release\ in a copy of instance A with the hardware-crash replays
  smoke-plain    Same boot without the replays
  test           Full pytest suite
  (Double-click ab_test\Run Safety Checks.bat for a menu.)

  launch-a/b     Start Azahar instance A or B (moves LayeredFS *.bak* out of romfs/)
  all-a / all-b  instances + install post-bake LayeredFS

  progress       Diff release EN TRB vs vanilla, POST script-text % to the site
  progress-dry   Same, but just print the numbers (no POST)

Override paths: copy ab_test\paths.local.ps1.example -> ab_test\paths.local.ps1
"@
    }
    "paths" = { Show-Paths }
    "build-azahar" = { Build-Azahar }
    "instances" = { Setup-Instances }
    "seed-a" = { Install-PostBake "a" }
    "seed-b" = { Install-PostBake "b" }
    "deploy-a" = { Deploy-NameInput "a" }
    "deploy-b" = { Deploy-NameInput "b" }
    "combine-a" = { Deploy-Combined "a" }
    "combine-b" = { Deploy-Combined "b" }
    "combine" = { Deploy-Combined "" }
    "restore-a" = { Restore-NameInput "a" }
    "restore-b" = { Restore-NameInput "b" }
    "restore" = { Restore-NameInput "" }
    "deploy" = { Deploy-NameInput "" }
    "save-nene-a" = { Import-SavePack "a" "nene" }
    "save-nene-b" = { Import-SavePack "b" "nene" }
    "save-nene" = { Import-SavePack "a" "nene"; Import-SavePack "b" "nene" }
    "launch-a" = { Launch-Instance "a" }
    "launch-b" = { Launch-Instance "b" }
    "all-a" = { Setup-Instances; Install-PostBake "a" }
    "all-b" = { Setup-Instances; Install-PostBake "b" }
    "progress" = { Invoke-Python @("src\report_progress.py") }
    "progress-dry" = { Invoke-Python @("src\report_progress.py", "--dry-run") }
    "checks" = { Invoke-CodeChecks }
    "smoke" = { Invoke-Smoke "name-walk,pane-flag,menu-vt" }
    "smoke-plain" = { Invoke-Smoke "" }
    "test" = { Invoke-Python @("-m", "pytest", "tests/", "-q", "-rs", "-p", "no:cacheprovider") }
}

if (-not $handlers.ContainsKey($Target)) {
    Write-Error "Unknown target: $Target. Try: .\ab_test\make.ps1 help"
}

& $handlers[$Target]
