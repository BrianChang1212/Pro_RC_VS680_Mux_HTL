# One-click: mavlink_mux + QGC (Arm / Takeoff / RTL / telem on :14551).
# Stick: HID -> mux -> FC. QGC Joystick forced OFF.
#
# Usage:
#   .\start-with-qgc.ps1
#   .\start-with-qgc.ps1 -BringUpEth -SkipOfflineMaps
#   .\start-with-qgc.ps1 -RestartQgc

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

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$bringUp = Join-Path $here "..\bring-up"

if ($BringUpEth) {
    $setup = Join-Path $bringUp "setup-eth-htl.ps1"
    $setupArgs = @{
        BoardSerial = $BoardSerial
        SkipOfflineMaps = [bool]$SkipOfflineMaps
        ProductionSafe = [bool]$ProductionSafe
    }
    if ($ComPort) { $setupArgs.ComPort = $ComPort }
    Write-Host "== Stage A: eth bring-up (QGC may briefly listen :14550) =="
    & $setup @setupArgs
}

Write-Host "== Stage B: mux + QGC :14551 =="
$joy = @{
    BoardSerial = $BoardSerial
    Link = "eth"
    Hz = $Hz
    DurationSec = $DurationSec
    RestartQgc = [bool]$RestartQgc
}
if ($ComPort) { $joy.ComPort = $ComPort }
& (Join-Path $here "start-joy-direct.ps1") @joy
exit $LASTEXITCODE
