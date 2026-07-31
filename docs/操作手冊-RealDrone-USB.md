# 操作手冊 — VS680 eth0 + mux ↔ Godwit（實體／HTL）

> 路徑：`docs/` · eth 一鍵：[`../tool/bring-up/setup-eth-htl.ps1`](../tool/bring-up/setup-eth-htl.ps1) · 搖桿 mux：[`../tool/with-qgc/start-joy-direct.ps1`](../tool/with-qgc/start-joy-direct.ps1)  
> **整合報告**：[`integration-report-eth0-fc-communication-20260731.md`](integration-report-eth0-fc-communication-20260731.md)  
> **延遲報告**：[`latency-report.html`](latency-report.html)（Baseline-Mux-Eth-HTL）  
> 驗證：2026-07-30 eth Pass · 2026-07-31 mux + 延遲 n=1000 · USB forward 已淘汰

## eth0 直連

### 前置

1. VS680 開機、USB 偵錯接筆電（adb）
2. **飛控 eth ↔ 板 eth0 網路線**（同網段 `192.168.144.0/24`）
3. 飛控 USB 接筆電（**僅**寫 `NET_*` 參數／首次設定；日常資料走 eth，不需 forwarder）
4. 板端 QGC：`org.mavlink.qgroundcontrolbeta`（腳本可自動安裝 APK）
5. PATH：`adb`、`python` + `pymavlink`

### 硬性條件

測 eth **必須關閉板端 Wi‑Fi**。Wi‑Fi ON 時 QGC 回包常走 wlan0 → 飛控收不到 PARAM 請求 → Downloading 卡住。

### 一鍵

```powershell
cd D:\Brian\projects\Accton_Pro_RC\20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB\tool
.\setup-eth-htl.ps1
# 正式機勿放寬 arming：
# .\setup-eth-htl.ps1 -ProductionSafe
# 已設好 FC、只重設板：
# .\setup-eth-htl.ps1 -SkipFc -BoardOnly
```

腳本會：關 Wi‑Fi（預設）→ 寫 FC `NET_*` →（預設）HTL bench 放寬 arming → 設板 eth0 → 開 QGC → 簡驗。

### IP／參數摘要

| 端點 | 值 |
|------|-----|
| FC eth | `192.168.144.14/24` · `NET_ENABLE=1` · `NET_DHCP=0` |
| FC `NET_P1` | TYPE=1 UDP Client → `192.168.144.20:14550` · PROTOCOL=2 MAVLink2 |
| 板 eth0 | `192.168.144.20/24`（`ip addr add`；重開機可能掉，重跑腳本） |
| QGC（setup 後） | 聽 `0.0.0.0:14550`（尚未跑 mux 時） |
| QGC（mux 後） | Comm Link `BoardMux14551` · `127.0.0.1:14551` · Joystick **OFF** |
| mux | 綁 `:14550` · 轉發 ↔ QGC `:14551` · 搖桿注入 |

### 驗收畫面

- QGC：**Connected**；遙測更新（HTL 可見 GPS sats）
- 勿期待室內實體六方位 Accel 校正成功（HTL 模擬 IMU → FAILED）
- Bench 略過 PreArm：腳本預設 `ARMING_CHECK=0` + 微小 `INS_ACCOFFS_*` — **拆槳**；正式飛行用 `-ProductionSafe`

### eth 疑難

| 現象 | 處理 |
|------|------|
| 參數下載卡一半／半雙工 | `svc wifi disable`；重跑 `-BoardOnly` |
| eth0 無 IPv4 | `.\set-board-eth.ps1`；確認線／link up |
| ping FC 失敗 | 常見（可不回 ICMP）；以 QGC／UDP 為準 |
| COM 找不到 | 重插 USB；`-ComPort COMx`（MAVLink 用 MI_00） |

證據：[`../test/evidence/20260730-eth-htl-connected/`](../test/evidence/20260730-eth-htl-connected/)

---

## 搖桿 mux（Option B · 飛行 UX）

> **Takeoff／Arm／RTL 只在 QGC 手動操作**；mux 只負責搖桿注入。

```powershell
cd D:\Brian\projects\Accton_Pro_RC\20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB\tool
.\build-joy-bridge.ps1          # 首次／改 C 後
.\start-joy-direct.ps1          # 推 mux + 改 QGC.ini + 開 QGC
```

| 檢查 | 指令／畫面 |
|------|------------|
| mux 在跑 | `adb shell su 0 pidof mavlink_mux`；`ss` 見 `:14550` |
| QGC | Connected · Joystick **未** Enable |
| 動杆 | Loiter 下有水平速度；mux log `mc=` 遞增 |
| 延遲重測 | `.\collect_joy_latency_1000.ps1` |

延遲結果（2026-07-31）：dense n=1000 · P50 **5.3 ms**／P95 **56.2 ms** · [`../test/evidence/latency-mux-n1000-latest/`](../test/evidence/latency-mux-n1000-latest/)

### mux 疑難

| 現象 | 處理 |
|------|------|
| QGC 卡住 Takeoff | 確認非 CRITICAL（HTL 可關 `FS_THR_ENABLE`／`BATT_MONITOR`）；先 ACTIVE 再飛 |
| 動杆無反應 | 查 HID signed/u8；確認 mux 有送、非 QGC Joystick 雙送 |
| eth0 IP 掉了 | `.\set-board-eth.ps1` 或重跑 setup `-BoardOnly` |
| EKF／Hit ground 橫幅 | HTL SIM 常見；先確認 mux `fwd_fc` 仍在漲 |

---

## 已淘汰 — USB → PC → Wi‑Fi UDP

> **不再使用。** 2026-07-29 Lab 驗證紀錄見 [`verification-report.md`](verification-report.md)。  
> `start-real-drone-forward.ps1` 已 Deprecated，請勿用於新測試。

---

## 室內／SITL

模擬飛行／Ready／Arm／搖桿 Mode 2：姊妹專案  
[`20260722_Accton_Pro_RC_VS680_QGC_Joystick`](../../20260722_Accton_Pro_RC_VS680_QGC_Joystick/) · `.\start-qgc-sitl.ps1`
