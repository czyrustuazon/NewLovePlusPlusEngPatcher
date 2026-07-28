# Resolve a dump path to something cmd.exe can safely consume.
# Prefer 8.3 short path; otherwise hardlink (or copy) to %TEMP%\nlpp_drop_input.<ext>.
param(
    [Parameter(Position = 0)]
    [string]$Path
)
$ErrorActionPreference = "Stop"
if (-not $Path) {
    $Path = $env:NLPP_ROM
}
if (-not $Path) {
    [Console]::Error.WriteLine("no path")
    exit 1
}
if (-not (Test-Path -LiteralPath $Path)) {
    [Console]::Error.WriteLine("not found: $Path")
    # Still emit something so the bat can report it
    [Console]::Out.Write($Path)
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
            [Console]::Out.Write($short)
            exit 0
        }
    }
} catch {
    # fall through
}

# 2) Hardlink / symlink / copy into %TEMP% with an ASCII name
$dest = Join-Path $env:TEMP ("nlpp_drop_input" + $ext)
if (Test-Path -LiteralPath $dest) {
    try { Remove-Item -LiteralPath $dest -Force } catch { }
}

$linked = $false
try {
    # Same-volume hardlink is instant even for multi-GB CIAs
    New-Item -ItemType HardLink -Path $dest -Target $full -ErrorAction Stop | Out-Null
    $linked = $true
} catch {
    try {
        New-Item -ItemType SymbolicLink -Path $dest -Target $full -ErrorAction Stop | Out-Null
        $linked = $true
    } catch {
        # Last resort: copy (slow for ~1.7GB)
        [Console]::Error.WriteLine("hardlink/symlink failed; copying dump to TEMP (may take a minute)...")
        Copy-Item -LiteralPath $full -Destination $dest -Force
        $linked = $true
    }
}

if (-not $linked -or -not (Test-Path -LiteralPath $dest)) {
    [Console]::Error.WriteLine("failed to stage dump path")
    [Console]::Out.Write($full)
    exit 1
}
[Console]::Out.Write($dest)
exit 0
