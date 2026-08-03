# VS680 Mux HTL — tasks

## 2026-07-31 Repo classify

- [x] New repo scaffold `20260731_Accton_Pro_RC_VS680_Mux_HTL`
- [x] Classify tool/: with-qgc / no-qgc / bring-up / latency / native
- [x] Fix script relative paths
- [x] Root one-click shortcuts
- [ ] GitHub remote push（see git status）

### Review

- Inherited mux + latency baseline from 20260730 RealDrone USB project.
- Entry: `.\tool\start-with-qgc.ps1` (A) / `.\tool\start-no-qgc.ps1` (B).

## 2026-08-03 QGC command path timing

- [x] Add mux logging for QGC command receive/forward timestamps.
- [x] Rebuild and run mux with QGC on board.
- [ ] Capture QGC Arm/Takeoff command path evidence.
- [ ] Update latency report with verified command-path results.

### Review

- 2026-08-03 capture `test/evidence/qgc-command-20260803-103309/` verified generic QGC command forwarding and ACK timing.
- Arm/Takeoff did not appear in the capture: `cmd=400` count 0, `cmd=22` count 0.

## 2026-08-03 Joystick injection rate comparison

- [x] Run 50 Hz, 100 Hz, and 200 Hz joystick injection captures on the real device.
- [x] Correct HID edge threshold for the connected 8-bit joystick and recalculate results.
- [x] Make `measure_joy_mux_latency.ps1` HID threshold configurable.
- [ ] Select production joystick rate after longer repeated captures.

### Review

- 50 Hz: n=23, P50 4.07 ms, P95 19.15 ms, max 20.00 ms.
- 100 Hz: n=27, P50 5.13 ms, P95 12.34 ms, max 13.13 ms.
- 200 Hz: n=29, P50 4.02 ms, P95 4.32 ms, max 5.12 ms.
- Evidence: `test/evidence/latency-mux-50hz-20260803/`, `test/evidence/latency-mux-100hz-20260803/`, `test/evidence/latency-mux-200hz-20260803/`.

## 2026-08-03 200 Hz full-flow capture

- [x] Run a 60-second 200 Hz capture on the connected real device.
- [x] Collect HID events, mux monotonic timestamps, and eth0 MAVLink pcap.
- [x] Analyze HID→mux latency and FC telemetry intervals.
- [ ] Add a synchronized FC receive timestamp before replacing the 35.85 ms reference.

### Review

- Evidence: `test/evidence/all-flow-200hz-20260803/`.
- HID→mux: n=35, P50 4.03 ms, P95 5.10 ms, max 5.11 ms.
- eth0 pcap: MANUAL_CONTROL=6434, ATTITUDE=644.
- Active MANUAL_CONTROL pcap intervals (excluding gaps >50 ms): mean 6.49 ms, P50 5.71 ms, P95 8.78 ms.
- ATTITUDE FC→board interval: mean 100.00 ms, P50 100.00 ms, P95 100.36 ms.
- These are segment latency or packet-period measurements with different endpoints; they must not be added as an end-to-end latency.
- Arm/Takeoff, QGC→mux, mux→QGC, and HUD/render latency were not measured in this No-QGC 200 Hz capture.

### User-requested reference sum

- [x] Present only the average direct segment sum as a 200 Hz reference.
- HID→mux mean: 3.011 ms; mux→FC active MANUAL_CONTROL interval mean: 6.49 ms.
- Average reference: 3.011 ms + 6.49 ms = 9.501 ms, shown as 9.50 ms.
- This reference sum is not a synchronized end-to-end FC receive measurement.
- The report now uses the 200 Hz reference for the current measurement table; synchronized FC receive timing is still unavailable.
- These are preliminary HID→mux measurements with small edge counts; do not replace the all-flow 35.85 ms reference yet.
