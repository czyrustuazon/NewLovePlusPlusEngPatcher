$mod = Join-Path $env:APPDATA 'Azahar\load\mods\00040000000F4E00\romfs\img.bin'
$bak = "$mod.bak_pre_msel5245"
Copy-Item -Force $bak $mod
Write-Host "Restored img.bin from bak_pre_msel5245"
