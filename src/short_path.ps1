# Resolve a dump path to something cmd.exe can safely consume.
# Prefer 8.3 short path; otherwise hardlink / copy to an ASCII stage name.
#
# Contract:
#   In:  $Path arg, or env NLPP_ROM
#   Out: env NLPP_DROP_PATH_FILE (default %TEMP%\nlpp_drop_path.txt) — single-line path
#        also stdout (same path) for callers that want it
# Never write progress to stderr (parents with $ErrorActionPreference=Stop treat it
# as a terminating NativeCommandError and can poison the resolved path).
param(
    [Parameter(Position = 0)]
    [string]$Path
)

$ErrorActionPreference = "Continue"

function Write-Result([string]$resultPath) {
    $outFile = $env:NLPP_DROP_PATH_FILE
    if ([string]::IsNullOrWhiteSpace($outFile)) {
        $outFile = Join-Path $env:TEMP "nlpp_drop_path.txt"
    }
    $dir = [IO.Path]::GetDirectoryName($outFile)
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [IO.File]::WriteAllText($outFile, $resultPath)
    [Console]::Out.Write($resultPath)
}

function Test-SameVolume([string]$a, [string]$b) {
    $ra = [IO.Path]::GetPathRoot($a)
    $rb = [IO.Path]::GetPathRoot($b)
    if ([string]::IsNullOrEmpty($ra) -or [string]::IsNullOrEmpty($rb)) { return $false }
    return ($ra.TrimEnd('\').ToUpperInvariant() -eq $rb.TrimEnd('\').ToUpperInvariant())
}

function Remove-StageFile([string]$dest) {
    if (-not (Test-Path -LiteralPath $dest)) { return }
    try { [IO.File]::Delete($dest) } catch {
        try { Remove-Item -LiteralPath $dest -Force -ErrorAction Stop } catch { }
    }
}

function Try-HardLink([string]$dest, [string]$target) {
    try {
        New-Item -ItemType HardLink -Path $dest -Target $target -ErrorAction Stop | Out-Null
        return (Test-Path -LiteralPath $dest)
    } catch {
        return $false
    }
}

function Try-SymLink([string]$dest, [string]$target) {
    try {
        New-Item -ItemType SymbolicLink -Path $dest -Target $target -ErrorAction Stop | Out-Null
        return (Test-Path -LiteralPath $dest)
    } catch {
        return $false
    }
}

function Try-FileCopy([string]$dest, [string]$target) {
    try {
        Write-Host "Staging dump copy to $dest (may take a minute for large CIAs)..."
        [IO.File]::Copy($target, $dest, $true)
        return (Test-Path -LiteralPath $dest)
    } catch {
        Write-Host ("Copy failed: " + $_.Exception.Message)
        return $false
    }
}

if (-not $Path) {
    $Path = $env:NLPP_ROM
}
if (-not $Path) {
    Write-Host "no path"
    exit 1
}
if (-not (Test-Path -LiteralPath $Path)) {
    Write-Host "not found: $Path"
    Write-Result $Path
    exit 0
}

$full = (Resolve-Path -LiteralPath $Path).Path
$ext = [IO.Path]::GetExtension($full).ToLowerInvariant()
if ($ext -notin @(".cia", ".3ds", ".cci")) {
    $ext = ".cia"
}

# 1) 8.3 short path (fast, no disk use) when the volume still generates them
try {
    if (-not ("NLPP.Native" -as [type])) {
        Add-Type -Namespace NLPP -Name Native -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern uint GetShortPathName(string lpszLongPath, System.Text.StringBuilder lpszShortPath, int cchBuffer);
"@
    }
    $sb = New-Object System.Text.StringBuilder 512
    $n = [NLPP.Native]::GetShortPathName($full, $sb, 512)
    if ($n -gt 0 -and $sb.Length -gt 0) {
        $short = $sb.ToString()
        # Only accept if it actually looks like 8.3 (contains ~) OR has no spaces/parens
        if (($short -match '~') -or ($short -notmatch '[\s()]')) {
            Write-Result $short
            exit 0
        }
    }
} catch {
    # fall through
}

# 2) Stage to an ASCII filename. Prefer same volume as the ROM so hardlinks work
#    (CIA on D: + %TEMP% on C: cannot hardlink).
$stageName = "nlpp_drop_input" + $ext
$romDir = [IO.Path]::GetDirectoryName($full)
$romRoot = [IO.Path]::GetPathRoot($full).TrimEnd('\')
$candidates = @(
    (Join-Path $env:TEMP $stageName),
    (Join-Path $romDir $stageName),
    (Join-Path (Join-Path $romRoot "nlpp_patcher_temp") $stageName)
)

# Same-volume destinations first (hardlink-friendly), stable order otherwise
$candidates = @(
    $candidates |
        Select-Object -Unique |
        Sort-Object -Property @{
            Expression = { if (Test-SameVolume $_ $full) { 0 } else { 1 } }
        }, @{ Expression = { $_ } }
)

foreach ($dest in $candidates) {
    $parent = [IO.Path]::GetDirectoryName($dest)
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        try {
            New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop | Out-Null
        } catch {
            continue
        }
    }
    Remove-StageFile $dest
    if (Try-HardLink $dest $full) {
        Write-Result $dest
        exit 0
    }
}

foreach ($dest in $candidates) {
    $parent = [IO.Path]::GetDirectoryName($dest)
    if ($parent -and -not (Test-Path -LiteralPath $parent)) { continue }
    Remove-StageFile $dest
    if (Try-SymLink $dest $full) {
        Write-Result $dest
        exit 0
    }
}

# Last resort: byte copy. Same-volume first so free space is on the right drive.
foreach ($dest in $candidates) {
    $parent = [IO.Path]::GetDirectoryName($dest)
    if ($parent -and -not (Test-Path -LiteralPath $parent)) { continue }
    Remove-StageFile $dest
    if (Try-FileCopy $dest $full) {
        Write-Result $dest
        exit 0
    }
}

Write-Host "failed to stage dump path"
Write-Result $full
exit 1
