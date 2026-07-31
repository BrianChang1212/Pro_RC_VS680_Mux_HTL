# Joy -> FC latency (mux path)

- Path: HID /dev/input/event1 -> mavlink_mux -> eth0 UDP :14550 -> FC
- Metric: L_cmd_board = T1 - T0
- T0: getevent -lt (CLOCK_MONOTONIC / uptime)
- T1: RC_CHANNELS_OVERRIDE or MANUAL_CONTROL on eth0
- Axis: HID ABS_Y <-> MC x / RC ch2
- Duration: 45s
