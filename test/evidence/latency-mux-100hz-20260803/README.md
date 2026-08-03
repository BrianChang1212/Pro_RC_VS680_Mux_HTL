# Joy -> FC latency (mux path)

- Path: HID /dev/input/event1 -> mavlink_mux send_stick -> eth0 UDP :14550
- Metric: L_cmd = T1 - T0 (both CLOCK_MONOTONIC)
- T0: getevent -lt
- T1: mux -L log at send_stick
- Axis: HID ABS_Y <-> MC x
- Duration: 45s
