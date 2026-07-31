# Joy → FC latency — 1000 samples (latest · 2026-07-31)

## Files
- `samples-n1000.csv` — **1000 rows** (primary)
- `getevent.txt` — raw HID
- `mux_stick_lat.log` — mux `-L` CLOCK_MONOTONIC sends
- Source capture: `../latency-mux-n1000-20260731-171753/`

## Columns
| column | meaning |
|--------|---------|
| idx | 1..1000 |
| t0_mono | last EV_ABS before send (s, CLOCK_MONOTONIC) |
| t1_mono | mux `send_stick` time |
| L_cmd_ms | (T1−T0)×1000 |
| hid_raw | HID raw at T0 |
| mc_x..mc_r | MANUAL_CONTROL axes |
| mc_axis | matched axis (x / pitch) |

## Stats (n=1000)
| | ms |
|--|--:|
| min | 0.00 |
| mean | 13.11 |
| **P50** | **5.30** |
| **P95** | **56.17** |
| max | 118.50 |

## Method
- Dense: each active mux inject paired with latest `EV_ABS` ≤ T1
- `mc_threshold=50`, `max_lag=0.12s`, `--any-abs`
- Path: HID → mavlink_mux → eth0 :14550 → FC
- Report: `docs/latency-report.html` (**Baseline-Mux-Eth-HTL**)

## Related
- Edge-style (n=22): `../latency-mux-20260731-171328/` · P50 8.7 / P95 17.9 ms
- Historical QGC path: `../20260731-latency-eth-htl/` · P50 97.6 ms（對照，非現行）
