# Accton Pro RC — VS680 Mux HTL（分類啟動）

> 繼承自 [`20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB`](../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/)（eth 驗證／歷史 evidence 仍在舊 repo）。  
> 本 repo 聚焦：**mavlink_mux 搖桿路徑** + **依 QGC／非 QGC 分類的一鍵啟動**。

## 狀態

- eth0 ↔ Godwit HTL：**Pass**
- Option B mux 搖桿注入：**Pass**
- 延遲 L_cmd dense n=1000 · P50 **5.3 ms**／P95 **56.2 ms**

## 一鍵啟動

| 分類 | 指令 | 說明 |
|------|------|------|
| **A. 透過 QGC** | `cd tool; .\start-with-qgc.ps1` | mux + QGC（Arm／Takeoff／遙測） |
| **B. 不透過 QGC** | `cd tool; .\start-no-qgc.ps1` | 僅 mux 搖桿→FC |

```powershell
cd D:\Brian\projects\Accton_Pro_RC\20260731_Accton_Pro_RC_VS680_Mux_HTL\tool
.\native\build-joy-bridge.ps1                 # once (Zig)
.\start-with-qgc.ps1 -BringUpEth -SkipOfflineMaps
# .\start-no-qgc.ps1 -BringUpEth -SkipOfflineMaps
```

目錄分類：`tool/with-qgc/` · `tool/no-qgc/` · `tool/bring-up/` · `tool/latency/` · `tool/native/`  
詳見 [`tool/README.md`](tool/README.md)。

## 主測環境

| 項目 | 值 |
|------|-----|
| 主板 | Astra／VS680 · `83bc469a34914114` |
| mux | UDP `:14550` ↔ QGC `:14551` |
| eth0 / FC | `192.168.144.20` / `192.168.144.14` · **Wi‑Fi OFF** |
| 搖桿 | 板 USB Host · `/dev/input/event1` |

## 文件與證據

- 延遲報告：[`docs/latency-report.html`](docs/latency-report.html)（Baseline-Mux-Eth-HTL）
- 操作手冊：[`docs/操作手冊-RealDrone-USB.md`](docs/操作手冊-RealDrone-USB.md)
- Evidence：[`test/evidence/latency-mux-n1000-latest/`](test/evidence/latency-mux-n1000-latest/)

## 技術棧

ArduPilot Godwit · QGroundControl Android · 板端 `mavlink_mux`（Zig aarch64）· adb／pymavlink

<!-- TODO: 授權條款待補 -->
