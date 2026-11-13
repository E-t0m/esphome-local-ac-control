#!/usr/bin/env python3
"""tcl_probe – investigate TCL air conditioners through the UART of the Wi-Fi module socket.

Protocol (ESPHome component tclac, project AC-hack):
	9600 baud, 8E1 (some units 8N1), 5 V levels
	Frame:    0xBB <response flag> <request flag> <command> <length> <payload …> <checksum>
	          module → unit: BB 00 01 …   unit → module: BB 01 00 …
	Total length = byte[4] + 6
	Checksum     = XOR of all bytes except the last one
	Poll:     BB 00 01 04 02 01 00 BD          (8 bytes)
	Control:  BB 00 01 03 20 03 01 …           (38 bytes, sets the complete state)
	Status:   byte[4] = 0x37 / 0x3B / 0x3E     (61 / 65 / 68 bytes)

Connection:
	-p PORT   directly through a USB UART adapter on the Wi-Fi connector of the board
	--url URL through the installed ESPHome module with the package tcl-protocol.yaml:
	          reading through the log of the web interface (/events),
	          sending through the text field "Raw frame"

Subcommands:
	sniff     read passively (one or more ports), decode frames
	poll      query the status once
	watch     poll cyclically and show changed bytes bit by bit
	set       change the state (reads the current state first)
	raw       send an arbitrary frame
	scan      try baud rates and protocols (tclac, Tuya) (only -p)
	simulate  virtual indoor unit on a pseudo terminal
"""

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
	import serial
except ImportError:
	serial = None

HEADER = 0xBB
STATUS_LENGTHS = {0x37: 61, 0x3B: 65, 0x3E: 68}
POLL_FRAME = bytes([0xBB, 0x00, 0x01, 0x04, 0x02, 0x01, 0x00, 0xBD])
MAX_FRAME = 255

# byte positions in the status frame (frame offset = payload offset + 5),
# after tclac and AC-hack (github.com/adaasch/AC-hack)
KNOWN_RX = {
	0: "header", 1: "response flag", 2: "request flag", 3: "command", 4: "length",
	5: "id 04",
	7: "power/mode/display/eco/turbo", 8: "fan/target temp", 9: "half degree/timer/comfort",
	10: "swing", 11: "off timer h", 12: "off timer min", 13: "on timer h", 14: "on timer min",
	15: "acknowledge request", 17: "room temp H", 18: "room temp L / selects byte 30",
	19: "sleep", 30: "outlet temp (or second value, see byte 18 bit 5)", 33: "quiet (tclac)",
	34: "indoor unit active", 38: "mute (AC-hack)", 39: "compressor frequency Hz",
	51: "vertical vane", 52: "horizontal vane",
}

# command byte (frame[3])
COMMANDS = {0x03: "set", 0x04: "get", 0x05: "display", 0x06: "ack", 0x09: "diag", 0x0A: "diag/energy",
	0x0B: "time"}

MODE_RX = {0x05: "auto", 0x01: "cool", 0x03: "dry", 0x02: "fan", 0x04: "heat"}
MODE_TX = {"heat": 0x01, "dry": 0x02, "cool": 0x03, "fan": 0x07, "auto": 0x08}
MODE_TX_REV = {v: k for k, v in MODE_TX.items()}
MODE_RX_REV = {v: k for k, v in MODE_RX.items()}

FAN_RX = {0x80: "auto", 0x90: "low", 0xC0: "middle", 0xA0: "medium", 0xD0: "high", 0xB0: "focus"}
FAN_RX_REV = {v: k for k, v in FAN_RX.items()}
# (byte 8, byte 10) in the control frame
FAN_TX = {
	"auto": (0x00, 0x00), "quiet": (0x80, 0x00), "low": (0x00, 0x01),
	"middle": (0x00, 0x06), "medium": (0x00, 0x03), "high": (0x00, 0x07),
	"focus": (0x00, 0x05), "diffuse": (0x40, 0x00),
}
FAN_TX_LOW_REV = {0x01: "low", 0x06: "middle", 0x03: "medium", 0x07: "high", 0x05: "focus"}

