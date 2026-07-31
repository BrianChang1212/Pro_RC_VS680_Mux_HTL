# VS680 Mux HTL — Agent Instructions

## Scope

Board ↔ physical ArduPilot Godwit via **eth0 + 系統 `mavlink_mux`**。  
**本專案定位：搖桿走板端 mavlink_mux**（非 QGC Joystick 注入）。  
**經 QGC 搖桿路徑**請用姊妹專案：`../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/`。

Do **not** conflate with SITL demo (`20260722_Accton_Pro_RC_VS680_QGC_Joystick`).

## Sister split

| 專案 | 搖桿路徑 | 說明 |
|------|----------|------|
| [QGC RealDrone](../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/) | HID → **QGC** → FC | 經 QGC；`setup-eth-htl.ps1` |
| **本專案（Mux HTL）** | HID → **mavlink_mux** → FC | 系統 mux；QGC 僅可選 UI（`:14551`） |

## Hard rules

- Wi‑Fi OFF during eth (`svc wifi disable`).
- Joystick on **board USB Host** → **mux** injects `RC_CHANNELS_OVERRIDE` + `MANUAL_CONTROL`.
- QGC（若用 A）：Joystick **OFF**；只做 Arm／Takeoff／RTL／遙測（`:14551`）。
- PC USB COM：param write only.
- Latency：mux `-L` + `getevent`（CLOCK_MONOTONIC）；勿用 `/proc/uptime` sync.

## tool/ classification

| Dir | Role |
|-----|------|
| `tool/with-qgc/` | A — mux + QGC UI（搖桿仍經 mux） |
| `tool/no-qgc/` | B — 僅 mux，無 QGC |
| `tool/bring-up/` | eth／FC／maps |
| `tool/latency/` | L_cmd measure |
| `tool/native/` | mavlink_mux + build |

Root：`tool/start-with-qgc.ps1` · `tool/start-no-qgc.ps1`

## Re-run（系統 mux）

```powershell
cd tool
.\native\build-joy-bridge.ps1
.\start-with-qgc.ps1 -BringUpEth -SkipOfflineMaps   # A: mux + QGC UI
# .\start-no-qgc.ps1                                # B: mux only
```

## SSOT docs

Index: [`docs/README.md`](docs/README.md)

- Latency: `docs/latency/latency-report.html`（Baseline-Mux-Eth-HTL）
- Architecture / Ops: `docs/mux/architecture.md` · `docs/mux/操作手冊-Mux-HTL.md`
- Bring-up: `docs/bring-up/verification-eth-htl-20260730.md` · `docs/bring-up/integration-report-eth0-fc-communication-20260731.md`
- Evidence: `test/evidence/mux-path/dense-n1000/latency-mux-n1000-latest/`
