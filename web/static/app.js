// FM26 Analyst dashboard: hash-routed single page over /api.
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
// phone companion: set from /api/status when this page came through the phone listener (web/remote.py)
let REMOTE = false;
let NEEDS_CLUB = false;    // first run: no club chosen yet
// every change request carries X-FM-Remote (the phone listener refuses changes without it, so other sites can't
// make them); a signed-out phone goes to the sign-in page; replies from the offline copy are flagged in the header
const _fetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const method = String(init.method || "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    const h = new Headers(init.headers || {});
    h.set("X-FM-Remote", "1");
    init = { ...init, headers: h };
  }
  const r = await _fetch(input, init);
  if (String(input).startsWith("/api/")) {
    if (r.status === 401) location.href = "/login";
    markOffline(r.headers.get("X-FM-Cached"));
  }
  return r;
};
function markOffline(when) {
  const el = document.getElementById("offline");
  if (!el) return;
  el.classList.toggle("hidden", !when);
  if (when) el.title = "Your PC can't be reached: showing the data saved on this device"
    + (when !== "1" ? ` (from ${new Date(when).toLocaleString("en-GB")})` : "");
}
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (v, d = 2) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));
const money = (v) => (v == null ? "–" : "£" + (v >= 1e6 ? (v / 1e6).toFixed(1) + "m" : v >= 1e3 ? Math.round(v / 1e3) + "k" : v));
const shown = (raw) => Math.round(raw / 5);
const label = (k) => k.replace(/_/g, " ");
const charts = [];
const GRID = { color: "#2a3340" }, TICK = { color: "#8b98a8" };

// ---- charts: one styling pass per size, so text sizes form a clear hierarchy
// (axis titles/legend > axis labels > value labels) and value labels never overlap
const CHART_SIZES = {
  small: { legend: 12, axis: 11, point: 11, value: 10, pad: 8, point_r: 3 },
  medium: { legend: 13, axis: 12, point: 12, value: 11, pad: 14, point_r: 4 },
  large: { legend: 15, axis: 13, point: 14, value: 12, pad: 22, point_r: 5 },
};
// enlarged view: text size follows the panel's real width, so small windows don't get oversized labels
const zoomSize = (w) => (w < 560 ? "small" : w < 900 ? "medium" : "large");
if (window.Chart) {
  Chart.defaults.color = "#c9d4e0";
  Chart.defaults.font.family = 'system-ui, "Segoe UI", sans-serif';
  Object.assign(Chart.defaults.plugins.tooltip, {
    padding: 10, titleFont: { size: 13, weight: "600" }, bodyFont: { size: 13 }, boxPadding: 4,
    backgroundColor: "rgba(13,17,23,.95)", borderColor: "#2a3340", borderWidth: 1 });
  if (window.ChartDataLabels) Chart.register(ChartDataLabels);
}
const fmtVal = (v) => (v == null ? "" : typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(2)) : v);

function styleChart(cfg, size) {
  const S = CHART_SIZES[size], type = cfg.type, multi = cfg.data.datasets.length > 1;
  const o = (cfg.options = cfg.options || {});
  o.responsive = true;
  o.layout = { padding: S.pad };
  o.interaction = type === "radar" ? { mode: "nearest", intersect: false } : { mode: "index", intersect: false };
  o.plugins = o.plugins || {};
  o.plugins.legend = { ...(o.plugins.legend || {}), labels: { color: "#e6edf3", boxWidth: 14, font: { size: S.legend } } };
  o.plugins.datalabels = {
    display: (ctx) => (ctx.dataset.data[ctx.dataIndex] == null || ctx.dataset.borderDash ? false : "auto"),  // "auto" hides overlaps
    formatter: fmtVal,
    // attribute charts colour the number by value; the pill border says whose value it is when comparing
    color: (ctx) => (ctx.dataset.valueColors ? attrColor(ctx.dataset.data[ctx.dataIndex])
      : multi && typeof ctx.dataset.borderColor === "string" ? ctx.dataset.borderColor : "#e6edf3"),
    borderColor: (ctx) => (ctx.dataset.valueColors && multi ? ctx.dataset.borderColor : null),
    borderWidth: (ctx) => (ctx.dataset.valueColors && multi ? 1.5 : 0),
    backgroundColor: "rgba(13,17,23,.82)", borderRadius: 4, padding: { top: 2, bottom: 1, left: 4, right: 4 },
    font: { size: S.value, weight: "600" },
    anchor: "end", offset: 3, clamp: true,
    align: type === "radar" ? (multi ? (ctx) => (ctx.datasetIndex === 0 ? "end" : "start") : "end")
      : type === "bar" ? "end" : (ctx) => (ctx.datasetIndex % 2 ? "bottom" : "top"),
  };
  for (const [name, ax] of Object.entries(o.scales || {})) {
    ax.ticks = { ...(ax.ticks || {}), font: { size: S.axis } };
    if (ax.pointLabels) ax.pointLabels = { ...ax.pointLabels, font: { size: S.point } };
    if (name === "x" && type === "bar" && size !== "small") {  // bar labels are hidden in the card, shown when enlarged
      ax.display = true;
      ax.ticks = { ...ax.ticks, maxRotation: 40, minRotation: 0, autoSkip: true, color: "#8b98a8" };
    }
  }
  cfg.data.datasets.forEach((d) => {
    if (type === "line") Object.assign(d, { pointRadius: d.borderDash ? 0 : S.point_r, pointHoverRadius: S.point_r + 3, borderWidth: 2 });
    if (type === "radar") Object.assign(d, { pointRadius: S.point_r, pointHoverRadius: S.point_r + 2, borderWidth: d.segment ? 3 : 2 });
  });
  return cfg;
}
// deep copy that keeps functions, so one config can be rendered small and large
const cloneCfg = (o) => (Array.isArray(o) ? o.map(cloneCfg) : o && typeof o === "object" && o.constructor === Object
  ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, cloneCfg(v)])) : o);

let zoomTimer = null;
function openZoom(cfg, title) {
  closeZoom();
  const back = document.createElement("div");
  back.className = "chartzoom";
  const shape = cfg.type === "radar" ? "square" : "wide";
  back.innerHTML = `<div class="zpanel ${shape}"><div class="zhead"><span class="ztitle">${esc(title || "")}</span>
    <span class="muted">move away, click outside or Esc to close</span></div><div class="zbody"><canvas></canvas></div></div>`;
  document.body.appendChild(back);
  const panel = back.querySelector(".zpanel");
  const render = () => {
    back._chart?.destroy();
    back._size = zoomSize(panel.clientWidth);
    const big = styleChart(cloneCfg(cfg), back._size);
    big.options.maintainAspectRatio = false;  // fill the panel; the panel itself is sized per chart shape
    back._chart = new Chart(back.querySelector("canvas"), big);
  };
  render();
  back._onResize = () => zoomSize(panel.clientWidth) !== back._size && render();
  window.addEventListener("resize", back._onResize);
  let entered = false;
  panel.addEventListener("mouseenter", () => (entered = true));
  panel.addEventListener("mouseleave", () => entered && closeZoom());
  back.addEventListener("click", (e) => e.target === back && closeZoom());
}
function closeZoom() {
  const z = document.querySelector(".chartzoom");
  if (z) { z._chart?.destroy(); window.removeEventListener("resize", z._onResize); z.remove(); }
}
document.addEventListener("keydown", (e) => e.key === "Escape" && closeZoom());

function chart(canvas, cfg) {
  const base = cloneCfg(cfg);
  charts.push(new Chart(canvas, styleChart(cfg, "small")));
  const box = document.createElement("div");
  box.className = "chartbox";
  box.innerHTML = '<span class="zhint">⤢ enlarge</span>';
  canvas.replaceWith(box);
  box.prepend(canvas);
  const title = canvas.closest(".card")?.querySelector("h2")?.textContent;
  const open = () => openZoom(base, title);
  box.addEventListener("mouseenter", () => { zoomTimer = setTimeout(open, 500); });
  box.addEventListener("mouseleave", () => clearTimeout(zoomTimer));
  box.addEventListener("click", () => { clearTimeout(zoomTimer); open(); });
}
const COLORS = ["#c8102e", "#58a6ff"];

function rating(r) {
  if (r == null) return "–";
  const c = r >= 7.5 ? "r-hi" : r >= 7.0 ? "r-mid" : r >= 6.7 ? "r-ok" : r >= 6.3 ? "r-lo" : "r-bad";
  return `<span class="rating ${c}">${Number(r).toFixed(2)}</span>`;
}
const res = (x) => (x ? `<span class="res ${x}">${x}</span>` : "");
const bar = (pct, color) =>
  `<div class="bar"><span style="width:${Math.max(0, Math.min(100, pct))}%;background:${color}"></span></div>`;
const condColor = (v) => (v >= 90 ? "var(--good)" : v >= 80 ? "var(--ok)" : "var(--bad)");
const spark = (rs) =>
  `<span class="spark">${(rs || []).map((r) => `<i title="${r}" style="height:${Math.max(2, (r - 5.5) * 6)}px"></i>`).join("")}</span>`;
// ⓘ next to a title: hover, keyboard focus or tap shows the explanation (keeps the cards clean)
const info = (text, cls = "") => `<span class="info ${cls}" tabindex="0" role="button" aria-label="More information">ⓘ<span class="infotip" role="tooltip">${text}</span></span>`;
const h2i = (title, text) => `<h2>${title}${text ? info(text) : ""}</h2>`;
function placeTip(i) {      // position against the window, so card edges never clip it; flip near the edges
  const tip = i.querySelector(".infotip");
  if (!tip) return;
  const r = i.getBoundingClientRect();
  Object.assign(tip.style, { position: "fixed", left: "0px", top: "0px", display: "block", visibility: "hidden" });
  const w = tip.offsetWidth, h = tip.offsetHeight;          // measured while laid out but invisible
  tip.style.display = tip.style.visibility = "";
  tip.style.left = `${Math.max(8, Math.min(r.left - 8, innerWidth - w - 12))}px`;
  tip.style.top = `${r.bottom + 6 + h > innerHeight - 8 ? Math.max(8, r.top - h - 6) : r.bottom + 6}px`;
}
document.addEventListener("mouseover", (e) => { const i = e.target.closest(".info"); if (i) placeTip(i); });
document.addEventListener("focusin", (e) => { const i = e.target.closest(".info"); if (i) placeTip(i); });
document.addEventListener("scroll", () => document.querySelectorAll(".info.open").forEach((o) => o.classList.remove("open")), true);
document.addEventListener("click", (e) => {      // tap support: toggle on touch, close others
  const i = e.target.closest(".info");
  document.querySelectorAll(".info.open").forEach((o) => { if (o !== i) o.classList.remove("open"); });
  if (i) { i.classList.toggle("open"); placeTip(i); }
});
const injBack = (i) => (i.back_max === 0 ? "back any day now" : i.back_min === i.back_max
  ? `back in ${i.back_max} day${i.back_max === 1 ? "" : "s"}` : `back in ${i.back_min}-${i.back_max} days`);
const injBadge = (i) => (i ? ` <span class="inj" title="Injured since ${esc(i.since)}, ${esc(injBack(i))}">🩹 ${i.back_max}d</span>` : "");
const playerLink = (uid, name) => `<a href="#player/${uid}">${esc(name)}</a>`;
const matchLink = (id, text) => `<a href="#match/${id}">${text}</a>`;
const delta = (d) => (d > 0 ? `<span class="up">+${d}</span>` : d < 0 ? `<span class="down">${d}</span>` : "0");
// a KPI tile: big value, small label, optional thin bar (0-1) underneath
const kpi = (v, lbl, frac = null, color = "var(--blue)") => `<div class="kpi tile"><div class="v">${v}</div>
  <div class="l">${lbl}</div>${frac != null ? `<div class="kbar"><span style="width:${Math.max(0, Math.min(1, frac)) * 100}%;background:${color}"></span></div>` : ""}</div>`;
// tile holding a name: spans two grid columns; text is shrunk to fit by fitTiles()
const kpiWide = (v, lbl) => kpi(v, lbl).replace('class="kpi tile"', 'class="kpi tile wide"');
function fitTiles(root = document) {
  root.querySelectorAll(".kpi.tile .v").forEach((el) => {
    el.style.fontSize = "";
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollWidth > el.clientWidth && size > 11) el.style.fontSize = `${--size}px`;
  });
}
new MutationObserver(() => { fitTiles(); tipHeaders(); }).observe(document.getElementById("view"), { childList: true });
let fitTimer;
window.addEventListener("resize", () => { clearTimeout(fitTimer); fitTimer = setTimeout(fitTiles, 100); });
const venueWord = (v) => (v === "H" ? "vs" : v === "A" ? "at" : "vs (N)");
// compact competition names for narrow lists (full name stays in the row tooltip)
const SHORT_COMP = [[/Premier League/, "PL"], [/Champions League Final/, "UCL Final"], [/Champions League/, "UCL"],
  [/FA Cup Final/, "FA Cup F"], [/FA Cup/, "FA Cup"], [/Carabao Cup/, "EFL Cup"], [/Community Shield/, "Shield"],
  [/Super Cup/, "Super Cup"], [/Friendly Cup/, "Friendly Cup"], [/Friendly/, "Friendly"]];
