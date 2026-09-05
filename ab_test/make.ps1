# NLPP a/b Azahar workflow. Prefer repo root: .\make.ps1 help
# Direct: .\ab_test\make.ps1 help
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
    Instances    = Join-Path $EngPatcher "out\azahar_instances"
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
    Write-Host "Instances:   $($Paths.Instances)"
    Write-Host "  instance a: $(Get-InstanceUser a)"
    Write-Host "  instance b: $(Get-InstanceUser b)"
    Write-Host "Roaming mod: $env:APPDATA\Azahar\load\mods\$($Paths.TitleId)"
}

function Build-Azahar {
    $build = $Paths.AzaharBuild
    if (-not (Test-Path $build)) { throw "Azahar build dir missing: $build" }
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
    } finally {
        Pop-Location
    }
}

function Setup-Instances {
    & powershell -NoProfile -ExecutionPolicy Bypass -File `
        (Join-Path $AbTest "setup_azahar_instances.ps1") `
        -AzaharExe $Paths.AzaharExe `
        -OutRoot $Paths.Instances
}

function Seed-Instance([string]$Id) {
    $mod = Join-Path (Get-InstanceUser $Id) "load\mods\$($Paths.TitleId)"
    $exefs = Join-Path $mod "exefs"
    $code = Join-Path $exefs "code.bin"
    $vanilla = Join-Path $Paths.VanillaDump "exefs\code.bin"
    $vanillaBak = Join-Path $Paths.VanillaDump "exefs\code.bin.bak"
    # Prefer untouched bak — extracted/code.bin is often already name-input patched.
    if (Test-Path $vanillaBak) { $vanilla = $vanillaBak }
    New-Item -ItemType Directory -Force -Path $exefs | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $mod "romfs") | Out-Null
    if (-not (Test-Path $vanilla)) {
        throw "Vanilla code.bin missing: $vanilla"
    }
    if (-not (Test-Path $code)) {
        Copy-Item $vanilla $code
        Copy-Item $vanilla (Join-Path $mod "code.bin")
        Write-Host "Seeded $code from $vanilla"
    } else {
        Write-Host "Already exists: $code"
    }
    $imgVanilla = Join-Path $Paths.VanillaDump "romfs\img.bin"
    $imgDest = Join-Path $mod "romfs\img.bin"
    if ((Test-Path $imgVanilla) -and -not (Test-Path $imgDest)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $imgDest) | Out-Null
        Copy-Item $imgVanilla $imgDest
        Write-Host "Seeded $imgDest"
    }
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
    if ($InstanceId) {
        $user = Set-DeployEnv $InstanceId
        Write-Host "Deploy target: $user"
        Seed-Instance $InstanceId
    } else {
        Clear-DeployEnv
        Write-Host "Deploy target: roaming Azahar (default)"
    }
    try {
        Invoke-Python @("tools\deploy_name_input_en.py")
        Invoke-Python @("tools\deploy_name_kanji_trb.py", "--deploy-azahar")
        Write-Host "Done. Name-input stack: romaji labels + romaji insert (no kanji list)."
    } finally {
        if ($InstanceId) { Clear-DeployEnv }
    }
}

function Deploy-Combined([string]$InstanceId) {
    if ($InstanceId) {
        $user = Set-DeployEnv $InstanceId
        Write-Host "Combine deploy target: $user"
        Seed-Instance $InstanceId
    } else {
        Clear-DeployEnv
        Write-Host "Combine deploy target: roaming Azahar (default)"
    }
    try {
        Invoke-Python @("tools\deploy_bleeding_edge_name_input.py")
        Write-Host "Done. Bake UI + name-input code + name-kanji TRB."
    } finally {
        if ($InstanceId) { Clear-DeployEnv }
    }
}

function Launch-Instance([string]$Id) {
    $bat = Join-Path $Paths.Instances "$Id\Launch-$Id.bat"
    if (Test-Path $bat) {
        Start-Process $bat
    } else {
        throw "Run '.\make.ps1 instances' first. Missing $bat"
    }
}

$handlers = @{
    "help" = {
        @"
NLPP a/b Azahar workflow (.\make.ps1 [target])
See ab_test\README.md

  paths          Show resolved folder paths
  build-azahar   cmake + ninja citra_meta
  instances      Create dual test instances + Launch-a/b.bat
  seed-a / seed-b  Copy vanilla code.bin + img.bin into instance mod

  deploy-a/b     Name-input only (vanilla img stay) -> instance A/B
  deploy         Name-input only -> roaming %AppData%\Azahar
  combine-a/b    Bleeding-Edge bake img + name-input + name-kanji TRB -> A/B
  combine        Same combine stack -> roaming Azahar
  restore-a/b    Restore default-stack baseline in instance
  restore        Restore baseline in roaming Azahar

  launch-a/b     Start Azahar instance A or B
  all-a / all-b  instances + seed + deploy

  progress       Diff release EN TRB vs vanilla, POST script-text % to the site
  progress-dry   Same, but just print the numbers (no POST)

Override paths: copy ab_test\paths.local.ps1.example -> ab_test\paths.local.ps1
"@
    }
    "paths" = { Show-Paths }
    "build-azahar" = { Build-Azahar }
    "instances" = { Setup-Instances }
    "seed-a" = { Seed-Instance "a" }
    "seed-b" = { Seed-Instance "b" }
    "deploy-a" = { Deploy-NameInput "a" }
    "deploy-b" = { Deploy-NameInput "b" }
    "combine-a" = { Deploy-Combined "a" }
    "combine-b" = { Deploy-Combined "b" }
    "combine" = { Deploy-Combined "" }
    "restore-a" = { Restore-NameInput "a" }
    "restore-b" = { Restore-NameInput "b" }
    "restore" = { Restore-NameInput "" }
    "deploy" = { Deploy-NameInput "" }
    "launch-a" = { Launch-Instance "a" }
    "launch-b" = { Launch-Instance "b" }
    "all-a" = { Setup-Instances; Seed-Instance "a"; Deploy-NameInput "a" }
    "all-b" = { Setup-Instances; Seed-Instance "b"; Deploy-NameInput "b" }
    "progress" = { Invoke-Python @("src\report_progress.py") }
    "progress-dry" = { Invoke-Python @("src\report_progress.py", "--dry-run") }
}

if (-not $handlers.ContainsKey($Target)) {
    Write-Error "Unknown target: $Target. Try: .\make.ps1 help"
}

& $handlers[$Target]