VSWING_MODE = {"updown": 0x08, "upper": 0x10, "lower": 0x18}
HSWING_MODE = {"leftright": 0x08, "left": 0x10, "center": 0x18, "right": 0x20}
VFIX = {"last": 0, "maxup": 1, "up": 2, "center": 3, "down": 4, "maxdown": 5}
HFIX = {"last": 0, "maxleft": 1, "left": 2, "center": 3, "right": 4, "maxright": 5}


# ---------------------------------------------------------------- frames

def checksum(frame):
	crc = 0
	for b in frame[:-1]:
		crc ^= b
	return crc


def with_checksum(frame):
	frame = bytearray(frame)
	frame[-1] = checksum(frame)
	return bytes(frame)


def hexs(data):
	return " ".join(f"{b:02X}" for b in data)


class FrameParser:
	"""Splits a byte stream into frames. Resynchronises byte by byte on errors."""

	def __init__(self):
		self.buf = bytearray()

	def feed(self, data):
		self.buf.extend(data)
		out = []
		while True:
			start = self.buf.find(bytes([HEADER]))
			if start < 0:
				if self.buf:
					out.append(("junk", bytes(self.buf)))
				self.buf.clear()
				break
			if start > 0:
				out.append(("junk", bytes(self.buf[:start])))
				del self.buf[:start]
			if len(self.buf) < 5:
				break
			total = self.buf[4] + 6
			if total > MAX_FRAME or total < 6:
				out.append(("junk", bytes(self.buf[:1])))
				del self.buf[:1]
				continue
			if len(self.buf) < total:
				break
			frame = bytes(self.buf[:total])
			if checksum(frame) == frame[-1]:
				out.append(("frame", frame))
				del self.buf[:total]
			else:
				out.append(("badsum", frame))
				del self.buf[:1]
		return out

	def flush(self):
		rest = bytes(self.buf)
		self.buf.clear()
		return [("junk", rest)] if rest else []


# ---------------------------------------------------------------- decoding

def frame_kind(frame):
	if frame == POLL_FRAME:
		return "poll"
	if len(frame) == 38 and frame[3] == 0x03 and frame[4] == 0x20:
		return "control"
	if frame[3] == 0x04 and frame[4] in STATUS_LENGTHS and len(frame) == STATUS_LENGTHS[frame[4]]:
		return "status"
	direction = {(0x00, 0x01): "module→unit", (0x01, 0x00): "unit→module"}.get((frame[1], frame[2]), "?")
	name = COMMANDS.get(frame[3], "unknown")
	return f"command {frame[3]:02X} ({name}, {direction})"


def decode_status(rx):
	raw_t = (rx[17] << 8) | rx[18]
	d = {
		"power": bool(rx[7] & 0x10),
		"mode": MODE_RX.get(rx[7] & 0x0F, "–" if rx[7] & 0x0F == 0 else f"?{rx[7] & 0x0F:#x}"),
		"target": (rx[8] & 0x0F) + 16,
		"current": round((raw_t / 374.0 - 32.0) / 1.8, 2),
		"display": bool(rx[7] & 0x20),
		"eco": bool(rx[7] & 0x40),
		"comfort": bool(rx[9] & 0x04),
		"sleep": bool(rx[19] & 0x01),
		"swing_v": bool(rx[10] & 0x40),
		"swing_h": bool(rx[10] & 0x20),
		"outlet": round((rx[30] * 4 - 200) / 10, 1),
	}
	if rx[33] & 0x80:
		d["fan"] = "quiet"
	elif rx[7] & 0x80:
		d["fan"] = "diffuse"
	else:
		d["fan"] = FAN_RX.get(rx[8] & 0xF0, f"?{rx[8] & 0xF0:#x}")
	return d


