/*
 * Board MAVLink mux (option B):
 *   FC eth  <->  UDP :14550 (this process)  <->  QGC 127.0.0.1:14551
 *   HID joystick -> MANUAL_CONTROL only (injected toward FC from :14550)
 *
 * Role split:
 *   - QGC issues Arm / Takeoff / RTL / Loiter / Guided / params (transparent
 *     forward of all QGC<->FC MAVLink).
 *   - This process never crafts those commands; it only injects MANUAL_CONTROL
 *     when sticks leave the deadband (idle sticks => no MC, so RC override
 *     times out and QGC mode commands are not overridden).
 *
 * QGC must listen on 14551 and must not bind 14550. Disable QGC Joystick
 * Enable to avoid dual MANUAL_CONTROL.
 *
 * Build:
 *   zig cc -target aarch64-linux-musl -O2 -static -o mavlink_mux mavlink_mux.c
 *
 * Run (root):
 *   ./mavlink_mux -d /dev/input/event1 -p 14550 -q 14551 -r 50
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

#define FC_PORT_DEFAULT 14550
#define QGC_PORT_DEFAULT 14551
#define MUX_GCS_PORT_DEFAULT 14552
#define RATE_DEFAULT 50
#define STICK_CENTER_U8 128
#define STICK_DEADBAND_U8 12
#define STICK_DEADBAND_S16 800	/* signed abs axes idle band */
#define CRC_EXTRA_MANUAL_CONTROL 243
#define CRC_EXTRA_RC_CHANNELS_OVERRIDE 124
#define MSGID_COMMAND_LONG 76
#define MSGID_COMMAND_ACK 77
#define MSGID_COMMAND_INT 75

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

/* ZhiXu may report 0..255 (center 128) or signed int16 (center 0). */
static int axis_signed_mode(int raw_x, int raw_y, int raw_z, int raw_rz)
{
	if (raw_x < 0 || raw_y < 0 || raw_z < 0 || raw_rz < 0)
		return 1;
	if (raw_x > 255 || raw_y > 255 || raw_z > 255 || raw_rz > 255)
		return 1;
	/* All near 0 => signed idle (u8 idle is ~128). */
	if (raw_x <= 20 && raw_y <= 20 && raw_z <= 20 && raw_rz <= 20)
		return 1;
	return 0;
}

static int16_t axis_to_mc(int raw, int invert, int signed_mode)
{
	double v;

	if (signed_mode)
		v = raw * (1000.0 / 32767.0);
	else
		v = (raw - STICK_CENTER_U8) * (1000.0 / 128.0);
	if (invert)
		v = -v;
	return clamp_i16((int)v);
}

static int stick_active(int raw_x, int raw_y, int raw_z, int raw_rz)
{
	int signed_mode = axis_signed_mode(raw_x, raw_y, raw_z, raw_rz);
	int db = signed_mode ? STICK_DEADBAND_S16 : STICK_DEADBAND_U8;
	int cx = signed_mode ? 0 : STICK_CENTER_U8;

	if (abs(raw_x - cx) > db)
		return 1;
	if (abs(raw_y - cx) > db)
		return 1;
	if (abs(raw_z - cx) > db)
		return 1;
	if (abs(raw_rz - cx) > db)
		return 1;
	return 0;
}

static int is_loopback(const struct sockaddr_in *a)
{
	uint32_t x = ntohl(a->sin_addr.s_addr);

	return (x >> 24) == 127;
}

