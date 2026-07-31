# 搖桿延遲量測計畫

> 狀態：**Done（鏈路延遲）** — 2026-07-31 · Baseline-Mux-Eth-HTL  
> 報告：[`latency-report.html`](latency-report.html)  
> Evidence：[`../test/evidence/latency-mux-n1000-latest/`](../test/evidence/latency-mux-n1000-latest/)

## 目標

```text
T0 主板搖桿 HID event
 → T1 mux send_stick（RC_CHANNELS_OVERRIDE / MANUAL_CONTROL）
 → （可選）T2 飛控作動／T2' ATTITUDE 回板
```

主報告：`L_cmd = T1−T0`（指令路徑）。

## 現行路徑（Option B mux）

1. 搖桿插**主板** USB Host；QGC **Joystick OFF**
2. `mavlink_mux` 佔 `:14550`，QGC Comm Link `:14551`
3. T0：`getevent -lt /dev/input/event1`
4. T1：mux `-L` log（CLOCK_MONOTONIC，與 getevent 同時鐘）
5. **勿**用 `/proc/uptime` 對齊 getevent（boottime 會灌水 ~70–90 ms）

```powershell
cd tool
.\start-joy-direct.ps1
.\collect_joy_latency_1000.ps1 -Count 1000 -Seconds 50
.\measure_joy_mux_latency.ps1 -Seconds 45   # edge-style
```

## 結果（2026-07-31）

| 指標 | n | min | P50 | P95 | max |
|------|---|-----|-----|-----|-----|
| L_cmd dense | 1000 | ~0 | **5.3 ms** | **56.2 ms** | ~118 ms |
| L_cmd_edge | 22 | 0.04 | **8.7 ms** | **17.9 ms** | 21.3 ms |

mux 50 Hz（週期 20 ms）+ poll 5 ms → 預期約 0–20 ms；edge P50/P95 相符。

### 歷史對照（勿與現行混用）

| 路徑 | n | P50 | P95 | 備註 |
|------|---|-----|-----|------|
| HID→QGC→eth MC（pcap+uptime sync） | 22 | 97.6 ms | 310.9 ms | 舊路徑；時鐘方法不同 |
| MC→ATTITUDE RTT* | 22 | 59.3 ms | 98.4 ms | 含 ~10 Hz 遙測週期 |

## 仍 Pending

- [ ] `L_telem_qgc`＝T3'−T2'（HUD／錄影）
- [ ] （可選）SITL／真機作動 T2−T0（需 Arm；拆槳）
- [ ] 中期空口後改標 **Baseline-Product**

## 驗收（鏈路）

- [x] sniff／mux log 確認動杆出現 RC/MC
- [x] 產出 `T1−T0` 統計（CSV n=1000）
- [x] evidence 目錄收錄 raw log
- [x] 更新 `latency-report.html`