def decode_control(tx):
	low = tx[10] & 0x07
	if tx[8] & 0x80:
		fan = "quiet"
	elif tx[8] & 0x40:
		fan = "diffuse"
	else:
		fan = FAN_TX_LOW_REV.get(low, "auto")
	return {
		"power": bool(tx[7] & 0x04),
		"mode": MODE_TX_REV.get(tx[8] & 0x0F, f"?{tx[8] & 0x0F:#x}"),
		"target": 31 - (tx[9] & 0x1F),
		"fan": fan,
		"eco": bool(tx[7] & 0x80),
		"display": bool(tx[7] & 0x40),
		"beep": bool(tx[7] & 0x20),
		"comfort": bool(tx[8] & 0x10),
		"sleep": bool(tx[19] & 0x01),
		"swing_v": bool(tx[10] & 0x38),
		"swing_h": bool(tx[11] & 0x08),
		"byte32": f"{tx[32]:08b}",
		"byte33": f"{tx[33]:08b}",
	}


def decode(frame):
	kind = frame_kind(frame)
	if kind == "status":
		return kind, decode_status(frame)
	if kind == "control":
		return kind, decode_control(frame)
	return kind, None


def fmt_state(d):
	if not d:
		return ""
	parts = []
	for k, v in d.items():
		if isinstance(v, bool):
			parts.append(f"{k}={'on' if v else 'off'}")
		else:
			parts.append(f"{k}={v}")
	return " ".join(parts)


# ---------------------------------------------------------------- control frame

def build_control(s):
	tx = bytearray(38)
	tx[0:7] = bytes([0xBB, 0x00, 0x01, 0x03, 0x20, 0x03, 0x01])
	tx[13] = 0x01
	power = s["power"]
	if s.get("beep"):
		tx[7] |= 0x20
	if s.get("display", True) and power:
		tx[7] |= 0x40
	if power:
		tx[7] |= 0x04
		tx[8] |= MODE_TX[s["mode"]]
	if s.get("eco"):
		tx[7] |= 0x80
	if s.get("comfort"):
		tx[8] |= 0x10
	b8, b10 = FAN_TX[s.get("fan", "auto")]
	tx[8] |= b8
	tx[10] |= b10
	if s.get("swing_v"):
		tx[10] |= 0x38
	if s.get("swing_h"):
		tx[11] |= 0x08
	temp = int(s["target"])
	if not 16 <= temp <= 31:
		raise ValueError("target temperature must be between 16 and 31 °C")
	tx[9] = 31 - temp
	if s.get("sleep"):
		tx[19] |= 0x01
	tx[32] = VSWING_MODE[s.get("vswing", "updown")] | VFIX[s.get("vfix", "last")]
	tx[33] = HSWING_MODE[s.get("hswing", "leftright")] | HFIX[s.get("hfix", "last")]
	return with_checksum(tx)


# ---------------------------------------------------------------- input/output

class Logger:
	def __init__(self, path):
		self.fh = open(path, "a", encoding="utf-8") if path else None
		self.lock = threading.Lock()

	def write(self, src, kind, data, decoded=None):
		if not self.fh:
			return
		rec = {"t": round(time.time(), 3), "src": src, "kind": kind, "hex": hexs(data)}
		if decoded:
			rec["decoded"] = decoded
		with self.lock:
			self.fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
			self.fh.flush()


PARITY = "E"


def open_port(path, baud, parity=None):
	if serial is None:
		sys.exit("pyserial missing: pip install pyserial")
	path = path.partition("=")[0]
	parity = parity or PARITY
	# pseudo terminals (simulator) have no parity
	if os.path.realpath(path).startswith("/dev/pts/"):
		parity = "N"
	return serial.Serial(path, baud, bytesize=8, parity=parity, stopbits=1, timeout=0.05)


def ts():
	t = time.time()
	return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"


def print_frame(label, kind, frame, decoded=None):
	tag = {"frame": "", "badsum": " BAD CHECKSUM", "junk": " JUNK"}[kind]
	print(f"{ts()} [{label}] {len(frame):3d} B{tag}: {hexs(frame)}")
	if kind == "frame":
		fkind, d = decode(frame)
		print(f"{'':12} → {fkind} {fmt_state(d)}")
	sys.stdout.flush()


class SerialLink:
	"""Direct connection through a USB UART adapter."""

	remote = False

	def __init__(self, path, baud):
		self.ser = open_port(path, baud)

	def send(self, data):
		self.ser.reset_input_buffer()
		self.ser.write(data)
		self.ser.flush()

	def frames(self, timeout):
		"""Yields (source, kind, bytes) until the timeout has expired."""
		parser = FrameParser()
		end = time.monotonic() + timeout
		while time.monotonic() < end:
			chunk = self.ser.read(256)
			for kind, data in parser.feed(chunk):
				yield "AC", kind, data
		for kind, data in parser.flush():
			yield "AC", kind, data