const shortComp = (c) => (SHORT_COMP.find(([re]) => re.test(c || "")) || [null, c || ""])[1];

function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 6000);
}

// sortable tables: click a header to sort by that column
function sortable(table) {
  table.querySelectorAll("thead th").forEach((th, i) =>
    th.addEventListener("click", () => {
      const body = table.tBodies[0];
      const rows = [...body.rows].filter((r) => !r.classList.contains("group"));
      const dir = th.dataset.dir === "desc" ? 1 : -1;
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      const val = (r) => {
        const c = r.cells[i];
        const v = c?.dataset.v ?? c?.textContent.trim() ?? "";
        const n = parseFloat(v.replace(/[£,%+mk]/g, ""));
        return isNaN(n) ? v.toLowerCase() : n;
      };
      rows.sort((a, b) => (val(a) > val(b) ? dir : val(a) < val(b) ? -dir : 0));
      body.querySelectorAll("tr.group").forEach((g) => g.remove());
      rows.forEach((r) => body.appendChild(r));
    })
  );
}

// rows with data-href navigate on click (links inside still work normally)
function clickableRows(root) {
  root.querySelectorAll("tr[data-href]").forEach((tr) =>
    tr.addEventListener("click", (e) => { if (!e.target.closest("a")) location.hash = tr.dataset.href; }));
}

// ------------------------------------------------------------------ header / capture
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    if (NEEDS_CLUB && !s.needs_club) { NEEDS_CLUB = false; route(); }
    NEEDS_CLUB = !!s.needs_club;
    if (s.remote && !REMOTE) {
      REMOTE = true;
      document.body.classList.add("remote");
      const st = $('#nav a[href="#settings"]');
      if (st) st.textContent = "Device";
      $("#snapChip").removeAttribute("href");
      if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
    const sv = s.save;
    const chip = $("#snapChip");
    chip.classList.toggle("hidden", !sv);
    if (sv) {
      chip.textContent = sv.name || sv.club || `Game #${sv.id}`;
      chip.title = `Game snapshot in use: ${sv.label}${sv.club ? ` · ${sv.club}` : ""}\n`
        + (REMOTE ? "Switch or start a new game in Settings on your PC" : "Switch or start a new game in Settings");
    }
    const gs = $("#gameState");
    gs.classList.toggle("on", !!s.game_running);
    const loadingSave = s.game_running && (s.health || {}).status === "loading";
    gs.querySelector(".glbl").textContent = !s.game_running ? "Game not running" : loadingSave ? "Loading save…" : "Game running";
    gs.title = !s.game_running ? "Start FM26 to capture" : loadingSave
      ? "FM26 is running but your save isn't readable yet (still loading?). Captures start once it is; this re-checks by itself."
      : "FM26 is running: captures can be taken";
    const lc = $("#lastCap");
    lc.textContent = s.latest ? `Updated ${fmtDate(s.latest.game_date)}` : "No captures yet";
    lc.title = s.latest ? `Last capture: game date ${s.latest.game_date} (capture #${s.latest.id})` : "Press Capture with FM26 running";
    const a = s.auto || {};
    $("#autoHdr").checked = !!a.enabled;
    $("#autoWrap").title = a.enabled
      ? `Auto-capture on: captures by itself after every match\n${a.status || ""}${a.next ? "\nNext: " + a.next : ""}`
        + `${a.last_reason ? "\nLast: " + a.last_reason + " (" + a.last_at + ")" : ""}\nClick to turn off`
      : "Auto-capture off: click to capture by itself after every match";
    if (sv) {   // the game snapshot in use changed since last time (a different save was detected, or it was switched)
      let seen = null;
      try { seen = localStorage.getItem("saveSeen"); localStorage.setItem("saveSeen", String(sv.id)); } catch { /* private mode */ }
      if (seen && seen !== String(sv.id)) { toast(`Now using game snapshot ${sv.label}`); route(); }
    }
    const h = s.health || {};
    const hb = $("#healthBanner");
    const failing = s.game_running && (h.status === "unknown_build" || h.status === "failed");
    hb.classList.toggle("hidden", !failing);
    if (failing) {
      hb.innerHTML = `<b>⚠ ${h.status === "unknown_build" ? "FM26 has been updated" : "The reader doesn't match this game build"}.</b>
        ${h.status === "unknown_build"
          ? `This game build (${esc(h.build_id || "?")}) has no reader profile yet, so the app can't read it safely.`
          : `The self-check found values that don't look right, so the app's memory offsets have probably moved.`}
        Captures and auto-capture are <b>paused</b>; your stored history is safe and the dashboard still works.
        The reader needs recalibrating for this build before captures resume.
        <details><summary>Self-check details</summary><ul>${(h.checks || []).map((c) =>
          `<li class="${c.ok ? "up" : "down"}">${c.ok ? "✓" : "✗"} ${esc(c.name)}: ${esc(c.detail || "")}</li>`).join("")}</ul></details>
        <button class="secondary" id="recheckBtn">Check again</button>`;
      $("#recheckBtn").addEventListener("click", async () => { await api("/api/health/recheck", { method: "POST" });
        toast("Re-checking the reader…"); setTimeout(refreshStatus, 4000); });
    }
    $("#captureBtn").disabled = !s.game_running || failing || NEEDS_CLUB;
    $("#captureBtn").title = failing ? "Paused: reader self-check failed for this game build"
      : `Capture now (or press ${String(s.hotkey || "").toUpperCase()} in game)`;
  } catch (e) {
    $("#gameState").classList.remove("on");
    $("#gameState .glbl").textContent = "App not responding";
    $("#lastCap").textContent = "";
  }
}
$("#autoHdr").addEventListener("change", (e) => setAuto(e.target.checked));
const fmtDate = (iso) => {
  const d = new Date(`${iso}T00:00:00`);
  return isNaN(d) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

async function setAuto(on) {
  await api("/api/auto", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: on }) });
  toast(on ? "Auto-capture on: captures after every match" : "Auto-capture off");
  refreshStatus();
  if (location.hash.startsWith("#settings")) settingsPage();
}

async function capture() {
  const btn = $("#captureBtn");
  btn.disabled = true;
  btn.textContent = "Capturing…";
  await api("/api/capture", { method: "POST" });
  const poll = async () => {
    const s = await api("/api/capture");
    if (s.running) {
      btn.textContent = `Capturing… ${Math.round(s.elapsed || 0)}s`;
      return setTimeout(poll, 1000);
    }
    btn.textContent = "Capture";
    btn.disabled = false;
    const l = s.last;
    if (l && l.ok) toast((l.new_save ? `A different save game was detected: started a new game snapshot (#${l.save_id}). ` : "")
      + (l.rewound_from ? `Game date went back from ${l.rewound_from}: an older save file was loaded. ` : "")
      + `Capture #${l.snapshot_id} (${l.game_date}): ${l.players} players, ${l.new_matches} new match(es), ${l.seconds}s`);
    else if (l) toast(`Capture failed: ${l.error}`, true);
    refreshStatus();
    route();
  };
  poll();
}
$("#captureBtn").addEventListener("click", capture);

// ------------------------------------------------------------------ shared: match card
function matchCard(summary, players, nav = null) {
  const s = summary;
  const head = `<h1>${esc(s.date)} · ${venueWord(s.venue)} ${esc(s.opponent)} ${res(s.result)} ${esc(s.score)}
      ${s.pens ? `<span class="muted">(${esc(s.pens)} pens)</span>` : ""}</h1><div class="muted">${esc(s.competition)}</div>`;
  const navBar = nav ? `<div class="matchnav">
      ${nav.previous ? `<a class="btn secondary" href="#match/${nav.previous}">← Previous</a>` : '<span class="btn secondary disabled">← Previous</span>'}
      <a class="btn secondary" href="#fixtures">All fixtures</a>
      ${nav.next ? `<a class="btn secondary" href="#match/${nav.next}">Next →</a>` : '<span class="btn secondary disabled">Next →</span>'}</div>` : "";
  if (!s.has_stats) {
    return `${navBar}${head}<div class="empty">No player stats were captured for this match. FM only keeps the last few
      matches in memory, so capture after each game.</div>`;
  }
  const tabs = Object.keys(MATCH_TABS);
  return `${navBar}${head}
    <div class="kpis tiles" style="margin-top:12px">
      ${kpi(esc(s.score), "score")}${kpi(s.goals, "goals by our players")}${kpi(num(s.xg), "team xG")}
      ${kpi(rating(s.avg_rating), "avg rating")}
      ${(() => { const best = players[0]; return best ? kpiWide(esc(best.name) + " " + rating(best.rating), "best rated") : ""; })()}
      ${(() => { const tot = (k) => players.reduce((a, p) => a + ((p.counters || {})[k] || 0), 0);
        return kpi(`${tot("shots_on_target")}/${tot("shots")}`, "shots on target") + kpi(tot("key_passes"), "key passes")
          + kpi(tot("tackles_won"), "tackles won"); })()}
    </div>
    <div class="tabs">${tabs.map((t, i) => `<button class="tab ${i ? "" : "on"}" data-tab="${t}">${t}</button>`).join("")}</div>
    ${tabs.map((t, i) => `<div class="scroll tabpane ${i ? "hidden" : ""}" data-pane="${t}"><table class="mt"><thead><tr><th>Player</th><th>Min</th>
      ${MATCH_TABS[t].map(([h]) => thTip(h)).join("")}</tr></thead><tbody>
      ${players.map((p) => `<tr><td>${playerLink(p.unique_id, p.name)}${p.started ? "" : ' <span class="muted">(sub)</span>'}</td>
        <td>${p.minutes}</td>${MATCH_TABS[t].map(([, f]) => { const v = f(p);
          const dv = typeof v === "number" ? v : v && typeof v === "object" ? v.v : null;
          return `<td${dv != null ? ` data-v="${dv}"` : ""}>${cellFmt(v)}</td>`; }).join("")}</tr>`).join("")}
    </tbody></table></div>`).join("")}`;
}

// report-style tabs; each column: [header, value(player)] - numbers are shown as-is, strings as given
const c = (p, k) => (p.counters || {})[k] ?? 0;
const ratio = (p, done, att) => { const a = c(p, att), d = c(p, done); return a ? `${d}/${a} <span class="muted">${Math.round(100 * d / a)}%</span>` : "–"; };
const MATCH_TABS = {
  "Key Statistics": [["Rating", (p) => ({ html: rating(p.rating), v: p.rating })], ["G", (p) => p.goals], ["A", (p) => p.assists],
    ["xG", (p) => num(p.xg)], ["xA", (p) => num(p.xa)], ["Pass %", (p) => (p.pass_pct == null ? "–" : num(p.pass_pct, 0))],
    ["Passes", (p) => `${p.passes_completed}/${p.passes_attempted}`], ["km", (p) => num(p.distance_km, 1)]],
  Passing: [["Passes", (p) => (p.passes_attempted ? `${p.passes_completed}/${p.passes_attempted} <span class="muted">${num(p.pass_pct, 0)}%</span>` : "–")],
    ["Crosses", (p) => ratio(p, "crosses_completed", "crosses_attempted")], ["Progressive", (p) => c(p, "progressive_passes")],
    ["Key passes", (p) => c(p, "key_passes")], ["xA", (p) => num(p.xa)], ["Assists", (p) => p.assists]],
  Attacking: [["Shots (on target)", (p) => ratio(p, "shots_on_target", "shots")], ["Goals", (p) => p.goals], ["xG", (p) => num(p.xg)],
    ["Hit woodwork", (p) => c(p, "shots_woodwork")], ["Dribbles", (p) => c(p, "dribbles")], ["Fouls won", (p) => c(p, "fouls_against")],
    ["km", (p) => num(p.distance_km, 1)]],
  Defending: [["Tackles won", (p) => ratio(p, "tackles_won", "tackles_attempted")], ["Headers won", (p) => ratio(p, "headers_won", "headers_attempted")],
    ["Interceptions", (p) => c(p, "interceptions")], ["Clearances", (p) => c(p, "clearances")], ["Fouls made", (p) => c(p, "fouls_made")]],
  Goalkeeping: [["Shots faced", (p) => c(p, "shots_faced")], ["Saves held", (p) => c(p, "saves_held")], ["Saves parried", (p) => c(p, "saves_parried")],
    ["Saves tipped", (p) => c(p, "saves_tipped")], ["Saves", (p) => c(p, "saves_held") + c(p, "saves_parried") + c(p, "saves_tipped")]],
  "Set Pieces": [["Throw-ins", (p) => c(p, "throw_ins")], ["Corners", (p) => c(p, "corners")],
    ["Defending free kicks", (p) => c(p, "defending_free_kicks")], ["Attacking free kicks", (p) => c(p, "attacking_free_kicks")]],
};
const cellFmt = (v) => (v && typeof v === "object" ? v.html : v);
// full names for short column headers, shown on hover
const HEAD_TIPS = { G: "Goals", A: "Assists", xG: "Expected goals", xA: "Expected assists", km: "Distance covered (km)",
  "Pass %": "Pass completion %", Min: "Minutes played", Res: "Result", "Shots faced": "Shots on target faced",
  "Δ CA": "Change in current ability", Headroom: "PA − CA: room left to grow", Tech: "Technical attributes changed (raw)",
  Ment: "Mental attributes changed (raw)", Phys: "Physical attributes changed (raw)", GK: "Goalkeeping attributes changed (raw)",
  Hidden: "Hidden attributes changed (raw), e.g. consistency, important matches", Jaded: "Jadedness: over 300 needs a rest",
  CA: "Current ability (out of 200)", PA: "Potential ability (out of 200)", "Wage/wk": "Wage per week",
  Match: "Similarity: 60% position overlap + 40% attribute closeness" };
