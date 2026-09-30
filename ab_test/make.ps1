# NLPP a/b Azahar workflow. From the repo root: .\ab_test\make.ps1 help
param(
    [Parameter(Position = 0)]
    [string]$Target = "help"
)

$ErrorActionPreference = "Stop"
$AbTest = $PSScriptRoot
$EngPatcher = Split-Path -Parent $AbTest
$Parent = Split-Path -Parent $EngPatcher

# --- paths (override in ab_test/paths.local.ps1) ---
$Paths = @{
    AzaharSrc    = "C:\Users\Zepse\Documents\azahar"
    AzaharBuild  = "C:\Users\Zepse\Documents\azahar\build"
    AzaharExe    = "C:\Users\Zepse\Documents\azahar\build\bin\Release\azahar.exe"
    VanillaDump  = Join-Path $Parent "New Love Plus Plus\extracted"
    RomPath      = ""
    Instances    = Join-Path $AbTest "azahar_instances"
    TitleId      = "00040000000F4E00"
}

$LocalPaths = Join-Path $AbTest "paths.local.ps1"
if (Test-Path $LocalPaths) { . $LocalPaths }

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
    Write-Host "Vanilla dump:$($Paths.VanillaDump)"
    Write-Host "Test ROM:    $($Paths.RomPath)"
    Write-Host "Instances:   $($Paths.Instances)"
    Write-Host "  instance a: $(Get-InstanceUser a)"
    Write-Host "  instance b: $(Get-InstanceUser b)"
    Write-Host "Roaming mod: $env:APPDATA\Azahar\load\mods\$($Paths.TitleId)"
}

function Ensure-AzaharOpenLinkFile {
    $src = Join-Path $Paths.AzaharSrc "src\core\hle\service\fs\file.cpp"
    $patch = Join-Path $AbTest "patches\azahar-openlinkfile.patch"
    if (-not (Test-Path $src)) { throw "Azahar source missing: $src" }
    if (-not (Test-Path $patch)) { throw "missing $patch" }
    $text = Get-Content -LiteralPath $src -Raw
    $stubbed = $text -match '\(STUBBED\) File command OpenLinkFile'
    $cloned = ($text -match 'clone offset=') -or ($text -match 'slot->size = original_file->size')
    if ($cloned -and -not $stubbed) {
        Write-Host "OpenLinkFile already clones the handle ($src)"
        return
    }
    Push-Location $Paths.AzaharSrc
    try {
        git apply $patch
        if ($LASTEXITCODE -ne 0) { throw "git apply failed: $patch" }
        Write-Host "Applied OpenLinkFile clone patch -> $src"
    } finally {
        Pop-Location
    }
}

function Copy-AzaharToInstances {
    $exe = $Paths.AzaharExe
    if (-not (Test-Path $exe)) { return }
    foreach ($id in @("a", "b")) {
        $destDir = Join-Path $Paths.Instances $id
        if (-not (Test-Path $destDir)) { continue }
        Copy-Item $exe (Join-Path $destDir "azahar.exe") -Force
        Write-Host "Copied azahar.exe -> $destDir"
    }
}

function Build-Azahar {
    $build = $Paths.AzaharBuild
    if (-not (Test-Path $build)) { throw "Azahar build dir missing: $build" }
    Ensure-AzaharOpenLinkFile
    $msysBin = "C:\msys64\clang64\bin"
    $env:PATH = "$msysBin;C:\msys64\usr\bin;" + $env:PATH
    Push-Location $build
    try {
        cmake .
        if ($LASTEXITCODE -ne 0) { throw "cmake failed" }
        ninja citra_meta
        if ($LASTEXITCODE -ne 0) { throw "ninja failed" }
        $release = Split-Path -Parent $Paths.AzaharExe
        foreach ($dll in @("libicudt78.dll", "libicuin78.dll", "libicuuc78.dll")) {
            $src = Join-Path $msysBin $dll
            if (Test-Path $src) {
                Copy-Item $src (Join-Path $release $dll) -Force
            }
        }
        Write-Host "Built: $($Paths.AzaharExe)"
        Copy-AzaharToInstances
    } finally {
        Pop-Location
    }
}

function Setup-Instances {
    & powershell -NoProfile -ExecutionPolicy Bypass -File `
        (Join-Path $AbTest "setup_azahar_instances.ps1") `
        -AzaharExe $Paths.AzaharExe `
        -OutRoot $Paths.Instances `
        -RomPath $Paths.RomPath
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
    $bat = Join-Path $Paths.Instances "$Id\Launch-$Id.bat"
    if (Test-Path $bat) {
        Start-Process $bat
    } else {
        throw "Run '.\ab_test\make.ps1 instances' first. Missing $bat"
    }
}

$handlers = @{
    "help" = {
        @"
NLPP a/b Azahar workflow (.\ab_test\make.ps1 [target])
See ab_test\README.md

  paths          Show resolved folder paths
  build-azahar   Apply azahar-openlinkfile.patch if file.cpp is still stubbed, then cmake + ninja citra_meta, then copy azahar.exe into instances
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
}

if (-not $handlers.ContainsKey($Target)) {
    Write-Error "Unknown target: $Target. Try: .\ab_test\make.ps1 help"
}

& $handlers[$Target]
