# All-flow pcap timing summary

- pcap packets/messages parsed: packets=5068 messages=5068
- board->FC MANUAL_CONTROL(69): 1183
- board->FC RC_CHANNELS_OVERRIDE(70): 1183
- FC->board ATTITUDE(30): 297

## Packet-clock stats

- MANUAL_CONTROL inter-packet: n=1182 min=19.51 mean=25.11 P50=21.76 P95=25.06 max=599.91 ms
- ATTITUDE inter-packet: n=296 min=96.74 mean=100.00 P50=100.00 P95=102.87 max=103.30 ms
- MANUAL_CONTROL -> next ATTITUDE proxy: n=1183 min=0.13 mean=50.77 P50=51.41 P95=95.14 max=102.99 ms

Note: pcap timestamps are eth0 packet timestamps. They verify wire-visible send/receive timing on VS680, not FC internal receive/handle or QGC HUD render timing.
