(() => {
"use strict";

/* ================= utilities ================= */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[m]));

const SESSION_KEY = "compliscan.session";

function authHeader() {
  try {
    const token = JSON.parse(localStorage.getItem(SESSION_KEY) || "null")?.token || "";
    return token ? { Authorization: "Bearer " + token } : {};
  } catch (e) { return {}; }
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { ...(opts.headers || {}), ...authHeader() },
  });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem(SESSION_KEY);
    location.href = "/login";
    throw new Error("Signed out — please sign in again.");
  }
  return res.json();
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return iso || "—"; }
}

function statusChip(status) {
  const label = status === "COMPLIANT" ? "Compliant" : status === "NON-COMPLIANT" ? "Non-Compliant" : "Review";
  return `<span class="status-chip ${esc(status)}"><span class="status-dot"></span>${label}</span>`;
}

/* ================= state ================= */
const state = {
  sup: null, // set from the landing-page session on boot
  view: "dashboard",
  scanFilter: "all",
  scanQuery: "",
  selectedRun: null,
};

const TITLES = {
  dashboard: ["Dashboard", "Key statistics and trends"],
  reports: ["Reports", "View all scans per official with status"],
  details: ["Report Details", "Highlighted issues and past history alerts"],
  products: ["Products", "Identify frequently flagged brands/products"],
  analytics: ["Analytics", "Trends, brands and officer performance"],
  map: ["Map View", "Heatmap of violations by region"],
  team: ["Team Management", "Manage officers and groups"],
  settings: ["Settings", "Prototype configuration"],
};

