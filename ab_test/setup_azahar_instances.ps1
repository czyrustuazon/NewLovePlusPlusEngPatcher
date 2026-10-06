# Bootstrap dual Azahar instances + tester-friendly launch shortcuts.
# Normally run through .\ab_test\make.ps1 instances, which passes the paths
# resolved from paths.local.ps1 / NLPP_* env vars.
param(
    [string]$AzaharExe = "",
    [string]$OutRoot = "",
    [string]$RomPath = "",
    [string]$MsysBin = ""
)

$ErrorActionPreference = "Stop"
$TitleId = "00040000000F4E00"
# Outside out\ so a Drop CIA wipe does not delete the instances.
if (-not $OutRoot) { $OutRoot = Join-Path $PSScriptRoot "azahar_instances" }
if (-not $MsysBin) { $MsysBin = $env:NLPP_MSYS_BIN }
if (-not $MsysBin) { $MsysBin = "C:\msys64\clang64\bin" }

if (-not $AzaharExe) { $AzaharExe = $env:NLPP_AZAHAR_EXE }
if (-not $AzaharExe) {
    $onPath = Get-Command azahar.exe -ErrorAction SilentlyContinue
    if ($onPath) { $AzaharExe = $onPath.Source }
}
if (-not $AzaharExe -or -not (Test-Path $AzaharExe)) {
    throw "azahar.exe not found ('$AzaharExe'). Set AzaharExe in ab_test\paths.local.ps1, NLPP_AZAHAR_EXE, or pass -AzaharExe."
}

if (-not (Test-Path $MsysBin)) {
    Write-Warning "MSYS2 clang64 bin not found at $MsysBin - ICU DLL copy may fail."
}

function Copy-IcuRuntimeDlls {
    param(
        [string]$DestDir,
        [string]$ExeDir
    )
    # ICU's major version follows the MSYS2 package, so match any libicu*.
    $found = @(Get-ChildItem -Path $ExeDir -Filter "libicu*.dll" -ErrorAction SilentlyContinue)
    if ($found.Count -eq 0 -and (Test-Path $MsysBin)) {
        $found = @(Get-ChildItem -Path $MsysBin -Filter "libicu*.dll")
    }
    if ($found.Count -eq 0) {
        Write-Warning "Missing ICU runtime libicu*.dll (Qt6 will not start without it)"
        return
    }
    foreach ($dll in $found) {
        Copy-Item -Path $dll.FullName -Destination $DestDir -Force
    }
}

$exeDir = Split-Path -Parent $AzaharExe
foreach ($id in @("a", "b")) {
    $inst = Join-Path $OutRoot $id
    $user = Join-Path $inst "user"
    $mod = Join-Path $user "load\mods\$TitleId"
    New-Item -ItemType Directory -Force -Path (Join-Path $mod "exefs") | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $mod "romfs") | Out-Null
    Copy-Item -Path (Join-Path $exeDir "*") -Destination $inst -Recurse -Force
    Copy-IcuRuntimeDlls -DestDir $inst -ExeDir $exeDir

    $commonArgs = @(
        "--user-dir", "`"$user`"",
        "--load-last",
        "--default-title", $TitleId,
        "--no-update-check",
        "--localization-studio",
        "--reload-mods-on-start",
        "--text-speed", "300"
    )
    if ($RomPath -and (Test-Path $RomPath)) {
        $commonArgs = @("--user-dir", "`"$user`"", "--load", "`"$RomPath`"", "--no-update-check", "--localization-studio", "--reload-mods-on-start")
    }

    $launch = @"
@echo off
set "PATH=$MsysBin;%PATH%"
start "Azahar $id" "$inst\azahar.exe" $($commonArgs -join ' ')
"@
    Set-Content -Path (Join-Path $inst "Launch-$id.bat") -Value $launch -Encoding ASCII
    Write-Host "Instance $id -> $user"
}

Write-Host ""
Write-Host "Quick launch (double-click):"
Write-Host "  $OutRoot\a\Launch-a.bat"
Write-Host "  $OutRoot\b\Launch-b.bat"
Write-Host ""
Write-Host "Manual:"
Write-Host "  $OutRoot\a\azahar.exe --user-dir `"$OutRoot\a\user`" --load-last --localization-studio"
Write-Host ""
Write-Host "Deploy to instance A:"
Write-Host "  .\ab_test\make.ps1 deploy-a"
Write-Host "Restore instance A:"
Write-Host "  .\ab_test\make.ps1 restore-a"
