// Extras for the ESPHome web interface (version 3), embedded by build-ui.py:
// - The log column is collapsed by default. The "log" icon at the top right next to light/dark
//   toggles it, as does a double click on a section header.
// - The divider to the right of the entities can be dragged to change the width.
// - Without a connection to the device (circle at the top right not green) all controls are locked.
// - The device name at the top reloads the page when clicked, e.g. after an update.
// - With history.yaml on the device, a history chart is shown above the entities.
// - With the switch "Power" (schedule.yaml) on the device, a power button at the very top left
//   switches the unit off, or on again with the last used mode.
// - Every section (and the history) collapses with a click on its header.
// - The schedule is edited in a resizable text field, one rule per line, next to the list of
//   the rules with the next switching point in bold.
// - The setpoint slider of a climate entity gets − and + buttons, one step of the unit each.
// - A line above the history sums up the operating state: mode, temperatures, fan, vanes.
// The browser remembers choice, widths and collapsed sections per device.
const KEY = "esphome-log-hidden";
const BUTTON = "log-toggle";

function root() {
	const app = document.querySelector("esp-app");
	return app && app.shadowRoot;
}

function grid() {
	const r = root();
	return r && r.querySelector("main.flex-grid-half");
}

function hidden() {
	const m = grid();
	return !m || m.classList.contains("expanded_entity");
}

function remember() {
	try {
		localStorage.setItem(KEY, hidden() ? "1" : "0");
	} catch (e) {
		// without browser storage the default applies
	}
	mark();
}

// highlight the icon while the log is visible
function mark() {
	const r = root();
	const b = r && r.getElementById(BUTTON);
	if (!b) return;
	const icon = b.querySelector("iconify-icon");
	icon.style.color = hidden() ? "" : "rgba(3, 169, 244, 0.9)";
	b.title = hidden() ? "Show log" : "Hide log";
}

function toggle(ev) {
	ev.preventDefault();
	const m = grid();
	if (!m) return;
	m.classList.remove("expanded_logs");
	m.classList.toggle("expanded_entity");
	remember();
}

// put the icon into the header, also after the interface has rebuilt it
function button() {
	const r = root();
	const scheme = r && r.getElementById("scheme");
	if (!scheme || r.getElementById(BUTTON)) return;
	const a = document.createElement("a");
	a.href = "#";
	a.id = BUTTON;
	const icon = document.createElement("iconify-icon");
	icon.setAttribute("icon", "mdi:text-box-outline");
	icon.className = "top-icon";
	a.appendChild(icon);
	a.addEventListener("click", toggle);
	scheme.after(a);
	mark();
}

