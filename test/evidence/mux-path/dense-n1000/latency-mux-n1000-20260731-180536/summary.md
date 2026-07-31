# Joy → FC latency — dense retest (2026-07-31 18:05)

## Stats (n=846)
| | ms |
|--|--:|
| min | 0.01 |
| mean | 10.83 |
| **P50** | **5.12** |
| **P95** | **40.89** |
| max | 49.83 |

## Method
- Dense: each active mux inject paired with latest `EV_ABS` ≤ T1
- Axis HID `ABS_Y` / MC `x` · `mc_threshold=100` · `max_lag=0.05s`
- Path: HID → mavlink_mux → eth0 :14550 → FC
- Report: `docs/latency/latency-report.html` (**Baseline-Mux-Eth-HTL**)

## Note
- Target was n=1000; capture yielded 846 matched samples (HID=2222, mux MC=2131).
- Formal baseline remains `../latency-mux-n1000-latest/` (n=1000 · P50 5.30 / P95 56.17).
- This run confirms P50 ≈ 5 ms on the same mux path.
