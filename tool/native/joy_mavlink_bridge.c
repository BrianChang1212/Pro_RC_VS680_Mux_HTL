/*
 * Board-side HID -> MAVLink2 MANUAL_CONTROL over eth0 UDP.
 * Binds local UDP :14550 (same as QGC), learns FC peer from first RX,
 * sends GCS HEARTBEAT + MANUAL_CONTROL.
 *
 * Build (Zig):
 *   zig cc -target aarch64-linux-android24 -O2 -o joy_mavlink_bridge \
 *     joy_mavlink_bridge.c
 *
 * Run on board (root, QGC stopped):
 *   ./joy_mavlink_bridge -i eth0 -d /dev/input/event1 -p 14550 -r 50
 */

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define MAV_PORT_DEFAULT 14550
#define RATE_DEFAULT 50
#define CRC_EXTRA_HEARTBEAT 50
#define CRC_EXTRA_MANUAL_CONTROL 243

static volatile int g_run = 1;

static void on_sig(int sig)
{
	(void)sig;
	g_run = 0;
}

static uint16_t x25_crc(const uint8_t *data, unsigned len, uint8_t crc_extra)
{
	uint16_t crc = 0xFFFF;
	unsigned i;

	for (i = 0; i < len; i++) {
		uint8_t tmp = data[i] ^ (crc & 0xFF);

		tmp ^= (tmp << 4);
		crc = (crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4);
	}
	{
		uint8_t tmp = crc_extra ^ (crc & 0xFF);

		tmp ^= (tmp << 4);
		crc = (crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4);
	}
	return crc;
}

static int mav2_pack(uint8_t *out, unsigned out_cap, uint32_t msgid,
		     const uint8_t *payload, uint8_t plen, uint8_t seq,
		     uint8_t sysid, uint8_t compid, uint8_t crc_extra)
{
	uint16_t crc;
	unsigned total = 10u + plen + 2u;

	if (out_cap < total)
		return -1;
	out[0] = 0xFD;
	out[1] = plen;
	out[2] = 0;
	out[3] = 0;
	out[4] = seq;
	out[5] = sysid;
	out[6] = compid;
	out[7] = (uint8_t)(msgid & 0xFF);
	out[8] = (uint8_t)((msgid >> 8) & 0xFF);
	out[9] = (uint8_t)((msgid >> 16) & 0xFF);
	if (plen)
		memcpy(out + 10, payload, plen);
	crc = x25_crc(out + 1, 9u + plen, crc_extra);
	out[10 + plen] = (uint8_t)(crc & 0xFF);
	out[11 + plen] = (uint8_t)((crc >> 8) & 0xFF);
	return (int)total;
}

static int16_t clamp_i16(int v)
{
	if (v < -1000)
		return -1000;
	if (v > 1000)
		return 1000;
	return (int16_t)v;
}

static int16_t axis_to_mc(int raw, int invert)
{
	double v = (raw - 128) * (1000.0 / 128.0);

	if (invert)
		v = -v;
	return clamp_i16((int)v);
}

static int send_heartbeat(int fd, const struct sockaddr_in *peer, uint8_t *seq)
{
	uint8_t payload[9];
	uint8_t frame[32];
	int n;
	uint32_t custom = 0;

	memcpy(payload, &custom, 4);
	payload[4] = 6; /* MAV_TYPE_GCS */
	payload[5] = 8; /* MAV_AUTOPILOT_INVALID */
	payload[6] = 0;
	payload[7] = 4; /* MAV_STATE_ACTIVE */
	payload[8] = 3;
	n = mav2_pack(frame, sizeof(frame), 0, payload, 9, (*seq)++, 255, 190,
		      CRC_EXTRA_HEARTBEAT);
	if (n < 0)
		return -1;
	return sendto(fd, frame, (size_t)n, 0, (const struct sockaddr *)peer,
		      sizeof(*peer));
}

static int send_manual(int fd, const struct sockaddr_in *peer, uint8_t *seq,
		       int16_t x, int16_t y, int16_t z, int16_t r)
{
	uint8_t payload[11];
	uint8_t frame[40];
	int n;

	payload[0] = 1; /* target system */
	memcpy(payload + 1, &x, 2);
	memcpy(payload + 3, &y, 2);
	memcpy(payload + 5, &z, 2);
	memcpy(payload + 7, &r, 2);
	payload[9] = 0;
	payload[10] = 0;
	n = mav2_pack(frame, sizeof(frame), 69, payload, 11, (*seq)++, 255, 190,
		      CRC_EXTRA_MANUAL_CONTROL);
	if (n < 0)
		return -1;
	return sendto(fd, frame, (size_t)n, 0, (const struct sockaddr *)peer,
		      sizeof(*peer));
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"Usage: %s [-d /dev/input/eventX] [-p port] [-r hz] [-t sec]\n",
		argv0);
}

