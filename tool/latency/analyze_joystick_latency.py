#!/usr/bin/env python3
"""Align getevent HID edges with MANUAL_CONTROL edges; report P50/P95.

getevent -lt uses CLOCK_MONOTONIC (~ /proc/uptime).
tcpdump -tt uses wall clock. Convert via sync line:
  SYNC wall=<float> uptime=<float>
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import struct
import sys
from pathlib import Path

from scapy.all import IP, UDP, rdpcap  # type: ignore

ABS_CODE = {
    0x00: "ABS_X",
    0x01: "ABS_Y",
    0x02: "ABS_Z",
    0x03: "ABS_RX",
    0x04: "ABS_RY",
    0x05: "ABS_RZ",
}


def parse_mavlink2_msgs(payload: bytes):
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
        frame_len = 10 + plen + 2 + (13 if incompat & 0x01 else 0)
        if i + frame_len > n:
            break
        msgid = payload[i + 7] | (payload[i + 8] << 8) | (payload[i + 9] << 16)
        yield msgid, payload[i : i + 10 + plen]
        i += frame_len


def decode_mc(frame: bytes):
    body = frame[10:]
    if len(body) < 11:
        return None
    x, y, z, r = struct.unpack_from("<hhhh", body, 1)
    return x, y, z, r


def decode_rc_override(frame: bytes):
    """RC_CHANNELS_OVERRIDE (msgid 70): target_system, target_component, chan1..chan8 u16."""
    body = frame[10:]
    if len(body) < 18:
        return None
    chans = struct.unpack_from("<8H", body, 2)
    return chans


def load_sync(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"SYNC\s+wall=([0-9.]+)\s+uptime=([0-9.]+)", text)
    if not m:
        raise SystemExit(f"No SYNC line in {path}")
    return float(m.group(1)), float(m.group(2))


def load_hid_edges(getevent_path: Path, axis_name: str, threshold: int, min_gap_s: float):
    """Return list of monotonic timestamps for rising edges on one ABS axis."""
    # getevent prints names like ABS_Y or hex codes depending on version
    axis_re = re.compile(
        rf"\[\s*([0-9]+)\.([0-9]+)\]\s+EV_ABS\s+{re.escape(axis_name)}\s+([0-9a-fA-F]+)"
    )
    # also match raw code form
    code = {v: k for k, v in ABS_CODE.items()}.get(axis_name)
    code_re = None
    if code is not None:
        code_re = re.compile(
            rf"\[\s*([0-9]+)\.([0-9]+)\]\s+EV_ABS\s+{code:04x}\s+([0-9a-fA-F]+)",
            re.I,
        )

    vals = []
    for line in getevent_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = axis_re.search(line) or (code_re.search(line) if code_re else None)
        if not m:
            continue
        ts = int(m.group(1)) + int(m.group(2)) / 1_000_000
        # value may be signed 32-bit displayed as hex
        raw = int(m.group(3), 16)
        if raw >= 0x80000000:
            raw -= 0x100000000
        vals.append((ts, raw))

    if not vals:
        return [], 0

    # Prefer resting band: signed pads near 0, 8-bit pads near 128
    near0 = [v for _, v in vals if abs(v) <= 40]
    near128 = [v for _, v in vals if abs(v - 128) <= 25]
    if len(near0) >= 10 and len(near0) >= len(near128):
        baseline = statistics.median(near0)
    elif len(near128) >= 10:
        baseline = statistics.median(near128)
    else:
        baseline = statistics.median([v for _, v in vals])

    edges = []
    last_edge = -1e9
    armed = True
    for ts, v in vals:
        delta = abs(v - baseline)
        if armed and delta >= threshold and (ts - last_edge) >= min_gap_s:
            edges.append(ts)
            last_edge = ts
            armed = False
        elif not armed and delta < max(8, threshold / 3):
            armed = True
    return edges, baseline


def _edge_series(series, threshold: int, min_gap_s: float, release_div: float = 2.0):
    if not series:
        return [], 0
    t0 = series[0][0]
    base_samples = [v for t, v in series if t <= t0 + 0.5][:50]
    baseline = statistics.median(base_samples) if base_samples else series[0][1]
    edges = []
    last_edge = -1e9
    armed = True
    for ts, v in series:
        delta = abs(v - baseline)
        if armed and delta >= threshold and (ts - last_edge) >= min_gap_s:
            edges.append(ts)
            last_edge = ts
            armed = False
        elif not armed and delta < threshold / release_div:
            armed = True
    return edges, baseline


def load_mc_edges(pcap: Path, board_ip: str, fc_ip: str, axis_idx: int, threshold: int, min_gap_s: float):
    pkts = rdpcap(str(pcap))
    series = []
    for p in pkts:
        if not p.haslayer(UDP) or not p.haslayer(IP):
            continue
        ip, udp = p[IP], p[UDP]
        if ip.src != board_ip or ip.dst != fc_ip:
            continue
        if udp.dport != 14550 and udp.sport != 14550:
            continue
        for msgid, frame in parse_mavlink2_msgs(bytes(udp.payload)):
            if msgid != 69:
                continue
            mc = decode_mc(frame)
            if not mc:
                continue
            series.append((float(p.time), mc[axis_idx]))
    return _edge_series(series, threshold, min_gap_s)


def load_rc_edges(
    pcap: Path,
    board_ip: str,
    fc_ip: str,
    chan_idx: int,
    threshold: int,
    min_gap_s: float,
):
    """chan_idx: 0=chan1 ...; pitch often chan2 (idx 1). Values are PWM µs around 1500."""
    pkts = rdpcap(str(pcap))
    series = []
    for p in pkts:
        if not p.haslayer(UDP) or not p.haslayer(IP):
            continue
        ip, udp = p[IP], p[UDP]
        if ip.src != board_ip or ip.dst != fc_ip:
            continue
        if udp.dport != 14550 and udp.sport != 14550:
            continue
        for msgid, frame in parse_mavlink2_msgs(bytes(udp.payload)):
            if msgid != 70:
                continue
            chans = decode_rc_override(frame)
            if not chans or chan_idx >= len(chans):
                continue
            series.append((float(p.time), int(chans[chan_idx])))
    return _edge_series(series, threshold, min_gap_s)


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def load_mux_mc_series(path: Path, axis_idx: int):
    """Lines: MC <mono_sec> <x> <y> <z> <r> from mavlink_mux -L."""
    series = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("MC "):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        t = float(parts[1])
        vals = [int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])]
        series.append((t, vals[axis_idx]))
    return series


def match_first_above(hid_edges, series, threshold: int, match_window: float, offset: float = 0.0):
    """For each HID edge, first series sample with |v|>=threshold after T0."""
    samples = []
    used = set()
    for t_mono in hid_edges:
        t0 = t_mono + offset
        best = None
        for i, (t1, v) in enumerate(series):
            if i in used:
                continue
            dt = t1 - t0
            if dt < 0:
                continue
            if dt > match_window:
                if best is None and t1 > t0 + match_window:
                    # series is time-ordered; no need to scan further
                    break
                continue
            if abs(v) >= threshold:
                best = (i, dt, t1)
                break
        if best:
            used.add(best[0])
            samples.append(
                {
                    "t0": t0,
                    "t1": best[2],
                    "L_cmd_board_ms": best[1] * 1000.0,
                }
            )
    return samples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", default="", help="SYNC wall=.. uptime=.. (pcap mode)")
    ap.add_argument("--getevent", required=True)
    ap.add_argument("--pcap", default="", help="eth0 pcap (wall-clock T1)")
    ap.add_argument(
        "--mux-log",
        default="",
        help="mavlink_mux -L log (CLOCK_MONOTONIC T1; preferred)",
    )
    ap.add_argument("--axis", default="ABS_Y", help="HID axis name")
    ap.add_argument("--mc-axis", choices=["x", "y", "z", "r"], default="x")
    ap.add_argument(
        "--probe",
        choices=["mc", "rc", "auto"],
        default="auto",
        help="T1 probe for pcap mode",
    )
    ap.add_argument("--rc-chan", type=int, default=2, help="1-based RC channel for --probe rc")
    ap.add_argument("--hid-threshold", type=int, default=8000, help="signed HID edge |delta|")
    ap.add_argument("--mc-threshold", type=int, default=100, help="MANUAL_CONTROL |axis|")
    ap.add_argument("--rc-threshold", type=int, default=80, help="PWM µs delta from baseline")
    ap.add_argument("--min-gap", type=float, default=1.5)
    ap.add_argument("--match-window", type=float, default=0.25, help="seconds T1 after T0")
    ap.add_argument("--csv", default="")
    ap.add_argument("--board-ip", default="192.168.144.20")
    ap.add_argument("--fc-ip", default="192.168.144.14")
    args = ap.parse_args()

    hid_edges, hid_base = load_hid_edges(
        Path(args.getevent), args.axis, args.hid_threshold, args.min_gap
    )
    print(f"HID edges={len(hid_edges)} baseline={hid_base} axis={args.axis}")
    axis_idx = {"x": 0, "y": 1, "z": 2, "r": 3}[args.mc_axis]

    samples = []
    probe_name = ""

    if args.mux_log:
        series = load_mux_mc_series(Path(args.mux_log), axis_idx)
        print(f"mux-log MC samples={len(series)} axis={args.mc_axis}")
        samples = match_first_above(
            hid_edges, series, args.mc_threshold, args.match_window, offset=0.0
        )
        # rename keys for CSV compat
        for s in samples:
            s["t0_wall"] = s.pop("t0")
            s["t1_wall"] = s.pop("t1")
        probe_name = "mux-log CLOCK_MONOTONIC"
    else:
        if not args.sync or not args.pcap:
            print("pcap mode requires --sync and --pcap (or use --mux-log)", file=sys.stderr)
            return 2
        wall0, up0 = load_sync(Path(args.sync))
        offset = wall0 - up0
        print(f"sync wall={wall0:.6f} uptime={up0:.6f} offset={offset:.6f}")
        print("NOTE: uptime vs getevent clock may skew; prefer --mux-log")

        mc_edges, mc_base = load_mc_edges(
            Path(args.pcap),
            args.board_ip,
            args.fc_ip,
            axis_idx,
            args.mc_threshold,
            args.min_gap,
        )
        rc_edges, rc_base = load_rc_edges(
            Path(args.pcap),
            args.board_ip,
            args.fc_ip,
            max(0, args.rc_chan - 1),
            args.rc_threshold,
            args.min_gap,
        )
        print(f"MC  edges={len(mc_edges)} baseline={mc_base} axis={args.mc_axis}")
        print(f"RC  edges={len(rc_edges)} baseline={rc_base} chan={args.rc_chan}")

        if args.probe == "mc":
            t1_edges, probe_name = mc_edges, "MANUAL_CONTROL"
        elif args.probe == "rc":
            t1_edges, probe_name = rc_edges, "RC_CHANNELS_OVERRIDE"
        else:
            if rc_edges and (not mc_edges or len(rc_edges) >= len(mc_edges)):
                t1_edges, probe_name = rc_edges, "RC_CHANNELS_OVERRIDE"
            else:
                t1_edges, probe_name = mc_edges, "MANUAL_CONTROL"
        print(f"T1 probe={probe_name} edges={len(t1_edges)}")

        used_t1 = set()
        for t_mono in hid_edges:
            t0 = t_mono + offset
            best = None
            for i, t1 in enumerate(t1_edges):
                if i in used_t1:
                    continue
                dt = t1 - t0
                if 0 <= dt <= args.match_window:
                    if best is None or dt < best[1]:
                        best = (i, dt, t1)
            if best:
                used_t1.add(best[0])
                samples.append(
                    {
                        "t0_wall": t0,
                        "t1_wall": best[2],
                        "L_cmd_board_ms": best[1] * 1000.0,
                    }
                )

    print(f"matched samples={len(samples)}")
    if not samples:
        return 1

    lats = sorted(s["L_cmd_board_ms"] for s in samples)
    p50 = percentile(lats, 50)
    p95 = percentile(lats, 95)
    print(
        f"L_cmd_board_ms ({probe_name}): n={len(lats)} min={lats[0]:.2f} "
        f"P50={p50:.2f} P95={p95:.2f} max={lats[-1]:.2f}"
    )

    if args.csv:
        out = Path(args.csv)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["idx", "t0_wall", "t1_wall", "L_cmd_board_ms"])
            w.writeheader()
            for i, s in enumerate(samples, 1):
                w.writerow(
                    {
                        "idx": i,
                        "t0_wall": f"{s['t0_wall']:.6f}",
                        "t1_wall": f"{s['t1_wall']:.6f}",
                        "L_cmd_board_ms": f"{s['L_cmd_board_ms']:.3f}",
                    }
                )
        print(f"wrote {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
