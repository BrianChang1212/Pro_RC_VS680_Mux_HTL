# Configure VS680 eth0 for FC direct MAVLink (HTL eth path).
#
# - Disable Wi-Fi (required: Android otherwise egresses QGC replies on wlan0)
# - Assign static eth0 IPv4
# - Ensure QGC beta installed/running and listening UDP 14550
#
# Usage:
#   .\set-board-eth.ps1
#   .\set-board-eth.ps1 -BoardSerial 83bc469a34914114 -BoardEthIp 192.168.144.20

[CmdletBinding()]
param(
    [string]$BoardSerial = "",
    [string]$BoardEthIp = "192.168.144.20",
    [int]$Prefix = 24,
    [int]$MavPort = 14550,
    [string]$QgcApk = "",
    [switch]$SkipWifiDisable,
    [switch]$SkipQgcStart
)

$ErrorActionPreference = "Stop"

function Get-AdbDeviceSerials {
    $lines = adb devices | Select-String "^\S+\s+device$"
    foreach ($m in $lines) {
        ($m.Line -split "\s+")[0]
    }
}

function Resolve-BoardSerial {
    param([string]$Serial)
    if ($Serial) {
        $hit = adb devices | Select-String "^$Serial\s+device$"
        if (-not $hit) { Write-Error "adb device $Serial not found" }
        return $Serial
    }
    $serials = @(Get-AdbDeviceSerials)
    if ($serials.Count -eq 1) { return $serials[0] }
    if ($serials.Count -eq 0) { Write-Error "No adb device in device state" }
    Write-Error "Multiple adb devices: $($serials -join ', '). Pass -BoardSerial."
}

function Resolve-QgcApk {
    param([string]$Explicit)
    if ($Explicit) {
        if (-not (Test-Path -LiteralPath $Explicit)) {
            Write-Error "APK not found: $Explicit"
        }
        return $Explicit
    }
    # PSScriptRoot = tool/bring-up → repo → Accton_Pro_RC sibling projects
    $repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $acctonRoot = Split-Path $repoRoot -Parent
    $candidates = @(
        (Join-Path $acctonRoot "20260722_Accton_Pro_RC_VS680_QGC_Joystick\tool\apk"),
        (Join-Path $repoRoot "..\20260722_Accton_Pro_RC_VS680_QGC_Joystick\tool\apk")
    )
    foreach ($dir in $candidates) {
        $resolved = Resolve-Path -LiteralPath $dir -ErrorAction SilentlyContinue
        if (-not $resolved) { continue }
        $apk = Get-ChildItem -Path $resolved.Path -Filter "QGroundControl64*.apk" -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($apk) { return $apk.FullName }
    }
    return ""
}

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    Write-Error "adb not in PATH"
}

$BoardSerial = Resolve-BoardSerial -Serial $BoardSerial
Write-Host "Board serial: $BoardSerial"
Write-Host "eth0 target : $BoardEthIp/$Prefix"

if (-not $SkipWifiDisable) {
    Write-Host "Disable Wi-Fi (eth half-duplex workaround)..."
    adb -s $BoardSerial shell "svc wifi disable" | Out-Null
    Start-Sleep -Seconds 2
}

Write-Host "Configure eth0..."
adb -s $BoardSerial shell "su 0 ip link set eth0 up"
adb -s $BoardSerial shell "su 0 sh -c 'ip addr flush dev eth0 2>/dev/null || true'"
adb -s $BoardSerial shell "su 0 ip addr add ${BoardEthIp}/${Prefix} dev eth0"
$ethShow = adb -s $BoardSerial shell "su 0 ip -4 addr show eth0" | Out-String
Write-Host $ethShow.TrimEnd()
if ($ethShow -notmatch [regex]::Escape($BoardEthIp)) {
    Write-Warning "eth0 missing $BoardEthIp — check cable / root (su 0)"
}

$pkg = "org.mavlink.qgroundcontrolbeta"
$activity = "org.mavlink.qgroundcontrol.QGCActivity"
$path = adb -s $BoardSerial shell "pm path $pkg"
if (-not $path) {
    $apk = Resolve-QgcApk -Explicit $QgcApk
    if (-not $apk) {
        Write-Error "QGC not installed and no QGroundControl64*.apk found. Pass -QgcApk."
    }
    Write-Host "Installing QGC: $apk"
    adb -s $BoardSerial install -r -g $apk
}

if (-not $SkipQgcStart) {
    Write-Host "Start QGC..."
    adb -s $BoardSerial shell "am force-stop $pkg" | Out-Null
    adb -s $BoardSerial shell "am start -n $pkg/$activity" | Out-Null
    Start-Sleep -Seconds 4
}

$listen = adb -s $BoardSerial shell "ss -ulnp 2>/dev/null | grep :$MavPort"
if ($listen) {
    Write-Host "OK: board listening UDP $MavPort"
    Write-Host $listen
} else {
    Write-Warning "UDP $MavPort not seen yet — open QGC UI if needed"
}

$wifi = adb -s $BoardSerial shell "settings get global wifi_on"
Write-Host "wifi_on=$wifi (expect 0 for eth bring-up)"
Write-Host "Board eth setup done."
