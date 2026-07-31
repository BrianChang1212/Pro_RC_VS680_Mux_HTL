# Root shortcut → with-qgc/start-with-qgc.ps1
[CmdletBinding()]
param(
    [string]$BoardSerial = "83bc469a34914114",
    [string]$ComPort = "",
    [double]$Hz = 50,
    [int]$DurationSec = 0,
    [switch]$BringUpEth,
    [switch]$SkipOfflineMaps,
    [switch]$ProductionSafe,
    [switch]$RestartQgc
)
& (Join-Path $PSScriptRoot "with-qgc\start-with-qgc.ps1") @PSBoundParameters
exit $LASTEXITCODE