ANSI = re.compile(r"\x1b\[[0-9;]*m")
UART_LOG = re.compile(r"\[uart_debug:\d+\]: (<<<|>>>) ([0-9A-Fa-f]{2}(?: [0-9A-Fa-f]{2})*)")
RAW_ENTITY = "Raw%20frame"


class NetLink:
	"""Connection through the ESPHome module: log stream /events and text field "Raw frame"."""

	remote = True

	def __init__(self, url, user, password):
		self.base = url.rstrip("/")
		if "://" not in self.base:
			self.base = "http://" + self.base
		mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
		if password is not None:
			mgr.add_password(None, self.base, user, password)
		self.opener = urllib.request.build_opener(
			urllib.request.HTTPDigestAuthHandler(mgr), urllib.request.HTTPBasicAuthHandler(mgr))
		self.queue = queue.Queue()
		self.parsers = {"AC": FrameParser(), "Module": FrameParser()}
		self.connected = threading.Event()
		self.error = None
		threading.Thread(target=self._reader, daemon=True).start()
		if not self.connected.wait(15):
			sys.exit(f"No connection to {self.base}/events")
		if self.error:
			sys.exit(f"Connection to {self.base}/events failed: {self.error}")

	def _reader(self):
		first = True
		while True:
			try:
				resp = self.opener.open(self.base + "/events", timeout=120)
			except (urllib.error.URLError, OSError) as e:
				if first:
					self.error = e
					self.connected.set()
					return
				time.sleep(2)
				continue
			first = False
			self.connected.set()
			event = None
			try:
				for raw in resp:
					line = raw.decode("utf-8", "replace").rstrip("\r\n")
					if line.startswith("event:"):
						event = line[6:].strip()
					elif line.startswith("data:") and event == "log":
						self._log_line(line[5:].strip())
					elif not line:
						event = None
			except (OSError, ValueError):
				pass
			self.queue.put(("info", "Connection lost, reconnecting …", b""))
			time.sleep(1)

	def _log_line(self, msg):
		m = UART_LOG.search(ANSI.sub("", msg))
		if not m:
			return
		label = "AC" if m.group(1) == "<<<" else "Module"
		for kind, frame in self.parsers[label].feed(bytes.fromhex(m.group(2))):
			self.queue.put((label, kind, frame))

	def send(self, data):
		value = urllib.parse.quote(data.hex().upper())
		req = urllib.request.Request(f"{self.base}/text/{RAW_ENTITY}/set?value={value}", data=b"", method="POST")
		try:
			with self.opener.open(req, timeout=10) as resp:
				resp.read()
		except urllib.error.HTTPError as e:
			if e.code == 404:
				sys.exit('Text field "Raw frame" missing: include tcl-protocol.yaml and upload the firmware.')
			raise

	def frames(self, timeout):
		end = time.monotonic() + timeout
		while True:
			rest = end - time.monotonic()
			if rest <= 0:
				return
			try:
				item = self.queue.get(timeout=rest)
			except queue.Empty:
				return
			if item[0] == "info":
				print(f"{ts()} {item[1]}", flush=True)
				continue
			yield item


def make_link(args):
	if args.url:
		password = args.password if args.password is not None else os.environ.get("TCL_WEB_PASS")
		return NetLink(args.url, args.user, password)
	return SerialLink(args.port[0], args.baud)


def do_poll(link, log, timeout, quiet=False):
	link.send(POLL_FRAME)
	log.write("pc", "frame", POLL_FRAME, {"kind": "poll"})
	for label, kind, data in link.frames(timeout):
		fkind, d = decode(data) if kind == "frame" else (None, None)
		log.write(label.lower(), kind, data, d)
		if label != "AC":
			continue
		if not quiet and kind != "frame":
			print_frame("AC", kind, data)
		if fkind == "status":
			return data
	return None


# ---------------------------------------------------------------- subcommands