// Divider to the right of the entities: dragging changes the width, a double click restores
// the default. With the log shown it splits the two columns, with the log hidden it limits
// the entity column. Both widths are remembered separately.
const SPLIT = "col-split";
// minimum widths: entities (room for the OTA field), log
const MIN_ENTITY = 420;
const MIN_LOG = 250;
const MODES = {
	pair: { prop: "--col-w", key: "esphome-col-width", reserve: MIN_LOG },
	solo: { prop: "--solo-w", key: "esphome-col-width-solo", reserve: 0 },
};
const STYLE = `
.flex-grid-half { position: relative; }
.flex-grid-half:not(.expanded_entity):not(.expanded_logs) {
	grid-template-columns: var(--col-w, 700px) 1fr;
}
main.flex-grid-half.expanded_entity {
	grid-template-columns: var(--solo-w, 1fr);
}
#${SPLIT} {
	position: absolute; top: 0; bottom: 0; width: 12px;
	left: calc(var(--col-w, 700px) + 2px);
	cursor: col-resize; touch-action: none; z-index: 1;
}
.flex-grid-half.expanded_entity #${SPLIT} {
	left: min(calc(var(--solo-w, 100vw) + 2px), calc(100% - 12px));
}
#${SPLIT}::after {
	content: ""; position: absolute; top: 8px; bottom: 8px; left: 5px; width: 2px;
	border-radius: 1px; background: #7f7f7f40;
}
#${SPLIT}:hover::after, #${SPLIT}.drag::after { background: rgba(3, 169, 244, 0.9); }
.flex-grid-half.expanded_logs #${SPLIT} { display: none; }
@media (width<=1024px) { #${SPLIT} { display: none; } }
section.offline-lock { opacity: 0.45; filter: grayscale(1); transition: opacity 0.3s; }
.op-state { margin: 8px 8px 12px; display: flex; flex-wrap: wrap; justify-content: center; gap: 2px 16px; font-size: 0.95em; }
.op-state .op-mode { font-weight: 700; }
.op-state .op-label { opacity: 0.65; margin-right: 4px; }
.hist { margin: 0 8px 16px; }
.hist-head { cursor: pointer; font-weight: 600; padding: 4px 0; }
.hist-head::before { content: "▾"; display: inline-block; width: 1.2em; }
.hist.closed .hist-head::before { content: "▸"; }
.hist.closed .hist-body { display: none; }
.hist-label { display: flex; justify-content: space-between; gap: 8px; font-size: 0.85em; margin-top: 6px; }
.hist-label small { opacity: 0.6; }
.hist svg { display: block; width: 100%; height: 56px; }
.hist path { fill: none; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.hist-grid { stroke: currentColor; stroke-opacity: 0.12; vector-effect: non-scaling-stroke; }
.hist-axis { display: flex; justify-content: space-between; font-size: 0.75em; opacity: 0.6; }
header a.reload { display: contents; color: inherit; text-decoration: none; }
`;

function mode() {
	return hidden() ? MODES.solo : MODES.pair;
}

function setWidth(m, md, w) {
	if (w === null) {
		m.style.removeProperty(md.prop);
		return;
	}
	const max = m.getBoundingClientRect().width - md.reserve;
	m.style.setProperty(md.prop, Math.round(Math.max(MIN_ENTITY, Math.min(w, max))) + "px");
}

function store(md, value) {
	try {
		if (value === null) localStorage.removeItem(md.key);
		else localStorage.setItem(md.key, value);
	} catch (e) {
		// without browser storage the default applies
	}
}

function splitter() {
	const r = root();
	const m = grid();
	if (!m) return;
	if (!r.getElementById(SPLIT + "-style")) {
		const s = document.createElement("style");
		s.id = SPLIT + "-style";
		s.textContent = STYLE;
		r.appendChild(s);
	}
	if (r.getElementById(SPLIT)) return;
	for (const md of Object.values(MODES)) {
		try {
			const w = localStorage.getItem(md.key);
			if (w) setWidth(m, md, parseInt(w, 10));
		} catch (e) {
			// without browser storage the default applies
		}
	}
	const d = document.createElement("div");
	d.id = SPLIT;
	d.title = "Drag to change the width, double click to reset";
	d.addEventListener("pointerdown", ev => {
		ev.preventDefault();
		d.setPointerCapture(ev.pointerId);
		d.classList.add("drag");
		const md = mode();
		const left = m.getBoundingClientRect().left;
		const move = e => setWidth(m, md, e.clientX - left - 8);
		const up = () => {
			d.classList.remove("drag");
			d.removeEventListener("pointermove", move);
			d.removeEventListener("pointerup", up);
			const w = m.style.getPropertyValue(md.prop);
			if (w) store(md, parseInt(w, 10));
		};
		d.addEventListener("pointermove", move);
		d.addEventListener("pointerup", up);
	});
	d.addEventListener("dblclick", () => {
		const md = mode();
		setWidth(m, md, null);
		store(md, null);
	});
	// append at the end so that the nth-child column rules still apply
	m.appendChild(d);
}