/* ================= charts (pure SVG, no dependencies) ================= */
function lineChart(labels, compliant, nonCompliant) {
  const W = 640, H = 220, P = { l: 34, r: 12, t: 14, b: 30 };
  const max = Math.max(5, ...compliant, ...nonCompliant);
  const X = (i) => P.l + (i / Math.max(1, labels.length - 1)) * (W - P.l - P.r);
  const Y = (v) => P.t + (1 - v / max) * (H - P.t - P.b);
  const line = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const area = (arr) => `${line(arr)} L${X(arr.length - 1).toFixed(1)},${Y(0).toFixed(1)} L${X(0).toFixed(1)},${Y(0).toFixed(1)} Z`;
  const grid = [0.25, 0.5, 0.75, 1].map((f) => {
    const y = P.t + (1 - f) * (H - P.t - P.b);
    return `<line x1="${P.l}" y1="${y}" x2="${W - P.r}" y2="${y}" stroke="#e7edf4" stroke-width="1"/>
      <text x="${P.l - 6}" y="${y + 4}" font-size="10" fill="#93a0b0" text-anchor="end">${Math.round(max * f)}</text>`;
  }).join("");
  const dots = (arr, color) => arr.map((v, i) =>
    `<circle cx="${X(i)}" cy="${Y(v)}" r="3.5" fill="${color}" stroke="#fff" stroke-width="1.5"/>`).join("");
  const xlabels = labels.map((l, i) =>
    `<text x="${X(i)}" y="${H - 10}" font-size="10" fill="#93a0b0" text-anchor="middle">${esc(l)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Scans over time">
    ${grid}
    <path d="${area(nonCompliant)}" fill="rgba(227,85,85,0.12)"/>
    <path d="${area(compliant)}" fill="rgba(21,122,59,0.10)"/>
    <path d="${line(nonCompliant)}" fill="none" stroke="#e35555" stroke-width="2.5" stroke-linecap="round"/>
    <path d="${line(compliant)}" fill="none" stroke="#1c9a4f" stroke-width="2.5" stroke-linecap="round"/>
    ${dots(nonCompliant, "#e35555")}${dots(compliant, "#1c9a4f")}
    ${xlabels}
  </svg>`;
}

function hbars(rows, maxVal, red) {
  if (!rows.length) return `<div class="empty">No data yet.</div>`;
  return rows.map((r) => `
    <div class="hbar-row">
      <span class="lbl" title="${esc(r.label)}">${esc(r.label)}</span>
      <div class="hbar-track"><div class="hbar-fill${red ? " red" : ""}" style="width:${Math.max(2, Math.round((r.value / maxVal) * 100))}%"></div></div>
      <span class="val">${esc(r.value)}</span>
    </div>`).join("");
}

/* Schematic India bubble map (positions approximate, prototype only) */
const CITY_POS = {
  Delhi: [122, 58], Jaipur: [96, 84], Lucknow: [132, 88], Ahmedabad: [62, 114],
  Kolkata: [166, 124], Mumbai: [56, 140], Hyderabad: [116, 150], Pune: [70, 152],
  Chennai: [136, 190], Bengaluru: [116, 176],
};
function indiaMap(locations) {
  const byCity = {};
  locations.forEach((l) => { byCity[l.city] = l.violations || 0; });
  const max = Math.max(1, ...Object.values(byCity));
  const dots = Object.entries(CITY_POS).map(([city, [x, y]]) => {
    const v = byCity[city] || 0;
    const color = v >= Math.max(3, max * 0.5) ? "#e35555" : v > 0 ? "#e0a92e" : "#34a463";
    const r = 5 + (v / max) * 9;
    return `<g>
      <circle cx="${x}" cy="${y}" r="${r + 5}" fill="${color}" opacity="0.18"/>
      <circle cx="${x}" cy="${y}" r="${r}" fill="${color}" opacity="0.9"/>
      <text x="${x}" y="${y - r - 7}" font-size="9" font-weight="700" fill="#2c3a4b" text-anchor="middle">${esc(city)}${v ? ` · ${v}` : ""}</text>
    </g>`;
  }).join("");
  return `<svg class="map-svg" viewBox="0 0 200 225" role="img" aria-label="Violation heatmap (schematic)">
    <polygon points="85,8 105,15 125,25 150,50 158,70 150,95 145,120 135,150 125,180 112,215 105,218 100,200 90,175 75,160 55,145 40,125 32,105 45,95 55,75 65,55 75,30"
      fill="#eef4fa" stroke="#c9d8e8" stroke-width="1.5"/>
    ${dots}
  </svg>`;
}

let _leafletMap = null;

function renderRealMap(containerId, pins) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (typeof L === "undefined") {
    el.innerHTML = `<div class="empty">Map library failed to load — check your connection. Showing ${pins.length} GPS scans below.</div>
      <div style="margin-top:10px;">${pins.map((p) => `<div class="det-kv"><span class="k">${esc(p.city)}</span><span class="v">${esc(p.product)} · ${p.lat.toFixed(3)}, ${p.lng.toFixed(3)} · ${esc(p.status)}</span></div>`).join("")}</div>`;
    return;
  }
  if (_leafletMap) { _leafletMap.remove(); _leafletMap = null; }
  if (!pins.length) {
    el.innerHTML = `<div class="empty">No GPS-tagged scans yet. Scans with location appear here as pins.</div>`;
    el.style.height = "";
    return;
  }
  el.style.height = "420px";
  const centerLat = pins.reduce((s, p) => s + p.lat, 0) / pins.length;
  const centerLng = pins.reduce((s, p) => s + p.lng, 0) / pins.length;
  const map = L.map(containerId).setView([centerLat, centerLng], 5);
  _leafletMap = map;
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 18,
  }).addTo(map);
  const heatPoints = pins.map((p) => [p.lat, p.lng, p.status === "NON-COMPLIANT" ? 1 : 0.3]);
  if (window.L && L.heatLayer) L.heatLayer(heatPoints, { radius: 28, blur: 18, maxZoom: 10, gradient: { 0.3: "#22c55e", 0.6: "#eab308", 1: "#ef4444" } }).addTo(map);
  const bounds = [];
  pins.forEach((p) => {
    const color = p.status === "NON-COMPLIANT" ? "#ef4444" : p.status === "REVIEW" ? "#eab308" : "#22c55e";
    const m = L.circleMarker([p.lat, p.lng], { radius: 8, fillColor: color, color: "#fff", weight: 2, fillOpacity: 0.95 }).addTo(map);
    m.bindPopup(`<b>${esc(p.product)}</b><br>${esc(p.brand)}<br>${esc(p.city)} · ${esc(p.status)}<br>${esc(p.officer_name)} · ${esc(fmtDate(p.date))}<br><a href="#" onclick="event.preventDefault(); window._openDetails && window._openDetails('${esc(p.run_id)}')">View details</a>`);
    bounds.push([p.lat, p.lng]);
  });
  if (bounds.length > 1) map.fitBounds(bounds, { padding: [24, 24] });
  setTimeout(() => map.invalidateSize(), 100);
}

