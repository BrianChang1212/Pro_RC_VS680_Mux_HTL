/*
 * Read-only MAVLink TIMESYNC probe for FC clock-offset confirmation.
 *
 * Sends TIMESYNC requests directly to the FC telemetry peer and prints RTT
 * plus the midpoint-estimated FC clock offset. It never sends flight-control
 * commands or changes either system clock.
 */

#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define MAVLINK_V2_STX 0xfd
#define MAVLINK_MSG_ID_TIMESYNC 111
#define MAVLINK_TIMESYNC_CRC_EXTRA 34
#define MAVLINK_SYS_ID_GCS 255
#define MAVLINK_COMP_ID_GCS 190

static uint16_t crc_accumulate(uint8_t data, uint16_t crc)
{
	uint8_t tmp = data ^ (uint8_t)(crc & 0xff);

	tmp ^= tmp << 4;
	return (crc >> 8) ^ ((uint16_t)tmp << 8) ^ ((uint16_t)tmp << 3) ^
	       ((uint16_t)tmp >> 4);
}

static int64_t monotonic_ns(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static size_t pack_timesync(uint8_t *frame, uint8_t seq, int64_t ts1)
{
	uint16_t crc = 0xffff;
	int64_t tc1 = 0;
	size_t i;

	frame[0] = MAVLINK_V2_STX;
	frame[1] = 16;
	frame[2] = 0;
	frame[3] = 0;
	frame[4] = seq;
	frame[5] = MAVLINK_SYS_ID_GCS;
	frame[6] = MAVLINK_COMP_ID_GCS;
	frame[7] = MAVLINK_MSG_ID_TIMESYNC;
	frame[8] = 0;
	frame[9] = 0;
	memcpy(frame + 10, &tc1, sizeof(tc1));
	memcpy(frame + 18, &ts1, sizeof(ts1));
	for (i = 1; i < 26; i++)
		crc = crc_accumulate(frame[i], crc);
	crc = crc_accumulate(MAVLINK_TIMESYNC_CRC_EXTRA, crc);
	frame[26] = (uint8_t)(crc & 0xff);
	frame[27] = (uint8_t)(crc >> 8);
	return 28;
}

static int parse_timesync_reply(const uint8_t *buf, size_t len,
				int64_t expected_ts1, int64_t *fc_tc1)
{
	uint32_t msgid;
	int64_t ts1;

	if (len < 28 || buf[0] != MAVLINK_V2_STX || buf[1] != 16)
		return 0;
	msgid = (uint32_t)buf[7] | ((uint32_t)buf[8] << 8) |
		((uint32_t)buf[9] << 16);
	if (msgid != MAVLINK_MSG_ID_TIMESYNC)
		return 0;
	memcpy(fc_tc1, buf + 10, sizeof(*fc_tc1));
	memcpy(&ts1, buf + 18, sizeof(ts1));
	return ts1 == expected_ts1 && *fc_tc1 != 0;
}

int main(int argc, char **argv)
{
	const char *ip = "192.168.144.14";
	int port = 62510;
	int local_port = 14550;
	int count = 8;
	struct sockaddr_in local;
	struct sockaddr_in peer;
	struct pollfd pfd;
	int fd;
	int opt;
	int i;
	int samples = 0;
	double rtt_sum_ms = 0.0;
	int64_t offset_min = INT64_MAX, offset_max = INT64_MIN;

	while ((opt = getopt(argc, argv, "h:p:s:n:")) != -1) {
		switch (opt) {
		case 'h': ip = optarg; break;
		case 'p': port = atoi(optarg); break;
		case 's': local_port = atoi(optarg); break;
		case 'n': count = atoi(optarg); break;
		default:
			fprintf(stderr, "Usage: %s [-h fc-ip] [-p fc-port] [-s local-port] "
				"[-n samples]\n",
				argv[0]);
			return 2;
		}
	}
	if (port < 1 || port > 65535 || local_port < 1 || local_port > 65535 ||
	    count < 1 || count > 100)
		return 2;

	fd = socket(AF_INET, SOCK_DGRAM, 0);
	if (fd < 0) {
		perror("socket");
		return 1;
	}
	memset(&local, 0, sizeof(local));
	local.sin_family = AF_INET;
	local.sin_port = htons((uint16_t)local_port);
	local.sin_addr.s_addr = htonl(INADDR_ANY);
	if (bind(fd, (struct sockaddr *)&local, sizeof(local)) < 0) {
		perror("bind local MAVLink port");
		close(fd);
		return 1;
	}
	memset(&peer, 0, sizeof(peer));
	peer.sin_family = AF_INET;
	peer.sin_port = htons((uint16_t)port);
	if (inet_pton(AF_INET, ip, &peer.sin_addr) != 1) {
		fprintf(stderr, "Invalid FC IPv4 address: %s\n", ip);
		close(fd);
		return 2;
	}
	if (connect(fd, (struct sockaddr *)&peer, sizeof(peer)) < 0) {
		perror("connect");
		close(fd);
		return 1;
	}
	pfd.fd = fd;
	pfd.events = POLLIN;
	for (i = 0; i < count; i++) {
		uint8_t frame[28];
		uint8_t reply[2048];
		int64_t t0 = monotonic_ns();
		int64_t t4;
		int64_t fc_tc1;
		int pr;

		if (send(fd, frame, pack_timesync(frame, (uint8_t)i, t0), 0) < 0) {
			perror("send TIMESYNC");
			continue;
		}
		pr = poll(&pfd, 1, 500);
		if (pr <= 0) {
			fprintf(stderr, "TIMESYNC seq=%d timeout\n", i + 1);
			continue;
		}
		for (;;) {
			ssize_t nr = recv(fd, reply, sizeof(reply), MSG_DONTWAIT);

			if (nr < 0)
				break;
			t4 = monotonic_ns();
			if (parse_timesync_reply(reply, (size_t)nr, t0, &fc_tc1)) {
				int64_t rtt_ns = t4 - t0;
				int64_t offset_ns = fc_tc1 - (t0 + t4) / 2;

				printf("TIMESYNC seq=%d t0=%lld t4=%lld fc_tc1=%lld "
				       "rtt_ns=%lld offset_ns=%lld\n", i + 1,
				       (long long)t0, (long long)t4,
				       (long long)fc_tc1, (long long)rtt_ns,
				       (long long)offset_ns);
				rtt_sum_ms += (double)rtt_ns / 1e6;
				if (offset_ns < offset_min)
					offset_min = offset_ns;
				if (offset_ns > offset_max)
					offset_max = offset_ns;
				samples++;
				break;
			}
		}
		usleep(100000);
	}
	if (!samples) {
		fprintf(stderr, "No TIMESYNC reply from %s:%d\n", ip, port);
		close(fd);
		return 1;
	}
	printf("SUMMARY samples=%d rtt_mean_ms=%.3f offset_span_ns=%lld\n",
	       samples, rtt_sum_ms / samples,
	       (long long)(offset_max - offset_min));
	close(fd);
	return 0;
}
