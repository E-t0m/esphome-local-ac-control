// Schedules as text: parse rules, find the rule for a given time, determine the next switching point.
// Included through schedule.yaml (esphome: includes), no dependency on ESPHome.
//
// Format: rules separated by ";", parts of a rule separated by spaces, case-insensitive.
//	Days         7 characters Mon…Sun, x = on, _ = off                (required)
//	Time         H:MM or HH:MM                                         (required)
//	Temperature  number 10–35, decimal separator . or ,                (optional, before the mode)
//	Mode         off, on, auto, heat, cool, dry, fan, keep             (required)
//	             on = last used mode, keep = mode and on/off unchanged
//	Fan          an option of the device's fan speed select           (optional, first word after the mode)
//	Vanes        v1–v5 vertical, h1–h5 horizontal                      (optional)
// Example: xxxxx__ 6:30 22 heat auto; xxxxx__ 8:00 off; _____xx 8:20 21 heat 2 v3 h1
#pragma once

#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <vector>

namespace schedule {

// Prefix SCH_, because tclac.h defines MODE_AUTO, MODE_HEAT … as macros
enum Mode : int8_t { SCH_OFF = 0, SCH_LAST, SCH_AUTO, SCH_HEAT, SCH_COOL, SCH_DRY, SCH_FAN, SCH_KEEP };
static const int MODE_COUNT = 8;
// at most this many rules; they are stored packed in 2 words each (see pack())
static const int MAX_RULES = 10;

static const char *const MODE_WORDS[] = {"off", "on", "auto", "heat", "cool", "dry", "fan", "keep"};
static const char *const MODE_LABELS[] = {"Off", "On", "Auto", "Heat", "Cool", "Dry", "Fan only", "Keep"};
static const char *const DAY_LABELS[] = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"};

struct Rule {
	uint8_t days;    // bit 0 = Monday … bit 6 = Sunday
	int16_t minute;  // minute of the day
	float temp;      // NAN = unchanged
	int8_t mode;     // Mode
	int8_t fan;      // index of the fan speed select, -1 = unchanged
	int8_t v;        // 1–5, 0 = unchanged
	int8_t h;        // 1–5, 0 = unchanged
};

// The parsed rules of the device (not an ESPHome global, because its type would be declared
// before this header is included)
inline std::vector<Rule> &rules() {
	static std::vector<Rule> r;
	return r;
}

inline std::string lower(std::string s) {
	for (auto &c : s)
		c = (char) std::tolower((unsigned char) c);
	return s;
}

// Monday = 0 from ESPTime::day_of_week (1 = Sunday … 7 = Saturday)
inline int weekday(int day_of_week) { return (day_of_week + 5) % 7; }

inline std::vector<std::string> split(const std::string &s, char sep) {
	std::vector<std::string> out;
	std::string cur;
	for (char c : s) {
		if (c == sep) {
			out.push_back(cur);
			cur.clear();
		} else {
			cur += c;
		}
	}
	out.push_back(cur);
	return out;
}

inline std::vector<std::string> words(const std::string &s) {
	std::vector<std::string> out;
	std::string cur;
	for (char c : s) {
		if (std::isspace((unsigned char) c)) {
			if (!cur.empty())
				out.push_back(cur);
			cur.clear();
		} else {
			cur += c;
		}
	}
	if (!cur.empty())
		out.push_back(cur);
	return out;
}

inline bool parse_rule(const std::vector<std::string> &w, const std::vector<std::string> &fans, Rule &r,
		std::string &err) {
	r = Rule{0, 0, NAN, -1, -1, 0, 0};
	if (w.size() < 3) {
		err = "too short";
		return false;
	}
	// days
	if (w[0].size() != 7) {
		err = "days need 7 characters";
		return false;
	}
	for (int i = 0; i < 7; i++) {
		char c = w[0][i];
		if (c == 'x' || c == 'X')
			r.days |= 1 << i;
		else if (c != '_') {
			err = "days: only x and _";
			return false;
		}
	}
	// time
	int hh, mm;
	char rest;
	if (std::sscanf(w[1].c_str(), "%d:%d%c", &hh, &mm, &rest) != 2 || hh < 0 || hh > 23 || mm < 0 || mm > 59 ||
			w[1].find(':') + 3 != w[1].size()) {
		err = "bad time '" + w[1] + "'";
		return false;
	}
	r.minute = hh * 60 + mm;
	size_t i = 2;
	// temperature
	std::string t = w[i];
	for (auto &c : t)
		if (c == ',')
			c = '.';
	char *end = nullptr;
	float temp = std::strtof(t.c_str(), &end);
	if (!t.empty() && end && *end == '\0') {
		if (std::isnan(temp) || temp < 10 || temp > 35) {
			err = "temperature out of range '" + w[i] + "'";
			return false;
		}
		r.temp = temp;
		i++;
	}
	// mode
	if (i >= w.size()) {
		err = "mode missing";
		return false;
	}
	std::string m = lower(w[i]);
	for (int k = 0; k < MODE_COUNT; k++)
		if (m == MODE_WORDS[k])
			r.mode = k;
	if (r.mode < 0) {
		err = "unknown mode '" + w[i] + "'";
		return false;
	}
	i++;
	if (r.mode == SCH_OFF)
		return true;  // nothing after "off" counts
	// fan and vanes
	bool first = true;
	for (; i < w.size(); i++, first = false) {
		std::string x = lower(w[i]);
		if (x.size() == 2 && (x[0] == 'v' || x[0] == 'h') && x[1] >= '1' && x[1] <= '5') {
			(x[0] == 'v' ? r.v : r.h) = x[1] - '0';
			continue;
		}
		if (first) {
			for (size_t k = 0; k < fans.size(); k++)
				if (x == fans[k])
					r.fan = (int8_t) k;
			if (r.fan >= 0)
				continue;
			err = "unknown fan '" + w[i] + "'";
			return false;
		}
		err = "unknown part '" + w[i] + "'";
		return false;
	}
	return true;
}

// Parses the text. Invalid rules are skipped, error names the first one.
inline void parse(const std::string &text, const std::vector<std::string> &fans, std::vector<Rule> &rules,
		std::string &error) {
	rules.clear();
	error.clear();
	int n = 0;
	for (const auto &part : split(text, ';')) {
		auto w = words(part);
		if (w.empty())
			continue;
		n++;
		Rule r;
		std::string err;
		if (!parse_rule(w, fans, r, err)) {
			if (error.empty())
				error = "Rule " + std::to_string(n) + ": " + err;
		} else if (rules.size() >= (size_t) MAX_RULES) {
			if (error.empty())
				error = "Rule " + std::to_string(n) + ": more than " + std::to_string(MAX_RULES) + " rules";
		} else {
			rules.push_back(r);
		}
	}
}

// Packs the rules into store[2 * MAX_RULES] for the device's settings storage, which is small on
// the ESP8266 (512 bytes for everything); unused slots are 0.
//	word 0: bit 31 valid, days (7 bits), minute (11 bits), mode (3 bits), v (3 bits), h (3 bits)
//	word 1: temperature × 2 (8 bits, 0xFF = unchanged), fan index + 1 (8 bits, 0 = unchanged)
inline void pack(const std::vector<Rule> &rules, uint32_t *store) {
	for (int i = 0; i < MAX_RULES; i++) {
		if ((size_t) i >= rules.size()) {
			store[2 * i] = store[2 * i + 1] = 0;
			continue;
		}
		const Rule &r = rules[i];
		store[2 * i] = 0x80000000u | (uint32_t) (r.days & 0x7F) | ((uint32_t) (r.minute & 0x7FF) << 7) |
				((uint32_t) (r.mode & 0x7) << 18) | ((uint32_t) (r.v & 0x7) << 21) | ((uint32_t) (r.h & 0x7) << 24);
		const uint32_t temp = std::isnan(r.temp) ? 0xFF : (uint32_t) std::lround(r.temp * 2);
		store[2 * i + 1] = (temp & 0xFF) | ((uint32_t) ((r.fan + 1) & 0xFF) << 8);
	}
}

inline void unpack(const uint32_t *store, std::vector<Rule> &rules) {
	rules.clear();
	for (int i = 0; i < MAX_RULES; i++) {
		const uint32_t a = store[2 * i], b = store[2 * i + 1];
		if (!(a & 0x80000000u))
			continue;
		Rule r;
		r.days = a & 0x7F;
		r.minute = (a >> 7) & 0x7FF;
		r.mode = (a >> 18) & 0x7;
		r.v = (a >> 21) & 0x7;
		r.h = (a >> 24) & 0x7;
		r.temp = (b & 0xFF) == 0xFF ? NAN : (b & 0xFF) / 2.0f;
		r.fan = (int8_t) (((b >> 8) & 0xFF) - 1);
		rules.push_back(r);
	}
}

// Writes the rules back as text in the input format, e.g. "xxxxx__ 6:30 22 heat auto v3"
inline std::string format(const std::vector<Rule> &rules, const std::vector<std::string> &fans) {
	std::string out;
	for (const auto &r : rules) {
		if (!out.empty())
			out += "; ";
		for (int d = 0; d < 7; d++)
			out += (r.days & (1 << d)) ? 'x' : '_';
		char buf[24];
		std::snprintf(buf, sizeof(buf), " %d:%02d", r.minute / 60, r.minute % 60);
		out += buf;
		if (!std::isnan(r.temp)) {
			std::snprintf(buf, sizeof(buf), " %g", r.temp);
			out += buf;
		}
		out += " ";
		out += MODE_WORDS[r.mode];
		if (r.mode == SCH_OFF)
			continue;
		if (r.fan >= 0 && (size_t) r.fan < fans.size())
			out += " " + fans[r.fan];
		if (r.v > 0)
			out += " v" + std::to_string(r.v);
		if (r.h > 0)
			out += " h" + std::to_string(r.h);
	}
	return out;
}

// Last rule switching on this weekday at this minute, otherwise nullptr
inline const Rule *match(const std::vector<Rule> &rules, int wd, int minute) {
	const Rule *found = nullptr;
	for (const auto &r : rules)
		if ((r.days & (1 << wd)) && r.minute == minute)
			found = &r;
	return found;
}

// Minutes until the next switching point after the current minute, -1 = none
inline int minutes_to_next(const std::vector<Rule> &rules, int wd, int minute, const Rule **next) {
	int best = -1;
	for (int d = 0; d <= 7; d++) {
		int day = (wd + d) % 7;
		for (const auto &r : rules) {
			if (!(r.days & (1 << day)) || (d == 0 && r.minute <= minute) || (d == 7 && r.minute > minute))
				continue;
			int delta = d * 1440 + r.minute - minute;
			if (best < 0 || delta <= best) {
				best = delta;
				if (next)
					*next = &r;
			}
		}
		if (best >= 0)
			break;
	}
	return best;
}

// Short text without device names, e.g. "Mon 06:30 Heat 22"
inline std::string describe(const Rule &r, int day) {
	char buf[40];
	int len = std::snprintf(buf, sizeof(buf), "%s %02d:%02d %s", DAY_LABELS[day], r.minute / 60, r.minute % 60,
			MODE_LABELS[r.mode]);
	if (r.mode != SCH_OFF && !std::isnan(r.temp))
		std::snprintf(buf + len, sizeof(buf) - len, " %g", r.temp);
	return buf;
}

// Detailed text with the names from the device's web interface. The device configuration sets
// describer(); until then describe() is used.
inline std::function<std::string(const Rule &, int)> &describer() {
	static std::function<std::string(const Rule &, int)> f;
	return f;
}

inline std::string text(const Rule &r, int day) { return describer() ? describer()(r, day) : describe(r, day); }

// Takes over a target temperature from a switching point, e.g. the setpoint guidance
// (setpoint-guidance.yaml), which uses it as comfort temperature. Returns true if that handled it.
inline std::function<bool(float)> &temperature_hook() {
	static std::function<bool(float)> f;
	return f;
}

inline bool hooked(float temp) { return temperature_hook() && temperature_hook()(temp); }

}  // namespace schedule
