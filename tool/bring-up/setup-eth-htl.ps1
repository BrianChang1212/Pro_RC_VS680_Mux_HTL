# One-click: VS680 eth0 <-> Godwit HTL FC MAVLink bring-up
#
# Flow:
#   1) Offline Maps — Wi-Fi ON, auto-cache Hsinchu downtown tiles, then stop
#   2) FC NET_* via USB COM
#   3) Board eth0 + Wi-Fi OFF + QGC UDP 14550
#
# WARNING: HTL bench defaults relax ARMING_CHECK (props OFF).
# Use -ProductionSafe to skip arming relax / ACC offsets.
#
# Usage:
#   .\setup-eth-htl.ps1
#   .\setup-eth-htl.ps1 -ComPort COM9 -BoardSerial 83bc469a34914114
#   .\setup-eth-htl.ps1 -ProductionSafe
#   .\setup-eth-htl.ps1 -SkipFc -BoardOnly
#   .\setup-eth-htl.ps1 -SkipVerify
#   .\setup-eth-htl.ps1 -SkipOfflineMaps
#   .\setup-eth-htl.ps1 -KeepWifi   # after maps: leave Wi-Fi on (eth half-duplex risk)

[CmdletBinding()]
param(
    [string]$ComPort = "",
    [string]$BoardSerial = "83bc469a34914114",
    [string]$FcIp = "192.168.144.14",
    [string]$BoardEthIp = "192.168.144.20",
    [int]$MavPort = 14550,
    [string]$QgcApk = "",
    [switch]$ProductionSafe,
    [switch]$SkipFc,
    [switch]$BoardOnly,
    [switch]$SkipFcReboot,
    [switch]$SkipVerify,
    [switch]$KeepWifi,
    [switch]$SkipOfflineMaps,
    [int]$InternetWaitSec = 180,
    [int]$MapZoom = 16
)

$ErrorActionPreference = "Stop"
$toolDir = $PSScriptRoot
$fcPy = Join-Path $toolDir "set_fc_eth_params.py"
$boardPs1 = Join-Path $toolDir "set-board-eth.ps1"
$mapPy = Join-Path $toolDir "cache_hsinchu_qgc_maps.py"
$qgcPkg = "org.mavlink.qgroundcontrolbeta"
$qgcActivity = "org.mavlink.qgroundcontrol.QGCActivity"
$mapCacheRel = "files/QGCMapCache300/qgcMapCache.db"

Write-Host @"
============================================================
  setup-eth-htl — VS680 eth0 <-> Godwit HTL
  FC IP     : $FcIp
  Board eth : $BoardEthIp
  MAVLink   : UDP $MavPort
  Maps      : $(if ($SkipOfflineMaps) { 'SKIP' } else { 'download before eth' })
  WARNING   : Remove props. HTL bench may relax ARMING_CHECK.
============================================================
"@

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
    Write-Error "adb not in PATH"
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not in PATH (need pymavlink)"
}
if (-not (Test-Path -LiteralPath $fcPy)) {
    Write-Error "Missing $fcPy"
}
if (-not (Test-Path -LiteralPath $boardPs1)) {
    Write-Error "Missing $boardPs1"
}
if (-not $SkipOfflineMaps -and -not (Test-Path -LiteralPath $mapPy)) {
    Write-Error "Missing $mapPy"
}

function Resolve-MavlinkComPort {
    param([string]$Port)
    if ($Port) { return $Port }
    # Prefer ArduPilot MAVLink friendly name; else VID_1209 MI_00
    $mav = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.FriendlyName -match 'ArduPilot MAVLink \(COM(\d+)\)' } |
        Select-Object -First 1
    if ($mav -and ($mav.FriendlyName -match 'COM(\d+)')) {
        return "COM$($Matches[1])"
    }
    $ents = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.DeviceID -match 'VID_1209&PID_5740&MI_00' -and $_.Name -match 'COM(\d+)' }
    foreach ($e in $ents) {
        if ($e.Name -match 'COM(\d+)') { return "COM$($Matches[1])" }
    }
    # Fallback: any 1209:5740 with COM
    $any = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object { $_.DeviceID -match 'VID_1209&PID_5740' -and $_.Name -match 'COM(\d+)' } |
        Select-Object -First 1
    if ($any -and ($any.Name -match 'COM(\d+)')) {
        Write-Warning "Using fallback COM$($Matches[1]) (verify MI_00 MAVLink)"
        return "COM$($Matches[1])"
    }
    Write-Error "No ArduPilot MAVLink COM found. Plug FC USB or pass -ComPort."
}