window._openDetails = (runId) => navigate("details", runId);

/* ================= views ================= */
async function navigate(view, param) {
  state.view = view;
  $$("#side-nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  const [title, sub] = TITLES[view] || [view, ""];
  $("#page-title").textContent = title;
  $("#page-sub").textContent = sub;
  const el = $("#view");
  el.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    if (view === "dashboard") await vDashboard(el);
    else if (view === "reports") await vReports(el);
    else if (view === "details") await vDetails(el, param);
    else if (view === "products") await vProducts(el);
    else if (view === "analytics") await vAnalytics(el);
    else if (view === "map") await vMap(el);
    else if (view === "team") await vTeam(el);
    else if (view === "settings") await vSettings(el);
  } catch (e) {
    el.innerHTML = `<div class="card"><div class="empty">Could not load data. Is the server running?<br><span class="muted">${esc(e.message)}</span></div></div>`;
  } finally {
    if (state.view === "map" && _leafletMap) setTimeout(() => _leafletMap.invalidateSize(), 120);
  }
  window.scrollTo(0, 0);
}

function emptyState(el, total) {
  if (total > 0) return false;
  el.innerHTML = `<div class="note-banner">
      <span><b>No scans in the shared database yet.</b> Register officers under Team Management, then every scan from the officer app appears here automatically.</span>
    </div>`;
  return true;
}

async function vDashboard(el) {
  const [ov, tr, brands, locs] = await Promise.all([
    api("/api/dashboard/overview"), api("/api/dashboard/trends?days=7"),
    api("/api/dashboard/brands?limit=5"), api("/api/dashboard/locations"),
  ]);
  if (emptyState(el, ov.total_scans)) return;
  const maxBrand = Math.max(1, ...brands.brands.map((b) => b.violations));
  el.innerHTML = `
    <div class="stat-row">
      <div class="stat blue"><b>${ov.total_scans}</b><span>Total Scans</span></div>
      <div class="stat red"><b>${ov.violations}</b><span>Violations</span></div>
      <div class="stat green"><b>${ov.compliant}</b><span>Compliant</span></div>
      <div class="stat plain"><b>${ov.officials}</b><span>Officials</span></div>
    </div>
    <div class="card">
      <h2>Scans Over Time</h2>
      <p class="sub">Last 7 days · shared database</p>
      <div class="legend"><span><i style="background:#1c9a4f"></i>Compliant</span><span><i style="background:#e35555"></i>Non-Compliant</span></div>
      <div class="chart-wrap">${lineChart(tr.labels, tr.compliant, tr.non_compliant)}</div>
    </div>
    <div class="grid-2 grid-2-wrap">
      <div class="card">
        <h2>Product/Brand-wise Analysis</h2>
        <p class="sub">Violations by brand</p>
        ${hbars(brands.brands.map((b) => ({ label: b.brand, value: b.violations })), maxBrand, true)}
      </div>
      <div class="card">
        <h2>Geographical Heatmap</h2>
        <p class="sub">Violations by region</p>
        ${hbars(locs.locations.slice(0, 5).map((l) => ({ label: `${l.city} · ${l.violations} violations`, value: l.violations })), Math.max(1, ...locs.locations.map((l) => l.violations)), true)}
      </div>
    </div>`;
}

