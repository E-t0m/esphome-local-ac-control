#!/usr/bin/env python3
"""Small web page to operate several air conditioners at once: on/off and setpoint.

Runs on a Linux computer in the home network and talks to the devices through their web
interface (REST and event stream). The passwords stay on this computer; the browser only
talks to this server.

Needs PyYAML (Debian/Ubuntu: sudo apt install python3-yaml; the ESPHome installation has it as
well). Run in the folder with secrets.yaml and ac-panel.yaml:
	python3 ac-panel.py
then open http://COMPUTER:8080 in the browser.

ac-panel.yaml (see ac-panel.example.yaml):
	port: 8080                      optional, default 8080
	panel_password: !secret ...     optional, password for this page (user "admin")
	devices:
	  - name: Klima TCL             shown on the page
	    host: klimatcl.local        host name or IP of the module
	    password: !secret tcl_web_pass
	    user: admin                 optional, default admin

Needs on each device the switch "Power" from schedule.yaml for on/off.
"""

import base64
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "ac-panel.yaml"
SECRETS = HERE / "secrets.yaml"


def load_config():
	"""Reads ac-panel.yaml; !secret NAME takes the value from secrets.yaml."""
	secrets = None

	def secret(loader, node):
		nonlocal secrets
		if secrets is None:
			secrets = yaml.safe_load(SECRETS.read_text(encoding="utf-8")) or {}
		name = loader.construct_scalar(node)
		if name not in secrets:
			sys.exit(f"secret {name} missing in {SECRETS.name}")
		return secrets[name]

	class Loader(yaml.SafeLoader):
		pass

	Loader.add_constructor("!secret", secret)
	return yaml.load(CONFIG.read_text(encoding="utf-8"), Loader=Loader)


