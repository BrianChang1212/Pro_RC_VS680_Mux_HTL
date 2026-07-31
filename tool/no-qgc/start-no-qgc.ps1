# One-click: mavlink_mux only — NO QGC.
# Stick: HID -> mux -> FC. Telem/Arm/Takeoff UI not available.
#
# Usage:
#   .\start-no-qgc.ps1
#   .\start-no-qgc.ps1 -BringUpEth -SkipOfflineMaps
#   .\start-no-qgc.ps1 -Link usb -ComPort COM9

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

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$bringUp = Join-Path $here "..\bring-up"
$withQgc = Join-Path $here "..\with-qgc"

if ($BringUpEth) {
    if ($Link -ne "eth") {
        Write-Error "-BringUpEth only applies to -Link eth"
    }
    $setup = Join-Path $bringUp "setup-eth-htl.ps1"
    $setupArgs = @{
        BoardSerial = $BoardSerial
        SkipOfflineMaps = [bool]$SkipOfflineMaps
        ProductionSafe = [bool]$ProductionSafe
        SkipVerify = $true
    }
    if ($ComPort) { $setupArgs.ComPort = $ComPort }
    Write-Host "== Stage A: eth/FC bring-up (no lasting QGC UX) =="
    & $setup @setupArgs
    adb -s $BoardSerial shell "am force-stop org.mavlink.qgroundcontrolbeta" 2>$null | Out-Null
}

Write-Host "== Stage B: mux only (NoQgc) =="
$joy = @{
    BoardSerial = $BoardSerial
    Link = $Link
    Hz = $Hz
    DurationSec = $DurationSec
    NoQgc = $true
    StopQgc = $true
}
if ($ComPort) { $joy.ComPort = $ComPort }
& (Join-Path $withQgc "start-joy-direct.ps1") @joy
exit $LASTEXITCODE
