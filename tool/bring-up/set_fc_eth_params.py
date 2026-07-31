#!/usr/bin/env python3
"""Idempotent Godwit HTL eth MAVLink + bench arming params via USB COM.

Defaults match 2026-07-30 RealDrone eth bring-up:
  NET_ENABLE=1, static 192.168.144.14/24
  NET_P1 UDP Client -> board 192.168.144.20:14550 MAVLink2
  ARMING_CHECK=0 + tiny INS_ACCOFFS_* (HTL bench; props OFF)
  BATT_MONITOR=0 + FS_THR_ENABLE=0 (HTL: no batt / no RC radio)

Usage:
  python set_fc_eth_params.py --port COM9
  python set_fc_eth_params.py --port COM9 --production-safe
  python set_fc_eth_params.py --port COM9 --skip-reboot
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    from pymavlink import mavutil
except ImportError:
    print("Install: python -m pip install pymavlink pyserial", file=sys.stderr)
    sys.exit(1)


def get_param(m, name: str, timeout: float = 2.5):
    m.mav.param_request_read_send(
        m.target_system, m.target_component, name.encode("ascii"), -1
    )
    t0 = time.time()
    while time.time() - t0 < timeout:
        msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.35)
        if not msg:
            continue
        n = msg.param_id
        if isinstance(n, bytes):
            n = n.decode("utf-8", "ignore")
        n = n.rstrip("\x00")
        if n == name:
            return float(msg.param_value)
    return None


def set_param(m, name: str, value: float, tol: float = 1e-3) -> bool:
    cur = get_param(m, name)
    if cur is not None and abs(cur - float(value)) <= tol:
        print(f"  OK  {name}={cur} (unchanged)")
        return True
    m.mav.param_set_send(
        m.target_system,
        m.target_component,
        name.encode("ascii"),
        float(value),
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    )
    t0 = time.time()
    while time.time() - t0 < 3.0:
        msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.35)
        if not msg:
            continue
        n = msg.param_id
        if isinstance(n, bytes):
            n = n.decode("utf-8", "ignore")
        n = n.rstrip("\x00")
        if n == name:
            print(f"  SET {name}={msg.param_value}")
            return True
    print(f"  WARN no ACK for {name}")
    return False


def close_conn(m) -> None:
    """Release COM so Windows allows reopen after reboot."""
    if m is None:
        return
    try:
        if hasattr(m, "port") and m.port:
            try:
                m.port.close()
            except Exception:
                pass
        m.close()
    except Exception:
        pass
    time.sleep(1.0)


def reboot_wait(
    port: str, baud: int, m: "mavutil.mavfile | None" = None
) -> "mavutil.mavfile":
    print("Rebooting FC...")
    if m is None:
        m = mavutil.mavlink_connection(port, baud=baud)
        m.wait_heartbeat(timeout=10)
    m.mav.command_long_send(
        m.target_system,
        m.target_component,
        mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
        0,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    close_conn(m)
    time.sleep(10)
    for i in range(20):
        try:
            m2 = mavutil.mavlink_connection(port, baud=baud)
            m2.wait_heartbeat(timeout=3)
            print(f"HB after reboot (try {i + 1}) sysid={m2.target_system}")
            return m2
        except Exception as e:
            print(f"  wait {i + 1}: {e}")
            time.sleep(2)
    raise SystemExit("FC did not return after reboot")


def main() -> int:
    ap = argparse.ArgumentParser(description="Configure FC eth MAVLink for VS680")
    ap.add_argument("--port", default="COM9", help="ArduPilot MAVLink COM port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--fc-ip", default="192.168.144.14")
    ap.add_argument("--board-ip", default="192.168.144.20")
    ap.add_argument("--mav-port", type=int, default=14550)
    ap.add_argument("--skip-reboot", action="store_true")
    ap.add_argument(
        "--production-safe",
        action="store_true",
        help="Do not set ARMING_CHECK=0, ACC offsets, BATT_MONITOR, FS_THR_ENABLE",
    )
    args = ap.parse_args()

    fc = [int(x) for x in args.fc_ip.split(".")]
    brd = [int(x) for x in args.board_ip.split(".")]
    if len(fc) != 4 or len(brd) != 4:
        print("bad IP", file=sys.stderr)
        return 2

    print(f"Open {args.port} @ {args.baud}")
    m = mavutil.mavlink_connection(args.port, baud=args.baud)
    m.wait_heartbeat(timeout=15)
    print(f"HB sysid={m.target_system} comp={m.target_component}")

    print("Stage1: NET stack + address")
    set_param(m, "NET_ENABLE", 1)
    set_param(m, "NET_DHCP", 0)
    set_param(m, "NET_IPADDR0", fc[0])
    set_param(m, "NET_IPADDR1", fc[1])
    set_param(m, "NET_IPADDR2", fc[2])
    set_param(m, "NET_IPADDR3", fc[3])
    set_param(m, "NET_NETMASK", 24)
    set_param(m, "NET_GWADDR0", fc[0])
    set_param(m, "NET_GWADDR1", fc[1])
    set_param(m, "NET_GWADDR2", fc[2])
    set_param(m, "NET_GWADDR3", 1)

    need_reboot = True
    if not args.skip_reboot:
        m = reboot_wait(args.port, args.baud, m)
    else:
        need_reboot = False

    print("Stage2: NET_P1 UDP Client -> board:14550")
    set_param(m, "NET_P1_TYPE", 1)
    if not args.skip_reboot and need_reboot:
        # TYPE change often needs reboot to expose/apply port fields
        m = reboot_wait(args.port, args.baud, m)

    set_param(m, "NET_P1_IP0", brd[0])
    set_param(m, "NET_P1_IP1", brd[1])
    set_param(m, "NET_P1_IP2", brd[2])
    set_param(m, "NET_P1_IP3", brd[3])
    set_param(m, "NET_P1_PORT", args.mav_port)
    set_param(m, "NET_P1_PROTOCOL", 2)

    if not args.production_safe:
        print("Stage3: HTL bench arming relax (PROPS OFF)")
        set_param(m, "ARMING_CHECK", 0)
        # No physical battery / RC on HTL: avoid MAV_STATE_CRITICAL so QGC
        # can set flying=true and swap Takeoff -> Land / enable Return.
        set_param(m, "BATT_MONITOR", 0)
        set_param(m, "FS_THR_ENABLE", 0)
        # Keep MAVLink stick overrides enabled (clear Ignore-Overrides bit1).
        cur = get_param(m, "RC_OPTIONS")
        if cur is not None and (int(cur) & 2):
            set_param(m, "RC_OPTIONS", float(int(cur) & ~2))
        elif cur is not None:
            print(f"  OK  RC_OPTIONS={cur}")
        for k in ("INS_ACCOFFS_X", "INS_ACCOFFS_Y", "INS_ACCOFFS_Z"):
            cur = get_param(m, k)
            if cur is not None and abs(cur) < 1e-6:
                set_param(m, k, 0.01)
            elif cur is not None:
                print(f"  OK  {k}={cur}")
    else:
        print("Stage3: skipped (--production-safe)")

    if not args.skip_reboot:
        m = reboot_wait(args.port, args.baud, m)

    print("Verify:")
    for k in (
        "NET_ENABLE",
        "NET_DHCP",
        "NET_IPADDR3",
        "NET_P1_TYPE",
        "NET_P1_PORT",
        "NET_P1_PROTOCOL",
        "NET_P1_IP3",
        "ARMING_CHECK",
        "BATT_MONITOR",
        "FS_THR_ENABLE",
    ):
        print(f"  {k}={get_param(m, k)}")

    close_conn(m)
    print("FC eth params done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
