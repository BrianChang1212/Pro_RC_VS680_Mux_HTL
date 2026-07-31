# Capture until ~1000 dense HID->mux latency samples, then save CSV.
# Hold / wiggle pitch stick continuously (~25s at 50 Hz).
#
# Usage:
#   .\collect_joy_latency_1000.ps1
#   .\collect_joy_latency_1000.ps1 -Count 1000 -Seconds 35

param(
    [string]$Serial = "83bc469a34914114",
    [string]$InputDev = "/dev/input/event1",
    [int]$Count = 1000,
    [int]$Seconds = 35,
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
    $OutDir = Join-Path $RepoRoot "test\evidence\latency-mux-n$Count-$stamp"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "== Collect $Count joy->FC latency samples =="
Write-Host "out=$OutDir  capture=${Seconds}s"
Write-Host "HOLD / WIGGLE pitch stick continuously until capture ends."

$bin = Join-Path $ToolRoot "native\mavlink_mux"
$RemoteLat = "/data/local/tmp/mux_stick_lat_n$Count.log"
$remoteGet = "/sdcard/Download/joy_mux_getevent_n.txt"

# Fresh mux + empty -L log (avoid truncate-while-open holes)
adb -s $Serial shell "su 0 sh -c 'killall -9 mavlink_mux getevent 2>/dev/null; true'" | Out-Null
Start-Sleep -Seconds 0.5
adb -s $Serial push $bin /data/local/tmp/mavlink_mux | Out-Null
adb -s $Serial shell "su 0 chmod 755 /data/local/tmp/mavlink_mux" | Out-Null
adb -s $Serial shell "su 0 sh -c 'rm -f $RemoteLat $remoteGet; nohup /data/local/tmp/mavlink_mux -d $InputDev -p 14550 -q 14551 -g 14552 -r 50 -L $RemoteLat >/data/local/tmp/mavlink_mux.log 2>&1 &'"
$muxPid = ""
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 400
    $muxPid = ((adb -s $Serial shell "su 0 pidof mavlink_mux") | Out-String).Trim()
    if ($muxPid) { break }
}
if (-not $muxPid) {
    adb -s $Serial shell "su 0 tail -30 /data/local/tmp/mavlink_mux.log"
    throw "mavlink_mux failed to start"
}
Write-Host "mavlink_mux pid=$muxPid lat=$RemoteLat"

adb -s $Serial shell "su 0 sh -c 'getevent -lt $InputDev > $remoteGet 2>&1 &'"
Start-Sleep -Seconds 1
Write-Host "Capturing ${Seconds}s - keep stick deflected / moving..."
Start-Sleep -Seconds $Seconds
adb -s $Serial shell "su 0 killall getevent 2>/dev/null; sleep 0.5" | Out-Null

$localGet = Join-Path $OutDir "getevent.txt"
$localLat = Join-Path $OutDir "mux_stick_lat.log"
adb -s $Serial pull $remoteGet $localGet
adb -s $Serial pull $RemoteLat $localLat

$csv = Join-Path $OutDir "samples-n$Count.csv"
$summary = Join-Path $OutDir "summary.md"
python (Join-Path $LatDir "collect_joy_latency_n.py") --getevent $localGet --mux-log $localLat --count $Count --axis $Axis --mc-axis $McAxis --mc-threshold 100 --max-lag 0.05 --csv $csv --summary $summary
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "WARNING: fewer than $Count samples; see $OutDir"
    exit $code
}
Write-Host "Saved $Count samples -> $csv"
Write-Host "Done: $OutDir"