// Lock the controls while the interface has no connection to the device.
// "inert" blocks clicks, input and keyboard focus in the whole section.
function lock() {
	const app = document.querySelector("esp-app");
	const r = root();
	const table = r && r.querySelector("esp-entity-table");
	const section = table && table.closest("section");
	if (!section) return;
	const off = !app.connected;
	const p = r.getElementById(POWER);
	if (p && p.inert !== off) {
		p.inert = off;
		p.style.opacity = off ? "0.45" : "";
	}
	if (section.inert !== off) {
		section.inert = off;
		section.classList.toggle("offline-lock", off);
		section.title = off ? "No connection to the device" : "";
	}
}

// Power button at the very top left for the switch "Power" (schedule.yaml). It appears once
// the device has reported the switch; blue = unit on. A click switches off, or on with the
// last used mode. The state comes from the event stream of the interface.
const POWER = "power-toggle";
let power = null;  // { path, on } once the device has reported the switch
let listening = false;
// last state per entity, key "domain/Name" (e.g. "text/Schedule")
const states = {};

function base() {
	return location.pathname.replace(/\/$/, "");
}

function post(key, action, query) {
	const path = key.split("/").map(encodeURIComponent).join("/");
	return fetch(`${base()}/${path}/${action}` + (query ? `?${query}` : ""), { method: "POST" });
}

function stateListen() {
	if (listening || !window.source) return;
	listening = true;
	window.source.addEventListener("state", (e) => {
		let d;
		try {
			d = JSON.parse(e.data);
		} catch (x) {
			return;
		}
		let key = d.name_id || d.id || "";
		if (key === "switch-power") key = "switch/Power";
		if (!key.includes("/")) return;
		states[key] = d;
		if (key === "switch/Power") {
			power = { path: key, on: d.value === true || d.state === "ON" };
			powerButton();
		} else if (key === "text/Schedule" || key === "text_sensor/Schedule rules") {
			scheduleBox();
		}
		opState();
	});
}

function powerClick(ev) {
	ev.preventDefault();
	if (!power) return;
	post(power.path, power.on ? "turn_off" : "turn_on").catch(() => {});
}

function powerButton() {
	const r = root();
	const header = r && r.querySelector("header");
	if (!power || !header) return;
	let a = r.getElementById(POWER);
	if (!a) {
		a = document.createElement("a");
		a.href = "#";
		a.id = POWER;
		const icon = document.createElement("iconify-icon");
		icon.setAttribute("icon", "mdi:power");
		icon.className = "top-icon";
		a.appendChild(icon);
		a.addEventListener("click", powerClick);
		// the header icons float right; this one floats left, as first element left of the logo
		a.style.float = "left";
		icon.style.float = "none";
		header.prepend(a);
	}
	a.querySelector("iconify-icon").style.color = power.on ? "rgba(3, 169, 244, 0.9)" : "";
	a.title = power.on ? "Switch off" : "Switch on (last mode)";
}

// device name in the header as a link to this page, so a click reloads it
function title() {
	const r = root();
	const h = r && r.querySelector("header h1");
	if (!h || (h.parentElement && h.parentElement.classList.contains("reload"))) return;
	const a = document.createElement("a");
	a.className = "reload";
	a.href = location.pathname;
	h.before(a);
	a.appendChild(h);
}

// History chart above the entities, from /history.json (history.yaml), refreshed with the
// sample interval of the device (at least every 5 s, at most every 60 s).
// Devices without history.yaml answer 404, then nothing is shown.
const HIST_KEY = "esphome-history-closed";
const HIST_W = 600;
const HIST_H = 56;
let histData = null;  // null = not loaded yet, false = not available
let histLoaded = 0;