Object.assign(HEAD_TIPS, { Avg: "Average match rating", Apps: "Appearances in captured matches", Starts: "Matches started",
  Form: "Ratings in the last captured matches" });
const thTip = (h, cls = "") => `<th${cls ? ` class="${cls}"` : ""}${HEAD_TIPS[h] ? ` title="${esc(HEAD_TIPS[h])}"` : ""}>${h}</th>`;
function tipHeaders(root = document) {      // any table header without a title gets one from HEAD_TIPS
  root.querySelectorAll("th:not([title])").forEach((th) => {
    const t = HEAD_TIPS[th.textContent.trim()];
    if (t) th.title = t;
  });
}

function wireTabs(root) {
  root.querySelectorAll(".tabs").forEach((bar) => bar.addEventListener("click", (e) => {
    const b = e.target.closest(".tab");
    if (!b) return;
    bar.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x === b));
    bar.parentElement.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== b.dataset.tab));
  }));
}

// ------------------------------------------------------------------ views
async function overview() {
  if (NEEDS_CLUB) return clubSetup();
  const o = await api("/api/overview");
  const lm = o.last_match.summary;
  const tf = o.team_form;
  let html = `<div class="grid">`;
  html += lm ? `<div class="card wide"><div class="cardhead"><h2>Last match</h2>
      <a class="btn secondary" href="#fixtures">All fixtures</a></div>${matchCard(lm, o.last_match.players)}</div>`
    : `<div class="card wide empty">No match stats yet. Play a match, then press Capture (or the hotkey).</div>`;
  html += `<div class="card"><div class="cardhead">${h2i(`Team form · last ${tf.results.length}`,
      "Competitive matches only (friendlies are left out). Click a result to open the match; 📊 = player stats were captured for it.")}
      <a class="btn secondary" href="#fixtures">All fixtures</a></div>
      <div class="formstr" style="font-size:16px;margin-bottom:8px">${tf.results.map((r) => matchLink(r.fixture_id, res(r.result))).join("")}</div>
      <div class="kpis tiles">${kpi(tf.points, "points", tf.points / (3 * tf.results.length || 1), "var(--good)")}
        ${kpi(`${tf.goals_for}–${tf.goals_against}`, "goals")}${kpi(tf.unbeaten_run, "unbeaten run")}</div>
      <table class="form"><tbody>${tf.results.slice().reverse().map((r) => `<tr class="clickrow" data-href="match/${r.fixture_id}"
        title="${esc(r.competition)}"><td class="l date">${r.date}</td><td class="l">${r.venue}</td>
        <td class="l opp">${esc(r.opponent)}</td><td>${r.gf}–${r.ga}</td><td>${res(r.result)}</td>
        <td class="l comp muted">${esc(shortComp(r.competition))}</td><td class="stats">${r.has_stats ? "📊" : ""}</td></tr>`).join("")}</tbody></table></div>`;
  html += `<div class="card"><div class="cardhead"><h2>Next fixtures</h2><a class="btn secondary" href="#fixtures">All fixtures</a></div>
      ${o.upcoming.length ? `<table class="form"><tbody>${o.upcoming.map((f) => `<tr title="${esc(f.competition)}">
        <td class="l date">${f.date}</td><td class="l">${f.venue}</td><td class="l opp">${esc(f.opponent)}</td>
        <td class="ko">${esc(f.kickoff || "")}</td><td class="l comp muted">${esc(shortComp(f.competition))}</td></tr>`).join("")}</tbody></table>`
        : '<div class="empty">No upcoming fixtures captured yet - press Capture.</div>'}</div>`;
  html += `<div class="card">${h2i("Alerts", "From the latest capture: injuries, condition under 85%, sharpness under 70%, "
      + "jadedness over 300 (needs a rest), and contracts ending within 12 months.")}${o.alerts.length ? o.alerts.map((a) =>
      `<div class="alert"><span class="k">${esc(a.kind)}</span>${playerLink(a.unique_id, a.name)}<span class="muted">${esc(a.detail)}</span></div>`).join("")
      : '<div class="empty">Nothing to flag</div>'}</div>`;
  html += `<div class="card">${h2i("In form · top 5", "Ranked on the average of the last 3 ratings, plus the trend and goal "
      + "involvements, over the last 5 captured matches. Needs at least 2 appearances in those matches.")}${o.in_form.length ? `<table class="form"><tbody>${o.in_form.map((p, i) =>
      `<tr class="clickrow" data-href="player/${p.unique_id}" title="${esc(p.why)}"><td class="rank">${i + 1}</td>
        <td class="l opp">${esc(p.name)}<div class="muted small0">${esc(p.why)}</div></td>
        <td class="sparkcell">${spark(p.ratings)}</td><td>${rating(p.ratings[p.ratings.length - 1])}</td></tr>`).join("")}</tbody></table>`
      : '<div class="empty">Needs at least two captured matches</div>'}</div>`;
  const nm = o.next_match, nx = o.upcoming[0];
  const fitTag = (p) => `<span style="color:${condColor(p.condition)}">${num(p.condition, 0)}%</span>`;
  html += `<div class="card span2">${h2i(`Recommended for next match${nx ? ` · ${nx.venue === "A" ? "at" : "vs"} ${esc(nx.opponent)}` : ""}`,
      `Scores combine form and trend over the last ${nm.basis.matches || 0} captured matches, goal involvements, xG+xA per 90 and
      ability, with condition, sharpness, jadedness and recent minutes from the latest capture (${esc(nm.basis.condition_at || "?")}).
      <br><br><b>Rest:</b> injured, condition under 85% or jadedness over 300. <b>Rotation</b> pairs a regular starter who needs a rest,
      or is tiring, with the best fit player in the same position group.`)}
      <div class="nextgrid">
      ${nm.swaps.length ? `<div class="swaps"><div class="sub">Rotation</div>${nm.swaps.map((w) => `<div class="swap ${w.must ? "must" : ""}">
        <span class="muted small0">${esc(w.group)}</span>
        <div>${playerLink(w.out.unique_id, w.out.name)} ${fitTag(w.out)} <span class="arrow">→</span>
          ${playerLink(w.in.unique_id, w.in.name)} ${fitTag(w.in)}</div>
        <div class="muted small0">${esc(w.reason)}</div></div>`).join("")}</div>` : ""}
      ${nm.recommended.length ? `<div><div class="sub">Best placed to start</div><table class="form"><tbody>${nm.recommended.map((p, i) =>
        `<tr class="clickrow" data-href="player/${p.unique_id}" title="${esc(p.why)}"><td class="rank">${i + 1}</td>
          <td class="l opp">${esc(p.name)} <span class="muted">${esc(p.position || "")}</span>
            <div class="muted small0">${esc(p.why)}${p.caution.length ? ` · <span class="down">${esc(p.caution.join(", "))}</span>` : ""}</div></td>
          <td>${rating(p.score)}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty">No captured squad yet</div>'}
      </div></div>`;
  html += `</div>`;
  view.innerHTML = html;
  view.querySelectorAll("table.mt").forEach(sortable);
  wireTabs(view);
  clickableRows(view);
}

async function matchPage(id) {
  const m = await api(`/api/match/${id}`);
  view.innerHTML = `<div class="card wide">${matchCard(m.summary, m.players, m)}</div>`;
  view.querySelectorAll("table.mt").forEach(sortable);
  wireTabs(view);
}

const STATUS_TITLES = { "first team": "First team", "loaned in": "Loaned in", "youth team": "Youth teams",
  "loaned out": "Out on loan", "no contract": "No contract (academy / trialists)" };

async function playersPage() {
  const d = await api("/api/players");
  const statuses = Object.keys(STATUS_TITLES);
  const counts = Object.fromEntries(statuses.map((s) => [s, d.players.filter((p) => p.status === s).length]));
  const saved = JSON.parse(localStorage.getItem("playerFilters") || "null") || ["first team", "loaned in", "youth team", "loaned out"];
  const row = (p) => `<tr data-status="${p.status}"><td>${playerLink(p.unique_id, p.name)}${injBadge(p.injury)}</td><td>${p.age ?? "–"}</td>
    <td class="l">${esc(p.position || "–")}</td><td class="l where">${esc(p.where)}</td><td>${p.ca}</td><td>${p.pa ?? "?"}</td>
    <td data-v="${p.condition}">${num(p.condition, 0)}% ${bar(p.condition, condColor(p.condition))}</td>
    <td data-v="${p.sharpness}">${num(p.sharpness, 0)}% ${bar(p.sharpness, condColor(p.sharpness))}</td>
    <td>${p.jadedness}</td><td>${p.apps}</td><td data-v="${p.avg_rating ?? 0}">${rating(p.avg_rating)}</td>
    <td data-v="${p.form.length ? p.form[p.form.length - 1] : 0}">${spark(p.form)} ${p.form_label ? `<span class="pill ${p.form_label}">${p.form_label}</span>` : ""}</td>
    <td data-v="${p.value}">${money(p.value)}</td><td data-v="${p.wage_per_week}">${money(p.wage_per_week)}</td>
    <td class="l">${p.status === "loaned in" ? '<span class="muted">loan</span>' : esc(p.contract_expires || "–")}</td>
    <td><a href="#compare/${p.unique_id}">compare</a></td></tr>`;
  const cols = 16;
  view.innerHTML = `<div class="card wide"><h2>All players · ${d.game_date || ""} · ${d.players.length} total</h2>
    <div class="filters">${statuses.map((s) => `<label><input type="checkbox" class="sf" value="${s}" ${saved.includes(s) ? "checked" : ""}>
      ${STATUS_TITLES[s]} <span class="muted">(${counts[s]})</span></label>`).join("")}
      <input id="search" placeholder="Search name / position / club…"></div>
    <div class="scroll"><table id="sq"><thead><tr><th>Player</th><th>Age</th><th class="l">Position</th><th class="l">At</th><th>CA</th><th>PA</th>
      <th>Condition</th><th>Sharpness</th><th>Jaded</th><th>Apps</th><th>Avg</th><th>Form</th><th>Value</th>
      <th>Wage/wk</th><th>Contract</th><th></th></tr></thead><tbody>
      ${statuses.map((s) => d.players.filter((p) => p.status === s).length
        ? `<tr class="group" data-status="${s}"><td colspan="${cols}">${STATUS_TITLES[s]}</td></tr>` + d.players.filter((p) => p.status === s).map(row).join("") : "").join("")}
    </tbody></table></div></div>`;
  const apply = () => {
    const on = new Set([...document.querySelectorAll(".sf:checked")].map((c) => c.value));
    localStorage.setItem("playerFilters", JSON.stringify([...on]));
    const q = $("#search").value.toLowerCase();
    document.querySelectorAll("#sq tbody tr").forEach((r) => {
      const match = r.classList.contains("group") || !q || r.textContent.toLowerCase().includes(q);
      r.style.display = on.has(r.dataset.status) && match ? "" : "none";
    });
  };
  document.querySelectorAll(".sf").forEach((c) => c.addEventListener("change", apply));
  $("#search").addEventListener("input", apply);
  apply();
  sortable($("#sq"));
}

function attrBlocks(attrs, history, isGK) {
  const groupNames = { technical: "Technical", mental: "Mental", physical: "Physical", goalkeeping: "Goalkeeping", hidden: "Hidden", other: "Other" };
  return Object.entries(attrs).filter(([g, a]) => Object.keys(a).length && (g !== "goalkeeping" || isGK))
    .map(([g, a]) => `<div><h2>${groupNames[g] || g}</h2>${Object.entries(a).map(([k, raw]) => {
      const hist = history[k] || [];
      const first = hist.length ? hist[0].raw : raw;
      const v = shown(raw), cls = v >= 16 ? "a20" : v >= 13 ? "a15" : v >= 8 ? "a10" : "a5";
      const ch = raw - first;
      return `<div class="row"><span>${label(k)}</span><span><span class="muted" style="font-size:11px">${ch ? (ch > 0 ? "+" : "") + ch + "raw " : ""}</span><span class="val ${cls}">${v}</span></span></div>`;
    }).join("")}</div>`).join("");
}

const RADAR_KEYS = {
  gk: ["reflexes", "handling", "one_on_ones", "aerial_reach", "command_of_area", "kicking", "positioning", "concentration"],
  outfield: ["finishing", "dribbling", "passing", "first_touch", "technique", "vision", "decisions", "anticipation", "work_rate", "pace", "acceleration", "strength", "stamina", "tackling"],
};

async function playerPage(uid) {
  const [d, sim, all] = await Promise.all([api(`/api/player/${uid}`), api(`/api/similar/${uid}`), api("/api/players")]);
  const p = d.player;
  const h = d.history;
  const now = h[h.length - 1] || {};
  const t = d.totals;
  const me = all.players.find((x) => x.unique_id === Number(uid)) || {};
  const isGK = (d.attributes.goalkeeping?.reflexes || 0) > 50;
  view.innerHTML = `<div class="grid">
    <div class="card wide"><div class="cardhead"><div><h1>${esc(p.name)}</h1>
      <div class="muted">${esc(me.position || "")} · ${esc(now.status || "")} · ${esc(me.where || "")} · born ${esc(p.dob || "?")}</div>
      ${me.injury ? `<div class="injline">🩹 Injured since ${esc(me.injury.since)} · ${esc(injBack(me.injury))}</div>` : ""}</div>
      <div><select id="cmpWith"><option value="">Compare with…</option>${all.players.filter((x) => x.unique_id !== Number(uid))
        .map((x) => `<option value="${x.unique_id}">${esc(x.name)} (${esc(x.primary || "?")}, ${x.status})</option>`).join("")}</select></div></div>
      <div class="kpis tiles" style="margin-top:12px">
        ${kpi(me.age ?? "–", "age")}${kpi(esc(me.primary || "–"), "position")}
        ${kpi(now.ca ?? "–", "current ability", (now.ca ?? 0) / 200)}${kpi(now.pa ?? "?", "potential", (now.pa ?? 0) / 200)}
        ${kpi(num(now.condition, 0) + "%", "condition", (now.condition ?? 0) / 100, condColor(now.condition))}
        ${kpi(num(now.sharpness, 0) + "%", "sharpness", (now.sharpness ?? 0) / 100, condColor(now.sharpness))}
        ${kpi(money(now.value), "value")}
        ${d.goalkeeping ? kpi(d.goalkeeping.apps, "apps stored") + kpi(rating(d.goalkeeping.avg_rating), "avg rating")
          + kpi(`${num(d.goalkeeping.save_pct, 1)}%`, "save %", (d.goalkeeping.save_pct || 0) / 100, "var(--good)")
          + kpi(d.goalkeeping.clean_sheets, "clean sheets") + kpi(num(d.goalkeeping.conceded_per90), "conceded / 90")
          : t ? kpi(t.apps, "apps stored") + kpi(rating(t.avg_rating), "avg rating") + kpi(`${t.goals}+${t.assists}`, "goals + assists")
          + kpi(num(t.per90s?.xg_plus_xa), "xG+xA / 90") : ""}
      </div></div>
    <div class="card"><h2>Attribute profile</h2><canvas id="radar"></canvas></div>
    ${d.roles ? `<div class="card">${h2i("Role profile", "Each score is 0–100 against your own outfield players with 180+ "
      + "captured minutes: 100 = best in your squad. " + ROLE_KEYS.map((k) => `<br><b>${esc(d.role_labels[k])}:</b> ${esc(ROLE_TIPS[k])}`).join(""))}
      ${roleBars(d.roles, d.role_labels)}</div>` : ""}
    <div class="card">${h2i("Similar players in your club", "Match = 60% position overlap + 40% attribute closeness. "
      + "Hover a match % for the split.")}
      <table><thead><tr><th>Player</th><th class="l">Position</th><th class="l">At</th><th>CA</th><th>Match</th><th></th></tr></thead><tbody>
      ${sim.similar.map((s) => `<tr><td>${playerLink(s.unique_id, s.name)}</td><td class="l">${esc(s.position || "–")}</td>
        <td class="l where">${esc(s.where)}</td><td>${s.ca}</td>
        <td title="position ${s.position_match}% · attributes ${s.attribute_match}%">${s.score}%</td>
        <td><a href="#compare/${uid}/${s.unique_id}">compare</a></td></tr>`).join("")}</tbody></table></div>
    <div class="card"><h2>Positions</h2><div id="pitch"></div></div>
    <div class="card"><h2>CA over time</h2><canvas id="ca"></canvas></div>
    <div class="card wide"><h2>Attributes</h2><div class="attrs">${attrBlocks(d.attributes, d.attribute_history, isGK)}</div></div>
    <div class="card wide"><h2>Match log</h2>${d.matches.length ? `<canvas id="ratings" style="max-height:200px"></canvas>
      <div class="scroll"><table><thead><tr><th>Date</th><th class="l">Opponent</th><th>Res</th><th>Min</th><th>Rating</th>
      <th>G</th><th>A</th><th>xG</th><th>xA</th><th>Pass %</th><th>km</th></tr></thead><tbody>
      ${d.matches.slice().reverse().map((m) => `<tr class="clickrow" data-href="match/${m.fixture_id}"><td>${m.date}</td><td class="l">${m.venue} ${esc(m.opponent)}</td>
        <td>${res(m.result)} ${m.score}</td><td>${m.minutes}</td><td>${rating(m.rating)}</td><td>${m.goals}</td>
        <td>${m.assists}</td><td>${num(m.xg)}</td><td>${num(m.xa)}</td><td>${m.pass_pct == null ? "–" : num(m.pass_pct, 0)}</td>
        <td>${num(m.distance_km, 1)}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty">No stored matches</div>'}</div>
  </div>`;
  $("#cmpWith").addEventListener("change", (e) => e.target.value && (location.hash = `compare/${uid}/${e.target.value}`));
  $("#pitch").innerHTML = pitch(me.positions || {});
  clickableRows(view);
  const flat = Object.assign({}, ...Object.values(d.attributes));
  const key = RADAR_KEYS[isGK ? "gk" : "outfield"];
  chart($("#radar"), radarCfg(key, [{ label: p.name, attrs: flat }]));
  chart($("#ca"), { type: "line", data: { labels: h.map((x) => x.game_date),
    datasets: [{ label: "CA", data: h.map((x) => x.ca), borderColor: "#58a6ff", tension: .2 },
               { label: "PA", data: h.map((x) => x.pa), borderColor: "#8b98a8", borderDash: [4, 4], pointRadius: 0 }] },
    options: { plugins: { legend: { labels: { color: "#e6edf3" } } }, scales: { x: { grid: GRID, ticks: TICK }, y: { grid: GRID, ticks: TICK } } } });
  if ($("#ratings")) chart($("#ratings"), { type: "bar", data: { labels: d.matches.map((m) => `${m.date} ${m.opponent}`),
    datasets: [{ data: d.matches.map((m) => m.rating), backgroundColor: d.matches.map((m) => m.rating >= 7.5 ? "#3fb950" : m.rating >= 7 ? "#a3c94f" : m.rating >= 6.7 ? "#d29922" : "#f85149") }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { min: 5, max: 10, grid: GRID, ticks: TICK } } } });
}

// attribute value (1-20) -> colour: red (poor) -> orange -> yellow-green -> green (excellent)
const ATTR_STOPS = [[1, [248, 81, 73]], [8, [240, 136, 62]], [12, [210, 170, 60]], [15, [163, 201, 79]], [18, [63, 185, 80]]];
function attrColor(v) {
  if (v <= ATTR_STOPS[0][0]) return `rgb(${ATTR_STOPS[0][1]})`;
  for (let i = 1; i < ATTR_STOPS.length; i++) {
    const [v1, c1] = ATTR_STOPS[i], [v0, c0] = ATTR_STOPS[i - 1];
    if (v <= v1) { const t = (v - v0) / (v1 - v0); return `rgb(${c0.map((c, j) => Math.round(c + (c1[j] - c) * t))})`; }
  }
  return `rgb(${ATTR_STOPS[ATTR_STOPS.length - 1][1]})`;
}

function radarCfg(keys, players) {
  const single = players.length === 1;
  const datasets = players.map((p, i) => {
    const data = keys.map((k) => shown(p.attrs[k] || 0));
    return single ? {
      label: p.label || p.name || "", data,
      backgroundColor: "rgba(139,152,168,.14)", borderColor: "#8b98a8",
      pointBackgroundColor: data.map(attrColor), pointBorderColor: data.map(attrColor),
      // each outline segment takes the colour of the average of its two ends
      segment: { borderColor: (ctx) => attrColor((ctx.p0.raw + ctx.p1.raw) / 2) },
      valueColors: true,
    } : {
      label: p.label || p.name || "", data, backgroundColor: COLORS[i] + "26", borderColor: COLORS[i],
      pointBackgroundColor: COLORS[i], valueColors: true,
    };
  });
  return { type: "radar", data: { labels: keys.map(label), datasets },
    options: { plugins: { legend: { display: !single, labels: { color: "#e6edf3" } } },
      scales: { r: { min: 0, max: 20, grid: GRID, angleLines: GRID, pointLabels: { color: "#e6edf3" }, ticks: { display: false } } } } };
}

// small pitch diagram: position familiarity (bright = natural)
const PITCH = [["ST"], ["AML", "AMC", "AMR"], ["ML", "MC", "MR"], ["WBL", "DM", "WBR"], ["DL", "DC", "DR"], ["GK"]];
const POS_LABEL = { GK: "GK", DL: "D L", DC: "D C", DR: "D R", DM: "DM", WBL: "WB L", WBR: "WB R", ML: "M L", MC: "M C", MR: "M R", AML: "AM L", AMC: "AM C", AMR: "AM R", ST: "ST" };
// familiarity colour: 20 = solid green, 15-19 = orange->green, 5-14 = orange, below 5 = red
const GREEN = [63, 185, 80], ORANGE = [240, 136, 62], RED = [248, 81, 73];
function posColor(v) {
  if (v >= 20) return `rgb(${GREEN})`;
  if (v >= 15) {
    const t = (v - 15) / 5;
    return `rgb(${ORANGE.map((o, i) => Math.round(o + (GREEN[i] - o) * t))})`;
  }
  return v >= 5 ? `rgb(${ORANGE})` : `rgba(${RED},0.55)`;
}
function pitch(pos, other = null) {
  const cell = (p) => {
    const v = pos[p] || 1, o = other ? other[p] || 1 : null;
    const bg = o === null ? posColor(v) : `linear-gradient(90deg, ${posColor(v)} 50%, ${posColor(o)} 50%)`;
    return `<div class="pcell" style="background:${bg}" title="${POS_LABEL[p]}: ${v}${o ? " / " + o : ""}">
      <b>${POS_LABEL[p]}</b><span>${v}${o !== null ? ` · <span style="color:${COLORS[1]}">${o}</span>` : ""}</span></div>`;
  };
  return `<div class="pitch">${PITCH.map((row) => `<div class="prow">${row.map(cell).join("")}</div>`).join("")}</div>`;
}

async function comparePage(a, b) {
  const all = await api("/api/players");
  const opts = (sel) => `<option value="">Choose a player…</option>` + all.players.map((x) =>
    `<option value="${x.unique_id}" ${String(x.unique_id) === String(sel) ? "selected" : ""}>${esc(x.name)} (${esc(x.primary || "?")}, ${x.status})</option>`).join("");
  let html = `<div class="card wide"><h2>Compare players</h2><div class="cmpsel">
    <select id="ca">${opts(a)}</select><span class="muted">vs</span><select id="cb">${opts(b)}</select>
    ${a && !b ? `<span class="muted">or pick a similar player below</span>` : ""}</div></div>`;
  if (a && !b) {
    const sim = await api(`/api/similar/${a}`);
    html += `<div class="card wide"><h2>Similar players</h2><table><tbody>${sim.similar.map((s) => `<tr class="clickrow" data-href="compare/${a}/${s.unique_id}">
      <td>${esc(s.name)}</td><td class="l">${esc(s.position || "")}</td><td class="l where">${esc(s.where)}</td><td>CA ${s.ca}</td><td>${s.score}% match</td></tr>`).join("")}</tbody></table></div>`;
  }
  if (a && b) {
    const c = await api(`/api/compare?a=${a}&b=${b}`);
    const [p, q] = c.players;
    const isGK = (p.positions.GK || 1) >= 15 && (q.positions.GK || 1) >= 15;
    const kv = (lbl, x, y, fmt = (v) => v ?? "–", higherBetter = true) => {
      const better = x != null && y != null && x !== y ? ((x > y) === higherBetter ? 0 : 1) : -1;
      return `<tr><td class="l">${lbl}</td><td class="${better === 0 ? "win" : ""}">${fmt(x)}</td><td class="${better === 1 ? "win" : ""}">${fmt(y)}</td></tr>`;
    };
    const tp = p.totals || {}, tq = q.totals || {};
    const p9 = (t, k) => t.per90 ? t.per90[k] : null;
    html += `<div class="grid">
      <div class="card">${h2i(`Overview · position match ${c.position_match}% · attribute match ${c.attribute_match}%`,
        "<b>Green</b> = the better value of the two. Match stats (apps, ratings, per 90s) only cover games captured so far. "
        + "Position match compares how well they know each position; attribute match compares the attributes that matter for their role.")}
        <table class="cmp"><thead><tr><th class="l"></th><th style="color:${COLORS[0]}">${playerLink(p.unique_id, p.name)}</th>
          <th style="color:${COLORS[1]}">${playerLink(q.unique_id, q.name)}</th></tr></thead><tbody>
        ${kv("Position", p.position, q.position, (v) => esc(v || "–"), true).replace(/class="win"/g, "")}
        ${kv("At", p.where, q.where, (v) => esc(v)).replace(/class="win"/g, "")}
        ${kv("Age", p.age, q.age, undefined, false)}
        ${kv("CA", p.ca, q.ca)}${kv("PA", p.pa, q.pa)}
        ${kv("Condition", p.condition, q.condition, (v) => num(v, 0) + "%")}${kv("Sharpness", p.sharpness, q.sharpness, (v) => num(v, 0) + "%")}
        ${kv("Value", p.value, q.value, money)}${kv("Wage / week", p.wage_per_week, q.wage_per_week, money, false)}
        ${kv("Apps (stored)", tp.apps, tq.apps)}${kv("Avg rating", tp.avg_rating, tq.avg_rating, (v) => num(v))}
        ${kv("Goals", tp.goals, tq.goals)}${kv("Assists", tp.assists, tq.assists)}
        ${kv("xG+xA / 90", p9(tp, "xg_plus_xa"), p9(tq, "xg_plus_xa"), (v) => num(v))}
        ${kv("G+A / 90", p9(tp, "goal_involvements"), p9(tq, "goal_involvements"), (v) => num(v))}
        ${kv("Goals − xG", tp.goals_minus_xg, tq.goals_minus_xg, (v) => num(v))}
        ${kv("Pass %", tp.pass_pct, tq.pass_pct, (v) => num(v, 1))}
        ${kv("km / 90", p9(tp, "distance_km"), p9(tq, "distance_km"), (v) => num(v, 1))}
        </tbody></table></div>
      <div class="card"><h2>Attribute profile</h2><canvas id="radar"></canvas></div>
      <div class="card"><h2>Positions <span class="muted">(${esc(p.name)} · <span style="color:${COLORS[1]}">${esc(q.name)}</span>)</span></h2>${pitch(p.positions, q.positions)}</div>
      <div class="card"><h2>CA over time</h2><canvas id="cah"></canvas></div>
      <div class="card wide"><h2>Attributes side by side</h2><div class="attrs">
        ${Object.entries(c.groups).filter(([g, ks]) => ks.length && (g !== "goalkeeping" || isGK)).map(([g, ks]) => `<div><h2>${g}</h2>
          ${ks.map((k) => { const x = shown(p.attributes[k] || 0), y = shown(q.attributes[k] || 0);
            return `<div class="row"><span>${label(k)}</span><span><span class="val ${x > y ? "win" : ""}">${x}</span>
              <span class="muted">·</span> <span class="val ${y > x ? "win" : ""}" style="color:${COLORS[1]}">${y}</span></span></div>`; }).join("")}</div>`).join("")}
      </div></div></div>`;
    view.innerHTML = html;
    const key = RADAR_KEYS[isGK ? "gk" : "outfield"];
    chart($("#radar"), radarCfg(key, [{ label: p.name, attrs: p.attributes }, { label: q.name, attrs: q.attributes }]));
    const dates = [...new Set([...p.ca_history, ...q.ca_history].map((x) => x.game_date))].sort();
    const series = (hist) => dates.map((dt) => (hist.filter((x) => x.game_date === dt).pop() || {}).ca ?? null);
    chart($("#cah"), { type: "line", data: { labels: dates, datasets: [p, q].map((x, i) => ({ label: x.name, data: series(x.ca_history),
      borderColor: COLORS[i], tension: .2, spanGaps: true })) },
      options: { plugins: { legend: { labels: { color: "#e6edf3" } } }, scales: { x: { grid: GRID, ticks: TICK }, y: { grid: GRID, ticks: TICK } } } });
  } else {
    view.innerHTML = html;
  }
  const go = () => { const x = $("#ca").value, y = $("#cb").value; location.hash = `compare/${x}${y ? "/" + y : ""}`; };
  $("#ca").addEventListener("change", go);
  $("#cb").addEventListener("change", go);
  clickableRows(view);
}

async function developmentPage() {
  const days = new URLSearchParams(location.hash.split("?")[1] || "").get("days") || "";
  const d = await api("/api/development" + (days ? `?days=${days}` : ""));
  const pair = d.pair;
  const head = `<div class="card wide">${h2i("Development", "Compares two captures: CA and every attribute. FM shows "
    + "attributes as 1–20, but stores them more finely, so <b>raw</b> changes show progress before the 1–20 number moves. "
    + "Headroom = PA − CA.")}
    <div>Compare over: ${["", "30", "90", "180"].map((x) => `<a href="#development${x ? "?days=" + x : ""}" style="margin-right:10px">${x ? x + " game days" : "all snapshots"}</a>`).join("")}</div>
    ${pair ? `<div class="muted" style="margin-top:6px">snapshot #${pair.before} (${pair.before_date}) → #${pair.after} (${pair.after_date}), ${pair.days} game days</div>` : ""}</div>`;
  if (!pair) { view.innerHTML = head + `<div class="card empty">Needs at least two snapshots.</div>`; return; }
  if (!pair.days) { view.innerHTML = head + `<div class="card empty">All snapshots so far are from the same game date. Capture again after some game time to see development.</div>`; return; }
  const table = (rows, title) => `<div class="card wide"><h2>${title}</h2>${rows.length ? `<div class="scroll"><table class="dev"><thead><tr>
    <th>Player</th><th>Age</th><th>CA</th><th>Δ CA</th><th>PA</th><th>Headroom</th><th>Tech</th><th>Ment</th><th>Phys</th><th>GK</th><th>Hidden</th>
    <th class="l">Biggest changes</th></tr></thead><tbody>${rows.map((x) => `<tr><td>${playerLink(x.unique_id, x.name)}</td><td>${x.age ?? "–"}</td>
      <td>${x.ca_before}→${x.ca_after}</td><td>${delta(x.ca_delta)}</td><td>${x.pa ?? "?"}</td><td>${x.headroom ?? "?"}</td>
      ${["technical", "mental", "physical", "goalkeeping", "hidden"].map((g) => `<td>${delta(x.groups[g])}</td>`).join("")}
      <td class="l">${x.moved.slice(0, 5).map((c) => c.shown_delta ? `<b>${label(c.attr)} ${c.shown_before}→${c.shown_after}</b>` : `${label(c.attr)} ${c.raw_delta > 0 ? "+" : ""}${c.raw_delta}`).join(", ")}</td></tr>`).join("")}
    </tbody></table></div>` : '<div class="empty">None</div>'}</div>`;
  view.innerHTML = head + `<div class="grid">${table(d.improvers, "Improving")}${table(d.decliners, "Declining")}</div>`;
  document.querySelectorAll("table.dev").forEach(sortable);
}

const ROLE_KEYS = ["chance_creation", "goal_threat", "finishing", "defensive_work", "ball_security"];
const roleCell = (v) => (v == null ? '<td class="muted">–</td>'
  : `<td data-v="${v}"><span class="score" style="--c:${attrColor(1 + v * 19 / 100)}">${v}</span></td>`);
const roleBars = (roles, labels) => `<div class="rolebars">${ROLE_KEYS.map((k) => roles[k] == null ? "" : `
  <div class="rb"><span class="l">${esc(labels[k])}</span><span class="bar"><span style="width:${roles[k]}%;background:${attrColor(1 + roles[k] * 19 / 100)}"></span></span>
  <b>${roles[k]}</b></div>`).join("")}</div>`;

async function per90Page() {
  const d = await api("/api/per90");
  const L = d.role_labels;
  const TH = (label, tip) => `<th title="${esc(tip)}">${label}</th>`;
  view.innerHTML = `${d.goalkeepers.length ? `<div class="card wide">${h2i("Goalkeepers · stored matches",
    "<b>Save %</b> = saves ÷ shots on target faced. <b>Goals conceded</b> use the score when the keeper played the full match "
    + "(so own goals count), otherwise shots on target faced minus saves for his minutes. A <b>clean sheet</b> needs 60+ minutes. "
    + "xG prevented isn't available: FM doesn't store the opponents' shot xG.")}
    <div class="scroll"><table id="gk"><thead><tr><th>Keeper</th>${TH("Apps", "Appearances in captured matches")}
      ${TH("Min", "Minutes")}${TH("Avg", "Average match rating")}${TH("Save %", "Saves ÷ shots on target faced")}
      <th>Saves</th><th>Shots on target faced</th>${TH("Conceded", "Goals conceded while on the pitch")}<th>Clean sheets</th>
      ${TH("Saves/90", "Saves per 90 minutes")}${TH("Conceded/90", "Goals conceded per 90 minutes")}
      ${TH("On target faced/90", "Shots on target faced per 90 minutes")}</tr></thead><tbody>
      ${d.goalkeepers.map((g) => `<tr><td>${playerLink(g.unique_id, g.name)}</td><td>${g.apps}</td><td>${g.minutes}</td>
        <td data-v="${g.avg_rating}">${rating(g.avg_rating)}</td><td>${num(g.save_pct, 1)}%</td><td>${g.saves}</td>
        <td>${g.shots_on_target_faced}</td><td>${g.goals_conceded}</td><td>${g.clean_sheets}</td><td>${num(g.saves_per90)}</td>
        <td>${num(g.conceded_per90)}</td><td>${num(g.faced_per90)}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
  <div class="card wide">${h2i("Outfield · per 90 and role scores",
    `<b>Role scores</b> are 0–100 against your own outfield players with ${d.min_minutes}+ captured minutes: 100 = best in your squad.`
    + ROLE_KEYS.map((k) => `<br><b>${esc(L[k])}:</b> ${esc(ROLE_TIPS[k])}`).join("")
    + `<br><br>Per-90 numbers are noisy below ${d.min_minutes} minutes, so those players are hidden by default. Hover a column header for its full name.`)}
    <label><input type="checkbox" id="rel" checked> only players with ≥ ${d.min_minutes} minutes</label>
    <div class="scroll" style="margin-top:10px"><table id="p90"><thead><tr><th>Player</th>
      ${ROLE_KEYS.map((k) => TH(esc(L[k]), ROLE_TIPS[k])).join("")}${TH("Apps", "Appearances in captured matches")}
      ${TH("Starts", "Matches started")}${TH("Min", "Minutes played")}${TH("Avg", "Average match rating")}
      ${TH("G", "Goals")}${TH("A", "Assists")}${TH("xG", "Expected goals")}${TH("xA", "Expected assists")}
      ${TH("G−xG", "Goals minus expected goals: positive = finishing above the chances")}
      ${TH("G+A/90", "Goals + assists per 90")}${TH("xG+xA/90", "Expected goals + expected assists per 90")}
      ${TH("xG/90", "Expected goals per 90")}${TH("xA/90", "Expected assists per 90")}
      ${TH("Pass %", "Pass completion %")}${TH("Passes/90", "Completed passes per 90")}${TH("Key p/90", "Key passes per 90")}
      ${TH("Prog/90", "Progressive passes per 90")}${TH("Drib/90", "Dribbles per 90")}${TH("Shots/90", "Shots per 90")}
      ${TH("Tkl won/90", "Tackles won per 90")}${TH("Int/90", "Interceptions per 90")}${TH("Clr/90", "Clearances per 90")}
      ${TH("Hdr won/90", "Headers won per 90")}${TH("km/90", "Distance covered, km per 90")}</tr></thead><tbody>
      ${d.players.map((a) => `<tr data-rel="${a.per90_reliable}"><td>${playerLink(a.unique_id, a.name)}</td>
        ${ROLE_KEYS.map((k) => roleCell(a.roles ? a.roles[k] : null)).join("")}<td>${a.apps}</td><td>${a.starts}</td>
        <td>${a.minutes}</td><td data-v="${a.avg_rating}">${rating(a.avg_rating)}</td><td>${a.goals}</td><td>${a.assists}</td>
        <td>${num(a.xg)}</td><td>${num(a.xa)}</td><td>${a.goals_minus_xg > 0 ? "+" : ""}${num(a.goals_minus_xg)}</td>
        <td>${num(a.per90s.goal_involvements)}</td><td>${num(a.per90s.xg_plus_xa)}</td><td>${num(a.per90s.xg)}</td>
        <td>${num(a.per90s.xa)}</td><td>${num(a.pass_pct, 1)}</td><td>${num(a.per90s.passes_completed, 1)}</td>
        ${["key_passes", "progressive_passes", "dribbles", "shots", "tackles_won", "interceptions", "clearances", "headers_won"]
          .map((k) => `<td>${num(a.per90s[k])}</td>`).join("")}
        <td>${num(a.per90s.distance_km, 1)}</td></tr>`).join("")}</tbody></table></div></div>`;
  const apply = () => document.querySelectorAll("#p90 tbody tr").forEach((r) =>
    (r.style.display = !$("#rel").checked || r.dataset.rel === "true" ? "" : "none"));
  $("#rel").addEventListener("change", apply);
  apply();
  sortable($("#p90"));
  if ($("#gk")) sortable($("#gk"));
}
const ROLE_TIPS = {
  chance_creation: "Key passes, xA, progressive passes and completed crosses per 90",
  goal_threat: "xG, shots and goals per 90",
  finishing: "Goals minus xG per 90 and shot accuracy (5+ shots)",
  defensive_work: "Tackles won, interceptions, clearances, headers won and key tackles per 90",
  ball_security: "Pass completion % and completed passes per 90",
};

async function fixturesPage() {
  const all = await api("/api/fixtures");
  const upcoming = all.fixtures.filter((f) => f.home_goals == null).reverse();
  const d = { fixtures: all.fixtures.filter((f) => f.home_goals != null) };
  const comps = [...new Set(d.fixtures.map((f) => f.competition))].sort();
  view.innerHTML = `${upcoming.length ? `<div class="card wide"><h2>Upcoming · ${upcoming.length}</h2><div class="scroll"><table id="up"><thead><tr>
    <th>Date</th><th>Kick-off</th><th class="l">Venue</th><th class="l">Opponent</th><th class="l">Competition</th></tr></thead><tbody>
    ${upcoming.map((f) => `<tr><td>${f.date}</td><td>${esc(f.kickoff || "")}</td><td class="l">${f.venue}</td>
      <td class="l">${esc(f.opponent)}</td><td class="l muted">${esc(f.competition)}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
  <div class="card wide">${h2i(`Results · ${d.fixtures.length}`, "Click a row to open the match. 📊 = player stats were "
    + "captured for it (FM keeps about the last 5 matches in memory, so earlier games have the score only).")}
    <div class="filters"><label><input type="checkbox" id="onlyStats"> only matches with player stats</label>
      <select id="comp"><option value="">All competitions</option>${comps.map((c) => `<option>${esc(c)}</option>`).join("")}</select></div>
    <div class="scroll"><table id="fx"><thead><tr>
    <th>Date</th><th class="l">Venue</th><th class="l">Opponent</th><th>Score</th><th>Res</th><th class="l">Competition</th>
    <th title="📊 = player stats captured for this match">Stats</th>
    </tr></thead><tbody>${d.fixtures.map((f) => `<tr class="clickrow" data-href="match/${f.id}" data-stats="${f.has_stats ? 1 : 0}" data-comp="${esc(f.competition)}">
      <td>${f.date}</td><td class="l">${f.venue}</td><td class="l">${esc(f.opponent)}</td>
      <td>${f.home_goals ?? "–"}–${f.away_goals ?? "–"}${f.home_pens != null ? ` <span class="muted">(${f.home_pens}–${f.away_pens}p)</span>` : ""}</td>
      <td>${res(f.result)}</td><td class="l muted">${esc(f.competition)}</td><td>${f.has_stats ? "📊" : ""}</td></tr>`).join("")}
    </tbody></table></div></div>`;
  const apply = () => document.querySelectorAll("#fx tbody tr").forEach((r) => {
    const okStats = !$("#onlyStats").checked || r.dataset.stats === "1";
    const okComp = !$("#comp").value || r.dataset.comp === $("#comp").value;
    r.style.display = okStats && okComp ? "" : "none";
  });
  $("#onlyStats").addEventListener("change", apply);
  $("#comp").addEventListener("change", apply);
  sortable($("#fx"));
  clickableRows(view);
}

const LLM_PRESETS = [
  { name: "OpenAI", url: "https://api.openai.com/v1", model: "gpt-4o-mini", note: "Paste an API key from platform.openai.com/api-keys, then Save and Test." },
  { name: "OpenRouter", url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini", note: "Paste an OpenRouter key; any model on openrouter.ai/models works." },
  { name: "Ollama (local)", url: "http://localhost:11434/v1", model: "llama3.1", note: "Free and offline: install Ollama, run 'ollama pull llama3.1'. No key needed." },
  { name: "LM Studio (local)", url: "http://localhost:1234/v1", model: "", note: "Start LM Studio's local server, load a model, then Test to list it. No key needed." },
];

const SETTINGS_SECTIONS = [["capture", "Capture"], ["coach", "AI coach"], ["snapshots", "Game snapshots"], ["phone", "Phone"],
  ["app", "App"]];
let settingsSection = (() => { try { return localStorage.getItem("settingsSection") || "capture"; } catch { return "capture"; } })();

async function settingsPage() {
  if (REMOTE) return devicePage();
  const [s, a, gpt, sv] = await Promise.all([api("/api/settings"), api("/api/auto"), api("/api/llm/status"), api("/api/snapshots")]);
  const useGpt = s.llm_provider === "chatgpt";
  const put0 = (url, body) => api(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const put = (body) => put0("/api/settings", body);
  const sec = SETTINGS_SECTIONS.some(([k]) => k === settingsSection) ? settingsSection : "capture";
  const pane = (k) => `class="secpane ${k === sec ? "" : "hidden"}" data-sec="${k}"`;
  view.innerHTML = `<div class="setnav">${SETTINGS_SECTIONS.map(([k, label]) =>
      `<button type="button" class="tab ${k === sec ? "on" : ""}" data-secbtn="${k}">${label}</button>`).join("")}</div>

  <div ${pane("capture")}>
  <div class="card wide">${h2i("Automatic capture", "While the app runs it watches the in-game clock and captures by itself "
    + "about 2½ game hours after each of your matches kicks off (once the match is over), and once a week of game time if "
    + "there's no match. The hotkey and the Capture button still work at any time.")}
    <label class="toggle"><input type="checkbox" id="autoOn" ${a.enabled ? "checked" : ""}> Capture by myself after every match</label>
    <div class="muted small">${esc(a.status || "")}${a.next ? ` · next ${esc(a.next)}` : ""}${a.last_reason ? `<br>Last: ${esc(a.last_reason)} (${esc(a.last_at || "")})` : ""}</div></div>
  <div class="card wide">${h2i("Club &amp; hotkey", "The club the app reads follows the game snapshot in use, so you rarely need "
    + "to change it here. A new hotkey (e.g. ctrl+alt+s, ctrl+shift+f9) applies after restarting the app.")}<form class="settings" id="sf">
    <label>Club ID</label><input name="club_id" type="number" value="${s.club_id}">
    <label>Capture hotkey</label><input name="hotkey" value="${esc(s.hotkey)}">
    <div style="margin-top:16px"><button type="submit">Save</button></div></form></div>
  </div>

  <div ${pane("coach")}>
  <div class="card wide">${h2i("AI coach", "Answers your questions using the stats the app has captured, focused on the page "
    + "you're viewing. Choose your ChatGPT plan (no API key; OpenAI's Sign in with ChatGPT for locally hosted apps, in preview) "
    + "or any OpenAI-compatible provider. Keys and sign-in tokens are encrypted with Windows DPAPI, tied to your Windows account, "
    + "and never committed or shown again.")}
    <div class="provider">
      <label class="opt ${useGpt ? "on" : ""}"><input type="radio" name="prov" value="chatgpt" ${useGpt ? "checked" : ""}>
        <b>ChatGPT plan</b><span class="muted">Use your ChatGPT Plus/Pro subscription. No API key.</span></label>
      <label class="opt ${useGpt ? "" : "on"}"><input type="radio" name="prov" value="api" ${useGpt ? "" : "checked"}>
        <b>API key / other provider</b><span class="muted">OpenAI API, OpenRouter, or a local model (Ollama, LM Studio)</span></label>
    </div>

    <div id="gptBox" class="${useGpt ? "" : "hidden"}">
      ${gpt.signed_in ? `<p>Signed in with ChatGPT${gpt.email ? ` as <b>${esc(gpt.email)}</b>` : ""}.
          ${gpt.plan_usage ? '<span class="pill">Using ChatGPT plan</span>' : '<span class="down">Plan usage not granted - sign in again and allow it.</span>'}
          <a href="${esc(gpt.manage_usage_url)}" target="_blank" rel="noopener">Manage usage</a>
          ${info("Coach answers count against your ChatGPT plan's usage limits, which you can review and cap in ChatGPT settings › Usage. "
            + "That's separate from this app, which has no charges of its own.")}</p>
          <form class="settings" id="gptForm"><label>Model ${info("The meter shows how heavily each answer draws on your plan, "
            + "estimated from OpenAI's own model descriptions (Astra › Sol › Terra › Luna); OpenAI doesn't publish exact rates.")}</label>
          <div id="gptModels" class="models"><div class="muted">Loading models…</div></div>
          <label>Thinking depth ${info("Deeper thinking multiplies usage on any model. Low is plenty for squad questions.")}</label>
          <select name="llm_chatgpt_effort" id="gptEffort">
            ${[["", "Model default"], ["low", "Low - quickest, least usage"], ["medium", "Medium - more considered"],
               ["high", "High - deepest, most usage"]].map(([v, t]) => `<option value="${v}" ${v === (s.llm_chatgpt_effort || "") ? "selected" : ""}>${t}</option>`).join("")}</select>
          <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><button type="submit">Save</button>
            <button type="button" class="secondary" id="llmTest2">Test</button>
            <button type="button" class="secondary" id="gptOut">Sign out</button></div></form>`
        : `<p class="muted">Sign in on chatgpt.com: the app can use your plan for coach answers, not see your conversations.</p>
           <button id="gptIn" class="gptbtn">Continue with ChatGPT</button>`}
      <div id="gptResult" class="muted small"></div>
    </div>

    <form class="settings ${useGpt ? "hidden" : ""}" id="apiBox">
      <label>Provider preset</label><div class="presets">${LLM_PRESETS.map((p, i) =>
        `<button type="button" class="secondary" data-preset="${i}">${esc(p.name)}</button>`).join("")}</div>
      <label>Base URL</label><input name="llm_base_url" value="${esc(s.llm_base_url)}" placeholder="https://api.openai.com/v1">
      <label>Model</label><input name="llm_model" value="${esc(s.llm_model)}" list="modelList" placeholder="gpt-4o-mini">
      <datalist id="modelList"></datalist>
      <label>API key ${s.llm_api_key_set ? `<span class="muted">(stored, ends ${esc(s.llm_api_key_hint)} - leave blank to keep)</span>` : '<span class="muted">(not needed for local models)</span>'}
        ${info("Encrypted with Windows DPAPI in data/config.json, never committed or shown again, and only sent to the base URL above.")}</label>
      <input name="llm_api_key" type="password" autocomplete="off" placeholder="${s.llm_api_key_set ? "••••••••" : "sk-…"}">
      <label>Creativity ${info("Temperature 0–1: lower is more factual and consistent.")}</label>
      <input name="llm_temperature" type="number" min="0" max="1" step="0.1" value="${s.llm_temperature ?? 0.4}">
      <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap"><button type="submit">Save</button>
        <button type="button" class="secondary" id="llmTest">Test connection</button>
        ${s.llm_api_key_set ? '<button type="button" class="secondary" id="llmClear">Remove stored key</button>' : ""}</div>
      <div id="llmResult" class="muted small"></div>
    </form></div>

  <div class="card wide">${h2i("Coach instructions", "The system instructions sent with every question, for any provider. They set "
    + "the coach's role, the FM rules it applies (condition, jadedness, sharpness, ratings) and how it answers. Edit them to change "
    + "its style or focus; <b>Reset to default</b> restores the built-in version.")}
    <textarea id="coachPrompt" rows="14" spellcheck="false" class="prompt">Loading…</textarea>
    <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center"><button id="promptSave">Save instructions</button>
      <button type="button" class="secondary" id="promptReset">Reset to default</button><span id="promptState" class="muted small"></span></div></div>
  </div>

  <div ${pane("snapshots")}>
  <div class="card wide">${h2i("Game snapshots", "Each game snapshot is a separate history: one FM save, or one job. Switch "
    + "between them here, or start a new one when you begin a new save or take a job at another club. A different save is also "
    + "detected by itself (from the players at the club), so histories never mix. Loading an older save file of the same career "
    + "stays in the same snapshot.")}
    <table class="saves"><tbody>${sv.careers.map((c) => `<tr class="${c.id === sv.active ? "on" : ""}">
      <td class="l"><b>${esc(c.name || c.club || "Game " + c.id)}</b> <span class="muted">#${c.id}</span>
        <br><span class="muted small0">${esc(c.club || "club not set")}</span></td>
      <td class="l muted">${c.first_game_date ? `${esc(c.first_game_date)} → ${esc(c.last_game_date || "")}` : "no captures yet"}
        · ${c.captures} capture${c.captures === 1 ? "" : "s"}
        ${c.rewound ? `<br><span class="down">older save file loaded: ${esc(c.rewound.from)} → ${esc(c.rewound.to)}</span>` : ""}</td>
      <td class="snapbtns">${c.id === sv.active ? '<span class="pill">in use</span>'
        : `<button class="secondary" data-switch="${c.id}">Switch to</button>`}
        <button class="secondary" data-rename="${c.id}" data-name="${esc(c.name || "")}">Rename</button>
        ${c.id === sv.active ? "" : `<button class="secondary danger" data-delete="${c.id}" data-name="${esc(c.name || c.club || "")}">Delete</button>`}</td></tr>`).join("")}
    </tbody></table>
    <button id="newGameBtn">Start a new game…</button>
    <form id="newGame" class="settings newgame hidden">
      <h3>Start a new game snapshot</h3>
      <label>Name</label><input name="name" placeholder="e.g. Real Madrid job, or a new save" maxlength="60">
      <label>Club you're managing</label>
      <input id="clubSearch" placeholder="Type to search clubs…" autocomplete="off">
      <select id="clubPick" size="6"></select>
      <div class="warn">⚠ <b>Before you start:</b> the dashboard will switch to an empty history, and captures will go into the new
        snapshot from now on. Your current snapshot <b>${esc(sv.careers.find((c) => c.id === sv.active)?.name || "")}</b> is
        kept unchanged and backed up first, so you can switch back to it at any time. In FM, load the new save (or be at the
        new club) before the next capture.</div>
      <label class="toggle"><input type="checkbox" id="newGameOk"> I understand: start a new, empty history</label>
      <div style="margin-top:12px;display:flex;gap:8px"><button type="submit" id="newGameGo" disabled>Start new game snapshot</button>
        <button type="button" class="secondary" id="newGameCancel">Cancel</button></div>
    </form>
    <h3 style="margin-top:20px">Safety backups${info(`A copy of this snapshot's database is made automatically once a day (on start-up
      and after captures) and before starting a new game; the newest ${sv.backups.keep} are kept.<br>Folder: <code>${esc(sv.backups.folder)}</code>
      <br>To restore: quit the app, copy a backup over the snapshot's database, then start the app again.`)}</h3>
    <p class="muted small">${sv.backups.count} of ${sv.backups.keep} kept${sv.backups.latest ? ` · latest ${esc(sv.backups.latest)}` : ""}</p>
    <button class="secondary" id="backupNow">Back up now</button></div>
  </div>

  <div ${pane("phone")} id="phonePane"><div class="empty">Loading…</div></div>

  <div ${pane("app")}>
  <div class="card wide">${h2i("App", "The app keeps running in the background after you close this window, so the hotkey "
    + "and auto-capture keep working. Double-click the FM26 Analyst shortcut to reopen the window. Quit stops it completely.")}
    <button id="quitBtn" class="secondary">Quit FM26 Analyst</button></div>
  </div>`;
  view.querySelectorAll("[data-secbtn]").forEach((b) => b.addEventListener("click", () => {
    settingsSection = b.dataset.secbtn;
    try { localStorage.setItem("settingsSection", settingsSection); } catch { /* private mode */ }
    view.querySelectorAll("[data-secbtn]").forEach((x) => x.classList.toggle("on", x === b));
    view.querySelectorAll(".secpane").forEach((p) => p.classList.toggle("hidden", p.dataset.sec !== settingsSection));
  }));

  $("#autoOn").addEventListener("change", (e) => setAuto(e.target.checked));
  // game snapshots
  const afterSwitch = () => { try { localStorage.removeItem("saveSeen"); } catch { /* private mode */ } refreshStatus(); settingsPage(); };
  view.querySelectorAll("[data-switch]").forEach((b) => b.addEventListener("click", async () => {
    try { const r = await put0("/api/snapshots/active", { id: Number(b.dataset.switch) });
      toast(`Switched to ${r.careers.find((c) => c.id === r.active)?.label || "#" + r.active}`); afterSwitch(); }
    catch (err) { toast(err.message, true); }
  }));
  view.querySelectorAll("[data-rename]").forEach((b) => b.addEventListener("click", async () => {
    const name = prompt("New name for this game snapshot:", b.dataset.name || "");
    if (!name) return;
    try { await put0(`/api/snapshots/${b.dataset.rename}/name`, { name }); settingsPage(); refreshStatus(); }
    catch (err) { toast(err.message, true); }
  }));
  view.querySelectorAll("[data-delete]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Delete the game snapshot "${b.dataset.name}"?\n\nIts history (captures, matches, development) is removed from the `
      + "app. Its safety backups are kept in data/backups. This can't be undone from the dashboard.")) return;
    try { await api(`/api/snapshots/${b.dataset.delete}`, { method: "DELETE" }); toast("Game snapshot deleted"); settingsPage(); }
    catch (err) { toast(err.message, true); }
  }));
  const ng = $("#newGame");
  let pickedName = {};
  const searchClubs = async () => {
    const r = await api(`/api/clubs?q=${encodeURIComponent($("#clubSearch").value)}`);
    pickedName = Object.fromEntries(r.clubs.map((c) => [c.club_id, c.name]));
    $("#clubPick").innerHTML = r.clubs.map((c) => `<option value="${c.club_id}">${esc(c.name)}</option>`).join("");
    if (r.clubs.length) $("#clubPick").selectedIndex = 0;
    checkReady();
  };
  const checkReady = () => { $("#newGameGo").disabled = !($("#newGameOk").checked && $("#clubPick").value); };
  let searchTimer;
  $("#newGameBtn").addEventListener("click", () => { ng.classList.remove("hidden"); $("#newGameBtn").classList.add("hidden");
    $("#clubSearch").value = ""; searchClubs(); ng.querySelector('[name="name"]').focus(); });
  $("#newGameCancel").addEventListener("click", () => { ng.classList.add("hidden"); $("#newGameBtn").classList.remove("hidden"); });
  $("#clubSearch").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(searchClubs, 250); });
  $("#clubPick").addEventListener("change", checkReady);
  $("#newGameOk").addEventListener("change", checkReady);
  ng.addEventListener("submit", async (e) => {
    e.preventDefault();
    const club_id = Number($("#clubPick").value);
    const club = pickedName[club_id];
    const name = ng.querySelector('[name="name"]').value.trim() || club;
    if (!confirm(`Start a new game snapshot "${name}" at ${club}?\n\nThe dashboard switches to an empty history and the next `
      + "capture goes into it. Your current snapshot is backed up and kept; you can switch back in Settings.")) return;
    try {
      const r = await api("/api/snapshots", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, club_id, club, confirm: true }) });
      toast(`Started "${name}" (#${r.started}). Capture once FM is in the new game.`); afterSwitch();
    } catch (err) { toast(err.message, true); }
  });
  $("#backupNow").addEventListener("click", async () => {
    try { const r = await api("/api/backup", { method: "POST" }); toast(`Backed up: ${r.file}`); settingsPage(); }
    catch (err) { toast(err.message, true); }
  });
  phonePane();
  $("#quitBtn").addEventListener("click", async () => {
    if (!confirm("Quit FM26 Analyst? The hotkey and auto-capture stop until you start it again.")) return;
    await api("/api/shutdown", { method: "POST" }).catch(() => {});
    document.body.innerHTML = '<div class="empty" style="margin-top:20vh">FM26 Analyst has stopped. You can close this window.</div>';
  });
  view.querySelectorAll('input[name="prov"]').forEach((r) => r.addEventListener("change", async () => {
    await put({ llm_provider: r.value }); toast(r.value === "chatgpt" ? "AI coach: ChatGPT plan" : "AI coach: API key / provider"); settingsPage();
  }));

  // coach instructions (system prompt)
  const showPrompt = (p) => {
    $("#coachPrompt").value = p.text;
    $("#promptState").textContent = p.custom ? "Using your edited instructions" : "Using the default instructions";
  };
  api("/api/coach/prompt").then(showPrompt);
  const savePrompt = async (text, msg) => {
    try { showPrompt(await api("/api/coach/prompt", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }) })); toast(msg); } catch (err) { toast(err.message, true); }
  };
  $("#promptSave").addEventListener("click", () => savePrompt($("#coachPrompt").value, "Instructions saved"));
  $("#promptReset").addEventListener("click", () => { if (confirm("Reset the coach instructions to the default?")) savePrompt("", "Instructions reset to default"); });

  // ChatGPT plan
  $("#gptIn")?.addEventListener("click", async () => {
    try {
      await api("/api/chatgpt/start", { method: "POST" });
      $("#gptResult").textContent = "A ChatGPT sign-in page opened in your browser. Finish there, then come back here.";
      const t0 = Date.now();
      const poll = setInterval(async () => {
        const st = await api("/api/llm/status");
        if (st.signed_in || Date.now() - t0 > 300000) {
          clearInterval(poll);
          if (st.signed_in && st.plan_usage && !st.first_use_ack) {
            alert("You're using your ChatGPT plan\n\nAI coach answers now count against your ChatGPT plan's usage. "
              + "You can review or cap this in ChatGPT settings › Usage.");
            await api("/api/chatgpt/ack", { method: "POST" });
          }
          settingsPage();
        }
      }, 2000);
    } catch (err) { toast(err.message, true); }
  });
  if ($("#gptModels")) {
    api("/api/chatgpt/models").then((r) => {
      if (!r.models.length) { $("#gptModels").innerHTML = '<div class="muted">No models available on this plan</div>'; return; }
      $("#gptModels").innerHTML = r.models.map((m) => `<label class="model ${m.id === r.selected ? "on" : ""}">
          <input type="radio" name="llm_chatgpt_model" value="${esc(m.id)}" ${m.id === r.selected ? "checked" : ""}>
          <span class="mname">${esc(m.name)}${m.note ? ' <span class="pill rec">recommended</span>' : ""}</span>
          <span class="meter u${m.usage || 0}" title="${esc(m.usage_label)}">${[1, 2, 3, 4].map((i) => `<i class="${i <= (m.usage || 0) ? "f" : ""}"></i>`).join("")}
            <span>${esc(m.usage_label)}</span></span>
          <span class="mdesc muted">${esc(m.description)}${m.note ? ` <b>${esc(m.note)}</b>` : ""}</span></label>`).join("");
      $("#gptModels").querySelectorAll("input").forEach((i) => i.addEventListener("change", () => {
        $("#gptModels").querySelectorAll(".model").forEach((l) => l.classList.toggle("on", l.contains(i) && i.checked));
      }));
    }).catch((err) => { $("#gptResult").innerHTML = `<span class="down">${esc(err.message)}</span>`; });
    $("#gptForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target));
      try { await put({ llm_chatgpt_model: f.llm_chatgpt_model || "", llm_chatgpt_effort: f.llm_chatgpt_effort || "" });
        toast("Saved"); settingsPage(); } catch (err) { toast(err.message, true); }
    });
    $("#gptOut").addEventListener("click", async () => {
      if (!confirm("Sign out of ChatGPT in FM26 Analyst?")) return;
      const r = await api("/api/chatgpt/signout", { method: "POST" });
      toast(r.revocation_confirmed ? "Signed out" : "Signed out here. Remote revocation wasn't confirmed: disconnect the app in ChatGPT settings.");
      settingsPage();
    });
  }

  // API key / OpenAI-compatible provider
  view.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
    const p = LLM_PRESETS[b.dataset.preset];
    $('[name="llm_base_url"]').value = p.url; $('[name="llm_model"]').value = p.model;
    $("#llmResult").textContent = p.note;
  }));
  const test = async (out) => {
    out.textContent = "Testing…";
    const r = await api("/api/llm/test", { method: "POST" });
    out.innerHTML = r.ok ? `<span class="up">✓ Connected: ${esc(r.model)} replied "${esc(r.reply)}"</span>` : `<span class="down">✗ ${esc(r.error)}</span>`;
    if (r.models?.length && $("#modelList")) $("#modelList").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
  };
  $("#llmTest").addEventListener("click", () => test($("#llmResult")));
  $("#llmTest2")?.addEventListener("click", () => test($("#gptResult")));
  $("#llmClear")?.addEventListener("click", async () => {
    if (!confirm("Remove the stored API key?")) return;
    await put({ llm_clear_key: true }); toast("API key removed"); settingsPage();
  });
  $("#apiBox").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    f.llm_temperature = f.llm_temperature === "" ? null : Number(f.llm_temperature);
    try { await put(f); toast("Saved"); settingsPage(); } catch (err) { toast(err.message, true); }
  });
  $("#sf").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    f.club_id = Number(f.club_id);
    try { await put(f); toast("Saved"); settingsPage(); refreshStatus(); } catch (err) { toast(err.message, true); }
  });
}