def cmd_sniff(args, log):
	if args.url:
		link = make_link(args)
		print(f"Reading through {link.base} – stop with Ctrl+C")
		try:
			while True:
				for label, kind, data in link.frames(3600):
					d = decode(data)[1] if kind == "frame" else None
					print_frame(label, kind, data)
					log.write(label, kind, data, d)
		except KeyboardInterrupt:
			print()
		return
	ports = []
	for spec in args.port:
		path, _, label = spec.partition("=")
		ports.append((open_port(path, args.baud), label or os.path.basename(path)))
	print(f"Reading on {', '.join(l for _, l in ports)} – stop with Ctrl+C")

	def reader(ser, label):
		parser = FrameParser()
		last = time.monotonic()
		while True:
			chunk = ser.read(256)
			now = time.monotonic()
			if not chunk:
				# after 100 ms of silence an unfinished rest counts as junk
				if parser.buf and now - last > 0.1:
					for kind, data in parser.flush():
						print_frame(label, kind, data)
						log.write(label, kind, data)
				continue
			last = now
			for kind, data in parser.feed(chunk):
				d = decode(data)[1] if kind == "frame" else None
				print_frame(label, kind, data)
				log.write(label, kind, data, d)

	threads = [threading.Thread(target=reader, args=p, daemon=True) for p in ports]
	for t in threads:
		t.start()
	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		print()


def cmd_poll(args, log):
	link = make_link(args)
	rx = do_poll(link, log, args.timeout)
	if rx is None:
		sys.exit("No status reply. Swap TX/RX, check levels and ground.")
	print(f"Status ({len(rx)} B): {hexs(rx)}")
	print(fmt_state(decode_status(rx)))
	if args.bytes:
		print_byte_table(rx)


def print_byte_table(rx):
	print("\nPos  Hex  Binary    Meaning")
	for i, b in enumerate(rx):
		meaning = KNOWN_RX.get(i, "checksum" if i == len(rx) - 1 else "")
		print(f"{i:3d}  {b:02X}   {b:08b}  {meaning}")


def cmd_watch(args, log):
	link = make_link(args)
	prev = None
	print(f"Polling every {args.interval} s – stop with Ctrl+C")
	print("Now use the remote control and watch which bytes change.\n")
	try:
		while True:
			rx = do_poll(link, log, args.timeout, quiet=True)
			if rx is None:
				print(f"{ts()} no reply")
			else:
				print(f"{ts()} {fmt_state(decode_status(rx))}")
				if prev is not None and len(prev) == len(rx):
					for i, (a, b) in enumerate(zip(prev, rx)):
						if a != b and i != len(rx) - 1:
							known = KNOWN_RX.get(i)
							tag = known if known else "UNKNOWN"
							print(f"{'':12} Byte {i:2d}: {a:02X} → {b:02X}   {a:08b} → {b:08b}   {tag}")
				elif prev is not None:
					print(f"{'':12} frame length changed: {len(prev)} → {len(rx)}")
				prev = rx
			time.sleep(args.interval)
	except KeyboardInterrupt:
		print()


def onoff(v):
	if v is None:
		return None
	if v.lower() in ("on", "1", "true", "yes"):
		return True
	if v.lower() in ("off", "0", "false", "no"):
		return False
	raise argparse.ArgumentTypeError(f"on/off expected, not {v!r}")


def cmd_set(args, log):
	link = make_link(args)
	rx = do_poll(link, log, args.timeout, quiet=True)
	if rx is None and not args.force:
		sys.exit("Current state not readable. With --force default values are assumed.")
	if rx is not None:
		state = decode_status(rx)
		print(f"Current: {fmt_state(state)}")
	else:
		state = {"power": False, "mode": "auto", "target": 24, "fan": "auto"}
	if state.get("mode", "").startswith("?") or state.get("mode") == "–":
		state["mode"] = "auto"
	if state.get("fan", "").startswith("?"):
		state["fan"] = "auto"

	for key in ("power", "eco", "sleep", "comfort", "display", "beep", "swing_v", "swing_h"):
		val = onoff(getattr(args, key))
		if val is not None:
			state[key] = val
	for key in ("mode", "fan", "vswing", "vfix", "hswing", "hfix"):
		val = getattr(args, key)
		if val is not None:
			state[key] = val
	if args.temp is not None:
		state["target"] = args.temp
	if args.mode is not None and args.power is None:
		state["power"] = True

	tx = build_control(state)
	print(f"Target:  {fmt_state(decode_control(tx))}")
	print(f"Frame:   {hexs(tx)}")
	if args.dry_run:
		return
	link.send(tx)
	log.write("pc", "frame", tx, {"kind": "control"})
	for _ in link.frames(args.settle):
		pass
	rx = do_poll(link, log, args.timeout, quiet=True)
	if rx is None:
		print("No status reply afterwards.")
	else:
		print(f"New:     {fmt_state(decode_status(rx))}")