function parseHistory(text) {
	const lines = text.split("\n");
	const head = lines[0];
	const age = parseInt(head.slice(0, 10), 10);
	const step = parseInt(head.slice(11, 15), 10);
	const n = parseInt(head.slice(16, 20), 10);
	const now = Date.now() / 1000;
	const rows = [];
	for (let i = 0; i < n; i++) {
		const l = lines[i + 1] || "";
		const f = parseInt(l.slice(0, 2), 16);
		let room = parseInt(l.slice(3, 7), 16);
		const t = parseInt(l.slice(8, 10), 16);
		const p = parseInt(l.slice(11, 15), 16);
		room = room === 0x8000 ? NaN : (room > 0x7fff ? room - 0x10000 : room) / 10;
		rows.push({
			t: now - age - (n - 1 - i) * step,
			freq: f === 0xff ? NaN : f,
			room: room,
			target: t === 0xff ? NaN : t / 2,
			power: p === 0xffff ? NaN : p,
		});
	}
	// the charts span from the oldest sample to now, so they fill the width from the start and
	// compress as the history grows
	const span = rows.length ? Math.max(now - rows[0].t, step) : step;
	return { rows: rows, span: span, end: now, step: step, powerName: head.slice(21).trim() || "Power" };
}

async function loadHistory() {
	try {
		const r = await fetch("/history.json", { cache: "no-store" });
		if (r.status === 404) {
			histData = false;
			return;
		}
		if (r.ok) histData = parseHistory(await r.text());
	} catch (e) {
		// keep the previous data, the next attempt follows in a minute
	}
}

function histPath(rows, get, t0, span, lo, hi) {
	let d = "";
	let pen = false;
	for (const r of rows) {
		const v = get(r);
		if (isNaN(v)) {
			pen = false;
			continue;
		}
		const x = ((r.t - t0) / span) * HIST_W;
		const y = HIST_H - 2 - ((v - lo) / (hi - lo || 1)) * (HIST_H - 4);
		d += (pen ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1) + " ";
		pen = true;
	}
	return d;
}

function histRange(rows, gets, zero) {
	let lo = Infinity;
	let hi = -Infinity;
	for (const r of rows)
		for (const g of gets) {
			const v = g(r);
			if (!isNaN(v)) {
				lo = Math.min(lo, v);
				hi = Math.max(hi, v);
			}
		}
	if (lo === Infinity) return null;
	if (zero) lo = Math.min(lo, 0);
	if (hi - lo < 1) hi = lo + 1;
	return [lo, hi];
}

function histLast(rows, get) {
	for (let i = rows.length - 1; i >= 0; i--)
		if (!isNaN(get(rows[i]))) return get(rows[i]);
	return NaN;
}

function histChart(title, unit, digits, lines, rows, t0, span, zero) {
	const range = histRange(rows, lines.map(l => l.get), zero);
	const fmt = v => (isNaN(v) ? "–" : v.toFixed(digits));
	let head = `<div class="hist-label"><span>${title}</span><span>`;
	head += lines.map(l => `${l.name ? l.name + " " : ""}<b>${fmt(histLast(rows, l.get))}</b> ${unit}`).join(" · ");
	if (range) head += ` <small>(${fmt(range[0])}–${fmt(range[1])})</small>`;
	head += "</span></div>";
	let svg = `<svg viewBox="0 0 ${HIST_W} ${HIST_H}" preserveAspectRatio="none">`;
	for (const f of [0.25, 0.5, 0.75])
		svg += `<line x1="${f * HIST_W}" x2="${f * HIST_W}" y1="0" y2="${HIST_H}" class="hist-grid"/>`;
	if (range)
		for (const l of lines)
			svg += `<path d="${histPath(rows, l.get, t0, span, range[0], range[1])}" stroke="${l.color}"` +
				(l.dash ? ' stroke-dasharray="6 4"' : "") + "/>";
	return head + svg + "</svg>";
}

// time before now for the axis, e.g. "−2.5 h" or "−40 min"
function histAgo(s) {
	if (s >= 5400) return "−" + (Math.round(s / 1800) / 2) + " h";
	return "−" + Math.max(1, Math.round(s / 60)) + " min";
}

