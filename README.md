# Accton Pro RC — VS680 Mux HTL（**系統 mux**）

> **定位：基於系統中 `mavlink_mux`** — 搖桿由板端 mux 注入 FC。  
> 經 QGC 搖桿路徑 → [`20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB`](../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/)。  
> GitHub：https://github.com/BrianChang1212/Pro_RC_VS680_Mux_HTL

## 狀態

- eth0 ↔ Godwit HTL：**Pass**
- 系統 mux 搖桿注入：**Pass**
- 延遲 L_cmd dense：基線 n=1000 · P50 **5.3**／P95 **56.2** ms；重測 n=846 · P50 **5.1**／P95 **40.9** ms

## 與姊妹專案分工

| 專案 | 搖桿路徑 | 一鍵 |
|------|----------|------|
| [QGC RealDrone USB](../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/) | HID → **QGC** → FC | `setup-eth-htl.ps1` |
| **本專案** | HID → **mavlink_mux** → FC | `start-with-qgc` / `start-no-qgc` |

```
本專案（系統 mux）:
  搖桿 HID → mavlink_mux :14550 → Godwit FC
  可選：QGC :14551 僅指令／遙測（Joystick OFF；杆仍走 mux）
```

## 一鍵啟動（mux 底下再分 A/B）

| 分類 | 指令 | 說明 |
|------|------|------|
| **A. mux + QGC UI** | `.\start-with-qgc.ps1` | 杆經 mux；QGC 畫面／Arm／Takeoff |
| **B. 僅 mux** | `.\start-no-qgc.ps1` | 無 QGC；杆→FC |

```powershell
cd D:\Brian\projects\Accton_Pro_RC\20260731_Accton_Pro_RC_VS680_Mux_HTL\tool
.\native\build-joy-bridge.ps1
.\start-with-qgc.ps1 -BringUpEth -SkipOfflineMaps
# .\start-no-qgc.ps1 -BringUpEth -SkipOfflineMaps
```

目錄：`with-qgc/` · `no-qgc/` · `bring-up/` · `latency/` · `native/` — 見 [`tool/README.md`](tool/README.md)。

## 主測環境

| 項目 | 值 |
|------|-----|
| 主板 | Astra／VS680 · `83bc469a34914114` |
| mux | UDP `:14550`（系統程序） |
| QGC（可選 A） | `:14551` · Joystick **OFF** |
| eth0 / FC | `192.168.144.20` / `192.168.144.14` · **Wi‑Fi OFF** |
| 搖桿 | 板 USB Host → **mux** |

## 文件與證據

索引：[`docs/README.md`](docs/README.md)

```
docs/
├── mux/          # 架構 · 操作手冊
├── latency/      # Baseline-Mux-Eth-HTL
└── bring-up/     # eth HTL · 整合報告
test/evidence/mux-path/
├── dense-n1000/  # 含 latency-mux-n1000-latest/
└── edge/
```

- [`docs/latency/latency-report.html`](docs/latency/latency-report.html)（Baseline-Mux-Eth-HTL）
- [`docs/mux/操作手冊-Mux-HTL.md`](docs/mux/操作手冊-Mux-HTL.md)
- [`test/evidence/mux-path/dense-n1000/latency-mux-n1000-latest/`](test/evidence/mux-path/dense-n1000/latency-mux-n1000-latest/)

<!-- TODO: 授權條款待補 -->
