#!/usr/bin/env python3
"""Collect N dense HID->mux latency samples (CLOCK_MONOTONIC) and save CSV.

For each mux -L MC line with |axis| >= threshold, pair with the latest
getevent ABS sample at or before T1. L_cmd_ms = (T1 - T0) * 1000.
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from pathlib import Path

ABS_CODE = {
    0x00: "ABS_X",
    0x01: "ABS_Y",
    0x02: "ABS_Z",
    0x03: "ABS_RX",
    0x04: "ABS_RY",
    0x05: "ABS_RZ",
}


def percentile(sorted_vals, p: float):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def load_hid_series(getevent_path: Path, axis_name: str, any_abs: bool = False):
    """Load HID timestamps. If any_abs, use every EV_ABS as activity T0 markers."""
    if any_abs:
        any_re = re.compile(
            r"\[\s*([0-9]+)\.([0-9]+)\]\s+EV_ABS\s+\S+\s+([0-9a-fA-F]+)"
        )
        vals = []
        for line in getevent_path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = any_re.search(line)
            if not m:
                continue
            ts = int(m.group(1)) + int(m.group(2)) / 1_000_000
            raw = int(m.group(3), 16)
            if raw >= 0x80000000:
                raw -= 0x100000000
            vals.append((ts, raw))
        return vals

    axis_re = re.compile(
        rf"\[\s*([0-9]+)\.([0-9]+)\]\s+EV_ABS\s+{re.escape(axis_name)}\s+([0-9a-fA-F]+)"
    )
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
        raw = int(m.group(3), 16)
        if raw >= 0x80000000:
            raw -= 0x100000000
        vals.append((ts, raw))
    return vals


def load_mux_series(path: Path, axis_idx: int):
    series = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("MC "):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        t = float(parts[1])
        vals = [int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])]
        series.append((t, vals[0], vals[1], vals[2], vals[3], vals[axis_idx]))
    return series


def collect_dense(
    hid,
    mux,
    mc_threshold: int,
    max_lag_s: float,
    count: int,
):
    """Pair each qualifying MC with latest HID at/before T1."""
    samples = []
    hi = 0
    n_hid = len(hid)
    for t1, x, y, z, r, axis_v in mux:
        if abs(axis_v) < mc_threshold:
            continue
        while hi + 1 < n_hid and hid[hi + 1][0] <= t1:
            hi += 1
        if n_hid == 0 or hid[hi][0] > t1:
            continue
        t0, hid_v = hid[hi]
        dt = t1 - t0
        if dt < 0 or dt > max_lag_s:
            continue
        samples.append(
            {
                "t0_mono": t0,
                "t1_mono": t1,
                "L_cmd_ms": dt * 1000.0,
                "hid_raw": hid_v,
                "mc_x": x,
                "mc_y": y,
                "mc_z": z,
                "mc_r": r,
                "mc_axis": axis_v,
            }
        )
        if len(samples) >= count:
            break
    return samples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--getevent", required=True)
    ap.add_argument("--mux-log", required=True)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--axis", default="ABS_Y")
    ap.add_argument("--mc-axis", choices=["x", "y", "z", "r"], default="x")
    ap.add_argument("--mc-threshold", type=int, default=100)
    ap.add_argument("--max-lag", type=float, default=0.05, help="max T1-T0 seconds")
    ap.add_argument(
        "--any-abs",
        action="store_true",
        help="use any EV_ABS as T0 (more samples while wiggling)",
    )
    ap.add_argument("--csv", required=True)
    ap.add_argument("--summary", default="")
    args = ap.parse_args()

    axis_idx = {"x": 0, "y": 1, "z": 2, "r": 3}[args.mc_axis]
    hid = load_hid_series(Path(args.getevent), args.axis, any_abs=args.any_abs)
    mux = load_mux_series(Path(args.mux_log), axis_idx)
    print(f"HID samples={len(hid)} mux MC={len(mux)} target={args.count}")

    samples = collect_dense(hid, mux, args.mc_threshold, args.max_lag, args.count)
    print(f"collected={len(samples)}")
    if len(samples) < args.count:
        print(
            f"WARNING: only {len(samples)}/{args.count} (hold stick longer / lower threshold)",
            file=sys.stderr,
        )

    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "idx",
        "t0_mono",
        "t1_mono",
        "L_cmd_ms",
        "hid_raw",
        "mc_x",
        "mc_y",
        "mc_z",
        "mc_r",
        "mc_axis",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, s in enumerate(samples, 1):
            w.writerow(
                {
                    "idx": i,
                    "t0_mono": f"{s['t0_mono']:.6f}",
                    "t1_mono": f"{s['t1_mono']:.6f}",
                    "L_cmd_ms": f"{s['L_cmd_ms']:.3f}",
                    "hid_raw": s["hid_raw"],
                    "mc_x": s["mc_x"],
                    "mc_y": s["mc_y"],
                    "mc_z": s["mc_z"],
                    "mc_r": s["mc_r"],
                    "mc_axis": s["mc_axis"],
                }
            )
    print(f"wrote {out}")

    if samples:
        lats = sorted(s["L_cmd_ms"] for s in samples)
        p50 = percentile(lats, 50)
        p95 = percentile(lats, 95)
        mean = statistics.fmean(lats)
        line = (
            f"L_cmd_ms: n={len(lats)} min={lats[0]:.2f} mean={mean:.2f} "
            f"P50={p50:.2f} P95={p95:.2f} max={lats[-1]:.2f}"
        )
        print(line)
        if args.summary:
            Path(args.summary).write_text(
                "# Joy->FC latency dense samples\n\n"
                f"- Axis HID `{args.axis}` / MC `{args.mc_axis}`\n"
                f"- mc_threshold={args.mc_threshold} max_lag={args.max_lag}s\n"
                f"- CSV: `{out.name}`\n\n"
                f"{line}\n",
                encoding="utf-8",
            )
            print(f"wrote {args.summary}")

    return 0 if len(samples) >= args.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