function renderHistory(box) {
	const body = box.querySelector(".hist-body");
	const h = histData;
	if (!h || !body) return;
	const t0 = h.end - h.span;
	body.innerHTML =
		histChart("Compressor", "Hz", 0, [{ get: r => r.freq, color: "#f59e0b" }], h.rows, t0, h.span, true) +
		histChart("Temperature", "°C", 1, [
			{ name: "room", get: r => r.room, color: "#3b82f6" },
			{ name: "setpoint", get: r => r.target, color: "#ef4444", dash: true },
		], h.rows, t0, h.span, false) +
		histChart(h.powerName, "W", 0, [{ get: r => r.power, color: "#10b981" }], h.rows, t0, h.span, true) +
		'<div class="hist-axis">' + [1, 0.75, 0.5, 0.25].map(f => `<span>${histAgo(h.span * f)}</span>`).join("") +
		"<span>now</span></div>";
}

function historyBox() {
	if (histData === false) return;
	const r = root();
	const table = r && r.querySelector("esp-entity-table");
	if (!table) return;
	let box = r.querySelector(".hist");
	if (!box) {
		box = document.createElement("div");
		box.className = "hist";
		box.innerHTML = '<div class="hist-head">History</div><div class="hist-body"></div>';
		let closed = false;
		try {
			closed = localStorage.getItem(HIST_KEY) === "1";
		} catch (e) {
			// without browser storage the default applies
		}
		box.classList.toggle("closed", closed);
		box.querySelector(".hist-head").addEventListener("click", () => {
			box.classList.toggle("closed");
			try {
				localStorage.setItem(HIST_KEY, box.classList.contains("closed") ? "1" : "0");
			} catch (e) {
				// without browser storage the default applies
			}
		});
		table.before(box);
		renderHistory(box);
	}
	const every = histData ? Math.min(60000, Math.max(5000, histData.step * 1000)) : 5000;
	if (Date.now() - histLoaded > every) {
		histLoaded = Date.now();
		loadHistory().then(() => {
			if (histData === false) box.remove();
			else renderHistory(box);
		});
	}
}

// Collapsible sections: a click on a section header (also "OTA Update" and "Debug Log") folds
// the section; the double click of the interface toggles the log column as before.
const FOLD_KEY = "esphome-closed-sections";
const FOLD_STYLE = `
.tab-header.fold { cursor: pointer; display: flex; width: fit-content; }
.tab-header.fold::before { content: "▾"; display: inline-block; width: 1.2em; margin-left: -0.6em; }
.tab-header.fold.closed::before { content: "▸"; }
.tab-header.fold.closed { border-radius: 12px; }
.tab-header.fold.closed + .tab-container { display: none; }
`;

function folded() {
	try {
		return JSON.parse(localStorage.getItem(FOLD_KEY) || "[]");
	} catch (e) {
		return [];
	}
}

function style(rootNode, id, css) {
	if (rootNode.getElementById(id)) return;
	const s = document.createElement("style");
	s.id = id;
	s.textContent = css;
	rootNode.appendChild(s);
}

// the shadow roots of the interface: the page and its components (entities, log, …)
function shadowRoots() {
	const r = root();
	if (!r) return [];
	const out = [r];
	r.querySelectorAll("*").forEach((el) => {
		if (el.shadowRoot) out.push(el.shadowRoot);
	});
	return out;
}

function sections() {
	const closed = folded();
	for (const sr of shadowRoots()) {
		const heads = sr.querySelectorAll(".tab-header");
		if (!heads.length) continue;
		style(sr, "fold-style", FOLD_STYLE);
		heads.forEach((h) => {
			const name = h.textContent.trim();
			if (!h.classList.contains("fold")) {
				h.classList.add("fold");
				h.addEventListener("click", () => {
					const list = folded().filter((n) => n !== h.dataset.name);
					if (!h.classList.contains("closed")) list.push(h.dataset.name);
					try {
						localStorage.setItem(FOLD_KEY, JSON.stringify(list));
					} catch (e) {
						// without browser storage the sections only stay folded until reload
					}
					h.classList.toggle("closed");
				});
			}
			// the interface reuses header elements when sections change, so check the name each time
			if (h.dataset.name !== name) {
				h.dataset.name = name;
				h.classList.toggle("closed", closed.includes(name));
			}
		});
	}
}

