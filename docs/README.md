# docs/ — Mux HTL（系統 mavlink_mux）

> **本專案 SSOT：搖桿走板端 `mavlink_mux`。**  
> 經 QGC 搖桿文件 → [`../../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/docs/`](../../20260730_Accton_Pro_RC_VS680_QGC_RealDrone_USB/docs/)

## 分類

| 目錄 | 內容 |
|------|------|
| [`mux/`](mux/) | **現行** mux 架構、操作手冊 |
| [`latency/`](latency/) | Baseline-Mux-Eth-HTL 報告與量測計畫 |
| [`bring-up/`](bring-up/) | eth0 HTL 驗證、整合報告（共用 bring-up 事實） |

## 現行

| 文件 | 說明 |
|------|------|
| [`mux/architecture.md`](mux/architecture.md) | 系統 mux 架構（Option A/B） |
| [`mux/操作手冊-Mux-HTL.md`](mux/操作手冊-Mux-HTL.md) | 操作手冊 |
| [`latency/latency-report.html`](latency/latency-report.html) | **Baseline-Mux-Eth-HTL** |
| [`latency/joystick-latency-plan.md`](latency/joystick-latency-plan.md) | 延遲量測計畫 |
| [`latency/cross-device-timestamp-assessment.md`](latency/cross-device-timestamp-assessment.md) | 跨設備事件時間記錄與延遲可量測性判定 |
| [`bring-up/verification-eth-htl-20260730.md`](bring-up/verification-eth-htl-20260730.md) | eth HTL 驗證 |
| [`bring-up/integration-report-eth0-fc-communication-20260731.md`](bring-up/integration-report-eth0-fc-communication-20260731.md) | eth0／FC／PC COM FAQ |

## 證據（test/evidence/mux-path/）

| 目錄 | 說明 |
|------|------|
| [`../test/evidence/mux-path/dense-n1000/latency-mux-n1000-latest/`](../test/evidence/mux-path/dense-n1000/latency-mux-n1000-latest/) | **基線** dense n=1000（P50 5.3 / P95 56.2 ms） |
| [`../test/evidence/mux-path/dense-n1000/latency-mux-n1000-20260731-180536/`](../test/evidence/mux-path/dense-n1000/latency-mux-n1000-20260731-180536/) | **重測** dense n=846（P50 5.1 / P95 40.9 ms） |
| [`../test/evidence/mux-path/dense-n1000/`](../test/evidence/mux-path/dense-n1000/) | dense 歷次 run |
| [`../test/evidence/mux-path/edge/`](../test/evidence/mux-path/edge/) | edge／早期 run |
