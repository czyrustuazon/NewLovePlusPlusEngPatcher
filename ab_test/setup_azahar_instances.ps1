# Bootstrap dual Azahar instances + tester-friendly launch shortcuts.
param(
    [string]$AzaharExe = "",
    [string]$OutRoot = "",
    [string]$RomPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$TitleId = "00040000000F4E00"
if (-not $OutRoot) { $OutRoot = Join-Path $RepoRoot "out\azahar_instances" }

if (-not $AzaharExe) {
    $candidates = @(
        "C:\Users\Zepse\Documents\azahar\build\bin\Release\azahar.exe",
        "C:\Users\Zepse\Documents\azahar\build\bin\azahar.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $AzaharExe = $c; break }
    }
}

if (-not (Test-Path $AzaharExe)) {
    Write-Error "Set -AzaharExe to your built azahar.exe."
}

$MsysClangBin = "C:\msys64\clang64\bin"
if (-not (Test-Path $MsysClangBin)) {
    Write-Warning "MSYS2 clang64 bin not found at $MsysClangBin - ICU DLL copy may fail."
}

function Copy-IcuRuntimeDlls {
    param(
        [string]$DestDir,
        [string]$ExeDir
    )
    foreach ($dll in @("libicudt78.dll", "libicuin78.dll", "libicuuc78.dll")) {
        $src = Join-Path $ExeDir $dll
        if (-not (Test-Path $src)) {
            $src = Join-Path $MsysClangBin $dll
        }
        if (Test-Path $src) {
            Copy-Item -Path $src -Destination $DestDir -Force
        } else {
            Write-Warning "Missing ICU runtime: $dll (Qt6 will not start without it)"
        }
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
set "PATH=$MsysClangBin;%PATH%"
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
Write-Host "  .\make.ps1 deploy-a"
Write-Host "Restore instance A:"
Write-Host "  .\make.ps1 restore-a"