// Schedule: resizable text field with one rule per line instead of the one-line input, next to
// it the rules as the device understood them (sensor "Schedule rules"), the next one in bold.
// A change is sent when the field loses the focus, joined with "; " (max. 255 characters).
const SCHED_SIZE_KEY = "esphome-schedule-size";
const SCHED_STYLE = `
.sched-edit { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px 16px;
	padding: 4px 8px 10px 8px; }
@media (width<=700px) { .sched-edit { grid-template-columns: minmax(0, 1fr); } }
.sched-edit textarea { width: 30em; min-width: 12em; max-width: 100%; min-height: 8em; resize: both;
	box-sizing: border-box; font: 14px/21px ui-monospace, monospace;
	padding: 6px; border-radius: 4px; border: 1px solid rgba(127, 127, 127, 0.5);
	background: transparent; color: inherit; white-space: pre; overflow-x: auto; }
.sched-edit ol { margin: 0; padding: 7px 0 0 1.8em; font-size: 14px; line-height: 21px; }
.sched-edit li.next { font-weight: 700; }
.sched-edit .sched-note { grid-column: 1 / -1; font-size: 0.8em; opacity: 0.7; }
.sched-edit .sched-note.error { opacity: 1; color: #ef4444; }
`;

function scheduleRows(sr) {
	let edit = null, list = null;
	sr.querySelectorAll(".entity-row").forEach((row) => {
		const name = row.children[1] && row.children[1].textContent.trim();
		if (name === "Schedule" && row.querySelector("input")) edit = row;
		else if (name === "Schedule rules") list = row;
	});
	return { edit, list };
}

function scheduleLines(text) {
	return text.split(/[;\n]/).map((s) => s.trim()).filter((s) => s);
}

function scheduleBox() {
	const r = root();
	const table = r && r.querySelector("esp-entity-table");
	const sr = table && table.shadowRoot;
	const text = states["text/Schedule"];
	if (!sr || !text) return;
	const { edit, list } = scheduleRows(sr);
	if (!edit) return;
	style(sr, "sched-style", SCHED_STYLE);
	edit.querySelector("input").parentElement.style.display = "none";
	if (list) list.style.display = "none";
	let box = sr.querySelector(".sched-edit");
	if (!box) {
		box = document.createElement("div");
		box.className = "sched-edit";
		box.innerHTML = '<textarea spellcheck="false"></textarea><ol></ol><div class="sched-note"></div>';
		const ta = box.querySelector("textarea");
		// size dragged by the user, remembered per device
		try {
			const size = JSON.parse(localStorage.getItem(SCHED_SIZE_KEY) || "null");
			if (size) {
				ta.style.width = size.w + "px";
				ta.style.height = size.h + "px";
			}
		} catch (e) {
			// without browser storage the default size applies
		}
		ta.addEventListener("mouseup", () => {
			if (!ta.style.width && !ta.style.height) return;
			try {
				localStorage.setItem(SCHED_SIZE_KEY, JSON.stringify({ w: ta.offsetWidth, h: ta.offsetHeight }));
			} catch (e) {
				// without browser storage the size is not remembered
			}
		});
		ta.addEventListener("input", () => {
			ta.dataset.dirty = "1";
			scheduleNote(box);
		});
		ta.addEventListener("change", () => {
			const value = scheduleLines(ta.value).join("; ");
			if (value.length > 255) return;
			post("text/Schedule", "set", "value=" + encodeURIComponent(value))
				.then(() => delete ta.dataset.dirty)
				.catch(() => {});
		});
	}
	// the interface may reorder rows; keep the box right below the schedule row
	if (box.previousElementSibling !== edit) edit.after(box);
	const ta = box.querySelector("textarea");
	const lines = scheduleLines(String(text.value !== undefined ? text.value : text.state || ""));
	if (!ta.dataset.dirty && box.getRootNode().activeElement !== ta) {
		ta.value = lines.join("\n");
		if (!ta.style.height) ta.rows = Math.max(4, lines.length + 1);
	}
	const rules = states["text_sensor/Schedule rules"];
	const items = rules ? String(rules.value !== undefined ? rules.value : rules.state || "").split("\n").filter((s) => s) : [];
	const ol = box.querySelector("ol");
	ol.innerHTML = "";
	for (const item of items) {
		const li = document.createElement("li");
		const next = item.startsWith("▶ ");
		li.textContent = next ? item.slice(2) : item;
		li.classList.toggle("next", next);
		if (next) li.title = "next switching point";
		ol.appendChild(li);
	}
	scheduleNote(box);
}