async function vReports(el) {
  const data = await api(`/api/dashboard/scans?status=${state.scanFilter}&q=${encodeURIComponent(state.scanQuery)}`);
  el.innerHTML = `
    <div class="card">
      <h2>Reports</h2>
      <p class="sub">All scans per official with status · same data as the officer app</p>
      <div class="toolbar">
        <div class="chip-row" id="rep-filters">
          ${["all", "COMPLIANT", "NON-COMPLIANT"].map((f) =>
            `<button class="f-chip${state.scanFilter === f ? " active" : ""}" data-f="${f}">${
              f === "all" ? "All" : f === "COMPLIANT" ? "Compliant" : "Non-Compliant"}</button>`).join("")}
        </div>
        <input class="search" id="rep-search" placeholder="Search product, brand, official…" value="${esc(state.scanQuery)}">
      </div>
      <div style="overflow-x:auto;">
      <table class="data">
        <thead><tr><th>Date</th><th>Product</th><th>Brand</th><th>Location</th><th>Official</th><th>Status</th><th>Report</th><th>Actions</th></tr></thead>
        <tbody>
          ${data.scans.map((s) => `<tr>
            <td>${esc(fmtDate(s.date))}</td>
            <td><b>${esc(s.product)}</b></td>
            <td>${esc(s.brand)}</td>
            <td>${esc(s.city)}</td>
            <td>${esc(s.officer_name)}</td>
            <td>${statusChip(s.status)}</td>
            <td>${s.submitted
              ? `<span class="status-chip COMPLIANT"><span class="status-dot"></span>Submitted</span>`
              : s.report_generated
                ? `<span class="status-chip REVIEW"><span class="status-dot"></span>Generated</span>`
                : `<span class="muted">—</span>`}</td>
            <td><button class="link-btn" data-run="${esc(s.run_id)}">View</button></td>
          </tr>`).join("") || `<tr><td colspan="8"><div class="empty">No scans match.</div></td></tr>`}
        </tbody>
      </table>
      </div>
    </div>`;
  $$("#rep-filters .f-chip", el).forEach((c) => c.addEventListener("click", () => {
    state.scanFilter = c.dataset.f;
    vReports(el);
  }));
  const search = $("#rep-search", el);
  let t = null;
  search.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => { state.scanQuery = search.value; vReports(el); }, 350);
  });
  // keep focus at end after re-render
  search.focus();
  search.setSelectionRange(search.value.length, search.value.length);
  $$("[data-run]", el).forEach((b) => b.addEventListener("click", () => navigate("details", b.dataset.run)));
}

async function vDetails(el, runId) {
  if (!runId) {
    el.innerHTML = `<div class="card"><div class="empty">Select a report from the <b>Reports</b> table to inspect it here.</div>
      <div style="text-align:center;"><button class="btn btn-outline btn-sm" id="go-reports">Open reports</button></div></div>`;
    $("#go-reports").addEventListener("click", () => navigate("reports"));
    return;
  }
  const d = await api(`/api/dashboard/scans/${runId}`);
  if (d.error) {
    el.innerHTML = `<div class="card"><div class="empty">${esc(d.error)}</div></div>`;
    return;
  }
  const r = d.result;
  const checks = (r && r.compliance && r.compliance.checks) || [];
  const issues = checks.filter((c) => c.status !== "PASS");
  const conflicts = (r && r.compliance && r.compliance.conflicts) || [];
  const firstImg = r && r.images && r.images[0];
  el.innerHTML = `
    <button class="back-link" id="det-back">← Back to reports</button>
    <div class="det-layout">
      <div class="card">
        ${firstImg ? `<div class="det-photo"><img src="${esc(firstImg.annotated_url)}" alt="Product photo"></div>` : ""}
        <div class="det-name">${esc(d.product)}</div>
        <div class="det-brand">${esc(d.brand)}</div>
        <div style="margin-bottom:10px;">${statusChip(d.status)}</div>
        <div class="det-kv"><span class="k">Inspection</span><span class="v">${esc(d.inspection_id)}</span></div>
        <div class="det-kv"><span class="k">Location</span><span class="v">${esc(d.city)}${d.lat != null ? ` (${Number(d.lat).toFixed(4)}°, ${Number(d.lng).toFixed(4)}°)` : ""}</span></div>
        <div class="det-kv"><span class="k">Official</span><span class="v">${esc(d.officer_name)}</span></div>
        <div class="det-kv"><span class="k">Date</span><span class="v">${esc(fmtDate(d.date))}</span></div>
        <div class="det-kv"><span class="k">Report</span><span class="v">${d.submitted ? "Submitted to supervisor" : d.report_generated ? "Generated, not yet submitted" : "Not generated yet"}</span></div>
      </div>
      <div>
        <div class="card">
          <h2>Detected Issues</h2>
          <p class="sub">${issues.length + conflicts.length ? "Declarations that failed or need review" : "No issues — all checks passed"}</p>
          <ul class="issue-list">
            ${issues.map((c) => `<li><span class="x">●</span><span><b>${esc(c.label)}</b> — ${esc(c.reason)}</span></li>`).join("")}
            ${conflicts.map((c) => `<li><span class="x">●</span><span><b>MRP consistency</b> — ${esc(c.message)} (${c.values.map((v) => "₹" + v).join(", ")})</span></li>`).join("")}
          </ul>
        </div>
        <div class="card">
          <h2>Previous Reports</h2>
          <p class="sub">Similar violations on record</p>
          ${(d.similar && d.similar.length)
            ? `<ul class="issue-list">${d.similar.map((s) =>
              `<li><span class="x">●</span><span><b>${esc(s.product)}</b> flagged in ${esc(s.city)} · ${esc(fmtDate(s.date))} · ${esc(s.officer_name)}</span></li>`).join("")}</ul>`
            : `<div class="empty">No similar violations found in this region.</div>`}
        </div>
        ${r && r.images && r.images.length ? `<div class="card">
          <h2>Extracted Label (Highlighted)</h2>
          <p class="sub">Annotated OCR evidence from the officer's scan</p>
          ${r.images.slice(0, 3).map((img) =>
            `<div class="ev-thumb"><img src="${esc(img.annotated_url)}" alt="Annotated label"></div>`).join("")}
        </div>` : ""}
      </div>
    </div>`;
  $("#det-back").addEventListener("click", () => navigate("reports"));
}

