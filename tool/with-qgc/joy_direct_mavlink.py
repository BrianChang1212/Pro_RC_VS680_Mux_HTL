#!/usr/bin/env python3
"""Bypass QGC joystick: board HID -> MANUAL_CONTROL to FC (eth mux or USB).

Default link=eth runs on-board mavlink_mux:
  FC eth <-> board :14550 (mux) <-> QGC 127.0.0.1:14551
  + HID MANUAL_CONTROL injected toward FC from :14550

link=usb uses PC pymavlink over FC USB COM (fallback).

Usage:
  python joy_direct_mavlink.py
  python joy_direct_mavlink.py --link eth --hz 50 --duration 20
  python joy_direct_mavlink.py --link usb --port COM9
  python joy_direct_mavlink.py --no-qgc   # mux only, leave QGC stopped

Rebuild: .\\build-joy-bridge.ps1
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import subprocess
import sys
import threading
import time

from pymavlink import mavutil

QGC_PKG = "org.mavlink.qgroundcontrolbeta"
DEFAULT_SERIAL = "83bc469a34914114"
BOARD_IP = "192.168.144.20"
FC_IP = "192.168.144.14"
MAV_PORT = 14550
QGC_LISTEN_PORT = 14551
MUX_GCS_PORT = 14552
INPUT_DEV = "/dev/input/event1"
QGC_INI = (
    "/data/user/0/org.mavlink.qgroundcontrolbeta/files/"
    ".config/QGroundControl.org/QGroundControl.ini"
)
BOARD_MUX = "/data/local/tmp/mavlink_mux"
BOARD_MUX_LOG = "/data/local/tmp/mavlink_mux.log"
BOARD_MUX_LAT = "/data/local/tmp/mux_stick_lat.log"

CRC_EXTRA_HEARTBEAT = 50
CRC_EXTRA_MANUAL_CONTROL = 243
X25_INIT = 0xFFFF


def x25_crc_accumulate(b: int, crc: int) -> int:
    tmp = b ^ (crc & 0xFF)
    tmp ^= (tmp << 4) & 0xFF
    return ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF


def x25_crc(data: bytes, crc_extra: int) -> int:
    crc = X25_INIT
    for b in data:
        crc = x25_crc_accumulate(b, crc)
    return x25_crc_accumulate(crc_extra, crc)


def mavlink2_frame(msgid: int, payload: bytes, seq: int, sysid: int = 255, compid: int = 190, crc_extra: int = 0) -> bytes:
    plen = len(payload)
    header = struct.pack(
        "<BBBBBBB",
        0xFD,
        plen,
        0,
        0,
        seq & 0xFF,
        sysid & 0xFF,
        compid & 0xFF,
    ) + struct.pack("<I", msgid)[:3]
    crc = x25_crc(header[1:] + payload, crc_extra)
    return header + payload + struct.pack("<H", crc)


def msg_heartbeat(seq: int) -> bytes:
    payload = struct.pack("<IBBBBB", 0, 6, 8, 0, 4, 3)
    return mavlink2_frame(0, payload, seq, crc_extra=CRC_EXTRA_HEARTBEAT)


def msg_manual_control_bytes(seq: int, x: int, y: int, z: int, r: int, buttons: int = 0) -> bytes:
    payload = struct.pack(
        "<BhhhhH",
        1,
        _clamp_i16(x),
        _clamp_i16(y),
        _clamp_i16(z),
        _clamp_i16(r),
        buttons & 0xFFFF,
    )
    return mavlink2_frame(69, payload, seq, crc_extra=CRC_EXTRA_MANUAL_CONTROL)


def _clamp_i16(v: int) -> int:
    return max(-1000, min(1000, int(v)))


def adb(serial: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["adb", "-s", serial, *args], check=check, capture_output=True, text=True)


def resolve_com_port(explicit: str) -> str:
    if explicit:
        return explicit
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'ArduPilot MAVLink \\(COM(\\d+)\\)' } | Select-Object -First 1 -ExpandProperty FriendlyName",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    m = re.search(r"COM(\d+)", r.stdout or "")
    if m:
        return f"COM{m.group(1)}"
    r2 = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -match 'VID_1209&PID_5740&MI_00' -and $_.Name -match 'COM(\\d+)' } | Select-Object -First 1 -ExpandProperty Name",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    m2 = re.search(r"COM(\d+)", r2.stdout or "")
    if m2:
        return f"COM{m2.group(1)}"
    raise SystemExit("No ArduPilot MAVLink COM found. Pass --port COMx.")


def discover_fc_peer(serial: str, timeout_s: float = 6.0) -> tuple[str, int]:
    cmd = (
        f"su 0 timeout {int(timeout_s)} tcpdump -i eth0 -n -c 30 "
        f"udp port {MAV_PORT} 2>/dev/null"
    )
    r = adb(serial, "shell", cmd, check=False)
    text = (r.stdout or "") + (r.stderr or "")
    pat = re.compile(
        rf"IP\s+(\d+\.\d+\.\d+\.\d+)\.(\d+)\s+>\s+{re.escape(BOARD_IP)}\.{MAV_PORT}"
    )
    for line in text.splitlines():
        m = pat.search(line)
        if m:
            return m.group(1), int(m.group(2))
    raise SystemExit("Could not discover FC UDP peer on eth0. Is eth HTL up?")


class StickState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.raw = {"ABS_X": 128, "ABS_Y": 128, "ABS_Z": 128, "ABS_RZ": 128}

    def set_abs(self, name: str, value: int) -> None:
        with self.lock:
            self.raw[name] = value

    def axes_mc(self) -> tuple[int, int, int, int]:
        with self.lock:
            x = _axis_to_mc(self.raw.get("ABS_Y", 128), invert=True)
            y = _axis_to_mc(self.raw.get("ABS_X", 128), invert=False)
            z_sym = _axis_to_mc(self.raw.get("ABS_RZ", 128), invert=False)
            z = int((z_sym + 1000) / 2)
            if abs(self.raw.get("ABS_RZ", 128) - 128) < 20:
                z = 0
            r = _axis_to_mc(self.raw.get("ABS_Z", 128), invert=False)
            return x, y, z, r


def _axis_to_mc(raw: int, invert: bool = False) -> int:
    v = (raw - 128) * (1000 / 128.0)
    if invert:
        v = -v
    return _clamp_i16(int(v))


def getevent_loop(serial: str, stick: StickState, stop: threading.Event) -> None:
    proc = subprocess.Popen(
        ["adb", "-s", serial, "exec-out", "su", "0", "getevent", "-lt", INPUT_DEV],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    abs_re = re.compile(r"EV_ABS\s+(ABS_\w+)\s+([0-9a-fA-F]+)")
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if stop.is_set():
                break
            m = abs_re.search(line)
            if not m:
                continue
            name = m.group(1)
            if name not in stick.raw:
                continue
            val = int(m.group(2), 16)
            if val >= 0x80000000:
                val -= 0x100000000
            if val < 0:
                val = 0
            if val > 255:
                val = val & 0xFF
            stick.set_abs(name, val)
    finally:
        stop.set()
        try:
            proc.kill()
        except Exception:
            pass


class UsbSender:
    def __init__(self, port: str, baud: int = 115200) -> None:
        print(f"Open FC USB {port} @ {baud}...")
        self.m = mavutil.mavlink_connection(port, baud=baud, source_system=255, source_component=190)
        self.m.wait_heartbeat(timeout=10)
        print(f"HB ok sysid={self.m.target_system}")

    def send(self, x: int, y: int, z: int, r: int, seq_unused: int = 0) -> None:
        self.m.mav.manual_control_send(
            self.m.target_system,
            _clamp_i16(x),
            _clamp_i16(y),
            _clamp_i16(z),
            _clamp_i16(r),
            0,
        )

    def heartbeat(self) -> None:
        self.m.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0,
            0,
            mavutil.mavlink.MAV_STATE_ACTIVE,
        )

    def close(self) -> None:
        try:
            self.m.close()
        except Exception:
            pass


def native_mux_host_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "native", "mavlink_mux")


def _ini_set_key(text: str, section: str, key: str, value: str) -> str:
    """Set key=value under [section]; create section/key if missing."""
    sec_re = re.compile(rf"^\[{re.escape(section)}\]\s*$", re.M)
    m = sec_re.search(text)
    if not m:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + f"\n[{section}]\n{key}={value}\n"

    start = m.end()
    nxt = re.search(r"^\[", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    body = text[start:end]
    key_re = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    if key_re.search(body):
        body = key_re.sub(f"{key}={value}", body, count=1)
    else:
        if body and not body.startswith("\n"):
            body = "\n" + body
        if not body.endswith("\n"):
            body += "\n"
        body += f"{key}={value}\n"
    return text[:start] + body + text[end:]


def _ini_remove_section(text: str, section: str) -> str:
    sec_re = re.compile(rf"^\[{re.escape(section)}\]\s*$", re.M)
    m = sec_re.search(text)
    if not m:
        return text
    start = m.start()
    nxt = re.search(r"^\[", text[m.end() :], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[:start] + text[end:]


def patch_qgc_ini_for_mux(serial: str) -> None:
    """Disable AutoConnect UDP :14550; add Comm Link UDP listen :14551."""
    print(
        f"Patch QGC.ini: LinkConfigurations UDP :{QGC_LISTEN_PORT}, "
        "autoConnectUDP=false, JoystickEnabled=false"
    )
    own = subprocess.run(
        ["adb", "-s", serial, "shell", f"su 0 stat -c %u:%g {QGC_INI}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    owner = (own.stdout or "").strip() or "0:0"
    r = subprocess.run(
        ["adb", "-s", serial, "shell", f"su 0 cat {QGC_INI}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise SystemExit(f"Failed to read {QGC_INI}: {r.stderr}")
    text = r.stdout.replace("\r\n", "\n").replace("\r", "\n")

    # Stop Autoconnect from grabbing :14550 (mux owns it).
    text = _ini_set_key(text, "AutoConnect", "autoConnectUDP", "false")
    text = _ini_set_key(text, "AutoConnect", "udpListenPort", str(QGC_LISTEN_PORT))
    # Pre-v5 group name (harmless if unused)
    text = _ini_set_key(text, "LinkManager", "autoConnectUDP", "false")
    text = _ini_set_key(text, "Vehicle1", "JoystickEnabled", "false")

    # Manual UDP listen link (TypeUdp=1 when Serial link is compiled in).
    text = _ini_remove_section(text, "LinkConfigurations")
    if text and not text.endswith("\n"):
        text += "\n"
    text += (
        "\n[LinkConfigurations]\n"
        "count=1\n"
        "Link0\\name=BoardMux14551\n"
        "Link0\\type=1\n"
        "Link0\\auto=true\n"
        "Link0\\high_latency=false\n"
        "Link0\\port=%d\n"
        "Link0\\hostCount=0\n"
    ) % QGC_LISTEN_PORT

    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_qgc_mux.ini")
    with open(local, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    adb(serial, "push", local, "/data/local/tmp/QGroundControl.ini")
    adb(
        serial,
        "shell",
        f"su 0 cp /data/local/tmp/QGroundControl.ini {QGC_INI} && "
        f"su 0 chown {owner} {QGC_INI} && su 0 chmod 660 {QGC_INI}",
        check=False,
    )
    try:
        os.remove(local)
    except OSError:
        pass


def start_qgc(serial: str) -> None:
    adb(
        serial,
        "shell",
        f"am start -n {QGC_PKG}/org.mavlink.qgroundcontrol.QGCActivity",
        check=False,
    )


def run_eth_mux(
    serial: str,
    hz: float,
    duration: float,
    with_qgc: bool,
) -> int:
    """Push/run board mavlink_mux; optionally start QGC on :14551."""
    host_bin = native_mux_host_path()
    if not os.path.isfile(host_bin):
        raise SystemExit(
            f"Missing {host_bin}\nBuild first: .\\build-joy-bridge.ps1"
        )

    adb(
        serial,
        "shell",
        "su 0 sh -c 'killall -9 mavlink_mux joy_mavlink_bridge 2>/dev/null; "
        "for p in $(pidof mavlink_mux); do kill -9 $p; done; true'",
        check=False,
    )
    time.sleep(0.5)

    if with_qgc:
        patch_qgc_ini_for_mux(serial)

    print(f"Push {host_bin} -> {BOARD_MUX}")
    adb(serial, "push", host_bin, BOARD_MUX)
    adb(serial, "shell", f"su 0 chmod 755 {BOARD_MUX}", check=False)

    cmd = (
        f"{BOARD_MUX} -d {INPUT_DEV} -p {MAV_PORT} "
        f"-q {QGC_LISTEN_PORT} -g {MUX_GCS_PORT} -r {int(hz)} "
        f"-L {BOARD_MUX_LAT}"
    )
    if duration and duration > 0:
        cmd += f" -t {int(duration)}"

    # Background so QGC can share the board; log to file.
    launch = (
        f"su 0 sh -c 'pkill -x mavlink_mux 2>/dev/null; "
        f"nohup {cmd} >{BOARD_MUX_LOG} 2>&1 &'"
    )
    print(f"Start mux: {cmd}")
    adb(serial, "shell", launch, check=False)
    time.sleep(1.0)

    # Confirm mux holds 14550
    chk = subprocess.run(
        [
            "adb",
            "-s",
            serial,
            "shell",
            f"su 0 sh -c 'ss -ulnp 2>/dev/null | grep -E \":{MAV_PORT}|mavlink_mux\" "
            f"|| netstat -ulnp 2>/dev/null | grep {MAV_PORT}; "
            f"head -5 {BOARD_MUX_LOG}'",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(chk.stdout.strip() or "(no ss/netstat output yet)")
    if "mavlink_mux" not in (chk.stdout + chk.stderr) and "14550" not in chk.stdout:
        # Still try pidof
        pid = subprocess.run(
            ["adb", "-s", serial, "shell", "su 0 pidof mavlink_mux"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print(f"pidof mavlink_mux: {(pid.stdout or '').strip() or 'NONE'}")
        if not (pid.stdout or "").strip():
            log = subprocess.run(
                ["adb", "-s", serial, "shell", f"su 0 cat {BOARD_MUX_LOG}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            print(log.stdout)
            raise SystemExit("mavlink_mux failed to start")

    if with_qgc:
        print("Start QGC (UDP listen 14551)...")
        start_qgc(serial)
        time.sleep(8.0)
        ports = subprocess.run(
            [
                "adb",
                "-s",
                serial,
                "shell",
                "su 0 sh -c 'ss -ulnp 2>/dev/null | grep -E \"14550|14551|14552\" "
                "|| netstat -uln 2>/dev/null | grep -E \"14550|14551|14552\"'",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        print("UDP ports:")
        print(ports.stdout.strip() or "(none)")

    print(
        "Mux running: stick -> eth MANUAL_CONTROL; FC telem -> QGC :14551.\n"
        "Props OFF. Ctrl+C stops mux (and leaves QGC up)."
    )
    try:
        if duration and duration > 0:
            time.sleep(duration + 1.0)
            rc = 0
        else:
            while True:
                time.sleep(2.0)
                alive = subprocess.run(
                    ["adb", "-s", serial, "shell", "su 0 pidof mavlink_mux"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if not (alive.stdout or "").strip():
                    print("mavlink_mux exited; see log:")
                    adb(serial, "shell", f"su 0 tail -20 {BOARD_MUX_LOG}", check=False)
                    rc = 1
                    break
    except KeyboardInterrupt:
        print("\nStopping mavlink_mux...")
        rc = 130
    finally:
        adb(
            serial,
            "shell",
            "su 0 sh -c 'killall mavlink_mux 2>/dev/null; sleep 0.3; "
            "killall -9 mavlink_mux 2>/dev/null; true'",
            check=False,
        )
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="Direct HID->FC MANUAL_CONTROL (bypass QGC joystick)")
    ap.add_argument("--serial", default=DEFAULT_SERIAL)
    ap.add_argument("--link", choices=["usb", "eth"], default="eth")
    ap.add_argument("--port", default="", help="FC MAVLink COM for --link usb")
    ap.add_argument("--hz", type=float, default=50.0)
    ap.add_argument("--duration", type=float, default=0.0)
    ap.add_argument("--fc-port", type=int, default=0, help="unused for native eth")
    ap.add_argument("--stop-qgc", action="store_true", help="force-stop QGC before start")
    ap.add_argument(
        "--restart-qgc",
        action="store_true",
        help="legacy alias: eth mux starts QGC unless --no-qgc",
    )
    ap.add_argument(
        "--no-qgc",
        action="store_true",
        help="eth: run mux only (do not start QGC after bind)",
    )
    args = ap.parse_args()

    print(f"Board: {args.serial}")
    print(f"Link : {args.link}  rate={args.hz} Hz")
    print("Bypass: QGC joystick path (HID -> mux/bridge -> FC)")

    if args.stop_qgc or args.link == "eth":
        print("Stop QGC (free UDP 14550 for mux)...")
        adb(args.serial, "shell", f"am force-stop {QGC_PKG}", check=False)
        time.sleep(1.0)
    else:
        print("NOTE: Disable QGC Joystick Enable to avoid dual MANUAL_CONTROL.")

    adb(args.serial, "shell", "svc wifi disable", check=False)

    if args.link == "eth":
        with_qgc = not args.no_qgc
        return run_eth_mux(args.serial, args.hz, args.duration, with_qgc)

    # USB fallback path (PC pymavlink)
    com = resolve_com_port(args.port)
    sender = UsbSender(com)
    stick = StickState()
    stop = threading.Event()
    threading.Thread(target=getevent_loop, args=(args.serial, stick, stop), daemon=True).start()

    period = 1.0 / max(args.hz, 1.0)
    t0 = time.monotonic()
    n_mc = 0
    n_hb = 0
    last_hb = 0.0
    last_stat = 0.0
    print("Streaming USB COM. Move sticks. Ctrl+C to stop.")

    try:
        while not stop.is_set():
            now = time.monotonic()
            if args.duration and (now - t0) >= args.duration:
                break
            if now - last_hb >= 1.0:
                sender.heartbeat()
                n_hb += 1
                last_hb = now
            x, y, z, r = stick.axes_mc()
            sender.send(x, y, z, r)
            n_mc += 1
            if now - last_stat >= 1.0:
                print(f"  mc={n_mc} hb={n_hb} x={x:5d} y={y:5d} z={z:5d} r={r:5d}", flush=True)
                last_stat = now
            time.sleep(max(0.0, period - (time.monotonic() - now)))
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop.set()
        sender.close()
        if args.restart_qgc:
            print("Restart QGC...")
            adb(
                args.serial,
                "shell",
                f"am start -n {QGC_PKG}/org.mavlink.qgroundcontrol.QGCActivity",
                check=False,
            )
    print(f"Done. MANUAL_CONTROL={n_mc} HEARTBEAT={n_hb}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
