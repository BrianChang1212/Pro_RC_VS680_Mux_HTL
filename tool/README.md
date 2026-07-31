# tool/ — Mux HTL helpers（分類）

> **唯一資料路徑：** eth0 + `mavlink_mux`（`:14550`）。PC USB 僅寫 FC 參數。

## 一鍵啟動分類

### A. 透過 QGC（`with-qgc/`）

| 一鍵 | 路徑 |
|------|------|
| [`start-with-qgc.ps1`](start-with-qgc.ps1) | root 捷徑 |
| [`with-qgc/start-with-qgc.ps1`](with-qgc/start-with-qgc.ps1) | 實作 |

```powershell
.\start-with-qgc.ps1
.\start-with-qgc.ps1 -BringUpEth -SkipOfflineMaps
```

mux `:14550` ↔ QGC `:14551` · 搖桿由 mux 注入 · QGC＝Arm／Takeoff／遙測

### B. 不透過 QGC（`no-qgc/`）

| 一鍵 | 路徑 |
|------|------|
| [`start-no-qgc.ps1`](start-no-qgc.ps1) | root 捷徑 |
| [`no-qgc/start-no-qgc.ps1`](no-qgc/start-no-qgc.ps1) | 實作 |

```powershell
.\start-no-qgc.ps1
.\start-no-qgc.ps1 -BringUpEth -SkipOfflineMaps
.\start-no-qgc.ps1 -Link usb -ComPort COM9
```

### bring-up / latency / native

| 目錄 | 內容 |
|------|------|
| [`bring-up/`](bring-up/) | `setup-eth-htl.ps1`、`set-board-eth.ps1`、`set_fc_eth_params.py`、maps cache |
| [`latency/`](latency/) | measure / collect n=1000 / analyze |
| [`native/`](native/) | `mavlink_mux` + `build-joy-bridge.ps1` |
| [`with-qgc/`](with-qgc/) | `start-joy-direct.ps1`、`joy_direct_mavlink.py` |

```powershell
.\native\build-joy-bridge.ps1          # once
.\latency\collect_joy_latency_1000.ps1
```

## 拓樸

```
                    ┌─ A. start-with-qgc ──→ QGC :14551
HID 搖桿 → mux :14550 ─┤
                    └─ B. start-no-qgc ────→（無 QGC）
                              ↓
                         FC eth
```
