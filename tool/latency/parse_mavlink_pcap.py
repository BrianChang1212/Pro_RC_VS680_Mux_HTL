#!/usr/bin/env python3
"""Parse MAVLink2 UDP payloads from a tcpdump -w pcap (linktype Ethernet).

Prints board-clock timestamps for MANUAL_CONTROL (69) and ATTITUDE (30).
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

try:
    from scapy.all import IP, UDP, rdpcap  # type: ignore
except ImportError:
    rdpcap = None


def parse_mavlink2_msgs(payload: bytes):
    """Yield (msgid, offset) for each MAVLink2 frame in payload."""
    i = 0
    n = len(payload)
    while i < n:
        if payload[i] != 0xFD:
            i += 1
            continue
        if i + 10 > n:
            break
        plen = payload[i + 1]
        incompat = payload[i + 2]
        # header 10 + payload + checksum 2 (+ signature 13 if bit0)
        frame_len = 10 + plen + 2
        if incompat & 0x01:
            frame_len += 13
        if i + frame_len > n:
            break
        msgid = payload[i + 7] | (payload[i + 8] << 8) | (payload[i + 9] << 16)
        yield msgid, i, payload[i : i + 10 + plen]
        i += frame_len


def decode_manual_control(body: bytes):
    # MAVLink2 MANUAL_CONTROL payload (minimal): target, x,y,z,r (int16), buttons (uint16)
    if len(body) < 11:
        return None
    target = body[0]
    x, y, z, r = struct.unpack_from("<hhhh", body, 1)
    buttons = struct.unpack_from("<H", body, 9)[0]
    return {"target": target, "x": x, "y": y, "z": z, "r": r, "buttons": buttons}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pcap")
    ap.add_argument("--board-ip", default="192.168.144.20")
    ap.add_argument("--fc-ip", default="192.168.144.14")
    ap.add_argument("--port", type=int, default=14550)
    ap.add_argument("--msgid", type=int, action="append", default=None)
    args = ap.parse_args()
    want = set(args.msgid) if args.msgid else {69, 30}

    if rdpcap is None:
        print("Need scapy: pip install scapy", file=sys.stderr)
        return 2

    pkts = rdpcap(args.pcap)
    rows = []
    for p in pkts:
        if not p.haslayer(UDP) or not p.haslayer(IP):
            continue
        ip, udp = p[IP], p[UDP]
        if udp.dport != args.port and udp.sport != args.port:
            continue
        direction = "?"
        if ip.src == args.board_ip and ip.dst == args.fc_ip:
            direction = "board->fc"
        elif ip.src == args.fc_ip and ip.dst == args.board_ip:
            direction = "fc->board"
        payload = bytes(udp.payload)
        for msgid, _off, frame in parse_mavlink2_msgs(payload):
            if msgid not in want:
                continue
            ts = float(p.time)
            extra = ""
            if msgid == 69 and len(frame) >= 10:
                mc = decode_manual_control(frame[10:])
                if mc:
                    extra = f" x={mc['x']} y={mc['y']} z={mc['z']} r={mc['r']}"
            rows.append((ts, direction, msgid, extra))

    print(f"pcap={args.pcap} packets={len(pkts)} hits={len(rows)}")
    for ts, direction, msgid, extra in rows:
        name = {69: "MANUAL_CONTROL", 30: "ATTITUDE"}.get(msgid, str(msgid))
        print(f"{ts:.6f}  {direction:10s}  msgid={msgid:3d} {name}{extra}")

    n69 = sum(1 for r in rows if r[2] == 69)
    n30 = sum(1 for r in rows if r[2] == 30)
    print(f"summary: MANUAL_CONTROL={n69} ATTITUDE={n30}")
    return 0 if n69 > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
