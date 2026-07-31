# Start board mavlink mux: HID MANUAL_CONTROL + FC telem to QGC.
#
# Default -Link eth (option B):
#   FC eth <-> board :14550 (mavlink_mux) <-> QGC 127.0.0.1:14551
#   Stick HID -> MANUAL_CONTROL injected from :14550
#
# Fallback -Link usb: PC pymavlink over FC USB COM (QGC not in path).
#
# Usage:
#   .\start-joy-direct.ps1
#   .\start-joy-direct.ps1 -Hz 50 -DurationSec 30
#   .\start-joy-direct.ps1 -NoQgc
#   .\start-joy-direct.ps1 -Link usb -ComPort COM9
#   .\build-joy-bridge.ps1   # rebuild native/mavlink_mux

[CmdletBinding()]
param(
    [string]$BoardSerial = "83bc469a34914114",
    [ValidateSet("eth", "usb")]
    [string]$Link = "eth",
    [string]$ComPort = "",
    [double]$Hz = 50,
    [int]$DurationSec = 0,
    [switch]$StopQgc,
    [switch]$RestartQgc,
    [switch]$NoQgc
)

$ErrorActionPreference = "Stop"
$py = Join-Path $PSScriptRoot "joy_direct_mavlink.py"
$bin = Join-Path $PSScriptRoot "..\native\mavlink_mux"
if (-not (Test-Path -LiteralPath $py)) { Write-Error "Missing $py" }
if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { Write-Error "adb not in PATH" }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Error "python not in PATH" }
if ($Link -eq "eth" -and -not (Test-Path -LiteralPath $bin)) {
    Write-Error "Missing $bin — run ..\native\build-joy-bridge.ps1 first"
}

Write-Host @"
============================================================
  joy-direct / mavlink mux (option B)
  Board : $BoardSerial
  Link  : $Link
  Rate  : $Hz Hz
  eth   : FC:14550 <-> mux <-> QGC:14551
  QGC   : Arm / Takeoff / RTL / Loiter / Guided (via mux forward)
  Stick : MANUAL_CONTROL only (off-center); idle sticks = no MC
  WARNING: Props OFF. QGC Joystick Enable forced off.
============================================================
"@

$argv = @(
    $py,
    "--serial", $BoardSerial,
    "--link", $Link,
    "--hz", "$Hz"
)
if ($ComPort) { $argv += @("--port", $ComPort) }
if ($DurationSec -gt 0) { $argv += @("--duration", "$DurationSec") }
if ($StopQgc) { $argv += "--stop-qgc" }
if ($RestartQgc) { $argv += "--restart-qgc" }
if ($NoQgc) { $argv += "--no-qgc" }

& python @argv
exit $LASTEXITCODE
