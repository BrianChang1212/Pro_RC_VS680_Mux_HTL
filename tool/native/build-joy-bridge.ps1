# Cross-compile board mavlink mux (static aarch64 musl via Zig).
#
# Builds: native/mavlink_mux  (FC :14550 <-> QGC :14551 + HID MANUAL_CONTROL)
# Legacy: also builds native/joy_mavlink_bridge if source present.
#
# Usage:
#   .\build-joy-bridge.ps1

[CmdletBinding()]
param(
    [string]$Zig = "D:\Brian\tools\zig\zig.exe"
)

$ErrorActionPreference = "Stop"
$muxSrc = Join-Path $PSScriptRoot "mavlink_mux.c"
$muxOut = Join-Path $PSScriptRoot "mavlink_mux"
$legacySrc = Join-Path $PSScriptRoot "joy_mavlink_bridge.c"
$legacyOut = Join-Path $PSScriptRoot "joy_mavlink_bridge"

if (-not (Test-Path -LiteralPath $Zig)) {
    Write-Error "Zig not found: $Zig"
}
if (-not (Test-Path -LiteralPath $muxSrc)) {
    Write-Error "Missing $muxSrc"
}

Write-Host "Building $muxOut (aarch64-linux-musl static)..."
& $Zig cc -target aarch64-linux-musl -O2 -static -o $muxOut $muxSrc
if ($LASTEXITCODE -ne 0) {
    Write-Error "zig cc failed for mavlink_mux ($LASTEXITCODE)"
}
Get-Item $muxOut | Format-List FullName, Length

if (Test-Path -LiteralPath $legacySrc) {
    Write-Host "Building legacy $legacyOut..."
    & $Zig cc -target aarch64-linux-musl -O2 -static -o $legacyOut $legacySrc
    if ($LASTEXITCODE -ne 0) {
        Write-Error "zig cc failed for joy_mavlink_bridge ($LASTEXITCODE)"
    }
}

Write-Host "OK. Push/run via: ..\start-with-qgc.ps1  or  ..\with-qgc\start-joy-direct.ps1"
