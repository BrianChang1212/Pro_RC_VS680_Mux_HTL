# 跨設備資料流事件時間記錄判定

> 判定日期：2026-08-02
> 適用路徑：VS680／SL1680 Android 主板 + Godwit FC + mavlink_mux + QGC

## 硬體與通訊前提

1. VS680 是 SoC，搭配 SL1680 主板。
2. Godwit FC 透過 USB port 連接電腦，提供 ArduPilot MAVLink COM port。
3. VS680 主板透過實體 Ethernet `eth0` 與 FC 直接連接。
4. VS680／SL1680 透過 USB Type-C 連接電腦，電腦以 `adb shell` 進入 Android 系統。
5. 現行資料路徑為：

```text
USB HID → mavlink_mux :14550 → VS680 eth0 → FC Ethernet
FC Ethernet → VS680 eth0 → mavlink_mux → QGC :14551 → HUD
```

FC USB COM 主要用於寫入 `NET_*` 參數、MAVLink 設定與診斷；`adb shell` 只控制 VS680 Android，不代表 FC 內部執行時間。

## 判定結論

**所有資料流事件都可以設計探針記錄事件時間；但現有設備與 repo 尚未能讓所有段落直接計算可信的單向延遲。**

| 資料段 | 事件時間 | 目前能否直接計算延遲 | 需要的條件 |
|---|---|---|---|
| USB HID → mavlink_mux | 可以 | 可以 | `getevent -lt` + mux `-L`，同為 VS680 `CLOCK_MONOTONIC` |
| mavlink_mux → VS680 eth0 發送 | 可以 | 尚未完成 | mux `sendto()` 前記錄時間、封包序號，並與 eth0 pcap 配對 |
| VS680 eth0 → FC 收到 UDP | FC 端可記錄 | 目前不行 | FC firmware 在 UDP receive/command handler 加探針 |
| FC 產生 ATTITUDE → eth0 發送 | FC 端可記錄 | 目前不行 | FC firmware 在 ATTITUDE 產生或送出處加探針 |
| VS680 eth0 收到 ATTITUDE → mux/QGC | 可以 | 可以加量 | VS680 端使用共同 monotonic 時鐘記錄 receive、forward、QGC receive |
| QGC 收到 → HUD 顯示 | 可記錄 | 目前不行 | QGC message callback 與 UI render callback 加探針；錄影只能估算 |

## 時鐘限制

- Android `getevent -lt` 使用 `CLOCK_MONOTONIC`。不能拿 Android 的 `/proc/uptime` 或未確認 clock domain 的時間直接補差。
- Linux `tcpdump -tt` 顯示核心套用到封包的 timestamp，通常是 Unix/wall-clock；它不是自動與 `CLOCK_MONOTONIC` 對齊的端到端時間。
- MAVLink `ATTITUDE.time_boot_ms` 是 FC 自開機起算的時間，只能表示 FC 自己的時間軸，不能直接與 VS680 timestamp 相減。
- MAVLink `TIMESYNC` 可估算 FC 與 VS680 的 clock offset；若要取得可信的跨設備單向延遲，仍需實際在兩端記錄並套用同步偏移。
- QGC `.tlog` 能保存收到的 MAVLink telemetry，但不等同於 FC 內部產生訊息的時間。

## Repo 現況證據

- `docs/mux/architecture.md` 定義 VS680 eth0、mavlink_mux、QGC 與 FC Ethernet 拓樸，FC USB 只作參數設定，ADB 連主板。
- `docs/latency/joystick-latency-plan.md` 已完成 `T0 → T1`；`T2−T1`、`T3−T2`、`T4−T3` 仍列為 pending。
- 現有 evidence 的 `L_cmd` 是 HID 到 mux 的同時鐘量測，不是完整 HID 到 FC 的端到端延遲。

## 建議的完整量測方案

1. 在 `mavlink_mux` `sendto()` 前記錄 `T2`、MAVLink sequence/封包識別資訊。
2. 在 FC firmware 的 UDP receive 與 ATTITUDE transmit 路徑分別記錄 `T3` 與 `T4_send`。
3. 在 VS680 eth0 記錄封包收到時間 `T4_receive`，優先確認 Android kernel/libpcap 的 timestamp clock domain；必要時改用 `SO_TIMESTAMPNS` 或 `SO_TIMESTAMPING`。
4. 以 MAVLink `TIMESYNC` 或明確的雙端 clock offset 校正 FC 與 VS680 時間。
5. 若要量 HUD 顯示，於 QGC 加入 message receive 與 UI render callback 兩個 probe；不要只用 `.tlog` 或螢幕錄影宣稱精確執行時間。

## 外部技術依據

- [Android AOSP `getevent`：`CLOCK_MONOTONIC` timestamp](https://source.android.com/docs/core/interaction/input/getevent)
- [Linux kernel timestamping：`SO_TIMESTAMPNS`／`SO_TIMESTAMPING`](https://docs.kernel.org/networking/timestamping.html)
- [tcpdump(8)：`-tt` 與 kernel packet timestamp 說明](https://man7.org/linux/man-pages/man8/tcpdump.8.html)
- [MAVLink common messages：`ATTITUDE.time_boot_ms`／`SYSTEM_TIME`](https://mavlink.io/en/messages/common.html)
- [MAVLink `TIMESYNC` service](https://mavlink.io/en/services/timesync.html)
- [QGroundControl telemetry log 說明](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/general.html)
