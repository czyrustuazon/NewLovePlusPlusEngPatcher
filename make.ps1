# Root shim — a/b Azahar workflow lives in ab_test/
param(
    [Parameter(Position = 0)]
    [string]$Target = "help"
)

& "$PSScriptRoot\ab_test\make.ps1" $Target
