# VS680 Mux HTL — Agent Instructions

## Scope

Board QGC ↔ **physical ArduPilot Godwit** via **eth0 + mavlink_mux**.  
Forked/classified from `20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB`（舊 repo 保留 eth／USB Lab 歷史）.

## Hard rules

- Wi‑Fi OFF during eth (`svc wifi disable`).
- Joystick on **board USB Host**.
- Stick: mux injects `RC_CHANNELS_OVERRIDE` + `MANUAL_CONTROL`（QGC Joystick OFF）.
- QGC：Arm／Takeoff／RTL／modes only（`:14551`）.
- PC USB COM：param write only.
- Latency：mux `-L` + `getevent`（CLOCK_MONOTONIC）；勿用 `/proc/uptime` sync.

## tool/ classification

| Dir | Role |
|-----|------|
| `tool/with-qgc/` | A — mux + QGC |
| `tool/no-qgc/` | B — mux only |
| `tool/bring-up/` | eth／FC／maps |
| `tool/latency/` | L_cmd measure |
| `tool/native/` | mavlink_mux binary + build |

Root shortcuts: `tool/start-with-qgc.ps1` · `tool/start-no-qgc.ps1`

## Re-run

```powershell
cd tool
.\native\build-joy-bridge.ps1
.\start-with-qgc.ps1 -BringUpEth -SkipOfflineMaps
```

## SSOT docs

- `docs/latency-report.html` · `docs/architecture.md` · `docs/操作手冊-RealDrone-USB.md`
- Evidence：`test/evidence/latency-mux-n1000-latest/`