async function vProducts(el) {
  const brands = await api("/api/dashboard/brands?limit=20");
  const scans = await api("/api/dashboard/scans?limit=500");
  const byProduct = {};
  scans.scans.forEach((s) => {
    const k = `${s.product} — ${s.brand}`;
    byProduct[k] = byProduct[k] || { product: s.product, brand: s.brand, total: 0, violations: 0 };
    byProduct[k].total += 1;
    if (s.status === "NON-COMPLIANT") byProduct[k].violations += 1;
  });
  const products = Object.values(byProduct).sort((a, b) => b.violations - a.violations || b.total - a.total).slice(0, 15);
  const maxV = Math.max(1, ...brands.brands.map((b) => b.violations));
  el.innerHTML = `
    <div class="grid-2 grid-2-wrap">
      <div class="card">
        <h2>Violations by Brand</h2>
        <p class="sub">Identify frequently flagged brands</p>
        ${hbars(brands.brands.map((b) => ({ label: b.brand, value: b.violations })), maxV, true)}
      </div>
      <div class="card">
        <h2>Scan Volume by Brand</h2>
        <p class="sub">Total inspections per brand</p>
        ${hbars(brands.brands.map((b) => ({ label: b.brand, value: b.total })), Math.max(1, ...brands.brands.map((b) => b.total)), false)}
      </div>
    </div>
    <div class="card">
      <h2>Top Flagged Products</h2>
      <p class="sub">Products with the most violations on record</p>
      <table class="data">
        <thead><tr><th>Product</th><th>Brand</th><th>Scans</th><th>Violations</th></tr></thead>
        <tbody>${products.map((p) => `<tr><td><b>${esc(p.product)}</b></td><td>${esc(p.brand)}</td><td>${p.total}</td><td>${statusChip(p.violations ? "NON-COMPLIANT" : "COMPLIANT").replace(/Non-Compliant|Compliant/, p.violations)}</td></tr>`).join("")}</tbody>
      </table>
    </div>`;
}