function Resolve-SisterWifiConnectScript {
    # toolDir = tool/bring-up → repo → Accton_Pro_RC
    $repoRoot = Split-Path (Split-Path $toolDir -Parent) -Parent
    $acctonRoot = Split-Path $repoRoot -Parent
    $candidates = @(
        (Join-Path $acctonRoot "20260722_Accton_Pro_RC_VS680_QGC_Joystick\tool\wifi\connect-board-wifi.ps1"),
        (Join-Path $repoRoot "..\20260722_Accton_Pro_RC_VS680_QGC_Joystick\tool\wifi\connect-board-wifi.ps1")
    )
    foreach ($p in $candidates) {
        $resolved = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
        if ($resolved) { return $resolved.Path }
    }
    return ""
}

function Get-QgcMapCacheBytes {
    param([string]$Serial)
    $path = "/data/user/0/$qgcPkg/$mapCacheRel"
    $raw = adb -s $Serial shell "su 0 stat -c %s $path 2>/dev/null" | Out-String
    $raw = $raw.Trim()
    if ($raw -match '^\d+$') { return [long]$raw }
    return 0L
}

function Test-BoardInternet {
    param([string]$Serial)
    $ping = adb -s $Serial shell "ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; echo `$?" | Out-String
    return ($ping.Trim() -eq "0")
}

function Wait-BoardInternet {
    param(
        [string]$Serial,
        [int]$TimeoutSec
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $ip = adb -s $Serial shell "ip -4 -o addr show wlan0 2>/dev/null" | Out-String
        $hasIp = ($ip -match 'inet\s+(\d{1,3}(?:\.\d{1,3}){3})')
        $online = Test-BoardInternet -Serial $Serial
        if ($hasIp -and $online) {
            Write-Host "OK: board internet via wlan0 ($($Matches[1]))"
            return $true
        }
        $left = [int]([math]::Ceiling(($deadline - (Get-Date)).TotalSeconds))
        Write-Host "  waiting internet... ${left}s left (connect Wi-Fi on board if needed)"
        Start-Sleep -Seconds 5
    }
    return $false
}

function Invoke-OfflineMapsStage {
    param(
        [string]$Serial,
        [int]$TimeoutSec,
        [int]$Zoom
    )

    Write-Host @"

------------------------------------------------------------
  Stage 1/3 — Offline Maps (Hsinchu auto-cache)
------------------------------------------------------------
  Target : Hsinchu downtown (Bing Hybrid, zoom $Zoom)
  Action : PC downloads tiles -> push QGC DB -> auto continue
"@

    # Wi-Fi still brought up (lab path); tile fetch itself uses PC internet.
    Write-Host "Enable Wi-Fi..."
    adb -s $Serial shell "svc wifi enable" | Out-Null
    Start-Sleep -Seconds 2

    $wifiConnect = Resolve-SisterWifiConnectScript
    if ($wifiConnect) {
        Write-Host "Associate Wi-Fi via: $wifiConnect"
        & $wifiConnect -BoardSerial $Serial
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "connect-board-wifi.ps1 failed (PC tile download may still work)."
        }
    } else {
        Write-Warning "Sister connect-board-wifi.ps1 not found — continuing with PC tile download."
    }

    # Best-effort board internet; do not hard-fail (tiles come from PC CDN).
    if (-not (Wait-BoardInternet -Serial $Serial -TimeoutSec ([Math]::Min($TimeoutSec, 60)))) {
        Write-Warning "Board has no internet yet — continuing; PC must reach Bing tile CDN."
    }

    $path = adb -s $Serial shell "pm path $qgcPkg"
    if (-not $path) {
        Write-Error "QGC package $qgcPkg not installed. Install APK first (set-board-eth.ps1 / -QgcApk)."
    }

    $baseline = Get-QgcMapCacheBytes -Serial $Serial
    Write-Host "Map cache baseline: $baseline bytes"

    Write-Host "Auto-cache Hsinchu tiles via $mapPy ..."
    & python $mapPy --serial $Serial --zoom $Zoom
    if ($LASTEXITCODE -ne 0) {
        Write-Error "cache_hsinchu_qgc_maps.py failed ($LASTEXITCODE)"
    }

    $final = Get-QgcMapCacheBytes -Serial $Serial
    Write-Host "OK: Offline Maps stage done (cache=$final bytes, was $baseline) — auto-stop."
}

