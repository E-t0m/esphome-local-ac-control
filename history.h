// History in RAM with growing interval: 600 samples of 6 bytes. It starts with one sample per
// second; whenever the buffer is full, neighbouring samples are averaged in pairs and the interval
// doubles (1, 2, 4 … 64 s). At 64 s the buffer covers about 10.7 hours, older samples drop out.
// Served as /history.json through the web server. Included through history.yaml. Lost on reboot.
//
// Response (plain text, fixed width so it can be streamed in chunks without a buffer):
//	header  "AAAAAAAAAA SSSS NNNN power-name-24-chars\n"
//	        A = seconds since the newest sample, S = seconds between samples, N = number of samples
//	rows    "ff rrrr tt pppp\n", oldest first, hexadecimal:
//	        ff = compressor frequency in Hz, rrrr = room temperature × 10 (int16),
//	        tt = setpoint × 2, pppp = power in W; all bits set = no value
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace history {

static const uint16_t SIZE = 600;
static const uint16_t MAX_STEP_S = 64;
static const size_t HEAD = 46;
static const size_t ROW = 16;

struct Sample {
	int16_t room;    // °C × 10, INT16_MIN = none
	uint16_t power;  // W, 0xFFFF = none
	uint8_t freq;    // Hz, 0xFF = none
	uint8_t target;  // °C × 2, 0xFF = none
};

struct Buffer {
	Sample s[SIZE];
	uint16_t head = 0;  // next write position
	uint16_t count = 0;
	uint16_t step = 1;  // seconds between samples
	uint32_t last_ms = 0;
	char power_name[25] = "Power";
	// running averages for the next sample
	float sum[4] = {0, 0, 0, 0};
	uint16_t n[4] = {0, 0, 0, 0};
	uint16_t ticks = 0;
};

inline Buffer &buf() {
	static Buffer b;
	return b;
}

inline void set_power_name(const char *name) {
	std::snprintf(buf().power_name, sizeof(buf().power_name), "%s", name);
}

inline Sample encode(float freq, float room, float target, float power) {
	Sample s;
	s.freq = std::isnan(freq) ? 0xFF : (uint8_t) std::max(0.0f, std::min(254.0f, std::round(freq)));
	s.room = std::isnan(room) ? INT16_MIN : (int16_t) std::max(-32000.0f, std::min(32000.0f, std::round(room * 10)));
	s.target = std::isnan(target) ? 0xFF : (uint8_t) std::max(0.0f, std::min(254.0f, std::round(target * 2)));
	s.power = std::isnan(power) ? 0xFFFF : (uint16_t) std::max(0.0f, std::min(65534.0f, std::round(power)));
	return s;
}

// average of two encoded samples; a missing value is replaced by the other one
inline Sample merge(const Sample &a, const Sample &b) {
	Sample s;
	s.freq = a.freq == 0xFF ? b.freq : b.freq == 0xFF ? a.freq : (uint8_t) ((a.freq + b.freq + 1) / 2);
	s.room = a.room == INT16_MIN ? b.room : b.room == INT16_MIN ? a.room : (int16_t) ((a.room + b.room) / 2);
	s.target = a.target == 0xFF ? b.target : b.target == 0xFF ? a.target : (uint8_t) ((a.target + b.target + 1) / 2);
	s.power = a.power == 0xFFFF ? b.power : b.power == 0xFFFF ? a.power : (uint16_t) ((a.power + b.power + 1) / 2);
	return s;
}

inline void store(const Sample &s, uint32_t now_ms) {
	auto &b = buf();
	if (b.count == SIZE && b.step < MAX_STEP_S) {
		// full: average pairs into the first half and double the interval (the buffer is not
		// wrapped yet, it only wraps at the largest interval)
		for (uint16_t i = 0; i < SIZE / 2; i++)
			b.s[i] = merge(b.s[2 * i], b.s[2 * i + 1]);
		b.count = SIZE / 2;
		b.head = SIZE / 2;
		b.step *= 2;
	}
	b.s[b.head] = s;
	b.head = (b.head + 1) % SIZE;
	if (b.count < SIZE)
		b.count++;
	b.last_ms = now_ms;
}

// called once per second; averages the values until the current interval is complete
inline void tick(float freq, float room, float target, float power, uint32_t now_ms) {
	auto &b = buf();
	const float v[4] = {freq, room, target, power};
	for (int i = 0; i < 4; i++)
		if (!std::isnan(v[i])) {
			b.sum[i] += v[i];
			b.n[i]++;
		}
	if (++b.ticks < b.step)
		return;
	float avg[4];
	for (int i = 0; i < 4; i++) {
		avg[i] = b.n[i] ? b.sum[i] / b.n[i] : NAN;
		b.sum[i] = 0;
		b.n[i] = 0;
	}
	b.ticks = 0;
	store(encode(avg[0], avg[1], avg[2], avg[3]), now_ms);
}

// Fills out[0..max) with the response from byte position index on; returns the number of bytes,
// 0 at the end. count/head/step/age are a snapshot taken when the request started.
inline size_t fill(uint8_t *out, size_t max, size_t index, uint16_t count, uint16_t head, uint16_t step,
		uint32_t age) {
	const auto &b = buf();
	const size_t total = HEAD + (size_t) count * ROW;
	size_t written = 0;
	char line[64];
	while (written < max && index < total) {
		size_t len, off;
		if (index < HEAD) {
			std::snprintf(line, sizeof(line), "%010lu %04u %04u %-24.24s\n", (unsigned long) age,
					(unsigned) step, (unsigned) count, b.power_name);
			len = HEAD;
			off = index;
		} else {
			const size_t r = (index - HEAD) / ROW;
			off = (index - HEAD) % ROW;
			const Sample &s = b.s[(head + SIZE - count + r) % SIZE];
			std::snprintf(line, sizeof(line), "%02x %04x %02x %04x\n", s.freq, (uint16_t) s.room, s.target, s.power);
			len = ROW;
		}
		const size_t n = std::min(len - off, max - written);
		std::memcpy(out + written, line + off, n);
		written += n;
		index += n;
	}
	return written;
}

#ifdef USE_WEBSERVER
// Handler for /history.json; registered with web_server_base, so the web server's
// authentication applies.
class Handler : public AsyncWebHandler {
 public:
	bool canHandle(AsyncWebServerRequest *request) const override { return request->url() == "/history.json"; }
	void handleRequest(AsyncWebServerRequest *request) override {
		const auto &b = buf();
		const uint16_t count = b.count, head = b.head, step = b.step;
		const uint32_t age = count ? (millis() - b.last_ms) / 1000 : 0;
		auto *response = request->beginChunkedResponse(
				"text/plain", [count, head, step, age](uint8_t *out, size_t max, size_t index) -> size_t {
					return fill(out, max, index, count, head, step, age);
				});
		response->addHeader("Cache-Control", "no-store");
		request->send(response);
	}
};
#endif

}  // namespace history
