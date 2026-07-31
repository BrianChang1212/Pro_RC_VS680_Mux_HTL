#!/usr/bin/env python3
import csv
from pathlib import Path

from scapy.all import IP, UDP, rdpcap  # type: ignore

ev = Path(
    r"D:\Brian\projects\Accton_Pro_RC\20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB"
    r"\test\evidence\20260731-latency-eth-htl"
)


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] if f == c else xs[f] + (xs[c] - xs[f]) * (k - f)


rows = []
with open(ev / "samples.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rows.append(
            {
                **r,
                "L": float(r["L_cmd_board_ms"]),
                "t0": float(r["t0_wall"]),
                "t1": float(r["t1_wall"]),
            }
        )

lats = [r["L"] for r in rows]
core = [x for x in lats if x <= 250]


def parse_msgs(payload):
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
        fl = 10 + plen + 2 + (13 if incompat & 1 else 0)
        if i + fl > n:
            break
        msgid = payload[i + 7] | (payload[i + 8] << 8) | (payload[i + 9] << 16)
        yield msgid
        i += fl


att = []
for p in rdpcap(str(ev / "lat-phaseB.pcap")):
    if not p.haslayer(UDP) or not p.haslayer(IP):
        continue
    ip, udp = p[IP], p[UDP]
    if ip.src != "192.168.144.14" or ip.dst != "192.168.144.20":
        continue
    for msgid in parse_msgs(bytes(udp.payload)):
        if msgid == 30:
            att.append(float(p.time))
att = sorted(att)

e2e = []
rtt = []
for r in rows:
    t1 = r["t1"]
    t0 = r["t0"]
    t2 = next((t for t in att if 0 <= t - t1 <= 0.5), None)
    if t2 is None:
        continue
    e2e.append((t2 - t0) * 1000)
    rtt.append((t2 - t1) * 1000)

print(
    "ALL n=%d P50=%.2f P95=%.2f min=%.2f max=%.2f"
    % (len(lats), pct(lats, 50), pct(lats, 95), min(lats), max(lats))
)
print(
    "CORE<=250ms n=%d P50=%.2f P95=%.2f"
    % (len(core), pct(core, 50), pct(core, 95))
)
print(
    "L_e2e n=%d P50=%.2f P95=%.2f" % (len(e2e), pct(e2e, 50), pct(e2e, 95))
)
print(
    "L_rtt n=%d P50=%.2f P95=%.2f" % (len(rtt), pct(rtt, 50), pct(rtt, 95))
)

summary = f"""# Latency evidence — Baseline-Eth-HTL — 2026-07-31

## Environment
- DUT: 83bc469a34914114
- Path: eth0 192.168.144.20 ↔ FC 192.168.144.14 UDP 14550
- Wi-Fi: OFF
- Joystick: ZhiXu Gamepad (`/dev/input/event1`)
- Mapping used: HID `ABS_Y` → MAVLink MANUAL_CONTROL `y`
- Arm: Disarmed (link latency only)
- Probes: `getevent -lt` (T0) + `tcpdump -tt` (T1/T2')
- Clock: getevent≈CLOCK_MONOTONIC/uptime; tcpdump wall; SYNC offset applied

## Phase A
- MANUAL_CONTROL present: YES (`lat-phaseA.pcap`)
- ATTITUDE present: YES

## Phase B — L_cmd_board = T1−T0
| Set | n | P50 (ms) | P95 (ms) | min | max |
|-----|---|----------|----------|-----|-----|
| All matched | {len(lats)} | {pct(lats, 50):.2f} | {pct(lats, 95):.2f} | {min(lats):.2f} | {max(lats):.2f} |
| Core (≤250 ms) | {len(core)} | {pct(core, 50):.2f} | {pct(core, 95):.2f} | {min(core):.2f} | {max(core):.2f} |

Notes: samples >250 ms likely edge mis-alignment / multi-axis; report **All** as primary, Core as sensitivity check.

## Optional — same capture
| Metric | n | P50 (ms) | P95 (ms) |
|--------|---|----------|----------|
| L_e2e = T2'−T0 | {len(e2e)} | {pct(e2e, 50):.2f} | {pct(e2e, 95):.2f} |
| L_rtt* ≈ T2'−T1 | {len(rtt)} | {pct(rtt, 50):.2f} | {pct(rtt, 95):.2f} |

ATTITUDE rate ~10 Hz → L_rtt*/L_e2e include telemetry period quantization.

## Files
- `lat-phaseA.pcap`, `lat-phaseB.pcap`
- `getevent-phaseB.txt`, `sync-phaseB.txt`
- `samples.csv`
"""
(ev / "summary.md").write_text(summary, encoding="utf-8")
print("wrote", ev / "summary.md")