def cmd_raw(args, log):
	data = bytes.fromhex(args.hex.replace(":", " "))
	if args.fix_checksum:
		data = with_checksum(data)
	elif checksum(data) != data[-1]:
		print(f"Warning: checksum does not match (expected {checksum(data):02X}). --fix-checksum sets it.")
	link = make_link(args)
	link.send(data)
	log.write("pc", "frame", data)
	print_frame("PC", "frame", data)
	for label, kind, frame in link.frames(args.wait):
		print_frame(label, kind, frame)
		log.write(label.lower(), kind, frame, decode(frame)[1] if kind == "frame" else None)


# ---------------------------------------------------------------- scan

def tuya_frame(cmd, data=b""):
	frame = bytes([0x55, 0xAA, 0x00, cmd, len(data) >> 8, len(data) & 0xFF]) + data
	return frame + bytes([sum(frame) & 0xFF])


SCAN_PROBES = [
	("tclac poll", POLL_FRAME),
	("Tuya heartbeat", tuya_frame(0x00)),
	("Tuya product info", tuya_frame(0x01)),
]


def classify(data):
	hits = []
	if b"\xBB\x00\x01" in data:
		hits.append("tclac frame (BB 00 01)")
	if b"\x55\xAA" in data:
		hits.append("Tuya frame (55 AA)")
	if b"\xAA" in data and not hits:
		hits.append("possibly Midea frame (AA)")
	return ", ".join(hits)


def cmd_scan(args, log):
	if serial is None:
		sys.exit("pyserial missing: pip install pyserial")
	bauds = [int(b) for b in args.bauds.split(",")]
	parities = [p.strip().upper() for p in args.parities.split(",")]
	found = False
	for parity in parities:
		for baud in bauds:
			ser = open_port(args.port[0], baud, parity)
			print(f"== {baud} baud 8{parity}1")
			ser.reset_input_buffer()
			steps = [("passive", None)] + SCAN_PROBES
			for name, frame in steps:
				if frame:
					ser.write(frame)
					ser.flush()
					log.write("pc", "frame", frame, {"probe": name, "baud": baud, "parity": parity})
				end = time.monotonic() + (args.listen if frame is None else args.wait)
				buf = bytearray()
				while time.monotonic() < end:
					buf.extend(ser.read(256))
				echo = bool(frame) and buf.startswith(frame)
				if echo:
					print(f"   {name:17} ECHO: own frame comes back (TX and RX connected?)")
					buf = buf[len(frame):]
				if buf:
					found = True
					tag = classify(buf)
					print(f"   {name:17} {len(buf):3d} B: {hexs(buf[:80])}{' …' if len(buf) > 80 else ''}")
					if tag:
						print(f"   {'':17} → {tag}")
					log.write("ac", "raw", bytes(buf), {"probe": name, "baud": baud, "parity": parity})
				elif not echo:
					print(f"   {name:17} –")
			ser.close()
	if not found:
		print("\nNo reply on any combination. Check the adapter with a loopback test (see docs/tcl-probe.md).")


# ---------------------------------------------------------------- simulator