static double mono_now_s(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void log_mavlink_commands(FILE *fp, const char *tag,
				 const uint8_t *buf, ssize_t len)
{
	ssize_t i = 0;

	if (!fp)
		return;
	while (i + 10 <= len) {
		uint8_t plen;
		uint8_t incompat;
		ssize_t frame_len;
		uint32_t msgid;
		const uint8_t *payload;
		int command = -1;
		int result = -1;

		if (buf[i] != 0xFD) {
			i++;
			continue;
		}
		plen = buf[i + 1];
		incompat = buf[i + 2];
		frame_len = 10 + plen + 2;
		if (incompat & 0x01)
			frame_len += 13;
		if (i + frame_len > len)
			break;
		msgid = (uint32_t)buf[i + 7] |
			((uint32_t)buf[i + 8] << 8) |
			((uint32_t)buf[i + 9] << 16);
		payload = &buf[i + 10];
		if (msgid == MSGID_COMMAND_LONG && plen >= 30)
			command = payload[28] | (payload[29] << 8);
		else if (msgid == MSGID_COMMAND_INT && plen >= 35)
			command = payload[33] | (payload[34] << 8);
		else if (msgid == MSGID_COMMAND_ACK && plen >= 2) {
			command = payload[0] | (payload[1] << 8);
			if (plen >= 3)
				result = payload[2];
		}

		if (msgid == MSGID_COMMAND_LONG || msgid == MSGID_COMMAND_INT ||
		    msgid == MSGID_COMMAND_ACK) {
			fprintf(fp,
				"%s %.6f msgid=%u cmd=%d result=%d seq=%u sys=%u comp=%u\n",
				tag, mono_now_s(), msgid, command, result,
				buf[i + 4], buf[i + 5], buf[i + 6]);
		}
		i += frame_len;
	}
}

static uint16_t stick_to_pwm(int16_t v)
{
	/* v: -1000..1000 -> PWM 1000..2000 */
	int pwm = 1500 + (int)v / 2;

	if (pwm < 1000)
		pwm = 1000;
	if (pwm > 2000)
		pwm = 2000;
	return (uint16_t)pwm;
}

/*
 * Prefer RC_CHANNELS_OVERRIDE for ArduCopter Loiter stick (SYSID 255).
 * Also send MANUAL_CONTROL in-range as secondary.
 */
static int send_stick(int fd, const struct sockaddr_in *peer, uint8_t *seq,
		      int16_t x, int16_t y, int16_t z, int16_t r)
{
	uint8_t payload[18];
	uint8_t frame[48];
	uint8_t mc_payload[11];
	uint16_t ch[8];
	int n;
	int16_t xc = clamp_i16(x);
	int16_t yc = clamp_i16(y);
	int16_t zc = z;
	int16_t rc = clamp_i16(r);

	if (zc < 0)
		zc = 0;
	if (zc > 1000)
		zc = 1000;

	/* Copter default: 1=roll 2=pitch 3=throttle 4=yaw */
	ch[0] = stick_to_pwm(yc);
	ch[1] = stick_to_pwm(-xc); /* pitch: +x forward => stick back in PWM? use -x */
	ch[2] = (uint16_t)(1000 + zc);
	ch[3] = stick_to_pwm(rc);
	ch[4] = 0;
	ch[5] = 0;
	ch[6] = 0;
	ch[7] = 0;

	/* MAVLink RC_CHANNELS_OVERRIDE: target_system, target_component, chan1..8 */
	payload[0] = 1;
	payload[1] = 1;
	memcpy(payload + 2, ch, 16);
	n = mav2_pack(frame, sizeof(frame), 70, payload, 18, (*seq)++, 255, 190,
		      CRC_EXTRA_RC_CHANNELS_OVERRIDE);
	if (n < 0)
		return -1;
	if (sendto(fd, frame, (size_t)n, 0, (const struct sockaddr *)peer,
		   sizeof(*peer)) < 0)
		return -1;

	mc_payload[0] = 1;
	memcpy(mc_payload + 1, &xc, 2);
	memcpy(mc_payload + 3, &yc, 2);
	memcpy(mc_payload + 5, &zc, 2);
	memcpy(mc_payload + 7, &rc, 2);
	mc_payload[9] = 0;
	mc_payload[10] = 0;
	n = mav2_pack(frame, sizeof(frame), 69, mc_payload, 11, (*seq)++, 255,
		      190, CRC_EXTRA_MANUAL_CONTROL);
	if (n < 0)
		return -1;
	return sendto(fd, frame, (size_t)n, 0, (const struct sockaddr *)peer,
		      sizeof(*peer));
}

static int bind_udp(int port, uint32_t addr_h)
{
	int fd;
	struct sockaddr_in local;
	int yes = 1;

	fd = socket(AF_INET, SOCK_DGRAM, 0);
	if (fd < 0)
		return -1;
	setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
	memset(&local, 0, sizeof(local));
	local.sin_family = AF_INET;
	local.sin_port = htons((uint16_t)port);
	local.sin_addr.s_addr = htonl(addr_h);
	if (bind(fd, (struct sockaddr *)&local, sizeof(local)) < 0) {
		close(fd);
		return -1;
	}
	return fd;
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"Usage: %s [-d /dev/input/eventX] [-p fc_port] [-q qgc_port]\n"
		"          [-g mux_gcs_port] [-r hz] [-t sec] [-L lat.log] [-n]\n"
		"  -L  log CLOCK_MONOTONIC stick sends (same clock as getevent -lt)\n"
		"  -n  no joystick inject (forward only)\n",
		argv0);
}