// ------------------------------------------------------------------ first run: choose your club
async function clubSetup() {
  view.innerHTML = `<div class="card wide setup">${h2i("Welcome to FM26 Analyst", "The app reads your save from the running "
    + "game, only ever reading memory, never changing it. It needs to know which club is yours; you can change it later in "
    + "Settings › Capture.")}
    ${REMOTE ? '<p>Choose your club in the dashboard on your PC first.</p>' : `
    <p>Start FM26 and load your save, then choose the club you manage.</p>
    <form class="settings newgame" id="clubForm">
      <input id="clubSearch" placeholder="Type to search clubs…" autocomplete="off">
      <select id="clubPick" size="8"></select>
      <div style="margin-top:12px"><button type="submit" id="clubGo" disabled>Use this club</button></div>
    </form><div id="clubMsg" class="muted small"></div>`}</div>`;
  if (REMOTE) return;
  const search = async () => {
    const d = await api(`/api/clubs?q=${encodeURIComponent($("#clubSearch").value)}`).catch(() => ({ clubs: [] }));
    const seen = {};
    d.clubs.forEach((c) => { seen[c.name] = (seen[c.name] || 0) + 1; });
    // the game has several clubs with some names (e.g. two Liverpools): show the id so they can be told apart
    $("#clubPick").innerHTML = d.clubs.map((c) => `<option value="${c.club_id}">${esc(c.name)}${seen[c.name] > 1 ? ` (club #${c.club_id})` : ""}</option>`).join("");
    $("#clubMsg").textContent = d.clubs.length ? "" : "No clubs found - is FM26 running with your save loaded?";
    $("#clubGo").disabled = !$("#clubPick").value;
  };
  let t = null;
  $("#clubSearch").addEventListener("input", () => { clearTimeout(t); t = setTimeout(search, 250); });
  $("#clubPick").addEventListener("change", () => { $("#clubGo").disabled = !$("#clubPick").value; });
  $("#clubForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const opt = $("#clubPick").selectedOptions[0];
    if (!opt) return;
    await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ club_id: Number(opt.value) }) });
    toast(`Now following ${opt.textContent}. Press Capture to take your first snapshot.`);
    NEEDS_CLUB = false;
    refreshStatus();
    route();
  });
  search();
}