class SimulatedUnit:
	def __init__(self, length):
		self.length = length
		self.lenbyte = {v: k for k, v in STATUS_LENGTHS.items()}[length]
		self.s = {"power": False, "mode": "cool", "target": 24, "fan": "auto",
			"eco": False, "display": True, "comfort": False, "sleep": False,
			"swing_v": False, "swing_h": False}
		self.room = 23.0
		self.counter = 0

	def status(self):
		s = self.s
		rx = bytearray(self.length)
		rx[0:5] = bytes([0xBB, 0x00, 0x01, 0x04, self.lenbyte])
		rx[7] = MODE_RX_REV[s["mode"]]
		if s["power"]:
			rx[7] |= 0x10
		if s["display"]:
			rx[7] |= 0x20
		if s["eco"]:
			rx[7] |= 0x40
		fan = s["fan"]
		rx[8] = (FAN_RX_REV.get(fan, 0x80)) | (s["target"] - 16)
		if fan == "diffuse":
			rx[7] |= 0x80
		if fan == "quiet":
			rx[33] |= 0x80
		if s["comfort"]:
			rx[9] |= 0x04
		if s["swing_v"]:
			rx[10] |= 0x40
		if s["swing_h"]:
			rx[10] |= 0x20
		if s["sleep"]:
			rx[19] |= 0x01
		raw_t = round((self.room * 1.8 + 32.0) * 374.0)
		rx[17], rx[18] = raw_t >> 8, raw_t & 0xFF
		# simulated unknown counter to try out "watch"
		rx[30] = self.counter & 0xFF
		return with_checksum(rx)

	def apply(self, tx):
		d = decode_control(tx)
		for k in ("power", "target", "fan", "eco", "display", "comfort", "sleep", "swing_v", "swing_h"):
			self.s[k] = d[k]
		if d["power"] and not d["mode"].startswith("?"):
			self.s["mode"] = d["mode"]

	def tick(self):
		self.counter += 1
		if self.s["power"]:
			step = 0.1 if self.room < self.s["target"] else -0.1
			self.room = round(self.room + step, 2)


def cmd_simulate(args, log):
	import pty
	import tty
	import select
	master, slave = pty.openpty()
	tty.setraw(slave)
	name = os.ttyname(slave)
	if args.link:
		try:
			os.unlink(args.link)
		except FileNotFoundError:
			pass
		os.symlink(name, args.link)
		name = f"{args.link} → {name}"
	print(f"Simulated indoor unit ({args.length} byte status) on {name}", flush=True)
	unit = SimulatedUnit(args.length)
	parser = FrameParser()
	last_tick = time.monotonic()
	try:
		while True:
			r, _, _ = select.select([master], [], [], 0.2)
			if time.monotonic() - last_tick > 1.0:
				unit.tick()
				last_tick = time.monotonic()
			if not r:
				continue
			data = os.read(master, 256)
			for kind, frame in parser.feed(data):
				if kind != "frame":
					print_frame("SIM←", kind, frame)
					continue
				fkind = frame_kind(frame)
				if fkind == "poll":
					time.sleep(0.15)
					os.write(master, unit.status())
				elif fkind == "control":
					unit.apply(frame)
					print(f"{ts()} [SIM] control frame applied: {fmt_state(unit.s)}", flush=True)
				else:
					print_frame("SIM←", kind, frame)
	except KeyboardInterrupt:
		print()
	finally:
		if args.link:
			try:
				os.unlink(args.link)
			except FileNotFoundError:
				pass


# ---------------------------------------------------------------- CLI

