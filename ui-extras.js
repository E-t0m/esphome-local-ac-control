// Extras for the ESPHome web interface (version 3), embedded by build-ui.py:
// - The log column is collapsed by default. The "log" icon at the top right next to light/dark
//   toggles it, as does a double click on a section header.
// - The divider to the right of the entities can be dragged to change the width.
// - Without a connection to the device (circle at the top right not green) all controls are locked.
// - The device name at the top reloads the page when clicked, e.g. after an update.
// - With history.yaml on the device, a history chart is shown above the entities.
// The browser remembers choice and widths per device.
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
	if (section.inert !== off) {
		section.inert = off;
		section.classList.toggle("offline-lock", off);
		section.title = off ? "No connection to the device" : "";
	}
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

function setup() {
	button();
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

apply();
// the interface toggles on double click itself, remember the state afterwards
document.addEventListener("entity-tab-header-double-clicked", () => setTimeout(remember, 0));
document.addEventListener("log-tab-header-double-clicked", () => setTimeout(remember, 0));