async function vAnalytics(el) {
  const [tr, brands, officers] = await Promise.all([
    api("/api/dashboard/trends?days=14"), api("/api/dashboard/brands?limit=8"), api("/api/dashboard/officers"),
  ]);
  const maxB = Math.max(1, ...brands.brands.map((b) => b.violations));
  const ranked = [...officers.officers].sort((a, b) => b.scans - a.scans).slice(0, 6);
  const maxS = Math.max(1, ...ranked.map((o) => o.scans));
  el.innerHTML = `
    <div class="card">
      <h2>Scans Over Time</h2>
      <p class="sub">Last 14 days</p>
      <div class="legend"><span><i style="background:#1c9a4f"></i>Compliant</span><span><i style="background:#e35555"></i>Non-Compliant</span></div>
      <div class="chart-wrap">${lineChart(tr.labels, tr.compliant, tr.non_compliant)}</div>
    </div>
    <div class="grid-2 grid-2-wrap">
      <div class="card">
        <h2>Violations by Brand</h2>
        <p class="sub">Top flagged brands</p>
        ${hbars(brands.brands.map((b) => ({ label: b.brand, value: b.violations })), maxB, true)}
      </div>
      <div class="card">
        <h2>Officer Activity</h2>
        <p class="sub">Scans per officer</p>
        ${hbars(ranked.map((o) => ({ label: `${o.name} (${o.id})`, value: o.scans })), maxS, false)}
      </div>
    </div>`;
}

async function vMap(el) {
  const [locs, pinsRes] = await Promise.all([api("/api/dashboard/locations"), api("/api/dashboard/map-pins")]);
  const pins = pinsRes.pins || [];
  const maxV = Math.max(1, ...locs.locations.map((l) => l.violations));
  el.innerHTML = `
    <div class="card">
      <h2>Live Violation Map</h2>
      <p class="sub">${pins.length ? `${pins.length} GPS-tagged scan${pins.length === 1 ? "" : "s"} · violations in red, heat overlay` : "No GPS-tagged scans yet — allow location on the officer device"}</p>
      <div id="real-map" style="border-radius:14px; overflow:hidden; border:1px solid var(--border-soft);"></div>
      <div class="legend" style="margin-top:10px;"><span><i style="background:#ef4444"></i>Violation</span><span><i style="background:#eab308"></i>Review</span><span><i style="background:#22c55e"></i>Compliant</span></div>
    </div>
    <div class="grid-2 grid-2-wrap">
      <div class="card">
        <h2>Violations by Region</h2>
        <p class="sub">Heatmap of violations by city / region</p>
        ${hbars(locs.locations.map((l) => ({ label: `${l.city} · ${l.violations} violations`, value: l.violations })), maxV, true)}
      </div>
    </div>`;
  // Leaflet needs the container in the DOM before initialising.
  setTimeout(() => renderRealMap("real-map", pins), 0);
}