int main(int argc, char **argv)
{
	const char *dev = "/dev/input/event1";
	const char *lat_path = NULL;
	FILE *lat_fp = NULL;
	int fc_port = FC_PORT_DEFAULT;
	int qgc_port = QGC_PORT_DEFAULT;
	int mux_gcs_port = MUX_GCS_PORT_DEFAULT;
	int rate = RATE_DEFAULT;
	int duration = 0;
	int no_joy = 0;
	int opt;
	int sock_fc = -1;
	int sock_gcs = -1;
	int ifd = -1;
	int raw_x = 128, raw_y = 128, raw_z = 128, raw_rz = 128;
	uint8_t seq = 0;
	struct sockaddr_in fc_peer, qgc_dst;
	int have_fc = 0;
	struct timespec t_next, t_stat, t_end, now;
	unsigned n_mc = 0, n_fwd_fc = 0, n_fwd_gcs = 0;
	long period_ns;

	while ((opt = getopt(argc, argv, "d:p:q:g:r:t:L:nh")) != -1) {
		switch (opt) {
		case 'd':
			dev = optarg;
			break;
		case 'p':
			fc_port = atoi(optarg);
			break;
		case 'q':
			qgc_port = atoi(optarg);
			break;
		case 'g':
			mux_gcs_port = atoi(optarg);
			break;
		case 'r':
			rate = atoi(optarg);
			break;
		case 't':
			duration = atoi(optarg);
			break;
		case 'L':
			lat_path = optarg;
			break;
		case 'n':
			no_joy = 1;
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
	setvbuf(stderr, NULL, _IOLBF, 0);

	if (lat_path) {
		lat_fp = fopen(lat_path, "w");
		if (!lat_fp) {
			perror("open latency log");
			return 1;
		}
		setvbuf(lat_fp, NULL, _IOLBF, 0);
		fprintf(stderr, "latency log %s (CLOCK_MONOTONIC)\n", lat_path);
	}

	sock_fc = bind_udp(fc_port, INADDR_ANY);
	if (sock_fc < 0) {
		perror("bind fc");
		fprintf(stderr, "Is another process holding UDP %d?\n", fc_port);
		return 1;
	}

	sock_gcs = bind_udp(mux_gcs_port, INADDR_LOOPBACK);
	if (sock_gcs < 0) {
		perror("bind gcs");
		return 1;
	}

	memset(&qgc_dst, 0, sizeof(qgc_dst));
	qgc_dst.sin_family = AF_INET;
	qgc_dst.sin_port = htons((uint16_t)qgc_port);
	inet_pton(AF_INET, "127.0.0.1", &qgc_dst.sin_addr);

	if (!no_joy) {
		ifd = open(dev, O_RDONLY | O_NONBLOCK);
		if (ifd < 0) {
			perror("open input");
			fprintf(stderr, "Continuing without joystick (-n).\n");
			no_joy = 1;
		}
	}

	fprintf(stderr,
		"mavlink_mux: FC :%d <-> QGC 127.0.0.1:%d (mux gcs :%d)%s\n",
		fc_port, qgc_port, mux_gcs_port,
		no_joy ? " [forward-only]" : "");
	if (!no_joy)
		fprintf(stderr, "  joy %s -> MANUAL_CONTROL @ %d Hz\n", dev,
			rate);

	clock_gettime(CLOCK_MONOTONIC, &t_next);
	t_stat = t_next;
	t_end = t_next;
	if (duration > 0)
		t_end.tv_sec += duration;

	while (g_run) {
		struct pollfd pfds[3];
		int nfds = 0;
		int pr;
		ssize_t nr;
		int idx_joy = -1, idx_fc = -1, idx_gcs = -1;

		if (!no_joy && ifd >= 0) {
			idx_joy = nfds;
			pfds[nfds].fd = ifd;
			pfds[nfds].events = POLLIN;
			nfds++;
		}
		idx_fc = nfds;
		pfds[nfds].fd = sock_fc;
		pfds[nfds].events = POLLIN;
		nfds++;
		idx_gcs = nfds;
		pfds[nfds].fd = sock_gcs;
		pfds[nfds].events = POLLIN;
		nfds++;

		pr = poll(pfds, nfds, 5);
		if (pr < 0) {
			if (errno == EINTR)
				continue;
			perror("poll");
			break;
		}

		if (idx_joy >= 0 && (pfds[idx_joy].revents & POLLIN)) {
			struct input_event ev;

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

		if (pfds[idx_fc].revents & POLLIN) {
			uint8_t buf[2048];
			struct sockaddr_in src;
			socklen_t slen = sizeof(src);

			while ((nr = recvfrom(sock_fc, buf, sizeof(buf),
					      MSG_DONTWAIT,
					      (struct sockaddr *)&src,
					      &slen)) > 0) {
				log_mavlink_commands(lat_fp, "FC_RX", buf, nr);
				if (!is_loopback(&src)) {
					fc_peer = src;
					have_fc = 1;
				}
				if (sendto(sock_gcs, buf, (size_t)nr, 0,
					   (const struct sockaddr *)&qgc_dst,
					   sizeof(qgc_dst)) > 0)
					n_fwd_fc++;
			}
		}

		if (pfds[idx_gcs].revents & POLLIN) {
			uint8_t buf[2048];
			struct sockaddr_in src;
			socklen_t slen = sizeof(src);

			while ((nr = recvfrom(sock_gcs, buf, sizeof(buf),
					      MSG_DONTWAIT,
					      (struct sockaddr *)&src,
					      &slen)) > 0) {
				log_mavlink_commands(lat_fp, "GCS_RX", buf, nr);
				if (!have_fc)
					continue;
				if (sendto(sock_fc, buf, (size_t)nr, 0,
					   (const struct sockaddr *)&fc_peer,
					   sizeof(fc_peer)) > 0) {
					log_mavlink_commands(lat_fp, "GCS_TX", buf, nr);
					n_fwd_gcs++;
				}
			}
		}

		clock_gettime(CLOCK_MONOTONIC, &now);
		if (duration > 0) {
			if (now.tv_sec > t_end.tv_sec ||
			    (now.tv_sec == t_end.tv_sec &&
			     now.tv_nsec >= t_end.tv_nsec))
				break;
		}

		/*
		 * Joystick path only: inject MANUAL_CONTROL while sticks move.
		 * Idle sticks => stop MC so ArduPilot RC override times out and
		 * QGC Arm/Takeoff/RTL/Loiter are not overridden.
		 */
		if (!no_joy && have_fc &&
		    stick_active(raw_x, raw_y, raw_z, raw_rz)) {
			if ((now.tv_sec > t_next.tv_sec) ||
			    (now.tv_sec == t_next.tv_sec &&
			     now.tv_nsec >= t_next.tv_nsec)) {
				int signed_mode = axis_signed_mode(
					raw_x, raw_y, raw_z, raw_rz);
				int16_t x = axis_to_mc(raw_y, 1, signed_mode);
				int16_t y = axis_to_mc(raw_x, 0, signed_mode);
				int16_t z_sym =
					axis_to_mc(raw_rz, 0, signed_mode);
				int16_t z = (int16_t)((z_sym + 1000) / 2);
				int16_t r = axis_to_mc(raw_z, 0, signed_mode);
				int thr_db = signed_mode ? STICK_DEADBAND_S16
							 : STICK_DEADBAND_U8;
				int thr_c = signed_mode ? 0 : STICK_CENTER_U8;

				if (abs(raw_rz - thr_c) < thr_db)
					z = 0;
				if (send_stick(sock_fc, &fc_peer, &seq, x, y, z,
					       r) > 0) {
					n_mc++;
					if (lat_fp) {
						double tmono =
							(double)now.tv_sec +
							(double)now.tv_nsec /
								1e9;

						fprintf(lat_fp,
							"MC %.6f %d %d %d %d\n",
							tmono, (int)x, (int)y,
							(int)z, (int)r);
					}
				}
				t_next = now;
				t_next.tv_nsec += period_ns;
				while (t_next.tv_nsec >= 1000000000L) {
					t_next.tv_nsec -= 1000000000L;
					t_next.tv_sec++;
				}
			}
		}

		if ((now.tv_sec > t_stat.tv_sec) ||
		    (now.tv_sec == t_stat.tv_sec &&
		     now.tv_nsec >= t_stat.tv_nsec)) {
			char ip[64] = "-";
			int signed_mode = axis_signed_mode(raw_x, raw_y, raw_z,
							   raw_rz);
			int16_t sx = axis_to_mc(raw_y, 1, signed_mode);
			int16_t sy = axis_to_mc(raw_x, 0, signed_mode);

			if (have_fc)
				inet_ntop(AF_INET, &fc_peer.sin_addr, ip,
					  sizeof(ip));
			fprintf(stderr,
				"fc %s:%u fwd_fc=%u fwd_gcs=%u mc=%u raw x=%d y=%d z=%d rz=%d out xy=%d,%d\n",
				ip,
				have_fc ? (unsigned)ntohs(fc_peer.sin_port) : 0,
				n_fwd_fc, n_fwd_gcs, n_mc, raw_x, raw_y, raw_z,
				raw_rz, (int)sx, (int)sy);
			t_stat = now;
			t_stat.tv_sec += 1;
		}
	}

	fprintf(stderr, "exit fwd_fc=%u fwd_gcs=%u mc=%u\n", n_fwd_fc,
		n_fwd_gcs, n_mc);
	if (lat_fp)
		fclose(lat_fp);
	if (ifd >= 0)
		close(ifd);
	close(sock_gcs);
	close(sock_fc);
	return 0;
}