def main():
	ap = argparse.ArgumentParser(description="Investigate and control a TCL air conditioner through the UART")
	ap.add_argument("-p", "--port", action="append", default=[],
		help="serial port, several possible with sniff, optionally with label: /dev/ttyUSB0=AC")
	ap.add_argument("-b", "--baud", type=int, default=9600)
	ap.add_argument("--parity", choices=["E", "N", "O"], default="E",
		help="parity: E (even, default), N (none), O (odd)")
	ap.add_argument("--log", help="also write frames as JSON Lines to this file")
	ap.add_argument("--url", help="ESPHome module instead of an adapter, e.g. http://klimatcl.local")
	ap.add_argument("--user", default="admin", help="user of the web interface (default: admin)")
	ap.add_argument("--password", help="password of the web interface, alternatively environment variable TCL_WEB_PASS")
	sub = ap.add_subparsers(dest="cmd", required=True)

	sub.add_parser("sniff", help="read passively")

	p = sub.add_parser("poll", help="query the status once")
	p.add_argument("--timeout", type=float, help="wait for the reply (default: 1 s, with --url 6 s)")
	p.add_argument("--bytes", action="store_true", help="print every byte with its meaning")

	p = sub.add_parser("watch", help="poll cyclically, show changes")
	p.add_argument("-i", "--interval", type=float, default=2.0)
	p.add_argument("--timeout", type=float, help="wait for the reply (default: 1 s, with --url 6 s)")

	p = sub.add_parser("set", help="change the state")
	p.add_argument("--power", metavar="on|off")
	p.add_argument("--mode", choices=sorted(MODE_TX))
	p.add_argument("--temp", type=int, metavar="16-31")
	p.add_argument("--fan", choices=sorted(FAN_TX))
	p.add_argument("--eco", metavar="on|off")
	p.add_argument("--sleep", metavar="on|off")
	p.add_argument("--comfort", metavar="on|off")
	p.add_argument("--display", metavar="on|off",
		help="note: according to tclac, display off switches to auto mode")
	p.add_argument("--beep", metavar="on|off")
	p.add_argument("--swing-v", dest="swing_v", metavar="on|off")
	p.add_argument("--swing-h", dest="swing_h", metavar="on|off")
	p.add_argument("--vswing", choices=sorted(VSWING_MODE))
	p.add_argument("--vfix", choices=sorted(VFIX))
	p.add_argument("--hswing", choices=sorted(HSWING_MODE))
	p.add_argument("--hfix", choices=sorted(HFIX))
	p.add_argument("--dry-run", action="store_true", help="only show the frame, do not send")
	p.add_argument("--force", action="store_true", help="send even without a readable current state")
	p.add_argument("--settle", type=float, default=1.0, help="wait before the verification poll")
	p.add_argument("--timeout", type=float, help="wait for the reply (default: 1 s, with --url 6 s)")

	p = sub.add_parser("raw", help="send an arbitrary frame")
	p.add_argument("hex", help='e.g. "BB 00 01 04 02 01 00 BD"')
	p.add_argument("--fix-checksum", action="store_true")
	p.add_argument("--wait", type=float, help="wait for replies (default: 1 s, with --url 3 s)")

	p = sub.add_parser("scan", help="try baud rates and protocols")
	p.add_argument("--bauds", default="9600,4800,19200,38400,57600,115200,2400")
	p.add_argument("--parities", default="E,N", help="parities to try, e.g. E,N")
	p.add_argument("--listen", type=float, default=2.0, help="passive listening time per baud rate")
	p.add_argument("--wait", type=float, default=1.0, help="wait after each probe")

	p = sub.add_parser("simulate", help="virtual indoor unit on a pseudo terminal")
	p.add_argument("--length", type=int, choices=sorted(STATUS_LENGTHS.values()), default=61)
	p.add_argument("--link", help="create a symlink to the pseudo terminal, e.g. /tmp/ttyTCL")

	args = ap.parse_args()
	global PARITY
	PARITY = args.parity
	if args.url and args.port:
		ap.error("either -p/--port or --url")
	if args.url and args.cmd in ("scan", "simulate"):
		ap.error(f"{args.cmd} only works with -p/--port")
	if args.cmd != "simulate" and not args.port and not args.url:
		ap.error("-p/--port or --url missing")
	if args.cmd in ("poll", "watch", "set", "raw", "scan") and len(args.port) > 1:
		ap.error(f"{args.cmd} uses exactly one port")
	if getattr(args, "timeout", 0) is None:
		args.timeout = 6.0 if args.url else 1.0
	if getattr(args, "wait", 0) is None:
		args.wait = 3.0 if args.url else 1.0
	log = Logger(args.log)
	{
		"sniff": cmd_sniff, "poll": cmd_poll, "watch": cmd_watch,
		"set": cmd_set, "raw": cmd_raw, "scan": cmd_scan, "simulate": cmd_simulate,
	}[args.cmd](args, log)


if __name__ == "__main__":
	try:
		main()
	except BrokenPipeError:
		sys.stderr.close()
	except KeyboardInterrupt:
		print()