async function vTeam(el) {
  const data = await api("/api/dashboard/officers");
  const groups = {};
  data.officers.forEach((o) => {
    (groups[o.dept] = groups[o.dept] || []).push(o);
  });
  el.innerHTML = `
    ${Object.entries(groups).map(([dept, members]) => `
      <div class="card">
        <div class="team-head">${esc(dept)} <span class="count">${members.length} officer${members.length === 1 ? "" : "s"}</span></div>
        <table class="data">
          <thead><tr><th>Officer ID</th><th>Name</th><th>Scans</th><th>Violations</th><th></th></tr></thead>
          <tbody>${members.map((o) => `<tr>
            <td><b>${esc(o.id)}</b></td><td>${esc(o.name)}</td><td>${o.scans}</td><td>${o.violations || 0}</td>
            <td><button class="link-btn" data-remove="${esc(o.id)}">Remove</button></td>
          </tr>`).join("")}</tbody>
        </table>
      </div>`).join("") || `<div class="card"><div class="empty">No teams yet.</div></div>`}
    <div class="card">
      <h2>Add Officer</h2>
      <p class="sub">Register an officer ID they can sign in with on the inspect app</p>
      <div class="inline-form">
        <input id="new-off-id" placeholder="Officer ID (e.g. OFF6604)">
        <input id="new-off-name" placeholder="Full name">
        <input id="new-off-dept" placeholder="Group / department">
        <button class="btn btn-gradient btn-sm" id="add-off">Add</button>
      </div>
    </div>`;
  $$("[data-remove]", el).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Remove ${b.dataset.remove} from your team? Their past scans stay on record.`)) return;
    await api(`/api/dashboard/officers/${encodeURIComponent(b.dataset.remove)}`, { method: "DELETE" });
    navigate("team");
  }));
  $("#add-off").addEventListener("click", async () => {
    const id = $("#new-off-id").value.trim();
    if (!id) return;
    await api("/api/dashboard/officers", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, name: $("#new-off-name").value.trim(), dept: $("#new-off-dept").value.trim() }),
    });
    navigate("team");
  });
}

async function vSettings(el) {
  const health = await api("/api/health");
  el.innerHTML = `
    <div class="card">
      <h2>Deployment</h2>
      <p class="sub">One service, two doors, one shared database</p>
      <div class="det-kv"><span class="k">Officer app</span><span class="v"><a href="/inspect">/inspect</a> — mobile scanning</span></div>
      <div class="det-kv"><span class="k">This dashboard</span><span class="v"><a href="/supervise">/supervise</a> — desktop supervision</span></div>
      <div class="det-kv"><span class="k">Database</span><span class="v">MongoDB Atlas · officers + scans in one store</span></div>
      <div class="det-kv"><span class="k">Rule set</span><span class="v">${esc(health.rule_set.rule_set_id)} — ${esc(health.rule_set.title)}</span></div>
      <div class="det-kv"><span class="k">OCR service</span><span class="v">${health.ocr_service && health.ocr_service.reachable ? "reachable (" + esc(health.ocr_service.service || "OCR") + ")" : "unreachable"}</span></div>
    </div>
    <div class="card">
      <h2>Change Password</h2>
      <p class="sub">Replace the initial supervisor password — all sessions sign out afterwards</p>
      <div class="inline-form">
        <input id="pw-current" type="password" placeholder="Current password" autocomplete="current-password">
        <input id="pw-new" type="password" placeholder="New password (min 6 characters)" autocomplete="new-password">
        <button class="btn btn-gradient btn-sm" id="pw-change">Update</button>
      </div>
      <div class="muted" id="pw-msg" style="margin-top:10px;"></div>
    </div>
    <div class="card">
      <h2>Live Data Pipeline</h2>
      <p class="sub">Everything here is live — no demo data</p>
      <div class="det-kv"><span class="k">Officer scans</span><span class="v">/inspect → MongoDB scans collection → this dashboard (live)</span></div>
      <div class="det-kv"><span class="k">Officer roster</span><span class="v">Team Management → officers table → login checks</span></div>
      <div class="det-kv"><span class="k">Refresh</span><span class="v">Views refetch on every navigation and whenever this tab regains focus</span></div>
    </div>`;
  $("#pw-change").addEventListener("click", async () => {
    const msg = $("#pw-msg");
    const current = $("#pw-current").value;
    const next = $("#pw-new").value;
    if (next.length < 6) { msg.textContent = "New password must be at least 6 characters."; return; }
    const res = await fetch("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify({ current, new: next }),
    });
    if (res.ok) {
      localStorage.removeItem(SESSION_KEY);
      location.href = "/login";
    } else {
      const data = await res.json().catch(() => ({}));
      msg.textContent = data.detail || "Could not update password.";
    }
  });
}

/* ================= boot ================= */
async function boot() {
  // Auth lives on the landing page (/login). This dashboard needs a supervisor session.
  let me = null;
  try {
    me = await api("/api/auth/me");
  } catch (e) { /* keep gate visible; don't auto-redirect and hide the sign-in prompt */ return; }
  if (!me || me.role !== "supervisor") {
    return;
  }
  document.getElementById("sup-gate")?.classList.add("hidden");
  state.sup = { id: me.id, name: me.name };
  $("#sup-app").classList.remove("hidden");
  $("#sup-who").textContent = `${me.name} · ${me.id}`;
  $$("#side-nav button").forEach((b) => b.addEventListener("click", () => navigate(b.dataset.view)));
  $("#sup-logout").addEventListener("click", async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ }
    localStorage.removeItem(SESSION_KEY);
    location.href = "/login";
  });
  // Live board: refetch list views whenever the tab regains focus + poll every 12s.
  window.addEventListener("focus", () => {
    if (["dashboard", "reports", "products", "analytics", "map", "team"].includes(state.view)) {
      navigate(state.view);
    }
  });
  setInterval(() => {
    if (["dashboard", "reports", "map"].includes(state.view)) navigate(state.view);
  }, 12000);
  navigate("dashboard");
}

document.addEventListener("DOMContentLoaded", boot);
})();
