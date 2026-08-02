# 驗證報告 — VS680 eth0 ↔ Godwit HTL（2026-07-30）

## 結論

| 驗收項 | 結果 | 說明 |
|--------|------|------|
| FC USB 列舉 | **Pass** | AcctonGodwit_GA1 · COM8／COM9（MAVLink 用 MI_00） |
| FC `NET_ENABLE` | **Pass** | 0→1；靜態 `192.168.144.14/24` |
| FC `NET_P1` | **Pass** | UDP Client → `192.168.144.20:14550` MAVLink2 |
| 板 eth0 IPv4 | **Pass** | `192.168.144.20/24`（`ip addr add`，重開機可能掉） |
| eth 雙向 UDP | **Pass** | 需 **Wi‑Fi OFF**；否則僅 FC→板（半雙工） |
| QGC 參數下載 | **Pass**（關 Wi‑Fi 後） | 開 Wi‑Fi 時卡一半：`Vehicle 1 did not respond to request for parameters` |
| QGC 遙測畫面 | **Pass** | Connected；HTL GPS sats 可見 |
| 實體 3D Accel 校正 | **Fail** | HTL 模擬 IMU；回報 Calibration FAILED |
| Bench 略過 PreArm | **Applied** | `ARMING_CHECK=0` + `INS_ACCOFFS_*=0.01`（拆槳） |

## 拓樸（2026-07-30 驗證當日）

```
Godwit HTL eth 192.168.144.14
    ↕ 網路線
VS680 eth0 192.168.144.20
    ↕
QGC UDP :14550
```

PC USB COM 僅用於參數寫入／備援，**不在** eth 資料路徑上。

> **後續（2026-07-31）：** 飛行 UX 改 **mavlink-router** 佔 `:14550`，QGC 聽 `:14551`；搖桿延遲見 [`../latency/latency-report.html`](../latency/latency-report.html)（Baseline-Mux-Eth-HTL）。

## 半雙工根因

Android 預設出口為 **wlan0** 時，QGC 的 PARAM 請求不走 eth0 → 飛控收不到 → Downloading 卡住。  
對策：測 eth 期間 `svc wifi disable`（一鍵腳本預設執行）。

## 一鍵重現

```powershell
cd D:\Brian\projects\Accton_Pro_RC\20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB\tool
.\setup-eth-htl.ps1
# 正式機勿關 arming：
# .\setup-eth-htl.ps1 -ProductionSafe
```

## 證據

[`../../../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/test/evidence/qgc-path/20260730-eth-htl-connected/`](../../../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/test/evidence/qgc-path/20260730-eth-htl-connected/)

## 與 2026-07-29 USB via PC 路徑

| | eth HTL（本報告） | USB→PC→Wi‑Fi（舊） |
|--|-------------------|---------------------|
| 標籤 | Baseline-Eth-HTL（通訊）→ 現 Baseline-Mux-Eth-HTL | Baseline-Lab |
| 延遲代表性 | mux 路徑 P50≈5.3 ms（n=1000） | 偏高（含 PC／serial） |
| 腳本 | `setup-eth-htl.ps1` + `start-joy-direct.ps1` | `start-real-drone-forward.ps1`（Deprecated） |
