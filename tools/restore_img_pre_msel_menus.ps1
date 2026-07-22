$mod = Join-Path $env:APPDATA "Azahar\load\mods\00040000000F4E00\romfs\img.bin"
$bak = "$mod.bak_pre_msel_menus"
if (-not (Test-Path $bak)) { throw "missing $bak" }
Copy-Item -Force $bak $mod
Write-Host "restored $mod from bak_pre_msel_menus"