int main(int argc, char **argv)
{
	const char *dev = "/dev/input/event1";
	int port = MAV_PORT_DEFAULT;
	int rate = RATE_DEFAULT;
	int duration = 0;
	int opt;
	int sock = -1;
	int ifd = -1;
	int raw_x = 128, raw_y = 128, raw_z = 128, raw_rz = 128;
	uint8_t seq = 0;
	struct sockaddr_in local, peer;
	socklen_t peer_len = sizeof(peer);
	int have_peer = 0;
	struct timespec t_next, t_hb, t_stat, t_end, now;
	unsigned n_mc = 0, n_hb = 0;
	long period_ns;

	while ((opt = getopt(argc, argv, "d:p:r:t:h")) != -1) {
		switch (opt) {
		case 'd':
			dev = optarg;
			break;
		case 'p':
			port = atoi(optarg);
			break;
		case 'r':
			rate = atoi(optarg);
			break;
		case 't':
			duration = atoi(optarg);
			break;
		default:
			usage(argv[0]);
			return 1;
		}
	}
	if (rate < 1)
		rate = 1;
	period_ns = 1000000000L / rate;

	signal(SIGINT, on_sig);
	signal(SIGTERM, on_sig);

	sock = socket(AF_INET, SOCK_DGRAM, 0);
	if (sock < 0) {
		perror("socket");
		return 1;
	}
	{
		int yes = 1;

		setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
	}
	memset(&local, 0, sizeof(local));
	local.sin_family = AF_INET;
	local.sin_port = htons((uint16_t)port);
	local.sin_addr.s_addr = htonl(INADDR_ANY);
	if (bind(sock, (struct sockaddr *)&local, sizeof(local)) < 0) {
		perror("bind");
		fprintf(stderr, "Is QGC still holding UDP %d?\n", port);
		return 1;
	}

	ifd = open(dev, O_RDONLY | O_NONBLOCK);
	if (ifd < 0) {
		perror("open input");
		return 1;
	}

	fprintf(stderr,
		"joy_mavlink_bridge: %s -> UDP :%d @ %d Hz (wait FC peer)\n",
		dev, port, rate);

	clock_gettime(CLOCK_MONOTONIC, &t_next);
	t_hb = t_next;
	t_stat = t_next;
	t_end = t_next;
	if (duration > 0)
		t_end.tv_sec += duration;

	while (g_run) {
		struct pollfd pfds[2];
		int pr;
		struct input_event ev;
		ssize_t nr;

		pfds[0].fd = ifd;
		pfds[0].events = POLLIN;
		pfds[1].fd = sock;
		pfds[1].events = POLLIN;
		pr = poll(pfds, 2, 5);
		if (pr < 0) {
			if (errno == EINTR)
				continue;
			perror("poll");
			break;
		}

		if (pfds[0].revents & POLLIN) {
			while ((nr = read(ifd, &ev, sizeof(ev))) ==
			       (ssize_t)sizeof(ev)) {
				if (ev.type != EV_ABS)
					continue;
				if (ev.code == ABS_X)
					raw_x = (int)ev.value;
				else if (ev.code == ABS_Y)
					raw_y = (int)ev.value;
				else if (ev.code == ABS_Z)
					raw_z = (int)ev.value;
				else if (ev.code == ABS_RZ)
					raw_rz = (int)ev.value;
			}
		}

		if (pfds[1].revents & POLLIN) {
			uint8_t buf[2048];
			struct sockaddr_in src;
			socklen_t slen = sizeof(src);

			nr = recvfrom(sock, buf, sizeof(buf), 0,
				      (struct sockaddr *)&src, &slen);
			if (nr > 0) {
				peer = src;
				peer_len = slen;
				have_peer = 1;
			}
		}

		clock_gettime(CLOCK_MONOTONIC, &now);
		if (duration > 0) {
			if (now.tv_sec > t_end.tv_sec ||
			    (now.tv_sec == t_end.tv_sec &&
			     now.tv_nsec >= t_end.tv_nsec))
				break;
		}

		if (!have_peer)
			continue;

		/* HEARTBEAT ~1 Hz */
		if ((now.tv_sec > t_hb.tv_sec) ||
		    (now.tv_sec == t_hb.tv_sec && now.tv_nsec >= t_hb.tv_nsec)) {
			if (send_heartbeat(sock, &peer, &seq) > 0)
				n_hb++;
			t_hb = now;
			t_hb.tv_sec += 1;
		}

		if ((now.tv_sec > t_next.tv_sec) ||
		    (now.tv_sec == t_next.tv_sec &&
		     now.tv_nsec >= t_next.tv_nsec)) {
			int16_t x = axis_to_mc(raw_y, 1);
			int16_t y = axis_to_mc(raw_x, 0);
			int16_t z_sym = axis_to_mc(raw_rz, 0);
			int16_t z = (int16_t)((z_sym + 1000) / 2);
			int16_t r = axis_to_mc(raw_z, 0);

			if (raw_x < 0)
				raw_x = 0;
			if (raw_x > 255)
				raw_x = raw_x & 0xFF;
			if (abs(raw_rz - 128) < 20)
				z = 0;
			if (send_manual(sock, &peer, &seq, x, y, z, r) > 0)
				n_mc++;
			t_next = now;
			t_next.tv_nsec += period_ns;
			while (t_next.tv_nsec >= 1000000000L) {
				t_next.tv_nsec -= 1000000000L;
				t_next.tv_sec++;
			}
		}

		if ((now.tv_sec > t_stat.tv_sec) ||
		    (now.tv_sec == t_stat.tv_sec &&
		     now.tv_nsec >= t_stat.tv_nsec)) {
			char ip[64];

			inet_ntop(AF_INET, &peer.sin_addr, ip, sizeof(ip));
			fprintf(stderr,
				"peer %s:%u mc=%u hb=%u raw x=%d y=%d z=%d rz=%d\n",
				ip, (unsigned)ntohs(peer.sin_port), n_mc, n_hb,
				raw_x, raw_y, raw_z, raw_rz);
			t_stat = now;
			t_stat.tv_sec += 1;
		}
	}

	fprintf(stderr, "exit mc=%u hb=%u\n", n_mc, n_hb);
	close(ifd);
	close(sock);
	return 0;
}