// ------------------------------------------------------------------ phone companion
const DEVICE_VIA = { qr: "QR code only", google: "Google + pairing code", password: "password + pairing code" };
const ago = (t) => (t ? new Date(t * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");

async function phonePane() {
  const el = $("#phonePane");
  if (!el) return;
  const r = await api("/api/remote");
  const put = (body) => api("/api/remote", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const srv = r.server || {};
  const fw = `New-NetFirewallRule -DisplayName "FM26 Analyst phone" -Direction Inbound -Protocol TCP -LocalPort ${r.port} `
    + `-RemoteAddress ${r.proxy_ip ? r.proxy_ip.replace(/\s/g, "") : "LocalSubnet"} -Action Allow`;
  const lan = r.lan_ips.length ? r.lan_ips.join(" or ") : "this PC's IP";
  const canPair = r.enabled && (r.password_set || r.google_ready);
  el.innerHTML = `
  <div class="card wide">${h2i("Phone access", "Your phone uses this dashboard through your reverse proxy (NGINX Proxy Manager), "
    + "from anywhere. It goes to a second, locked-down listener: only paired devices get in, and they can read every page, use the "
    + "coach, Capture and switch Auto. Settings, game snapshots, sign-ins and Quit stay on this PC. The desktop dashboard is unchanged.")}
    <label class="switch"><input type="checkbox" id="remoteOn" ${r.enabled ? "checked" : ""}><span class="knob"></span>
      <span>Allow phone access</span></label>
    <div class="muted small">${!r.enabled ? "Off" : srv.running ? `<span class="up">●</span> Listening on ${esc(srv.address)}`
      : `<span class="down">✗ Not listening: ${esc(srv.error || "starting…")}</span>`}</div>
    <form class="settings" id="remoteForm">
      <label>Public address ${info("The HTTPS address your proxy serves with its Let's Encrypt certificate, e.g. "
        + "https://fm.example.com. Needed for Google sign-in and for pairing from outside your home network.")}</label>
      <input name="public_url" value="${esc(r.public_url)}" placeholder="https://fm.example.com">
      <label>Port ${info("The port your proxy forwards to on this PC.")}</label>
      <input name="port" type="number" min="1024" max="65535" value="${r.port}">
      <label>Only accept connections from ${info("The IP of the machine running NGINX Proxy Manager. Then nothing else on your "
        + "network can reach the phone listener directly. Leave blank to accept any address (e.g. to test on Wi-Fi first).")}</label>
      <input name="proxy_ip" value="${esc(r.proxy_ip)}" placeholder="e.g. 192.168.1.20">
      <div style="margin-top:12px"><button type="submit">Save</button></div></form>
    <details class="setup"><summary>Setup guide</summary><ol>
      <li>Give this PC a fixed IP on your network (a DHCP reservation in your router). It's ${esc(lan)} now.</li>
      <li>Allow the port through Windows Firewall (PowerShell as administrator):<br><code>${esc(fw)}</code></li>
      <li>In NGINX Proxy Manager add a <b>Proxy Host</b>: your domain → <code>http</code> · <code>${esc(r.lan_ips[0] || "PC-IP")}</code>
        · <code>${r.port}</code>. On the SSL tab request a Let's Encrypt certificate and tick <b>Force SSL</b>.
        On the Advanced tab add <code>proxy_buffering off;</code> so coach answers stream.</li>
      <li>Enter the public address above, turn on phone access, then pair your phone below.</li>
      <li>On the phone, open the site and add it to the home screen (Safari: Share › Add to Home Screen; Chrome: Install app).</li>
    </ol></details>
  </div>

  <div class="card wide">${h2i("Pair a device", "Pairing takes two steps on the phone: sign in with Google or the password, "
    + "then enter this one-time code (scan the QR code with the phone's camera, or type the code). Neither alone is enough. "
    + "The code works for 10 minutes and for one device.")}
    <button id="pairBtn" ${canPair ? "" : "disabled"}>Show pairing code</button>
    ${!r.enabled ? '<span class="muted small0">Turn on phone access first.</span>'
      : !canPair ? '<span class="muted small0">Set up the password or Google sign-in below first.</span>' : ""}
    <div id="pairOut" class="pairout hidden"><div id="qr"></div><div><div class="muted small0">Pairing code</div>
      <div id="pairCode" class="paircode"></div><div class="muted small0">or open on the phone: <code id="pairUrl"></code></div>
      <div id="pairLeft" class="muted small"></div></div></div>
    <h3 style="margin-top:18px">Paired devices${info("Each device stays signed in until you revoke it here or it isn't used for 180 days.")}</h3>
    ${r.devices.length ? `<table class="saves"><tbody>${r.devices.map((d) => `<tr><td class="l"><b>${esc(d.name)}</b>
      <br><span class="muted small0">via ${esc(DEVICE_VIA[d.method] || d.method)} · paired ${ago(d.created)}</span></td>
      <td class="l muted">last used ${ago(d.last_seen)}</td>
      <td class="snapbtns"><button class="secondary danger" data-revoke="${esc(d.id)}">Revoke</button></td></tr>`).join("")}</tbody></table>`
      : '<p class="muted">No devices paired yet.</p>'}
  </div>

  <div class="card wide">${h2i("Google sign-in", "Sign in on the phone with your Google account; Google's own 2-step "
    + "verification then protects the dashboard. Set-up, once: in Google Cloud Console › APIs &amp; Services › Credentials, "
    + "create an <b>OAuth client ID</b> of type <b>Web application</b> and add the redirect URI shown here. Then paste its "
    + "client ID and secret below. The secret is encrypted with Windows DPAPI.")}
    <p class="muted small0">${r.google_ready ? '<span class="up">✓ Ready</span>' : "Not set up yet"}</p>
    <form class="settings" id="googleForm">
      <label>Redirect URI ${info("Copy this into the Google OAuth client's Authorized redirect URIs.")}</label>
      <input readonly value="${esc(r.redirect_uri || "Set the public address first")}" onclick="this.select()">
      <label>Client ID</label><input name="google_client_id" value="${esc(r.google_client_id)}" placeholder="….apps.googleusercontent.com">
      <label>Client secret ${r.google_secret_set ? '<span class="muted">(stored - leave blank to keep)</span>' : ""}</label>
      <input name="google_client_secret" type="password" autocomplete="off" placeholder="${r.google_secret_set ? "••••••••" : "GOCSPX-…"}">
      <label>Allowed Google accounts ${info("Only these accounts can sign in. Separate several with commas.")}</label>
      <input name="allowed_emails" value="${esc(r.allowed_emails.join(", "))}" placeholder="you@gmail.com">
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><button type="submit">Save</button>
        ${r.google_client_id ? '<button type="button" class="secondary" id="googleClear">Remove</button>' : ""}</div></form>
  </div>

  <div class="card wide">${h2i("Password (backup)", "A username and password for when Google sign-in isn't available. "
    + "Only a scrypt hash of it is stored. After 5 wrong tries in 15 minutes, password sign-in pauses.")}
    <p class="muted small0">${r.password_set ? `<span class="up">✓ Set</span> for ${esc(r.password_user)}` : "Not set"}</p>
    <form class="settings" id="pwForm">
      <label>Username</label><input name="password_user" value="${esc(r.password_user)}" autocomplete="off" autocapitalize="none">
      <label>${r.password_set ? "New password" : "Password"} <span class="muted">(at least 10 characters)</span></label>
      <input name="password" type="password" autocomplete="new-password">
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><button type="submit">Save</button>
        ${r.password_set ? '<button type="button" class="secondary" id="pwClear">Remove password</button>' : ""}</div></form>
  </div>`;

  const save = async (body, msg) => {
    try { await put(body); toast(msg); phonePane(); } catch (err) { toast(err.message, true); }
  };
  $("#remoteOn").addEventListener("change", (e) => save({ enabled: e.target.checked },
    e.target.checked ? "Phone access on" : "Phone access off"));
  $("#remoteForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    save({ public_url: f.get("public_url"), port: Number(f.get("port")), proxy_ip: f.get("proxy_ip") }, "Saved");
  });
  $("#googleForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    save({ google_client_id: f.get("google_client_id"), google_client_secret: f.get("google_client_secret"),
      allowed_emails: String(f.get("allowed_emails")).split(",") }, "Google sign-in saved");
  });
  $("#googleClear")?.addEventListener("click", () => confirm("Remove Google sign-in? Devices already paired stay signed in.")
    && save({ clear_google: true }, "Google sign-in removed"));
  $("#pwForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    save({ password_user: f.get("password_user"), password: f.get("password") }, "Password saved");
  });
  $("#pwClear")?.addEventListener("click", () => confirm("Remove the password? Devices already paired stay signed in.")
    && save({ clear_password: true }, "Password removed"));
  el.querySelectorAll("[data-revoke]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Revoke this device? It will have to sign in again.")) return;
    try { await api(`/api/remote/devices/${b.dataset.revoke}`, { method: "DELETE" }); toast("Device revoked"); phonePane(); }
    catch (err) { toast(err.message, true); }
  }));
  $("#pairBtn").addEventListener("click", async () => {
    try {
      const p = await api("/api/remote/pair", { method: "POST" });
      await loadScript("https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js");
      $("#qr").innerHTML = "";
      new QRCode($("#qr"), { text: p.url, width: 200, height: 200, colorDark: "#0d1117", colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.M });
      $("#pairUrl").textContent = p.url;
      $("#pairCode").textContent = p.code;
      $("#pairOut").classList.remove("hidden");
      const until = Date.now() + p.expires_in * 1000;
      clearInterval(phonePane.timer);
      const tick = () => {
        const out = $("#pairLeft");
        const left = Math.max(0, Math.round((until - Date.now()) / 1000));
        if (out) out.textContent = left ? `Works once, for ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`
          : "Expired - make a new one";
        if (!left || !out) clearInterval(phonePane.timer);
      };
      tick();
      phonePane.timer = setInterval(tick, 1000);
    } catch (err) { toast(err.message, true); }
  });
}