function scheduleNote(box) {
	const ta = box.querySelector("textarea");
	const n = scheduleLines(ta.value).join("; ").length;
	const note = box.querySelector(".sched-note");
	note.classList.toggle("error", n > 255);
	note.textContent = n > 255 ? `${n} of 255 characters: too long, not saved`
		: `One rule per line (or separated by ";"), saved when leaving the field · ${n} of 255 characters`;
}

// Operating state above the history: mode, setpoint, room temperature, fan, vanes.
// Built from the entities the device has (TCL: "… fixing", Midea: "… louver").
const MODE_LABELS = { OFF: "Off", HEAT: "Heat", COOL: "Cool", HEAT_COOL: "Heat/Cool", AUTO: "Auto",
	DRY: "Dry", FAN_ONLY: "Fan only" };

function stateValue(key) {
	const d = states[key];
	if (!d) return null;
	const v = d.value !== undefined && typeof d.value !== "boolean" ? d.value : d.state;
	return v === undefined || v === null || v === "" ? null : String(v);
}

function opItems() {
	const ckey = Object.keys(states).find((k) => k.startsWith("climate/"));
	const c = ckey && states[ckey];
	if (!c) return null;
	const items = [];
	const mode = c.mode || "";
	items.push(["", MODE_LABELS[mode] || mode, "op-mode"]);
	const num = (v) => {
		const n = parseFloat(v);
		return isNaN(n) ? null : n;
	};
	if (mode !== "OFF" && num(c.target_temperature) !== null) items.push(["Setpoint", `${num(c.target_temperature)} °C`]);
	if (num(c.current_temperature) !== null) items.push(["Room", `${num(c.current_temperature)} °C`]);
	if (mode === "OFF") return items;
	const fan = stateValue("select/Fan speed");
	if (fan) items.push(["Fan", fan]);
	const swing = stateValue("select/Swing") || "Off";
	const swingV = swing === "Vertical" || swing === "Both";
	const swingH = swing === "Horizontal" || swing === "Both";
	const v = stateValue("select/Vertical louver") || stateValue("select/Vertical fixing");
	const h = stateValue("select/Horizontal louver") || stateValue("select/Horizontal fixing");
	if (swingV) items.push(["Vertical", "swing"]);
	else if (v) items.push(["Vertical", v]);
	if (swingH) items.push(["Horizontal", "swing"]);
	else if (h) items.push(["Horizontal", h]);
	return items;
}

function opState() {
	const r = root();
	const table = r && r.querySelector("esp-entity-table");
	const items = table && opItems();
	if (!items) return;
	let line = r.querySelector(".op-state");
	if (!line) {
		line = document.createElement("div");
		line.className = "op-state";
	}
	// directly above the history, or above the entities without history
	const anchor = r.querySelector(".hist") || table;
	if (line.nextElementSibling !== anchor) anchor.before(line);
	line.innerHTML = "";
	for (const [label, value, cls] of items) {
		const span = document.createElement("span");
		if (cls) span.className = cls;
		if (label) {
			const l = document.createElement("span");
			l.className = "op-label";
			l.textContent = label;
			span.appendChild(l);
		}
		span.appendChild(document.createTextNode(value));
		line.appendChild(span);
	}
}