class Device:
	"""One air conditioner: keeps an event stream open and caches climate and power state."""

	def __init__(self, cfg):
		self.name = str(cfg["name"])
		self.host = str(cfg["host"])
		self.base = f"http://{self.host}"
		user = str(cfg.get("user", "admin"))
		password = cfg.get("password")
		handlers = []
		if password is not None:
			mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
			mgr.add_password(None, self.base, user, str(password))
			handlers = [urllib.request.HTTPDigestAuthHandler(mgr), urllib.request.HTTPBasicAuthHandler(mgr)]
		self.opener = urllib.request.build_opener(*handlers)
		self.lock = threading.Lock()
		self.online = False
		self.climate = None  # REST path, e.g. "climate/Climate"
		self.power = None  # REST path of the switch "Power"
		self.state = {}
		threading.Thread(target=self.listen, daemon=True).start()

	def path(self, key):
		# "climate/Klima Climate" (new format) -> URL path; legacy ids "climate-…" are not used
		return "/".join(urllib.parse.quote(p, safe="") for p in key.split("/"))

	def handle(self, d):
		key = d.get("name_id") or d.get("id") or ""
		if "/" not in key:
			return
		domain = key.split("/", 1)[0]
		with self.lock:
			if domain == "climate" and (self.climate is None or self.climate == self.path(key)):
				self.climate = self.path(key)
				s = self.state
				for k in ("mode", "action", "target_temperature", "current_temperature", "step", "min_temp", "max_temp"):
					if k in d:
						s[k] = d[k]
			elif domain == "switch" and key.split("/")[-1] == "Power":
				self.power = self.path(key)
				self.state["power"] = d.get("value") is True or d.get("state") == "ON"

	def listen(self):
		last = None  # last error, logged only when it changes
		while True:
			try:
				with self.opener.open(f"{self.base}/events", timeout=60) as r:
					event = None
					data = []
					for raw in r:
						line = raw.decode("utf-8", "replace").rstrip("\r\n")
						if line.startswith("event:"):
							event = line[6:].strip()
						elif line.startswith("data:"):
							data.append(line[5:].strip())
						elif line == "":
							if last is not None:
								print(f"{self.name}: connected", file=sys.stderr, flush=True)
								last = None
							if event == "ping":
								self.online = True
							elif event == "state" and data:
								self.online = True
								try:
									self.handle(json.loads("\n".join(data)))
								except ValueError:
									pass
							event = None
							data = []
			except Exception as e:
				if str(e) != last:
					print(f"{self.name}: {e}", file=sys.stderr, flush=True)
				last = str(e)
			else:
				last = None
			self.online = False
			time.sleep(10)

	def post(self, path, query=""):
		url = f"{self.base}/{path}" + (f"?{query}" if query else "")
		req = urllib.request.Request(url, data=b"", method="POST")
		with self.opener.open(req, timeout=10) as r:
			r.read()

	def set_power(self, on):
		if not self.power:
			raise RuntimeError("no switch Power")
		self.post(f"{self.power}/{'turn_on' if on else 'turn_off'}")

	def set_temp(self, value):
		if not self.climate:
			raise RuntimeError("no climate entity")
		self.post(f"{self.climate}/set", urllib.parse.urlencode({"target_temperature": f"{value:g}"}))

	def snapshot(self):
		with self.lock:
			s = dict(self.state)
		s.update(name=self.name, online=self.online, has_power=self.power is not None)
		return s


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Air conditioners</title>
<style>
:root { --bg: #f4f4f4; --card: #fff; --fg: #222; --dim: #777; --on: #039be5; --line: #ddd; }
@media (prefers-color-scheme: dark) {
	:root { --bg: #1b1b1f; --card: #26262b; --fg: #eee; --dim: #999; --on: #29b6f6; --line: #3a3a40; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; background: var(--bg); color: var(--fg); font: 16px system-ui, sans-serif; }
main { max-width: 520px; margin: 0 auto; display: grid; gap: 12px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px;
	display: grid; grid-template-columns: 1fr auto; gap: 10px 12px; align-items: center; }
.card.offline { opacity: 0.5; }
.name { font-weight: 600; font-size: 1.1em; }
.info { color: var(--dim); font-size: 0.9em; grid-column: 1; }
.power { width: 52px; height: 52px; border-radius: 50%; border: 2px solid var(--line); background: none;
	color: var(--dim); cursor: pointer; grid-row: 1 / span 2; grid-column: 2; }
.power svg { width: 28px; height: 28px; display: block; margin: auto; }
.power.on { border-color: var(--on); color: var(--on); }
.temp { grid-column: 1 / span 2; display: flex; align-items: center; justify-content: center; gap: 16px; }
.temp button { width: 48px; height: 48px; border-radius: 50%; border: 1px solid var(--line); background: none;
	color: var(--fg); font-size: 1.6em; cursor: pointer; }
.temp .value { font-size: 2em; min-width: 4.5em; text-align: center; font-variant-numeric: tabular-nums; }
button:disabled { opacity: 0.4; cursor: default; }
</style>
</head>
<body>
<main id="list"></main>
<script>
const POWER_ICON = '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M16.56,5.44L15.11,6.89C16.84,7.94 18,9.83 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12C6,9.83 7.16,7.94 8.88,6.88L7.44,5.44C5.36,6.88 4,9.28 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,9.28 18.64,6.88 16.56,5.44M13,3H11V13H13"/></svg>';
let devices = [];
// setpoint changed on the page, sent after a short pause so that several clicks make one request
const pending = {};

function num(v) {
	const n = parseFloat(v);
	return isNaN(n) ? null : n;
}

function render() {
	const list = document.getElementById("list");
	devices.forEach((d, i) => {
		let card = document.getElementById("dev" + i);
		if (!card) {
			card = document.createElement("section");
			card.id = "dev" + i;
			card.className = "card";
			card.innerHTML = `<div class="name"></div><button class="power" title="On / off">${POWER_ICON}</button>
				<div class="info"></div>
				<div class="temp"><button class="down">&minus;</button><span class="value"></span><button class="up">+</button></div>`;
			card.querySelector(".power").onclick = () => power(i);
			card.querySelector(".down").onclick = () => step(i, -1);
			card.querySelector(".up").onclick = () => step(i, 1);
			list.appendChild(card);
		}
		const on = d.power === true;
		card.classList.toggle("offline", !d.online);
		card.querySelector(".name").textContent = d.name;
		const room = num(d.current_temperature);
		const mode = d.mode ? d.mode.replace("_", " ").toLowerCase() : "";
		card.querySelector(".info").textContent = !d.online ? "no connection"
			: [room !== null ? `room ${room} °C` : "", on ? mode : "off"].filter(x => x).join(" · ");
		const pb = card.querySelector(".power");
		pb.classList.toggle("on", on);
		pb.disabled = !d.online || !d.has_power;
		const target = pending[i] !== undefined ? pending[i].value : num(d.target_temperature);
		card.querySelector(".value").textContent = target !== null ? `${target} °C` : "–";
		card.querySelectorAll(".temp button").forEach(b => b.disabled = !d.online || target === null);
	});
}

async function load() {
	try {
		const r = await fetch("api/state", { cache: "no-store" });
		devices = await r.json();
	} catch (e) {
		devices = devices.map(d => Object.assign({}, d, { online: false }));
	}
	render();
}

async function send(path) {
	try {
		const r = await fetch(path, { method: "POST" });
		if (!r.ok) console.error(await r.text());
	} catch (e) {
		console.error(e);
	}
	setTimeout(load, 700);
}

function power(i) {
	send(`api/${i}/power?on=${devices[i].power ? 0 : 1}`);
}

function step(i, dir) {
	const d = devices[i];
	const s = num(d.step) || 0.5;
	const cur = pending[i] !== undefined ? pending[i].value : num(d.target_temperature);
	if (cur === null) return;
	let v = Math.round((cur + dir * s) / s) * s;
	const lo = num(d.min_temp), hi = num(d.max_temp);
	if (lo !== null) v = Math.max(lo, v);
	if (hi !== null) v = Math.min(hi, v);
	v = Math.round(v * 10) / 10;
	if (pending[i]) clearTimeout(pending[i].timer);
	pending[i] = {
		value: v,
		timer: setTimeout(() => {
			delete pending[i];
			send(`api/${i}/temp?value=${v}`);
		}, 800),
	};
	render();
}

load();
setInterval(load, 3000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
	devices = []
	password = None

	def log_message(self, fmt, *args):
		pass

	def authorized(self):
		if self.password is None:
			return True
		expected = "Basic " + base64.b64encode(f"admin:{self.password}".encode()).decode()
		if self.headers.get("Authorization") == expected:
			return True
		self.send_response(401)
		self.send_header("WWW-Authenticate", 'Basic realm="Air conditioners"')
		self.end_headers()
		return False

	def reply(self, code, body, ctype="text/plain; charset=utf-8"):
		data = body.encode() if isinstance(body, str) else body
		self.send_response(code)
		self.send_header("Content-Type", ctype)
		self.send_header("Content-Length", str(len(data)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(data)

	def do_GET(self):
		if not self.authorized():
			return
		url = urllib.parse.urlparse(self.path)
		if url.path == "/":
			self.reply(200, PAGE, "text/html; charset=utf-8")
		elif url.path == "/api/state":
			self.reply(200, json.dumps([d.snapshot() for d in self.devices]), "application/json")
		else:
			self.reply(404, "not found")

	def do_POST(self):
		if not self.authorized():
			return
		url = urllib.parse.urlparse(self.path)
		q = urllib.parse.parse_qs(url.query)
		parts = url.path.strip("/").split("/")
		try:
			if len(parts) != 3 or parts[0] != "api":
				raise LookupError
			dev = self.devices[int(parts[1])]
			if parts[2] == "power":
				dev.set_power(q.get("on", ["1"])[0] == "1")
			elif parts[2] == "temp":
				dev.set_temp(float(q["value"][0]))
			else:
				raise LookupError
		except (LookupError, ValueError, KeyError):
			self.reply(404, "not found")
			return
		except Exception as e:
			self.reply(502, f"{dev.name}: {e}")
			return
		self.reply(200, "ok")


def main():
	if not CONFIG.exists():
		sys.exit(f"{CONFIG.name} missing, see ac-panel.example.yaml")
	cfg = load_config()
	Handler.devices = [Device(d) for d in cfg["devices"]]
	pw = cfg.get("panel_password")
	Handler.password = str(pw) if pw is not None else None
	port = int(cfg.get("port", 8080))
	server = ThreadingHTTPServer(("", port), Handler)
	print(f"Panel on port {port} for {', '.join(d.name for d in Handler.devices)}", flush=True)
	server.serve_forever()


if __name__ == "__main__":
	main()
