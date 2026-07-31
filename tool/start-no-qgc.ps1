# Root shortcut → no-qgc/start-no-qgc.ps1
[CmdletBinding()]
param(
    [string]$BoardSerial = "83bc469a34914114",
    [ValidateSet("eth", "usb")]
    [string]$Link = "eth",
    [string]$ComPort = "",
    [double]$Hz = 50,
    [int]$DurationSec = 0,
    [switch]$BringUpEth,
    [switch]$SkipOfflineMaps,
    [switch]$ProductionSafe
)
& (Join-Path $PSScriptRoot "no-qgc\start-no-qgc.ps1") @PSBoundParameters
exit $LASTEXITCODE
