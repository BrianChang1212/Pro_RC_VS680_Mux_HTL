# QGC command path capture

Date: 2026-08-03

Path under test:

```text
QGC -> mavlink_mux GCS socket -> eth0 -> FC -> COMMAND_ACK -> mavlink_mux
```

## Files

- `mux_command_lat.log`: mux `-L` command timestamp log, `CLOCK_MONOTONIC`
- `eth0.pcap`: VS680 eth0 UDP `:14550` capture
- `lo.pcap`: VS680 loopback UDP `:14551/:14552` capture
- `eth0-command.txt`: parsed `COMMAND_LONG` / `COMMAND_INT` / `COMMAND_ACK` from eth0 pcap

## Command IDs Seen

| MAV_CMD | Count | Notes |
|---:|---:|---|
| 512 | 13 | QGC/FC command traffic |
| 511 | 8 | QGC/FC command traffic |
| 521 | 6 | QGC/FC command traffic |
| 176 | 5 | QGC/FC command traffic |
| 400 | 0 | `MAV_CMD_COMPONENT_ARM_DISARM`; not captured |
| 22 | 0 | `MAV_CMD_NAV_TAKEOFF`; not captured |

## Timing

| Segment | n | min | mean | P50 | P95 | max |
|---|---:|---:|---:|---:|---:|---:|
| GCS_RX -> GCS_TX | 32 | 0.034 ms | 0.106 ms | 0.104 ms | 0.148 ms | 0.177 ms |
| GCS_TX -> FC_RX `COMMAND_ACK` | 32 | 1.493 ms | 2.941 ms | 2.931 ms | 3.919 ms | 8.162 ms |

## Result

The mux command forwarding path was verified and measured for QGC-generated
MAVLink command traffic.

Arm/Takeoff-specific commands were not captured in this run: no
`MAV_CMD_COMPONENT_ARM_DISARM` (`cmd=400`) and no `MAV_CMD_NAV_TAKEOFF`
(`cmd=22`) appeared in the mux command log.

This evidence should not be used to claim Arm/Takeoff timing until a run
captures `cmd=400` and/or `cmd=22`.