const loadScript = (src) => new Promise((ok, fail) => {
  if (document.querySelector(`script[src="${src}"]`)) return ok();
  const s = document.createElement("script");
  s.src = src; s.onload = ok; s.onerror = () => fail(new Error("Couldn't load the QR code library"));
  document.head.appendChild(s);
});

// on the phone, the Settings tab becomes this device's page
async function devicePage() {
  const d = await api("/auth/me").catch(() => null);
  view.innerHTML = `<div class="card wide">${h2i("This device", "Settings, game snapshots and sign-ins are only on your PC: "
    + "open Settings there to change them or to revoke devices.")}
    ${d ? `<p><b>${esc(d.name)}</b><br><span class="muted">Signed in via ${esc(DEVICE_VIA[d.method] || d.method)} · since ${ago(d.created)}</span></p>` : ""}
    <button class="secondary" id="signOut">Sign out</button></div>`;
  $("#signOut").addEventListener("click", async () => {
    if (!confirm("Sign out of FM26 Analyst on this device?")) return;
    await fetch("/auth/logout", { method: "POST" }).catch(() => {});
    if (window.caches) for (const k of await caches.keys()) await caches.delete(k);   // drop the offline copy too
    location.href = "/login";
  });
}

// ------------------------------------------------------------------ router
const routes = { overview, players: playersPage, squad: playersPage, development: developmentPage, per90: per90Page,
  fixtures: fixturesPage, settings: settingsPage };
async function route() {
  closeZoom();
  charts.splice(0).forEach((c) => c.destroy());
  const [name, ...args] = (location.hash.slice(1).split("?")[0] || "overview").split("/");
  const navName = { squad: "players", player: "players", match: "fixtures" }[name] || name;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + navName));
  view.innerHTML = '<div class="empty">Loading…</div>';
  try {
    if (name === "player") await playerPage(args[0]);
    else if (name === "match") await matchPage(args[0]);
    else if (name === "compare") await comparePage(args[0], args[1]);
    else await (routes[name] || overview)();
  } catch (e) {
    view.innerHTML = `<div class="card empty">Error: ${esc(e.message)}</div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
setInterval(refreshStatus, 15000);
refreshStatus().then(route);   // status first, so the phone layout is known before the first page draws
