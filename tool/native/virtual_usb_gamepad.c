/*
 * Create a short-lived virtual USB HID gamepad and emit four direction pulses.
 *
 * The emitted input_event is read by mavlink_mux through a normal evdev node,
 * allowing a controlled HID -> mux -> FC MANUAL_CONTROL validation.
 */

#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define DEVICE_NAME "Codex Test Gamepad"
#define CENTER_VALUE 128

static void usage(const char *prog)
{
	fprintf(stderr, "Usage: %s [-s delay-ms] [-p pulse-ms] [-n neutral-ms] "
		"[-a amplitude] [-h hold-ms]\n", prog);
}

static int write_event(int fd, unsigned short type, unsigned short code,
		       int value)
{
	struct input_event ev;

	memset(&ev, 0, sizeof(ev));
	ev.type = type;
	ev.code = code;
	ev.value = value;
	return write(fd, &ev, sizeof(ev)) == (ssize_t)sizeof(ev) ? 0 : -1;
}

static void sleep_ms(long ms)
{
	struct timespec req;

	req.tv_sec = ms / 1000;
	req.tv_nsec = (ms % 1000) * 1000000L;
	while (nanosleep(&req, &req) < 0 && errno == EINTR)
		;
}

static double monotonic_s(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static int emit_direction(int fd, unsigned int seq, const char *name,
			  unsigned short axis,
			  int value, long pulse_ms, long neutral_ms)
{
	double t0 = monotonic_s();

	if (write_event(fd, EV_MSC, MSC_SERIAL, (int)seq) < 0 ||
	    write_event(fd, EV_ABS, axis, value) < 0 ||
	    write_event(fd, EV_SYN, SYN_REPORT, 0) < 0)
		return -1;
	fprintf(stderr, "INJECT seq=%u dir=%s t0=%.9f\n", seq, name, t0);
	sleep_ms(pulse_ms);
	if (write_event(fd, EV_ABS, axis, CENTER_VALUE) < 0 ||
	    write_event(fd, EV_SYN, SYN_REPORT, 0) < 0)
		return -1;
	fprintf(stderr, "NEUTRAL %s axis=%u value=%d\n", name, axis,
		CENTER_VALUE);
	sleep_ms(neutral_ms);
	return 0;
}

int main(int argc, char **argv)
{
	struct uinput_user_dev dev;
	long delay_ms = 3000;
	long pulse_ms = 500;
	long neutral_ms = 500;
	long hold_ms = 2000;
	long amplitude = 13;
	int fd;
	int opt;
	int ret = 1;

	while ((opt = getopt(argc, argv, "s:p:n:a:h:")) != -1) {
		switch (opt) {
		case 's': delay_ms = strtol(optarg, NULL, 10); break;
		case 'p': pulse_ms = strtol(optarg, NULL, 10); break;
		case 'n': neutral_ms = strtol(optarg, NULL, 10); break;
		case 'a': amplitude = strtol(optarg, NULL, 10); break;
		case 'h': hold_ms = strtol(optarg, NULL, 10); break;
		default: usage(argv[0]); return 2;
		}
	}
	if (delay_ms < 0 || pulse_ms <= 0 || neutral_ms < 0 || hold_ms < 0 ||
	    amplitude <= 12 || amplitude > CENTER_VALUE - 1) {
		usage(argv[0]);
		return 2;
	}

	fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
	if (fd < 0) {
		perror("open /dev/uinput");
		return 1;
	}
	if (ioctl(fd, UI_SET_EVBIT, EV_ABS) < 0 ||
	    ioctl(fd, UI_SET_EVBIT, EV_MSC) < 0 ||
	    ioctl(fd, UI_SET_MSCBIT, MSC_SERIAL) < 0 ||
	    ioctl(fd, UI_SET_ABSBIT, ABS_X) < 0 ||
	    ioctl(fd, UI_SET_ABSBIT, ABS_Y) < 0 ||
	    ioctl(fd, UI_SET_ABSBIT, ABS_Z) < 0 ||
	    ioctl(fd, UI_SET_ABSBIT, ABS_RZ) < 0) {
		perror("configure uinput");
		goto out_close;
	}

	memset(&dev, 0, sizeof(dev));
	strncpy(dev.name, DEVICE_NAME, UINPUT_MAX_NAME_SIZE - 1);
	dev.id.bustype = BUS_USB;
	dev.id.vendor = 0x1209;
	dev.id.product = 0x0001;
	dev.id.version = 1;
	dev.absmin[ABS_X] = 0;
	dev.absmax[ABS_X] = 255;
	dev.absflat[ABS_X] = 15;
	dev.absmin[ABS_Y] = 0;
	dev.absmax[ABS_Y] = 255;
	dev.absflat[ABS_Y] = 15;
	dev.absmin[ABS_Z] = 0;
	dev.absmax[ABS_Z] = 255;
	dev.absflat[ABS_Z] = 15;
	dev.absmin[ABS_RZ] = 0;
	dev.absmax[ABS_RZ] = 255;
	dev.absflat[ABS_RZ] = 15;
	if (write(fd, &dev, sizeof(dev)) != (ssize_t)sizeof(dev) ||
	    ioctl(fd, UI_DEV_CREATE) < 0) {
		perror("create uinput device");
		goto out_close;
	}

	fprintf(stderr, "READY %s\n", DEVICE_NAME);
	sleep_ms(delay_ms);
	if (emit_direction(fd, 1, "UP", ABS_Y, CENTER_VALUE - (int)amplitude,
			   pulse_ms, neutral_ms) < 0 ||
	    emit_direction(fd, 2, "DOWN", ABS_Y, CENTER_VALUE + (int)amplitude,
			   pulse_ms, neutral_ms) < 0 ||
	    emit_direction(fd, 3, "LEFT", ABS_X, CENTER_VALUE - (int)amplitude,
			   pulse_ms, neutral_ms) < 0 ||
	    emit_direction(fd, 4, "RIGHT", ABS_X, CENTER_VALUE + (int)amplitude,
			   pulse_ms, neutral_ms) < 0) {
		perror("emit direction");
		goto out_destroy;
	}
	sleep_ms(hold_ms);
	ret = 0;

out_destroy:
	if (ioctl(fd, UI_DEV_DESTROY) < 0)
		perror("destroy uinput device");
out_close:
	close(fd);
	return ret;
}
