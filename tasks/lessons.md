# Lessons

## 2026-07-31 — Latency clock sync

- `getevent -lt` uses **CLOCK_MONOTONIC** (input_event time).
- `/proc/uptime` is **CLOCK_BOOTTIME** (includes suspend) → offset can inflate L_cmd by tens of ms.
- Prefer mux `-L` log with `clock_gettime(CLOCK_MONOTONIC)` so T0/T1 share one clock.
- Dense pairing (every MC ↔ last HID) ≠ edge pairing (猛推); report both and label metrics.

## 2026-07-31 — Mux stick vs QGC commands

- Idle sticks must **not** spam MANUAL_CONTROL / RC override (blocks Takeoff).
- QGC Joystick must be **OFF** when mux injects sticks.
- `RC_CHANNELS_OVERRIDE` payload order: `target_system`, `target_component`, then chan1..8.
