# Joy -> FC latency (mux path) — 2026-07-31

## Metric
L_cmd = T1 - T0 where:
- **T0**: HID ABS_Y edge (getevent -lt, CLOCK_MONOTONIC)
- **T1**: mavlink_mux send_stick (-L log, CLOCK_MONOTONIC)
- Path: event1 -> mux -> eth0 UDP :14550 -> FC
- Eth hop after T1 is sub-ms on 192.168.144/24; this is the board command-path latency.

## Result (pooled 2 captures)
| | ms |
|--|--:|
| n | 22 |
| min | 0.04 |
| **P50** | **8.67** |
| **P95** | **17.87** |
| max | 21.27 |

## Method notes
- Prefer mux -L log over tcpdump+/proc/uptime sync: uptime is CLOCK_BOOTTIME and inflated earlier pcap-only run to ~90 ms.
- Mux inject rate 50 Hz (period 20 ms) + poll 5 ms => expected ~0–20 ms; measured P50/P95 match.
- Edge: HID |ABS_Y|>=8000, T1 first mux sample with |MC.x|>=100 within 250 ms.
- Evidence: latency-mux-20260731-171232, latency-mux-20260731-171328

## Compare
- Prior Baseline-Eth-HTL (QGC path, pcap sync): P50 ~97.6 ms — different path + clock method; not directly comparable to this mux monotonic result.
