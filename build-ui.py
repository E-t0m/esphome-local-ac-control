#!/usr/bin/env python3
"""Builds esphome-ui.js: the web interface (version 3) of the installed ESPHome version with all
required icons and ui-extras.js, to be embedded with js_include. The interface then needs no
internet access at runtime.

Run with the Python of the ESPHome installation, in the folder with the device configurations:
	~/venv/esphome/bin/python build-ui.py klima-tcl.yaml klima-bosch.yaml

Steps:
	1. generates the C++ code for each configuration (esphome compile --only-generate)
	2. collects all icon names (mdi:…) from it and from the interface
	3. downloads the icons once from the Iconify set "mdi" (cached in .mdi.json)
	4. writes esphome-ui.js

Run again after every ESPHome update and after adding icons to a configuration,
then compile and upload the devices.
"""

import glob
import gzip
import json
import os
import re
import subprocess
import sys
import urllib.request

import esphome
from esphome.const import __version__

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "esphome-ui.js")
CACHE = os.path.join(HERE, ".mdi.json")
LOG = os.path.join(HERE, "build-ui.log")
EXTRAS = os.path.join(HERE, "ui-extras.js")
MDI_URL = "https://raw.githubusercontent.com/iconify/icon-sets/master/json/mdi.json"
# icons used by the interface itself, including composed names
UI_ICONS = {"circle", "circle-off-outline", "theme-light-dark",
	"checkbox-marked-circle", "checkbox-blank-circle-outline", "text-box-outline", "power"}
# names ending with a hyphen are beginnings of composed names and are dropped
ICON_RE = re.compile(r"mdi:([a-z0-9][a-z0-9-]*)")


def ui_script():
	header = os.path.join(os.path.dirname(esphome.__file__), "components", "web_server", "server_index_v3.h")
	src = open(header, encoding="utf-8").read()
	arrays = re.findall(r"\{([0-9xA-Fa-f,\s]+)\}", src)
	if not arrays:
		sys.exit(f"No embedded interface found in {header}")
	data = bytes(int(x, 0) for x in max(arrays, key=len).split(",") if x.strip())
	html = gzip.decompress(data).decode("utf-8")
	m = re.search(r"<script type=module[^>]*>(.*?)</script>", html, re.S)
	if not m:
		sys.exit("Script part of the interface not found")
	return m.group(1)


def device_icons(configs):
	# js_include must exist for the configuration check
	if not os.path.exists(OUT):
		with open(OUT, "w", encoding="utf-8") as f:
			f.write("// placeholder, replaced by build-ui.py\n")
	icons = set()
	for cfg in configs:
		print(f"Generating code for {cfg} …", flush=True)
		r = subprocess.run([sys.executable, "-m", "esphome", "compile", "--only-generate", cfg],
			cwd=HERE, capture_output=True, text=True)
		if r.returncode != 0:
			# complete output into the log file, only the error lines on screen
			with open(LOG, "w", encoding="utf-8") as f:
				f.write(r.stdout + r.stderr)
			lines = (r.stdout + r.stderr).splitlines()
			marks = ("ERROR", "error:", "invalid", "Couldn't", "Unable", "required", "not found", "Failed")
			hits = [i for i, l in enumerate(lines) if any(m in l for m in marks)]
			shown = sorted({k for i in hits for k in range(max(0, i - 3), min(len(lines), i + 4))})
			text = "\n".join(lines[k] for k in shown) or "\n".join(lines[-40:])
			sys.exit(f"{cfg}: code generation failed, complete output in {LOG}\n{text}")
	for main in glob.glob(os.path.join(HERE, ".esphome", "build", "*", "src", "main.cpp")):
		icons |= set(ICON_RE.findall(open(main, encoding="utf-8").read()))
	return icons


def mdi_set():
	if not os.path.exists(CACHE):
		print(f"Downloading icon set {MDI_URL} …", flush=True)
		with urllib.request.urlopen(MDI_URL, timeout=60) as r, open(CACHE, "wb") as f:
			f.write(r.read())
	return json.load(open(CACHE, encoding="utf-8"))


def preload(names, mdi):
	icons, aliases, missing = {}, {}, []
	for n in sorted(names):
		if n in mdi["icons"]:
			icons[n] = mdi["icons"][n]
		elif n in mdi.get("aliases", {}):
			alias = mdi["aliases"][n]
			aliases[n] = alias
			parent = alias.get("parent")
			if parent in mdi["icons"]:
				icons[parent] = mdi["icons"][parent]
		else:
			missing.append(n)
	data = {"prefix": "mdi", "icons": icons, "width": mdi.get("width", 24), "height": mdi.get("height", 24)}
	if aliases:
		data["aliases"] = aliases
	return data, missing


def main():
	configs = sys.argv[1:]
	if not configs:
		sys.exit(__doc__)
	if not os.path.exists(EXTRAS):
		sys.exit(f"{EXTRAS} is missing, it belongs next to build-ui.py")
	extras = open(EXTRAS, encoding="utf-8").read()
	ui = ui_script()
	names = UI_ICONS | set(ICON_RE.findall(ui)) | device_icons(configs)
	names = {n for n in names if not n.endswith("-")}
	data, missing = preload(names, mdi_set())
	if missing:
		print("Not found in the icon set: " + ", ".join(missing))
	with open(OUT, "w", encoding="utf-8") as f:
		f.write(f"// Web interface from ESPHome {__version__} with {len(data['icons'])} icons, built by build-ui.py\n")
		# provide the icons in advance, the interface then does not ask Iconify
		f.write("window.IconifyPreload = " + json.dumps(data, separators=(",", ":")) + ";\n")
		f.write(ui)
		# separate block so that no names clash with the interface
		f.write("\n;\n{\n")
		f.write(extras)
		f.write("}\n")
	size = os.path.getsize(OUT)
	print(f"{OUT}: ESPHome {__version__}, {len(data['icons'])} icons, {size // 1024} KiB "
		f"(about {len(gzip.compress(open(OUT, 'rb').read())) // 1024} KiB compressed)")


if __name__ == "__main__":
	main()