// − and + next to the setpoint slider of climate entities. Several clicks add up and are sent
// together 0.6 s after the last one.
const STEP_STYLE = `
.setpoint-step { width: 28px; height: 28px; margin: 0 6px; border-radius: 50%; padding: 0;
	border: 1px solid rgba(127, 127, 127, 0.6); background: transparent; color: inherit;
	font-size: 18px; line-height: 1; cursor: pointer; align-self: center; flex: none; }
.setpoint-step:hover { border-color: rgba(3, 169, 244, 0.9); }
`;
const SETPOINT_FIELDS = { "Target:": "target_temperature", "Target Low:": "target_temperature_low",
	"Target High:": "target_temperature_high" };
const setpointPending = {};

function setpointStep(key, field, dir) {
	const d = states[key];
	if (!d) return;
	const step = parseFloat(d.step) || 0.5;
	const id = key + "|" + field;
	const pending = setpointPending[id];
	let v = pending ? pending.value : parseFloat(d[field]);
	if (isNaN(v)) return;
	v = Math.round((v + dir * step) / step) * step;
	const lo = parseFloat(d.min_temp), hi = parseFloat(d.max_temp);
	if (!isNaN(lo)) v = Math.max(lo, v);
	if (!isNaN(hi)) v = Math.min(hi, v);
	v = Math.round(v * 10) / 10;
	if (pending) clearTimeout(pending.timer);
	setpointPending[id] = {
		value: v,
		timer: setTimeout(() => {
			delete setpointPending[id];
			post(key, "set", `${field}=${v}`).catch(() => {});
		}, 600),
	};
	// show the new value right away on the slider
	const r = root();
	const table = r && r.querySelector("esp-entity-table");
	const slider = table && table.shadowRoot.querySelector(`[data-setpoint="${CSS.escape(id)}"]`);
	if (slider) slider.value = v;
}

function setpointButtons() {
	const r = root();
	const table = r && r.querySelector("esp-entity-table");
	const sr = table && table.shadowRoot;
	if (!sr) return;
	sr.querySelectorAll(".climate-row").forEach((row) => {
		const label = row.querySelector("label");
		const slider = row.querySelector("esp-range-slider");
		const field = label && SETPOINT_FIELDS[label.textContent.trim()];
		const entity = row.closest(".entity-row");
		if (!field || !slider || !entity || row.querySelector(".setpoint-step")) return;
		style(sr, "step-style", STEP_STYLE);
		const name = entity.children[1] && entity.children[1].textContent.trim();
		const key = "climate/" + name;
		slider.dataset.setpoint = key + "|" + field;
		const make = (text, dir) => {
			const b = document.createElement("button");
			b.className = "setpoint-step";
			b.textContent = text;
			b.title = dir < 0 ? "lower" : "higher";
			b.addEventListener("click", () => setpointStep(key, field, dir));
			return b;
		};
		slider.before(make("−", -1));
		slider.after(make("+", 1));
	});
}

function setup() {
	button();
	stateListen();
	setpointButtons();
	opState();
	powerButton();
	sections();
	scheduleBox();
	splitter();
	title();
	historyBox();
}

function apply(tries = 0) {
	const m = grid();
	if (!m) {
		if (tries < 100) setTimeout(() => apply(tries + 1), 100);
		return;
	}
	let hide = true;
	try {
		hide = localStorage.getItem(KEY) !== "0";
	} catch (e) {
		// without browser storage the default applies
	}
	m.classList.remove("expanded_logs");
	m.classList.toggle("expanded_entity", hide);
	setup();
	setInterval(setup, 1000);
	setInterval(lock, 500);
}

// listen right away, the device sends the states once when the event stream opens
stateListen();
apply();
// the interface toggles on double click itself, remember the state afterwards
document.addEventListener("entity-tab-header-double-clicked", () => setTimeout(remember, 0));
document.addEventListener("log-tab-header-double-clicked", () => setTimeout(remember, 0));