# Stop forwarders that may hold COM
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'mavlink-forward|set_fc_eth_params' } |
    ForEach-Object {
        Write-Warning "Stopping PID $($_.ProcessId) holding python/COM"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1

if (-not $SkipOfflineMaps) {
    Invoke-OfflineMapsStage -Serial $BoardSerial -TimeoutSec $InternetWaitSec -Zoom $MapZoom
} else {
    Write-Host "Skip Offline Maps stage (-SkipOfflineMaps)"
}

if (-not $SkipFc -and -not $BoardOnly) {
    Write-Host @"

------------------------------------------------------------
  Stage 2/3 — FC NET_* via USB COM
------------------------------------------------------------
"@
    $ComPort = Resolve-MavlinkComPort -Port $ComPort
    Write-Host "FC COM: $ComPort"
    $pyArgs = @(
        $fcPy,
        "--port", $ComPort,
        "--fc-ip", $FcIp,
        "--board-ip", $BoardEthIp,
        "--mav-port", "$MavPort"
    )
    if ($ProductionSafe) { $pyArgs += "--production-safe" }
    if ($SkipFcReboot) { $pyArgs += "--skip-reboot" }
    & python @pyArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "set_fc_eth_params.py failed ($LASTEXITCODE)"
    }
} else {
    Write-Host "Skip FC param stage"
}

Write-Host @"

------------------------------------------------------------
  Stage 3/3 — Board eth0 + Wi-Fi OFF + QGC
------------------------------------------------------------
"@

$boardArgs = @{
    BoardSerial = $BoardSerial
    BoardEthIp  = $BoardEthIp
    MavPort     = $MavPort
}
if ($QgcApk) { $boardArgs.QgcApk = $QgcApk }
if ($KeepWifi) { $boardArgs.SkipWifiDisable = $true }

& $boardPs1 @boardArgs

if (-not $SkipVerify) {
    Write-Host "Verify eth UDP (5s tcpdump sample)..."
    $ser = $BoardSerial
    if (-not $ser) {
        $ser = (adb devices | Select-String "^\S+\s+device$" | ForEach-Object { ($_.Line -split "\s+")[0] } | Select-Object -First 1)
    }
    $dump = adb -s $ser shell "su 0 timeout 5 tcpdump -i eth0 -n udp port $MavPort -c 6 2>&1"
    Write-Host $dump
    if ($dump -match "$([regex]::Escape($FcIp)).*>.*$([regex]::Escape($BoardEthIp))\.$MavPort") {
        Write-Host "OK: FC -> board UDP seen on eth0"
    } else {
        Write-Warning "Did not see FC->board UDP in sample. Check cable / NET_ENABLE / QGC."
    }
    if ($dump -match "$([regex]::Escape($BoardEthIp))\.$MavPort.*>.*$([regex]::Escape($FcIp))") {
        Write-Host "OK: board -> FC UDP seen (full duplex)"
    } else {
        Write-Warning "No board->FC sample. Ensure Wi-Fi is OFF and QGC is open."
    }
}

Write-Host @"

Done.
  - Offline map tiles stay in app cache after Wi-Fi OFF.
  - Keep Wi-Fi OFF while using eth direct.
  - Check board QGC Connected / telemetry + map background.
  - Evidence: test/evidence/20260730-eth-htl-connected/
  - Re-run without maps: .\setup-eth-htl.ps1 -SkipOfflineMaps
"@
