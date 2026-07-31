# Measure HID event -> mux stick inject latency (same CLOCK_MONOTONIC).
# T0: getevent -lt
# T1: mavlink_mux -L log line (send_stick time)
#
# Prerequisites: mux running with -L /data/local/tmp/mux_stick_lat.log
# Usage:
#   .\measure_joy_mux_latency.ps1
#   .\measure_joy_mux_latency.ps1 -Seconds 45

param(
    [string]$Serial = "83bc469a34914114",
    [string]$InputDev = "/dev/input/event1",
    [int]$Seconds = 40,
    [string]$Axis = "ABS_Y",
    [ValidateSet("x", "y", "z", "r")]
    [string]$McAxis = "x",
    [string]$RemoteLat = "/data/local/tmp/mux_stick_lat.log",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$LatDir = $PSScriptRoot
$ToolRoot = Split-Path $LatDir -Parent
$RepoRoot = Split-Path $ToolRoot -Parent
if (-not $OutDir) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutDir = Join-Path $RepoRoot "test\evidence\latency-mux-$stamp"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "== Joy->FC latency (mux path, CLOCK_MONOTONIC) =="
Write-Host "serial=$Serial seconds=$Seconds out=$OutDir"
Write-Host "MOVE the pitch stick (ABS_Y) hard every ~2 seconds during capture."

$muxPid = (adb -s $Serial shell "su 0 pidof mavlink_mux").Trim()
if (-not $muxPid) {
    throw "mavlink_mux not running. Start: ..\start-no-qgc.ps1  or  ..\start-with-qgc.ps1"
}
Write-Host "mavlink_mux pid=$muxPid"

$remoteGet = "/sdcard/Download/joy_mux_getevent.txt"
adb -s $Serial shell "su 0 killall getevent 2>/dev/null; rm -f $remoteGet; : > $RemoteLat" | Out-Null

adb -s $Serial shell "su 0 sh -c 'getevent -lt $InputDev > $remoteGet 2>&1 &'"
Start-Sleep -Seconds 1
adb -s $Serial shell "su 0 ps -A | grep getevent"
Write-Host "Capturing ${Seconds}s - MOVE pitch stick now..."
Start-Sleep -Seconds $Seconds

adb -s $Serial shell "su 0 killall getevent 2>/dev/null; sleep 0.5" | Out-Null

$localGet = Join-Path $OutDir "getevent.txt"
$localLat = Join-Path $OutDir "mux_stick_lat.log"
adb -s $Serial pull $remoteGet $localGet
adb -s $Serial pull $RemoteLat $localLat

Write-Host ("pulled getevent={0} latlog={1}" -f (Get-Item $localGet).Length, (Get-Item $localLat).Length)

$py = Join-Path $LatDir "analyze_joystick_latency.py"
$csv = Join-Path $OutDir "samples.csv"
python $py --getevent $localGet --mux-log $localLat --axis $Axis --mc-axis $McAxis --hid-threshold 8000 --mc-threshold 100 --min-gap 1.5 --match-window 0.25 --csv $csv | Tee-Object -FilePath (Join-Path $OutDir "analyze.log")

@(
    "# Joy -> FC latency (mux path)",
    "",
    "- Path: HID $InputDev -> mavlink_mux send_stick -> eth0 UDP :14550",
    "- Metric: L_cmd = T1 - T0 (both CLOCK_MONOTONIC)",
    "- T0: getevent -lt",
    "- T1: mux -L log at send_stick",
    "- Axis: HID $Axis <-> MC $McAxis",
    "- Duration: ${Seconds}s"
) -join "`n" | Set-Content -Path (Join-Path $OutDir "README.md") -Encoding utf8
Write-Host "Done: $OutDir"
