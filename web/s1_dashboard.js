// Anthropic S-1 Economics: interactivity. Requires Plotly, S1MODEL, DATA and SOURCES.
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmtB = v => (v == null || isNaN(v)) ? "–" : (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString(undefined, {maximumFractionDigits: Math.abs(v) < 10 ? 1 : 0}) + "B";
const fmtM = v => (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString(undefined, {maximumFractionDigits: 0}) + "m";
const pct = (v, d = 1) => (v == null || isNaN(v)) ? "–" : (v * 100).toFixed(d) + "%";
const CFG = {displaylogo: false, responsive: true};

// ---------------------------------------------------------------- theme
let T = {};
function readTheme() {
  const cs = getComputedStyle(document.documentElement), g = n => cs.getPropertyValue(n).trim();
  T = {bg: g("--bg"), surface: g("--surface"), fg: g("--fg"), muted: g("--muted"), line: g("--line"), grid: g("--grid"), accent: g("--accent"), accentSoft: g("--accent-soft"), ink: g("--ink"),
       good: g("--good"), bad: g("--bad"), amber: g("--amber"), violet: g("--violet"), c: [1, 2, 3, 4, 5, 6, 7].map(i => g("--c" + i)),
       heat: [[0, g("--heat0")], [0.5, g("--heat1")], [1, g("--heat2")]]};
  T.div = [[0, T.bad], [0.5, T.surface], [1, T.good]];
}
const L = (extra = {}) => Object.assign({
  paper_bgcolor: T.surface, plot_bgcolor: T.surface, font: {family: "Public Sans, system-ui, sans-serif", size: 12, color: T.fg},
  margin: {l: 58, r: 22, t: 48, b: 50}, hoverlabel: {bgcolor: T.surface, bordercolor: T.line, font: {color: T.fg}},
  xaxis: {gridcolor: T.grid, linecolor: T.line, zerolinecolor: T.line}, yaxis: {gridcolor: T.grid, linecolor: T.line, zerolinecolor: T.line},
  legend: {orientation: "h", y: -0.2, font: {size: 11}}, title: {x: 0.01, font: {size: 14, color: T.ink, family: "Source Serif 4, Georgia, serif"}}}, extra,
  {xaxis: Object.assign({gridcolor: T.grid, linecolor: T.line, zerolinecolor: T.line}, extra.xaxis || {}), yaxis: Object.assign({gridcolor: T.grid, linecolor: T.line, zerolinecolor: T.line}, extra.yaxis || {}),
   title: Object.assign({x: 0.01, font: {size: 14, color: T.ink, family: "Source Serif 4, Georgia, serif"}}, extra.title || {})});
function onClick(id, f) { const el = $(id); if (!el || !el.on) return; if (el.removeAllListeners) el.removeAllListeners("plotly_click"); el.on("plotly_click", ev => { const s = f(ev.points[0]); if (s && SOURCES[s]) openSource(s); }); }

// ---------------------------------------------------------------- source drawer
function openSource(id) {
  const s = SOURCES[id]; if (!s) return;
  $("d-title").textContent = s.title; $("d-meta").textContent = s.meta;
  $("d-body").innerHTML = s.texts.length ? s.texts.map(t => "<p>" + esc(t) + "</p>").join("") : "<p>No source text attached.</p>";
  $("drawer").classList.add("open"); $("drawer").setAttribute("aria-hidden", "false"); $("d-close").focus();
}
function closeDrawer() { $("drawer").classList.remove("open"); $("drawer").setAttribute("aria-hidden", "true"); }
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
document.addEventListener("click", e => { const el = e.target.closest("[data-src]"); if (el && el.dataset.src) openSource(el.dataset.src); });
function chips(el, items, active, onPick) {
  el.innerHTML = "";
  items.forEach(([key, label]) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = label; if (String(key) === String(active)) b.className = "on";
    b.onclick = () => { [...el.children].forEach(c => c.className = ""); b.className = "on"; onPick(key); };
    el.appendChild(b);
  });
}

// ---------------------------------------------------------------- 1. margin
let PERIOD = "H1 2026";
function renderBridge() {
  const b = DATA.bridges[PERIOD], R = b.revenue;
  const COL = {fact: T.c[1], floor: T.c[3], unallocated: T.c[6], subtotal: T.ink, revenue: T.c[0]};
  const KIND = {fact: "filed", floor: "floor (lower bound)", unallocated: "bucket the filing does not split", subtotal: "subtotal", revenue: "filed"};
  const SHORT = [[/^Revenue/, "Revenue"], [/^Cost of revenue/, "Cost of<br>revenue"], [/^Accounting gross/, "Gross<br>profit"], [/^Channel partner/, "Channel<br>fees"], [/^Rest of S&M/, "Rest of<br>S&M"],
                 [/^Sales and marketing/, "S&M"], [/^Contribution/, "Contri-<br>bution"], [/^R&D/, "R&D"], [/^General/, "G&A"], [/^Bartz/, "Settle-<br>ment"], [/^Operating income/, "Operating<br>income"]];
  const lab = s => (SHORT.find(([re]) => re.test(s.label)) || [null, s.label])[1];
  let level = 0; const xs = [], base = [], ys = [], cols = [], txt = [], hov = [];
  b.steps.forEach((s, i) => {
    const kind = i === 0 ? "revenue" : s.kind;
    if (i === 0 || s.kind === "subtotal") { base.push(Math.min(0, s.value)); ys.push(Math.abs(s.value)); level = s.value; }
    else { const nl = level + s.value; base.push(Math.min(level, nl)); ys.push(Math.abs(s.value)); level = nl; }
    xs.push(lab(s)); cols.push(COL[kind]); txt.push(`${fmtM(s.value)}<br>${pct(s.value / R)}`);
    hov.push(`${s.label}<br>${fmtM(s.value)} · ${pct(s.value / R)} of revenue<br><i>${KIND[kind]}</i>` + (s.src ? "<br>click for the source" : ""));
  });
  const legend = [["filed", COL.fact], ["floor", COL.floor], ["not split by the filing", COL.unallocated], ["subtotal", COL.subtotal]].map(([n, c]) => ({type: "bar", x: [null], y: [null], name: n, marker: {color: c}, hoverinfo: "skip"}));
  Plotly.react("fig-bridge", [{type: "bar", x: xs, y: ys, base, marker: {color: cols}, text: txt, textposition: "outside", cliponaxis: false, textfont: {size: 10, color: T.fg}, hovertext: hov, hoverinfo: "text", showlegend: false}].concat(legend),
    L({title: {text: `Revenue to operating income, ${PERIOD} ($m)`}, margin: {l: 60, r: 16, t: 50, b: 96}, xaxis: {tickfont: {size: 10}}, yaxis: {title: "$ millions"}, legend: {orientation: "h", y: -0.3}, bargap: 0.25}), CFG);
  onClick("fig-bridge", p => p.curveNumber === 0 ? b.steps[p.pointIndex].src : null);
  renderAlpha(); renderMarginTable();
}
function bounds(b, a, inc) {
  const R = b.revenue, ch = inc ? b.channel_floor : 0;
  return [(R - b.cor - b.free_access_ceiling - ch - a * (b.compute - b.cor - b.free_access_ceiling)) / R, (R - DATA.cor_floor * b.cor - ch - a * (b.compute - DATA.cor_floor * b.cor)) / R];
}
function renderAlpha() {
  const b = DATA.bridges[PERIOD], a = +$("alpha").value / 100, inc = $("incl-channel").checked;
  $("alpha-v").textContent = Math.round(a * 100) + "%";
  const xs = [...Array(101).keys()].map(i => i / 100), lo = xs.map(x => bounds(b, x, inc)[0] * 100), hi = xs.map(x => bounds(b, x, inc)[1] * 100), [clo, chi] = bounds(b, a, inc);
  const ref = (y, name, color) => ({x: [0, 1], y: [y * 100, y * 100], mode: "lines", name, line: {dash: "dot", color, width: 1.5}, hovertemplate: name + ": %{y:.1f}%<extra></extra>"});
  Plotly.react("fig-alpha", [
    {x: xs, y: hi, mode: "lines", line: {width: 0}, showlegend: false, hoverinfo: "skip"},
    {x: xs, y: lo, mode: "lines", fill: "tonexty", fillcolor: T.c[0] + "33", line: {color: T.c[0], width: 1}, name: "range the filing allows", hovertemplate: "%{x:.0%} charged: %{y:.1f}% (low)<extra></extra>"},
    {x: [a, a], y: [clo * 100, chi * 100], mode: "lines+markers", line: {color: T.ink, width: 3}, marker: {size: 8, color: T.ink}, name: `at ${Math.round(a * 100)}%: ${pct(clo)} to ${pct(chi)}`, hoverinfo: "skip"},
    ref(b.accounting_gm, "accounting gross margin", T.c[0]), ref(b.compute_margin_all_workloads, "revenue less all compute", T.c[1]), ref(b.operating_margin, "operating margin", T.muted)],
    L({title: {text: "Margin as more non-serving compute is charged"}, xaxis: {title: "share of non-serving compute charged as cost of goods", tickformat: ".0%", range: [0, 1]}, yaxis: {title: "% of revenue", ticksuffix: "%"}, legend: {orientation: "h", y: -0.32}}), CFG);
}
function renderMarginTable() {
  const rows = Object.values(DATA.bridges).map(b => `<tr><td>${b.period}</td><td class="num">${fmtM(b.revenue)}</td><td class="num">${pct(b.accounting_gm)}</td><td class="num">${b.contribution_margin_channel_only == null ? "–" : pct(b.contribution_margin_channel_only)}</td><td class="num">${pct(b.contribution_margin)}</td><td class="num">${pct(b.compute_margin_all_workloads)}</td><td class="num">${pct(b.operating_margin)}</td><td class="num">${fmtM(b.serving_compute_lo)}–${fmtM(b.serving_compute_hi)}</td><td class="num">${fmtM(Math.max(b.rd_compute_lo, 0))}–${fmtM(b.rd_compute_hi)}</td></tr>`).join("");
  $("margin-table").innerHTML = `<table class="t"><thead><tr><th>Period</th><th class="num">Revenue</th><th class="num">Accounting gross margin <span class="tag fact">filed</span></th><th class="num">After channel-fee floor</th><th class="num">After all S&amp;M</th><th class="num">All compute as cost of goods <span class="tag derived">derived</span></th><th class="num">Operating margin</th><th class="num">Serving compute <span class="tag assume">range</span></th><th class="num">Non-serving compute <span class="tag assume">range</span></th></tr></thead><tbody>${rows}</tbody></table>
  <p class="note">Serving compute ranges from ${Math.round(DATA.cor_floor * 100)}% of cost of revenue (the filing says "substantially all") to all of it. Non-serving compute (training, research, internal use) is total compute less serving and free-access compute. The filing does not break training out on its own. Operating margin includes the $1.5B Bartz settlement in FY2025.</p>`;
}

// ---------------------------------------------------------------- 2. efficiency
let RATIO = "rev_per_compute", LAG = 0;
const RATIO_LEGEND = {rev_per_compute: "revenue per compute dollar, same quarter", rolling_2q_ratio: "revenue per compute dollar, rolling two quarters",
  lag1_ratio: "revenue per compute dollar of the prior quarter", lag2_ratio: "revenue per compute dollar of two quarters earlier", incremental_ratio: "added revenue per added compute dollar"};
const RATIO_TITLE = {rev_per_compute: "Revenue, compute, and revenue per compute dollar", rolling_2q_ratio: "Revenue, compute, and revenue per compute dollar (rolling two quarters)",
  lag1_ratio: "Revenue against the prior quarter's compute", lag2_ratio: "Revenue against compute two quarters earlier", incremental_ratio: "Revenue, compute, and the return on added compute"};
const RATIOS = [["rev_per_compute", "same quarter"], ["rolling_2q_ratio", "rolling two quarters"], ["lag1_ratio", "vs compute a quarter earlier"], ["lag2_ratio", "two quarters earlier"], ["incremental_ratio", "incremental"]];
function renderEff() {
  const e = DATA.eff, q = e.map(r => r.quarter), xi = q.map((_, i) => i), relQ = {};
  DATA.releases.forEach(r => (relQ[r.quarter] = relQ[r.quarter] || []).push(r.label + " (" + r.date + ")"));
  const shapes = [], rx = [], rt = [], ratio = e.map(r => r[RATIO]), ymax2 = Math.max(...ratio.filter(v => v != null)) * 1.2;
  Object.entries(relQ).forEach(([qq, labs]) => {
    const i = q.indexOf(qq), x = i >= 0 ? i : q.length - 0.5;
    shapes.push({type: "line", xref: "x", yref: "paper", x0: x, x1: x, y0: 0, y1: 1, line: {color: T.amber, width: 1, dash: i >= 0 ? "dot" : "dash"}});
    rx.push(x); rt.push((i >= 0 ? qq : "after the data (" + qq + ")") + ": " + labs.join("; "));
  });
  Plotly.react("fig-eff", [
    {type: "bar", x: xi, y: e.map(r => r.revenue / 1000), name: "revenue ($B)", marker: {color: T.c[0]}, customdata: q, hovertemplate: "%{customdata}: revenue $%{y:.2f}B<extra></extra>"},
    {type: "bar", x: xi, y: e.map(r => r.compute / 1000), name: "compute and infrastructure ($B)", marker: {color: T.c[1]}, customdata: q, hovertemplate: "%{customdata}: compute $%{y:.2f}B<extra></extra>"},
    {type: "scatter", mode: "lines+markers+text", x: xi, y: ratio, yaxis: "y2", name: RATIO_LEGEND[RATIO], line: {color: T.ink, width: 3}, marker: {color: T.ink}, customdata: q,
     text: ratio.map(v => v == null ? "" : "$" + v.toFixed(2)), textposition: "top center", textfont: {color: T.fg, size: 11}, hovertemplate: "%{customdata}: %{y:.2f}<extra></extra>"},
    {type: "scatter", mode: "markers", x: rx, y: rx.map(() => ymax2 * 0.97), yaxis: "y2", name: "model and product releases", marker: {symbol: "triangle-down", size: 11, color: T.amber}, text: rt, hovertemplate: "%{text}<extra></extra>"}],
    L({barmode: "group", title: {text: RATIO_TITLE[RATIO]}, margin: {l: 52, r: 52, t: 48, b: 50}, xaxis: {tickvals: xi, ticktext: q, range: [-0.6, q.length - 0.3]},
       yaxis: {title: "$ billions"}, yaxis2: {title: RATIO === "incremental_ratio" ? "added revenue per added compute $" : "revenue per compute $", overlaying: "y", side: "right", range: [0, ymax2], showgrid: false, linecolor: T.line}, legend: {orientation: "h", y: -0.18}, shapes}), CFG);
  onClick("fig-eff", p => p.curveNumber > 2 ? null : "fact:q_" + (p.curveNumber === 1 ? "compute_" : "revenue_") + q[Math.round(p.x)]);
  renderDecomp(); renderEffTable();
}
function renderDecomp() {
  const e = DATA.eff, q = e.map(r => r.quarter), comp = [], effc = [], tot = [];
  for (let i = 0; i < e.length; i++) {
    const j = i - LAG;
    if (i === 0 || j - 1 < 0) { comp.push(null); effc.push(null); tot.push(null); continue; }
    const gR = Math.log(e[i].revenue / e[i - 1].revenue), gC = Math.log(e[j].compute / e[j - 1].compute);
    comp.push(gC); effc.push(gR - gC); tot.push(gR);
  }
  Plotly.react("fig-decomp", [
    {type: "bar", x: q, y: comp, name: LAG ? `compute growth, ${LAG} quarter${LAG > 1 ? "s" : ""} earlier` : "compute growth", marker: {color: T.c[1]}, hovertemplate: "%{x}: %{y:.2f} log points<extra></extra>"},
    {type: "bar", x: q, y: effc, name: "revenue-per-compute-dollar growth", marker: {color: T.c[2]}, hovertemplate: "%{x}: %{y:.2f} log points<extra></extra>"},
    {type: "scatter", mode: "markers", x: q, y: tot, name: "revenue growth", marker: {color: T.fg, size: 9, symbol: "diamond"}, customdata: tot.map(v => v == null ? null : Math.exp(v)), hovertemplate: "%{x}: revenue %{y:.2f} log points (×%{customdata:.2f})<extra></extra>"}],
    L({barmode: "relative", title: {text: "Quarterly revenue growth, split into compute and efficiency"}, yaxis: {title: "log growth"}, legend: {orientation: "h", y: -0.22}}), CFG);
}
function renderEffTable() {
  const e = DATA.eff, f = (v, d = 2) => v == null ? "–" : v.toFixed(d), a = e[1], b = e[5];
  const rows = e.map(r => `<tr data-src="fact:q_revenue_${r.quarter}"><td>${r.quarter}</td><td class="num">${fmtM(r.revenue)}</td><td class="num">${fmtM(r.compute)}</td><td class="num">${f(r.rev_per_compute)}</td><td class="num">${r.efficiency_qoq == null ? "–" : pct(r.efficiency_qoq, 0)}</td><td class="num">${f(r.incremental_ratio)}</td><td class="num">${f(r.rolling_2q_ratio)}</td><td class="num">${f(r.lag1_ratio)}</td><td class="num">${f(r.lag2_ratio)}</td><td class="num">${pct(r.compute_pct_rev, 0)}</td></tr>`).join("");
  const yoy = [0, 1].map(lag => { const cN = e[5 - lag].compute, cT = e[1 - lag].compute, gR = Math.log(b.revenue / a.revenue), gC = Math.log(cN / cT);
    return `<tr><td>${lag ? "compute a quarter earlier" : "same quarter"}</td><td class="num">×${(b.revenue / a.revenue).toFixed(1)}</td><td class="num">×${(cN / cT).toFixed(2)}</td><td class="num">×${((b.revenue / cN) / (a.revenue / cT)).toFixed(2)}</td><td class="num">${pct(gC / gR, 0)}</td><td class="num">${pct(1 - gC / gR, 0)}</td></tr>`; }).join("");
  $("eff-table").innerHTML = `<div class="tablewrap"><table class="t"><thead><tr><th>Quarter</th><th class="num">Revenue</th><th class="num">Compute</th><th class="num">Rev / compute</th><th class="num">Change q/q</th><th class="num">Incremental</th><th class="num">Rolling 2Q</th><th class="num">Lag 1</th><th class="num">Lag 2</th><th class="num">Compute % rev</th></tr></thead><tbody>${rows}</tbody></table></div>
  <div class="tablewrap"><table class="t"><thead><tr><th>Q2 2025 → Q2 2026</th><th class="num">Revenue</th><th class="num">Compute</th><th class="num">Rev per compute $</th><th class="num">Growth from compute</th><th class="num">From efficiency</th></tr></thead><tbody>${yoy}</tbody></table></div>`;
}

// ---------------------------------------------------------------- 3. contracted compute
const SCOPE = {cancelable: false, vendor_conditional: false, estimates: false};  // firm commitments by default; each switch adds a category
let RAMP = String(DATA.assumptions.ramp_in.value); if (!DATA.ramps.includes(RAMP)) RAMP = DATA.ramps.find(r => +r === +RAMP) || DATA.ramps[1];
const P = Object.assign({}, DATA.base);
const catKey = c => c.slice(0, 2), CATC = () => ({"A.": T.c[0], "B.": T.c[7 - 1], "C.": T.c[4], "D.": T.c[1], "E.": T.c[3], "F.": T.c[6]});
function inScope(l) {
  return l.toggle ? !!SCOPE[l.toggle] : l.base;
}
function schedule() { const s = new Array(DATA.years.length).fill(0); DATA.ledger.filter(inScope).forEach(l => l.sched[RAMP].forEach((v, i) => s[i] += v)); return s; }
function renderLedger() {
  const cc = CATC(), tot = DATA.ledger.filter(inScope).reduce((a, l) => a + l.amount[RAMP], 0);
  const rows = DATA.ledger.map(l => `<tr data-src="ledger:${l.id}" style="${inScope(l) ? "" : "opacity:.45"}"><td><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${cc[catKey(l.category)]}"></span> ${esc(l.category.split(" (")[0])}</td><td>${esc(l.item)}</td><td class="num">${fmtB(l.amount[RAMP])}</td><td>${esc(l.status)}</td><td>${esc(l.window)}</td></tr>`).join("");
  $("ledger-table").innerHTML = `<table class="t"><thead><tr><th>Category</th><th>Item</th><th class="num">Amount</th><th>Status</th><th>Window</th></tr></thead><tbody>${rows}<tr class="total"><td></td><td>In scope now</td><td class="num">${fmtB(tot)}</td><td colspan="2">set by the scope switches above the calendar</td></tr><tr class="total"><td></td><td>Firm commitments (base case)</td><td class="num">${fmtB(DATA.firm_total)}</td><td colspan="2">excludes the cancelable SpaceXAI tail and the vendor-conditional deals</td></tr><tr class="total"><td></td><td>Upper bound</td><td class="num">${fmtB(DATA.upper_total)}</td><td colspan="2">every contracted category; possible amendment overlap not removed</td></tr></tbody></table>`;
  $("recon-table").innerHTML = `<table class="t"><thead><tr><th>Reconciliation check</th><th class="num">Value</th><th>Detail</th></tr></thead><tbody>${Object.keys(SOURCES).filter(k => k.startsWith("recon:")).map(k => `<tr data-src="${k}"><td>${esc(SOURCES[k].title)}</td><td class="num">${esc(SOURCES[k].meta)}</td><td>${esc(SOURCES[k].texts[0] || "")}</td></tr>`).join("")}</tbody></table>`;
}
function renderCalendar() {
  const cc = CATC(), yrs = DATA.years.map(y => y === 2026 ? "H2 2026" : String(y)), cats = {};
  DATA.ledger.filter(inScope).forEach(l => { const c = l.category.split(" (")[0]; cats[c] = cats[c] || {y: new Array(yrs.length).fill(0), color: cc[catKey(l.category)]}; l.sched[RAMP].forEach((v, i) => cats[c].y[i] += v); });
  const tr = Object.entries(cats).map(([c, o]) => ({type: "bar", x: yrs, y: o.y, name: c, marker: {color: o.color}, hovertemplate: c + "<br>%{x}: $%{y:.1f}B<extra></extra>"}));
  tr.push({type: "scatter", mode: "markers", x: ["H2 2026"], y: [DATA.observed_h2_2026_compute], name: "observed: Q2 2026 compute expense × 2", marker: {symbol: "line-ew-open", size: 30, color: T.fg, line: {width: 3}}, hovertemplate: "Q2 2026 compute expense × 2: $%{y:.1f}B<extra></extra>"});
  const last = Math.max(...DATA.years.map((y, i) => Object.values(cats).some(o => o.y[i] > 0.05) ? i : 0));
  Plotly.react("fig-calendar", tr, L({barmode: "stack", title: {text: "When the contracted payments fall due ($B)"}, xaxis: {type: "category", range: [-0.5, last + 0.5]}, yaxis: {title: "$ billions"}, legend: {orientation: "h", y: -0.2}}), CFG);
}
const CTRL = [
  ["Capacity and demand"],
  ["u", "utilization of serving capacity", 0.3, 1.0, 0.01, v => pct(v, 0) + ` (${(v / P.u_obs).toFixed(2)}× H1 2026)`],
  ["u_obs", "utilization assumed for H1 2026", 0.5, 1.0, 0.01, v => pct(v, 0)],
  ["demand_g", "demand growth from the Q2 2026 run-rate (when capped)", 0, 1.5, 0.01, v => pct(v, 0) + " a year"],
  ["Economics"],
  ["train_end", "non-serving share of compute by the ramp year", 0.1, 0.8, 0.01, v => pct(v, 0)],
  ["ramp_year", "ramp year", 2027, 2035, 1, v => v],
  ["k_drift", "yearly change in revenue per used serving dollar", -0.4, 0.3, 0.01, v => (v >= 0 ? "+" : "") + pct(v, 0)],
  ["opex_pct", "non-compute cash costs, % of revenue", 0.1, 0.6, 0.005, v => pct(v, 1)],
  ["policy_share", "usage-policy revenue removed", 0, 0.1, 0.005, v => pct(v, 1)],
  ["tax", "cash tax rate", 0, 0.35, 0.01, v => pct(v, 0)],
  ["Discount rates"],
  ["rate_rev", "revenue side (unlevered CAPM)", 0.05, 0.25, 0.0025, v => pct(v, 2)],
  ["rate_premium", "extra premium on the revenue side", 0, 0.15, 0.0025, v => "+" + pct(v, 2)],
  ["rate_pay", "payment side (lease rate)", 0.03, 0.15, 0.0025, v => pct(v, 2)],
  ["Customer stress"],
  ["loss_share", "revenue lost to large-customer churn or in-sourcing", 0, 0.5, 0.01, v => pct(v, 0)],
  ["loss_year", "loss starts in", 2027, 2032, 1, v => v],
];
const ctrlFmt = k => CTRL.find(c => c[0] === k)[5];
function setP(k, v) { P[k] = v; $("c-" + k).value = v; $("v-" + k).textContent = ctrlFmt(k)(v); }
function buildControls() {
  $("model-controls").innerHTML = CTRL.map(c => c.length === 1 ? `<div class="group">${c[0]}</div>` :
    `<div><label for="c-${c[0]}">${c[1]}: <span class="val" id="v-${c[0]}">${c[5](P[c[0]])}</span></label><input type="range" id="c-${c[0]}" min="${c[2]}" max="${c[3]}" step="${c[4]}" value="${P[c[0]]}"></div>`).join("")
    + `<div class="group">Presets and switches</div>
       <div><span class="clabel">Utilization</span><div class="chips" id="u-chips"></div></div>
       <div><span class="clabel">Revenue limited by</span><div class="chips" id="demand-chips"></div></div>
       <div><span class="clabel">Customer stress</span><div class="chips" id="loss-chips"></div></div>
       <div><label class="check" style="margin:0"><input type="checkbox" id="c-revolver_in_cash"> count the undrawn $${DATA.base.revolver}B revolver as cash</label><button type="button" class="reset" id="reset">Reset to base case</button></div>`;
  CTRL.filter(c => c.length > 1).forEach(([k]) => $("c-" + k).addEventListener("input", e => { P[k] = +e.target.value; $("v-" + k).textContent = ctrlFmt(k)(P[k]); if (k === "u_obs") $("v-u").textContent = ctrlFmt("u")(P.u); syncChips(); renderModel(); }));
  $("c-revolver_in_cash").addEventListener("change", e => { P.revolver_in_cash = e.target.checked; renderModel(); });
  $("reset").onclick = () => { Object.assign(P, DATA.base); CTRL.filter(c => c.length > 1).forEach(([k]) => setP(k, P[k])); $("c-revolver_in_cash").checked = false; syncChips(); renderModel(); };
  syncChips();
}
function syncChips() {
  chips($("u-chips"), [["0.5", "50%"], ["0.7", "70%"], ["0.9", "90%"]], String(P.u), k => { setP("u", +k); renderModel(); });
  chips($("demand-chips"), [["off", "capacity (demand fills it)"], ["on", "demand growth"]], P.demand_on ? "on" : "off", k => { P.demand_on = k === "on"; renderModel(); });
  const t5 = DATA.cust.top5_q3, cur = P.loss_share === 0 ? "none" : Math.abs(P.loss_share - t5) < 1e-6 ? "all" : Math.abs(P.loss_share - t5 / 2) < 1e-6 ? "half" : "custom";
  chips($("loss-chips"), [["none", "none"], ["half", `half the top five (${pct(t5 / 2, 0)})`], ["all", `the top five (${pct(t5, 0)})`]], cur, k => { setP("loss_share", k === "none" ? 0 : k === "all" ? t5 : t5 / 2); renderModel(); });
}
function renderModel() {
  const s = schedule(), Y = DATA.years, lab = Y.map(y => y === 2026 ? "H2 2026" : String(y)), cov = DATA.obs.min_liquidity;
  const r = S1MODEL.model(P, s, Y), m = S1MODEL.solveMult(P, s, Y), dem = S1MODEL.solveDemand(P, s, Y, cov);
  const feasible = !isNaN(m), req = feasible ? S1MODEL.model(Object.assign({}, P, {k_mult: m}), s, Y) : null;
  const last = Math.max(...s.map((v, i) => v > 0.05 ? i : 0)), xr = {type: "category", range: [-0.5, last + 0.5]};
  const total = s.reduce((a, b) => a + b, 0), gtxt = g => isNaN(g) ? "not reachable" : pct(g, 0) + " a year";
  const kpi = (v, l, cls = "", lead = false) => `<div class="kpi${lead ? " lead" : ""}"><div class="v ${cls}">${v}</div><div class="l">${l}</div></div>`;
  const mode = P.demand_on ? `revenue limited by ${pct(P.demand_g, 0)} demand growth` : "demand fills capacity";
  $("kpis").innerHTML = [
    kpi(gtxt(dem.g_both), "demand growth needed for NPV ≥ 0 and cash above the covenant every year", isNaN(dem.g_both) ? "warn" : "", true),
    kpi(gtxt(dem.g_npv), "demand growth needed for NPV ≥ 0 alone"),
    kpi(fmtB(r.npv), `NPV at current settings (${mode})`, r.npv < 0 ? "warn" : "ok"),
    kpi(fmtB(total) + " / " + fmtB(r.pv_pay), `payments in scope / their present value at ${pct(P.rate_pay, 1)}`),
    kpi(feasible ? "×" + m.toFixed(2) : "none", feasible ? "price-efficiency needed for NPV = 0 (× H1 2026)" : "no price-efficiency reaches NPV = 0: revenue is capped by demand", feasible ? (m > 1 ? "warn" : "") : "warn"),
    kpi(feasible ? (P.u * m / P.u_obs).toFixed(2) + "× H1 2026" : "–", feasible ? `serving load needed at H1 2026 prices (${pct(P.u * m, 0)} if H1 ran at ${pct(P.u_obs, 0)})` : "serving load needed: not defined under a demand cap"),
    kpi(fmtB(r.min_cash) + " (" + r.min_cash_year + ")", `lowest cash at current settings; covenant $${cov}B`, r.min_cash < cov ? "warn" : ""),
  ].join("");
  // NPV and lowest cash against demand growth
  const gs = [...Array(61).keys()].map(i => i * 0.025), q = Object.assign({}, P, {demand_on: true, k_mult: 1});
  const npvs = gs.map(g => S1MODEL.model(Object.assign({}, q, {demand_g: g}), s, Y)), sh = [];
  [[dem.g_npv, "NPV = 0", T.accent], [dem.g_cash, "covenant", T.amber]].forEach(([g, n, c]) => { if (!isNaN(g)) sh.push({type: "line", xref: "x", yref: "paper", x0: g, x1: g, y0: 0, y1: 1, line: {color: c, dash: "dot", width: 1.5}}); });
  Plotly.react("fig-demand", [
    {x: gs, y: npvs.map(o => o.npv), name: "NPV", mode: "lines", line: {color: T.accent, width: 3}, hovertemplate: "demand growth %{x:.0%}: NPV $%{y:.0f}B<extra></extra>"},
    {x: gs, y: npvs.map(o => o.min_cash - cov), name: "lowest cash above the covenant", mode: "lines", line: {color: T.amber, width: 2.5, dash: "dash"}, hovertemplate: "demand growth %{x:.0%}: lowest cash $%{y:.0f}B above the covenant<extra></extra>"}],
    L({title: {text: "What demand growth the contracts need"}, xaxis: {title: "annual demand growth from the Q2 2026 run-rate", tickformat: ".0%"}, yaxis: {title: "$ billions (zero = threshold)", zeroline: true, zerolinecolor: T.fg, zerolinewidth: 1.5},
       shapes: sh, legend: {orientation: "h", y: -0.22},
       annotations: [!isNaN(dem.g_npv) ? {x: dem.g_npv, y: 0.98, yref: "paper", text: "NPV ≥ 0 from " + pct(dem.g_npv, 0), showarrow: false, xanchor: "right", font: {size: 11, color: T.accent}, yanchor: "top", bgcolor: T.surface} : null,
                     !isNaN(dem.g_cash) ? {x: dem.g_cash, y: 0.06, yref: "paper", text: "covenant met from " + pct(dem.g_cash, 0), showarrow: false, xanchor: "left", font: {size: 11, color: T.amber}, yanchor: "bottom", bgcolor: T.surface} : null].filter(Boolean)}), CFG);
  // revenue paths
  const tr = [];
  if (feasible) tr.push({x: lab, y: req.R, name: "revenue needed for NPV = 0", mode: "lines+markers", line: {color: T.ink, width: 3}, marker: {color: T.ink}, hovertemplate: "%{x}: needed $%{y:.0f}B<extra></extra>"});
  tr.push({x: lab, y: r.R, name: "revenue at current settings", mode: "lines", line: {color: T.accent, dash: "dash", width: 2}, hovertemplate: "%{x}: $%{y:.0f}B<extra></extra>"});
  tr.push({x: lab, y: r.breakeven_R, name: "revenue for zero cash flow that year", mode: "lines", line: {color: T.c[1], dash: "dot"}, hovertemplate: "%{x}: break-even $%{y:.0f}B<extra></extra>"});
  tr.push({x: lab, y: Y.map(y => P.q2_run_rate * (y === 2026 ? 0.5 : 1)), name: "Q2 2026 run-rate, flat", mode: "lines", line: {color: T.muted, width: 1}, hovertemplate: "%{x}: $%{y:.0f}B<extra></extra>"});
  Plotly.react("fig-revenue", tr, L({title: {text: "Revenue the contracts require ($B a year)"}, xaxis: xr, yaxis: {title: "$ billions"}, legend: {orientation: "h", y: -0.24},
    annotations: feasible ? [] : [{xref: "paper", yref: "paper", x: 0.5, y: 0.92, showarrow: false, text: "No break-even path: revenue is capped by demand at these settings", font: {color: T.bad, size: 12}}]}), CFG);
  // NPV surface: utilization × price-efficiency, respecting the demand setting
  const us = [], ks = [];
  for (let u = 0.3; u <= 1.0001; u += 0.05) us.push(+u.toFixed(2));
  for (let k = 0.2; k <= 1.6001; k += 0.05) ks.push(+k.toFixed(2));
  const z = ks.map(k => us.map(u => S1MODEL.model(Object.assign({}, P, {u, k_mult: k}), s, Y).npv)), zmax = Math.max(...z.flat().map(Math.abs));
  Plotly.react("fig-surface", [
    {type: "heatmap", x: us, y: ks, z, zmid: 0, zmin: -zmax, zmax, colorscale: T.div, colorbar: {title: {text: "NPV $B"}, thickness: 10}, hovertemplate: "utilization %{x:.0%} · price-efficiency ×%{y:.2f}<br>NPV $%{z:.0f}B<extra></extra>"},
    {type: "contour", x: us, y: ks, z, contours: {start: 0, end: 0, size: 1, coloring: "none", showlabels: true, labelfont: {color: T.fg}}, line: {color: T.fg, width: 2}, showscale: false, hoverinfo: "skip"},
    {type: "scatter", mode: "markers+text", x: [0.5, 0.7, 0.9], y: [1, 1, 1], text: ["50%", "70%", "90%"], textposition: "top center", textfont: {color: T.fg}, marker: {color: T.ink, size: 9}, hoverinfo: "skip"},
    {type: "scatter", mode: "markers", x: [P.u], y: [P.k_mult], marker: {symbol: "x", size: 12, color: T.c[1]}, hoverinfo: "skip"}],
    L({title: {text: "NPV by utilization and price-efficiency" + (P.demand_on ? " (demand-capped)" : "")}, xaxis: {title: "utilization of serving capacity", tickformat: ".0%"}, yaxis: {title: "revenue per used serving $ (× H1 2026)"}, showlegend: false}), CFG);
  Plotly.react("fig-cash", [
    {type: "bar", x: lab, y: r.fcf, name: "free cash flow", marker: {color: r.fcf.map(v => v < 0 ? T.c[1] : T.c[2])}, opacity: 0.7, hovertemplate: "%{x}: FCF $%{y:.0f}B<extra></extra>"},
    {x: lab, y: r.cash, mode: "lines+markers", name: "cash and investments", line: {color: T.accent, width: 3}, marker: {color: T.accent}, hovertemplate: "%{x}: $%{y:.0f}B<extra></extra>"},
    {x: lab, y: lab.map(() => cov), mode: "lines", name: "minimum liquidity covenant", line: {color: T.bad, dash: "dot"}}],
    L({title: {text: `Cash path from $${DATA.obs.liquidity.toFixed(0)}B (${mode})`}, xaxis: xr, yaxis: {title: "$ billions"}, legend: {orientation: "h", y: -0.24}}), CFG);
  const rows = [0.5, 0.7, 0.9].map(u => {
    const q0 = Object.assign({}, P, {u, demand_on: false}), r0 = S1MODEL.model(q0, s, Y), mm = S1MODEL.solveMult(q0, s, Y), dd = S1MODEL.solveDemand(q0, s, Y, cov);
    const rc = S1MODEL.model(Object.assign({}, P, {u, demand_on: true}), s, Y);
    return `<tr><td>${pct(u, 0)}</td><td class="num">${(u / P.u_obs).toFixed(2)}×</td><td class="num">${fmtB(r0.npv)}</td><td class="num">${fmtB(rc.npv)}</td><td class="num">${isNaN(mm) ? "none" : "×" + mm.toFixed(2)}</td><td class="num">${gtxt(dd.g_npv)}</td><td class="num">${gtxt(dd.g_cash)}</td><td class="num">${fmtB(r0.min_cash)}</td></tr>`;
  }).join("");
  $("scen-table").innerHTML = `<table class="t"><thead><tr><th>Utilization</th><th class="num">vs H1 2026</th><th class="num">NPV, demand fills capacity</th><th class="num">NPV at ${pct(P.demand_g, 0)} demand growth</th><th class="num">Price-efficiency for NPV = 0</th><th class="num">Demand growth for NPV ≥ 0</th><th class="num">Demand growth for covenant</th><th class="num">Lowest cash, unconstrained</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function renderScope() {
  chips($("ramp-chips"), DATA.ramps.map(r => [r, +r === 0 ? "straight-line" : (+r).toFixed(1).replace(".0", "") + " yr"]), RAMP, k => { RAMP = k; $("ramp-v").textContent = k + " yr"; refreshContracts(); });
  $("ramp-v").textContent = RAMP + " yr";
  const el = $("scope-chips"); el.innerHTML = "";
  [["cancelable", "Add SpaceXAI after its notice period (cancelable)"], ["vendor_conditional", "Add vendor-conditional deals (Nscale, Lambda Aug)"], ["estimates", "Add estimates outside the filing (TPU, AMD)"]].forEach(([k, lab]) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = lab; b.className = SCOPE[k] ? "on" : "";
    b.onclick = () => { SCOPE[k] = !SCOPE[k]; b.className = SCOPE[k] ? "on" : ""; refreshContracts(); };
    el.appendChild(b);
  });
}
function refreshContracts() { renderLedger(); renderCalendar(); renderModel(); }

// ---------------------------------------------------------------- 4. customers
function renderCustomers() {
  const c = DATA.cust, tiers = [["$10M+", c.n10m, "fact:cust_10m_sep26"], ["$1M–10M", c.n1m - c.n10m, "fact:cust_1m_sep26"], ["$100K–1M", c.n100k - c.n1m, "fact:cust_100k_sep26"], ["under $100K", c.small_m * 1e6, "fact:cust_small_users"]];
  Plotly.react("fig-tiers", [{type: "bar", x: tiers.map(t => t[0]), y: tiers.map(t => t[1]), marker: {color: [T.ink, T.c[0], T.c[0] + "99", T.c[6]]}, customdata: tiers.map(t => t[2]),
      text: tiers.map(t => t[1] >= 1e6 ? (t[1] / 1e6).toFixed(0) + " million" : "≈" + Math.round(t[1]).toLocaleString()), textposition: "outside", cliponaxis: false, textfont: {color: T.fg},
      hovertemplate: "%{x}: %{text} customers<br><i>click for the source</i><extra></extra>"}],
    L({title: {text: "Customers by annual spend, Sep 30, 2026 (log scale)"}, yaxis: {type: "log", title: "customers"}, showlegend: false}), CFG);
  Plotly.react("fig-cohort", [
    {type: "scatter", mode: "lines+markers+text", x: c.series.map(r => r.date), y: c.series.map(r => r.n), name: "customers spending $100K+", line: {color: T.accent, width: 3}, marker: {color: T.accent},
     text: c.series.map(r => r.n.toLocaleString()), textposition: "top left", textfont: {color: T.fg, size: 10}, customdata: c.series.map(r => r.src), hovertemplate: "%{x}: %{y:,} customers<extra></extra>"},
    {type: "scatter", mode: "markers+text", x: c.shares.map(r => r.date), y: c.shares.map(r => r.share), yaxis: "y2", name: "their share of revenue", marker: {color: T.c[1], size: 11, symbol: "square"},
     text: c.shares.map(r => r.label + " " + pct(r.share, 0)), textposition: c.shares.map((r, i) => i % 2 ? "top center" : "bottom center"), textfont: {size: 10, color: T.c[1]}, customdata: c.shares.map(r => r.src), hovertemplate: "%{text}<extra></extra>"}],
    L({title: {text: "$100K+ customers: count (log) and share of revenue"}, yaxis: {type: "log", title: "customers"}, margin: {l: 58, r: 64, t: 48, b: 50},
       yaxis2: {type: "linear", overlaying: "y", side: "right", range: [0, 1.05], tickmode: "linear", tick0: 0, dtick: 0.25, tickformat: ".0%", showgrid: false, title: "share of revenue"}, legend: {orientation: "h", y: -0.22}}), CFG);
  Plotly.react("fig-top5", [{type: "bar", x: c.top5.map(r => r.label), y: c.top5.map(r => r.share), marker: {color: [T.c[1], T.c[3], T.c[2]]}, customdata: c.top5.map(r => r.src),
      text: c.top5.map(r => pct(r.share, 0)), textposition: "outside", textfont: {color: T.fg}, hovertemplate: "%{x}: %{y:.0%}<extra></extra>"}],
    L({title: {text: "Top five customers' share of revenue"}, yaxis: {tickformat: ".0%", range: [0, 0.45]}, showlegend: false}), CFG);
  ["fig-tiers", "fig-cohort", "fig-top5"].forEach(id => onClick(id, p => p.customdata));
}

// ---------------------------------------------------------------- Part II: theme the Python-built figures, wire their clicks
function themePyFigs() {
  DATA.pyfigs.forEach(fid => {
    const el = $("fig-" + fid); if (!el || !el.data) return;
    const upd = {paper_bgcolor: T.surface, plot_bgcolor: T.surface, "font.color": T.fg, "xaxis.gridcolor": T.grid, "yaxis.gridcolor": T.grid, "xaxis.linecolor": T.line, "yaxis.linecolor": T.line,
                 "xaxis.zerolinecolor": T.line, "yaxis.zerolinecolor": T.line, "hoverlabel.bgcolor": T.surface, "hoverlabel.font.color": T.fg, "title.font.color": T.ink,
                 "updatemenus[0].bgcolor": T.surface, "updatemenus[0].font.color": T.fg, "updatemenus[0].bordercolor": T.line, "updatemenus[0].activecolor": T.accentSoft};
    if (el.layout.updatemenus && el.layout.updatemenus[1]) Object.assign(upd, {"updatemenus[1].bgcolor": T.surface, "updatemenus[1].font.color": T.fg, "updatemenus[1].bordercolor": T.line, "updatemenus[1].activecolor": T.accentSoft});
    Plotly.relayout(el, upd);
    el.data.forEach((tr, i) => {
      if (tr.type === "heatmap") Plotly.restyle(el, {colorscale: [T.heat], "textfont.color": T.fg}, [i]);
      if (tr.type === "treemap") Plotly.restyle(el, {"marker.colorscale": [T.heat], "textfont.color": T.fg}, [i]);
      if (tr.type === "scatter" && tr.mode && tr.mode.includes("text")) Plotly.restyle(el, {"textfont.color": T.muted}, [i]);
    });
  });
}
function wirePyFigs() {
  onClick("fig-words", p => p.data.meta ? "theme:" + p.data.meta[p.pointIndex] : null);
  onClick("fig-evidence", p => "ev:" + p.data.meta[Array.isArray(p.pointIndex) ? p.pointIndex[0] : p.pointNumber[0]] + "|" + p.x);
  onClick("fig-factors", p => SOURCES["risk:" + p.id] ? "risk:" + p.id : (SOURCES["theme:" + p.id] ? "theme:" + p.id : null));
  onClick("fig-genre", p => "theme:" + p.data.meta[p.pointIndex]);
  onClick("fig-vendors", p => "agreement:" + p.x);
  onClick("fig-roles", p => "role:" + p.y + "|" + p.x.replace(/ /g, "_"));
}

// ---------------------------------------------------------------- contents: highlight the section in view
function initToc() {
  const links = [...document.querySelectorAll(".toc a[data-target]")], byId = {};
  links.forEach(a => byId[a.dataset.target] = a);
  const targets = links.map(a => $(a.dataset.target)).filter(Boolean);
  const setActive = () => {
    const y = window.innerHeight * 0.28; let cur = null;
    targets.forEach(t => { if (t.getBoundingClientRect().top <= y) cur = t; });
    links.forEach(a => a.classList.remove("active"));
    if (!cur) return;
    const a = byId[cur.id]; if (a) a.classList.add("active");
    const sec = cur.closest("section.sec"); if (sec && byId[sec.id] && sec.id !== cur.id) byId[sec.id].classList.add("active");
  };
  window.addEventListener("scroll", setActive, {passive: true}); setActive();
  const mq = window.matchMedia("(max-width: 1100px)"), d = $("toc-d"), sync = () => { d.open = !mq.matches; };
  sync(); mq.addEventListener("change", sync);
  links.forEach(a => a.addEventListener("click", () => { if (mq.matches) d.open = false; }));
}

// ---------------------------------------------------------------- boot
function renderAll() { readTheme(); renderBridge(); renderEff(); refreshContracts(); renderCustomers(); themePyFigs(); }
function boot() {
  readTheme();
  $("d-close").addEventListener("click", closeDrawer);
  chips($("period-chips"), Object.keys(DATA.bridges).map(p => [p, p]), PERIOD, k => { PERIOD = k; renderBridge(); });
  $("alpha").addEventListener("input", renderAlpha); $("incl-channel").addEventListener("change", renderAlpha);
  chips($("alpha-chips"), [["0", "Accounting view (training in R&D)"], ["100", "All compute as cost of goods"]], "", k => { $("alpha").value = k; renderAlpha(); });
  chips($("ratio-chips"), RATIOS, RATIO, k => { RATIO = k; renderEff(); });
  chips($("lag-chips"), [[0, "no lag"], [1, "compute lagged a quarter"], [2, "two quarters"]], LAG, k => { LAG = +k; renderDecomp(); });
  renderScope(); buildControls();
  renderAll(); wirePyFigs(); initToc();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
  new MutationObserver(renderAll).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
