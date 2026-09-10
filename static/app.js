(() => {
"use strict";

/* ============================================================
   Constants
   ============================================================ */
const ANGLE_SLOTS = [
  { id: "front", label: "Front" },
  { id: "back", label: "Back" },
  { id: "left", label: "Left" },
  { id: "right", label: "Right" },
  { id: "top", label: "Top" },
  { id: "bottom", label: "Bottom" },
];

const ANALYSIS_STEPS = [
  "Enhancing image quality",
  "Detecting text (OCR)",
  "Extracting declarations",
  "Validating against rules",
  "Finalizing results",
];

const FIELD_LABELS = {
  product_name: "Product name",
  manufacturer: "Manufacturer / packer",
  address: "Address",
  net_quantity: "Net quantity",
  mrp: "MRP",
  date: "Packing / mfg. date",
  consumer_care: "Consumer care",
  country_of_origin: "Country of origin",
  readability: "Readability score",
};

const STORAGE_KEYS = {
  officer: "compliscan.officer",
  history: "compliscan.history",
  settings: "compliscan.settings",
};

const RING_CIRCUMFERENCE = 2 * Math.PI * 74;

/* ============================================================
   Tiny utilities
   ============================================================ */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[m]));
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function fmtDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) {
    return iso || "—";
  }
}

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (e) {
    return fallback;
  }
}
function writeJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage full/unavailable */ }
}

/* ============================================================
   App state
   ============================================================ */
const state = {
  officer: readJSON(STORAGE_KEYS.officer, null),
  history: readJSON(STORAGE_KEYS.history, []),
  settings: readJSON(STORAGE_KEYS.settings, { defaultBackend: "auto", lastSync: null }),
  captureSlots: {},   // id -> { file, dataUrl, name }
  extraShots: [],      // [{ file, dataUrl, name }]
  currentRun: null,    // last /api/scan response
  currentHistoryId: null, // id of the history entry currently being viewed
  resultOrigin: "home", // where to go back to from result screen
  location: null,      // { lat, lng } if geolocation succeeded
};

/* ============================================================
   Icons (small inline helpers reused across dynamic renders)
   ============================================================ */
const ICONS = {
  check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="m5 13 4 4L19 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  cross: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
  warn: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M12 9v4.5M12 17v.01" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M10.9 4.3 2.7 18a1.8 1.8 0 0 0 1.5 2.7h15.6a1.8 1.8 0 0 0 1.5-2.7L13.1 4.3a1.8 1.8 0 0 0-2.2 0Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>',
  camera: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M4 8V6a2 2 0 0 1 2-2h2M4 16v2a2 2 0 0 0 2 2h2M20 8V6a2 2 0 0 0-2-2h-2M20 16v2a2 2 0 0 1-2 2h-2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.7"/></svg>',
  image: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="16" rx="2.4" stroke="currentColor" stroke-width="1.6"/><circle cx="8.3" cy="9.3" r="1.6" stroke="currentColor" stroke-width="1.5"/><path d="m4 17 5-5 3.2 3.2L16 10.5l4 4.5" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
};

function checkIconFor(status) {
  if (status === "PASS") return ICONS.check;
  if (status === "FAIL") return ICONS.cross;
  return ICONS.warn;
}

/* ============================================================
   Screen / navigation management
   ============================================================ */
const TABBAR_SCREENS = new Set(["home", "history", "reports", "profile"]);

function navigateToTab(screen) {
  if (screen === "home") renderHome();
  if (screen === "history") renderHistory();
  if (screen === "reports") renderReports();
  if (screen === "profile") renderProfile();
  showScreen(screen);
}

function showScreen(name) {
  $$(".screen").forEach((el) => el.classList.remove("active"));
  const el = $("#screen-" + name);
  if (el) el.classList.add("active");
  const tabbar = $("#tabbar");
  if (TABBAR_SCREENS.has(name)) {
    tabbar.classList.remove("hidden");
    $$(".tab-item", tabbar).forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.nav === name);
    });
  } else {
    tabbar.classList.add("hidden");
  }
  $("#app-body").scrollTop = 0;
  if (el) el.scrollTop = 0;
}

let toastTimer = null;
function toast(message) {
  const el = $("#toast");
  $("#toast-text").textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2400);
}

/* ============================================================
   Boot / auth
   ============================================================ */
function boot() {
  wireStaticEvents();
  renderCaptureGrid();

  if (state.officer) {
    enterApp();
  } else {
    showScreen("login");
  }
}

function enterApp() {
  renderProfile();
  renderHome();
  showScreen("home");
  tryGeolocate();
}

function login(officer) {
  state.officer = officer;
  writeJSON(STORAGE_KEYS.officer, officer);
  toast(`Welcome, ${officer.name.split(" ")[0]}`);
  enterApp();
}

function logout() {
  state.officer = null;
  localStorage.removeItem(STORAGE_KEYS.officer);
  showScreen("login");
}

function tryGeolocate() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    (pos) => { state.location = { lat: pos.coords.latitude, lng: pos.coords.longitude }; },
    () => { /* silently ignore — location is optional in this prototype */ },
    { timeout: 4000 }
  );
}

/* ============================================================
   Static event wiring (elements that always exist)
   ============================================================ */
function wireStaticEvents() {
  // Login
  $("#login-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const id = $("#li-id").value.trim();
    const name = $("#li-name").value.trim();
    const dept = $("#li-dept").value.trim() || "Legal Metrology Department";
    if (!id || !name) return;
    login({ id, name, dept });
  });
  $("#btn-govt-id").addEventListener("click", () => {
    login({ id: "GOVT-VERIFIED", name: "Verified Officer", dept: "Legal Metrology Department" });
  });
  $("#btn-offline").addEventListener("click", () => {
    login({ id: "OFFLINE", name: "Offline Officer", dept: "Legal Metrology Department" });
  });

  // Tab bar
  $$(".tab-item[data-nav]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const screen = btn.dataset.nav;
      if (screen === "home") renderHome();
      if (screen === "history") renderHistory();
      if (screen === "reports") renderReports();
      if (screen === "profile") renderProfile();
      showScreen(screen);
    });
  });
  $("#tab-scan").addEventListener("click", () => startCaptureFlow("home"));
  $("#home-scan-cta").addEventListener("click", () => startCaptureFlow("home"));
  $("#home-profile-btn").addEventListener("click", () => { renderProfile(); showScreen("profile"); });
  $("#qa-history").addEventListener("click", () => { renderHistory(); showScreen("history"); });
  $("#qa-reports").addEventListener("click", () => { renderReports(); showScreen("reports"); });

  // Capture
  $("#capture-back").addEventListener("click", () => navigateToTab(state.resultOrigin === "history" ? "history" : "home"));
  $("#extra-shot-input").addEventListener("change", onExtraShotChosen);
  $("#btn-proceed-analysis").addEventListener("click", onProceedToAnalysis);

  // Result
  $("#result-back").addEventListener("click", () => navigateToTab(state.resultOrigin));
  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab-btn").forEach((b) => b.classList.remove("active"));
      $$(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("#tab-" + btn.dataset.tab).classList.add("active");
    });
  });
  $("#btn-generate-report").addEventListener("click", () => {
    markCurrentReportGenerated();
    renderReport();
    showScreen("report");
  });

  // Report
  $("#report-back").addEventListener("click", () => showScreen("result"));
  $("#report-share").addEventListener("click", downloadPdf);
  $("#btn-download-pdf").addEventListener("click", downloadPdf);
  $("#btn-submit-supervisor").addEventListener("click", submitToSupervisor);

  // History
  $$("#history-filters .filter-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $$("#history-filters .filter-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      renderHistory(chip.dataset.filter);
    });
  });
  $("#history-clear").addEventListener("click", () => {
    if (!state.history.length) return;
    if (confirm("Clear all scan history on this device?")) {
      state.history = [];
      writeJSON(STORAGE_KEYS.history, state.history);
      renderHistory();
      renderHome();
    }
  });

  // Profile
  $("#profile-sync").addEventListener("click", () => {
    state.settings.lastSync = new Date().toISOString();
    writeJSON(STORAGE_KEYS.settings, state.settings);
    renderProfile();
    toast("Data synced");
  });
  $("#profile-settings").addEventListener("click", () => {
    const order = ["auto", "paddle", "tesseract", "mock"];
    const next = order[(order.indexOf(state.settings.defaultBackend) + 1) % order.length];
    state.settings.defaultBackend = next;
    writeJSON(STORAGE_KEYS.settings, state.settings);
    toast(`Default OCR engine set to ${next}`);
  });
  $("#profile-help").addEventListener("click", () => {
    toast("For support, contact your district Legal Metrology office.");
  });
  $("#profile-logout").addEventListener("click", () => {
    if (confirm("Log out of CompliScan?")) logout();
  });
}

/* ============================================================
   HOME
   ============================================================ */
function renderHome() {
  if (!state.officer) return;
  $("#home-greeting").textContent = `Hello, ${state.officer.name.split(" ")[0]}!`;

  const now = new Date();
  const monthEntries = state.history.filter((h) => {
    const d = new Date(h.date);
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  });
  $("#stat-scans").textContent = monthEntries.length;
  $("#stat-flagged").textContent = monthEntries.filter((h) => h.status === "NON-COMPLIANT").length;
  $("#stat-pending").textContent = monthEntries.filter((h) => !h.submitted).length;

  const recent = [...state.history].sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 5);
  const listEl = $("#home-recent-list");
  const emptyEl = $("#home-recent-empty");
  listEl.innerHTML = "";
  emptyEl.classList.toggle("hidden", recent.length > 0);
  recent.forEach((h) => listEl.appendChild(buildRecentRow(h)));
}

function buildRecentRow(h) {
  const row = document.createElement("div");
  row.className = "recent-row";
  row.innerHTML = `
    <div class="recent-thumb">${ICONS.image}</div>
    <div class="recent-info">
      <div class="rn">${esc(h.product || "Unnamed product")}</div>
      <div class="rd">${esc(fmtDate(h.date))}</div>
    </div>
    <span class="status-chip ${h.status}"><span class="status-dot"></span>${statusLabel(h.status)}</span>
  `;
  row.addEventListener("click", () => openHistoryEntry(h.id, "home"));
  return row;
}

function statusLabel(status) {
  if (status === "COMPLIANT") return "Compliant";
  if (status === "NON-COMPLIANT") return "Flagged";
  if (status === "REVIEW") return "Review";
  return status;
}

/* ============================================================
   CAPTURE
   ============================================================ */
function startCaptureFlow(origin) {
  state.resultOrigin = origin;
  state.captureSlots = {};
  state.extraShots = [];
  renderCaptureGrid();
  renderExtraShots();
  updateCaptureFooter();
  $("#backend-select").value = state.settings.defaultBackend || "auto";
  showScreen("capture");
}

function renderCaptureGrid() {
  const grid = $("#capture-grid");
  grid.innerHTML = "";
  ANGLE_SLOTS.forEach((slot) => {
    const el = document.createElement("label");
    el.className = "capture-slot";
    el.dataset.slot = slot.id;
    el.innerHTML = `
      <input type="file" accept="image/*" capture="environment" data-slot-input="${slot.id}">
      <span class="cs-icon">${ICONS.camera}</span>
      <span class="cs-label">${slot.label}</span>
    `;
    el.querySelector("input").addEventListener("change", (e) => onSlotChosen(slot, e));
    grid.appendChild(el);
  });
}

async function onSlotChosen(slot, e) {
  const file = e.target.files[0];
  if (!file) return;
  const dataUrl = await fileToDataUrl(file);
  state.captureSlots[slot.id] = { file, dataUrl, name: `${slot.id}_${file.name}` };
  renderSlotFilled(slot);
  updateCaptureFooter();
}

function renderSlotFilled(slot) {
  const el = $(`.capture-slot[data-slot="${slot.id}"]`);
  const shot = state.captureSlots[slot.id];
  if (!shot) return;
  el.classList.add("filled");
  el.innerHTML = `
    <input type="file" accept="image/*" capture="environment" data-slot-input="${slot.id}">
    <img class="cs-preview" src="${shot.dataUrl}" alt="${esc(slot.label)} preview">
    <span class="cs-badge">${ICONS.check}${slot.label}</span>
    <button type="button" class="cs-remove" aria-label="Remove">${ICONS.cross}</button>
  `;
  el.querySelector("input").addEventListener("change", (e) => onSlotChosen(slot, e));
  el.querySelector(".cs-remove").addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    delete state.captureSlots[slot.id];
    renderCaptureGrid();
    // re-render any already-filled slots after the full grid reset
    Object.keys(state.captureSlots).forEach((id) => {
      const s = ANGLE_SLOTS.find((a) => a.id === id);
      if (s) renderSlotFilled(s);
    });
    updateCaptureFooter();
  });
}

async function onExtraShotChosen(e) {
  const file = e.target.files[0];
  if (!file) return;
  const dataUrl = await fileToDataUrl(file);
  state.extraShots.push({ file, dataUrl, name: `extra_${state.extraShots.length + 1}_${file.name}` });
  e.target.value = "";
  renderExtraShots();
  updateCaptureFooter();
}

function renderExtraShots() {
  const list = $("#extra-shots-list");
  list.innerHTML = "";
  state.extraShots.forEach((shot, idx) => {
    const tile = document.createElement("div");
    tile.className = "extra-shot";
    tile.innerHTML = `<img src="${shot.dataUrl}" alt="Additional angle"><button type="button" aria-label="Remove">${ICONS.cross}</button>`;
    tile.querySelector("button").addEventListener("click", () => {
      state.extraShots.splice(idx, 1);
      renderExtraShots();
      updateCaptureFooter();
    });
    list.appendChild(tile);
  });
  const addTile = document.createElement("label");
  addTile.className = "add-shot-tile";
  addTile.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><input type="file" accept="image/*" capture="environment" id="extra-shot-input">`;
  addTile.querySelector("input").addEventListener("change", onExtraShotChosen);
  list.appendChild(addTile);
}

function collectAllShots() {
  const slotShots = ANGLE_SLOTS.filter((s) => state.captureSlots[s.id]).map((s) => state.captureSlots[s.id]);
  return [...slotShots, ...state.extraShots];
}

function updateCaptureFooter() {
  const count = collectAllShots().length;
  $("#capture-count").textContent = count === 0 ? "0 images captured" : `${count} image${count > 1 ? "s" : ""} captured`;
  $("#btn-proceed-analysis").disabled = count === 0;
}

function onProceedToAnalysis() {
  const shots = collectAllShots();
  if (!shots.length) return;
  const backend = $("#backend-select").value;
  runAnalysis(shots, backend);
}

/* ============================================================
   ANALYZING
   ============================================================ */
function renderAnalysisSteps() {
  const list = $("#analyzing-steps");
  list.innerHTML = "";
  ANALYSIS_STEPS.forEach((label, i) => {
    const row = document.createElement("div");
    row.className = "step-row";
    row.dataset.step = i;
    row.innerHTML = `<span class="step-icon"><span class="spinner"></span></span><span>${esc(label)}</span>`;
    list.appendChild(row);
  });
}

function setStepState(i, cls) {
  const row = $(`.step-row[data-step="${i}"]`);
  if (!row) return;
  row.classList.remove("active", "done");
  if (cls) row.classList.add(cls);
  const icon = row.querySelector(".step-icon");
  icon.innerHTML = cls === "done" ? ICONS.check : cls === "active" ? '<span class="spinner"></span>' : "";
}

function setRingProgress(pct) {
  const ring = $("#ring-fg");
  const offset = RING_CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, pct)) / 100);
  ring.style.strokeDashoffset = String(offset);
  $("#ring-pct").textContent = `${Math.round(pct)}%`;
}

async function runAnalysis(shots, backendVal) {
  state.resultOrigin = state.resultOrigin || "home";
  showScreen("analyzing");
  renderAnalysisSteps();
  setRingProgress(0);
  setStepState(0, "active");

  let stepIndex = 0;
  const stepTimer = setInterval(() => {
    if (stepIndex < ANALYSIS_STEPS.length - 1) {
      setStepState(stepIndex, "done");
      stepIndex += 1;
      setStepState(stepIndex, "active");
    }
    const softCap = Math.min(90, Math.round(((stepIndex + 0.5) / ANALYSIS_STEPS.length) * 100));
    setRingProgress(softCap);
  }, 900);

  try {
    const formData = new FormData();
    shots.forEach((shot) => formData.append("files", shot.file, shot.name));
    formData.append("backend", backendVal);

    const response = await fetch("/api/scan", { method: "POST", body: formData });
    const data = await response.json();
    clearInterval(stepTimer);
    if (!response.ok || data.error) throw new Error(data.error || "Scan failed");

    for (let i = stepIndex; i < ANALYSIS_STEPS.length; i++) {
      setStepState(i, "done");
      setRingProgress(Math.round(((i + 1) / ANALYSIS_STEPS.length) * 100));
      await sleep(140);
    }
    setRingProgress(100);
    await sleep(280);
    handleScanSuccess(data, shots);
  } catch (err) {
    clearInterval(stepTimer);
    toast(err.message || "Scan failed — please try again.");
    showScreen("capture");
  }
}

/* ============================================================
   Scan result → history entry
   ============================================================ */
function handleScanSuccess(data, shots) {
  state.currentRun = data;
  const c = data.compliance;
  const fields = c.fields || {};

  const entry = {
    id: data.inspection_id,
    date: new Date().toISOString(),
    product: fields.product_name && fields.product_name.value ? fields.product_name.value : "Unnamed product",
    manufacturer: fields.manufacturer && fields.manufacturer.value ? fields.manufacturer.value : null,
    netQuantity: fields.net_quantity && fields.net_quantity.value ? fields.net_quantity.value : null,
    status: c.overall_status,
    passed: c.summary.passed,
    failed: c.summary.failed,
    review: c.summary.review,
    submitted: false,
    reportGenerated: false,
    imageCount: (data.images || []).length,
    raw: stripBoxesForStorage(data),
  };

  const existingIdx = state.history.findIndex((h) => h.id === entry.id);
  if (existingIdx >= 0) state.history[existingIdx] = entry; else state.history.unshift(entry);
  writeJSON(STORAGE_KEYS.history, state.history);
  state.currentHistoryId = entry.id;

  renderResult(data);
  showScreen("result");
}

function stripBoxesForStorage(data) {
  // Keep the payload lean for localStorage: drop the raw OCR boxes, keep everything the UI renders.
  const clone = JSON.parse(JSON.stringify(data));
  (clone.images || []).forEach((img) => { delete img.boxes; });
  return clone;
}

function openHistoryEntry(id, origin) {
  const entry = state.history.find((h) => h.id === id);
  if (!entry) return;
  state.resultOrigin = origin;
  state.currentHistoryId = id;
  state.currentRun = entry.raw;
  renderResult(entry.raw);
  showScreen("result");
}

/* ============================================================
   RESULT
   ============================================================ */
function renderResult(data) {
  const c = data.compliance;
  const fields = c.fields || {};

  const hero = $("#result-hero");
  hero.className = `result-hero ${c.overall_status}`;
  $("#result-hero-status").textContent = statusLabel(c.overall_status);
  $("#result-hero-badge").innerHTML = c.overall_status === "COMPLIANT" ? ICONS.check : c.overall_status === "NON-COMPLIANT" ? ICONS.cross : ICONS.warn;
  $("#result-hero-meta").textContent = `${data.inspection_id} · Rule set ${data.rule_set_id} · ${(data.images || []).length} image(s)`;

  $("#result-product-name").textContent = (fields.product_name && fields.product_name.value) || "Product name not detected";
  const sub = [];
  if (fields.net_quantity && fields.net_quantity.value) sub.push(`Net qty: ${fields.net_quantity.value}`);
  if (fields.mrp && fields.mrp.value) sub.push(`MRP: ₹${fields.mrp.value}`);
  $("#result-product-sub").textContent = sub.length ? sub.join(" · ") : "No net quantity / MRP detected";

  $("#find-pass").textContent = c.summary.passed;
  $("#find-fail").textContent = c.summary.failed;
  $("#find-review").textContent = c.summary.review;

  const conflictsEl = $("#result-conflicts");
  conflictsEl.innerHTML = "";
  (c.conflicts || []).forEach((conf) => {
    const div = document.createElement("div");
    div.className = "conflict-note";
    div.innerHTML = `${ICONS.warn}<span><b>${esc(conf.type.replace(/_/g, " "))}:</b> ${esc(conf.message)} (${conf.values.map((v) => "₹" + v).join(", ")})</span>`;
    conflictsEl.appendChild(div);
  });

  renderChecksTab(c);
  renderFieldsTab(fields);
  renderEvidenceTab(data.images || []);

  const warnings = (data.warnings || []).length ? `<div style="margin-top:8px;">Notes: ${esc(data.warnings.join("; "))}</div>` : "";
  $("#result-disclaimer").innerHTML = esc(data.disclaimer) + warnings;
}

function renderChecksTab(c) {
  const el = $("#checks-list");
  el.innerHTML = "";
  c.checks.forEach((row) => {
    const div = document.createElement("div");
    div.className = "check-row";
    const f = row.field || {};
    const confPct = Math.round((f.confidence || 0) * 100);
    div.innerHTML = `
      <div class="check-icon ${row.status}">${checkIconFor(row.status)}</div>
      <div class="check-main">
        <div class="check-label">${esc(row.label)}</div>
        <div class="check-reason">${esc(row.reason)}</div>
        ${f.value != null ? `<div class="check-value">Detected: "${esc(f.value)}" · ${confPct}% confidence</div>` : ""}
      </div>
    `;
    el.appendChild(div);
  });
  (c.conflicts || []).forEach((conf) => {
    const div = document.createElement("div");
    div.className = "check-row";
    div.innerHTML = `
      <div class="check-icon FAIL">${ICONS.cross}</div>
      <div class="check-main">
        <div class="check-label">MRP consistency</div>
        <div class="check-reason">${esc(conf.message)}</div>
        <div class="check-value">Values found: ${conf.values.map((v) => "₹" + esc(v)).join(", ")}</div>
      </div>
    `;
    el.appendChild(div);
  });
}

function renderFieldsTab(fields) {
  const el = $("#fields-list");
  el.innerHTML = "";
  Object.keys(FIELD_LABELS).forEach((key) => {
    const f = fields[key];
    if (!f) return;
    const div = document.createElement("div");
    div.className = "field-row";
    const confPct = Math.round((f.confidence || 0) * 100);
    div.innerHTML = `
      <div class="field-k">${esc(FIELD_LABELS[key])}</div>
      <div>
        <div class="field-v">${f.value != null ? esc(f.value) : "Not detected"}</div>
        ${f.detected ? `<div class="field-conf">${confPct}% confidence</div>` : ""}
      </div>
    `;
    el.appendChild(div);
  });
}

function renderEvidenceTab(images) {
  const el = $("#evidence-list");
  el.innerHTML = "";
  if (!images.length) {
    el.innerHTML = `<div class="empty-note">No annotated images available.</div>`;
    return;
  }
  images.forEach((img) => {
    const div = document.createElement("div");
    div.className = "evidence-item";
    div.innerHTML = `
      <img src="${img.annotated_url}" alt="Annotated evidence for ${esc(img.filename || "image")}">
      <div class="evidence-cap"><span>${esc(img.filename || "image")} · ${esc(img.backend)}</span><span>sharpness ${esc(img.quality.sharpness_score)}</span></div>
    `;
    el.appendChild(div);
  });
}

function markCurrentReportGenerated() {
  const entry = state.history.find((h) => h.id === state.currentHistoryId);
  if (entry) {
    entry.reportGenerated = true;
    writeJSON(STORAGE_KEYS.history, state.history);
  }
}

/* ============================================================
   REPORT
   ============================================================ */
function currentEntry() {
  return state.history.find((h) => h.id === state.currentHistoryId) || null;
}

function renderReport() {
  const data = state.currentRun;
  if (!data) return;
  const c = data.compliance;
  const fields = c.fields || {};
  const entry = currentEntry();

  $("#rp-id").textContent = data.inspection_id;
  $("#rp-date").textContent = fmtDate(entry ? entry.date : new Date().toISOString());
  $("#rp-location").textContent = state.location
    ? `${state.location.lat.toFixed(4)}, ${state.location.lng.toFixed(4)}`
    : "Location unavailable";
  $("#rp-product").textContent = (fields.product_name && fields.product_name.value) || "Not detected";
  $("#rp-manufacturer").textContent = (fields.manufacturer && fields.manufacturer.value) || "Not declared";
  $("#rp-officer").textContent = state.officer ? `${state.officer.name} (${state.officer.id})` : "—";
  $("#rp-status").innerHTML = `<span class="status-chip ${c.overall_status}"><span class="status-dot"></span>${statusLabel(c.overall_status)}</span>`;

  $("#rp-pass").textContent = c.summary.passed;
  $("#rp-fail").textContent = c.summary.failed;
  $("#rp-review").textContent = c.summary.review;

  $("#rp-submit-note").textContent = entry && entry.submitted
    ? "Already submitted to supervisor."
    : "Not yet submitted to your supervisor.";
}

function submitToSupervisor() {
  const entry = currentEntry();
  if (!entry) return;
  entry.submitted = true;
  writeJSON(STORAGE_KEYS.history, state.history);
  $("#rp-submit-note").textContent = "Submitted to supervisor.";
  toast("Report submitted to supervisor");
  renderHome();
}

async function urlToBase64(url) {
  const resp = await fetch(url);
  const blob = await resp.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

async function downloadPdf() {
  const data = state.currentRun;
  if (!data) return;
  if (!window.jspdf) { toast("PDF library unavailable — check your connection."); return; }

  const entry = currentEntry();
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const pageWidth = doc.internal.pageSize.getWidth();
  const margin = 48;
  let y = 56;

  doc.setFillColor(10, 37, 64);
  doc.rect(0, 0, pageWidth, 64, "F");
  doc.setTextColor(255, 255, 255);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  doc.text("CompliScan — Legal Metrology Inspection Report", margin, 38);
  doc.setTextColor(20, 33, 47);
  y = 92;

  const c = data.compliance;
  const fields = c.fields || {};

  const kv = [
    ["Inspection ID", data.inspection_id],
    ["Date & time", fmtDate(entry ? entry.date : new Date().toISOString())],
    ["Location", state.location ? `${state.location.lat.toFixed(4)}, ${state.location.lng.toFixed(4)}` : "Not available"],
    ["Officer", state.officer ? `${state.officer.name} (${state.officer.id})` : "—"],
    ["Product", (fields.product_name && fields.product_name.value) || "Not detected"],
    ["Manufacturer", (fields.manufacturer && fields.manufacturer.value) || "Not declared"],
    ["Overall status", statusLabel(c.overall_status)],
  ];

  doc.setFontSize(10.5);
  kv.forEach(([k, v]) => {
    doc.setFont("helvetica", "bold");
    doc.text(`${k}:`, margin, y);
    doc.setFont("helvetica", "normal");
    doc.text(String(v), margin + 130, y, { maxWidth: pageWidth - margin * 2 - 130 });
    y += 20;
  });

  y += 6;
  doc.setFont("helvetica", "bold");
  doc.setFontSize(12);
  doc.text(`Findings — ${c.summary.passed} compliant, ${c.summary.failed} violations, ${c.summary.review} needing review`, margin, y);
  y += 18;

  doc.setFontSize(10);
  c.checks.forEach((row) => {
    if (y > 760) { doc.addPage(); y = 56; }
    doc.setFont("helvetica", "bold");
    doc.text(`[${row.status}]`, margin, y);
    doc.setFont("helvetica", "normal");
    doc.text(row.label, margin + 62, y, { maxWidth: pageWidth - margin * 2 - 62 });
    y += 14;
    doc.setTextColor(107, 119, 135);
    doc.text(row.reason, margin + 62, y, { maxWidth: pageWidth - margin * 2 - 62 });
    doc.setTextColor(20, 33, 47);
    y += 18;
  });

  (c.conflicts || []).forEach((conf) => {
    if (y > 760) { doc.addPage(); y = 56; }
    doc.setFont("helvetica", "bold");
    doc.text("[FAIL]", margin, y);
    doc.setFont("helvetica", "normal");
    doc.text(`MRP consistency — ${conf.message}`, margin + 62, y, { maxWidth: pageWidth - margin * 2 - 62 });
    y += 18;
  });

  y += 8;
  if (y > 700) { doc.addPage(); y = 56; }
  doc.setFont("helvetica", "italic");
  doc.setFontSize(9);
  doc.setTextColor(107, 119, 135);
  doc.text(doc.splitTextToSize(data.disclaimer || "", pageWidth - margin * 2), margin, y);
  y += 40;

  const firstImage = (data.images || [])[0];
  if (firstImage && firstImage.annotated_url) {
    try {
      const b64 = await urlToBase64(firstImage.annotated_url);
      if (y > 560) { doc.addPage(); y = 56; }
      doc.setTextColor(20, 33, 47);
      doc.setFont("helvetica", "bold");
      doc.setFontSize(11);
      doc.text("Visual evidence", margin, y);
      y += 12;
      const imgWidth = pageWidth - margin * 2;
      doc.addImage(b64, "JPEG", margin, y, imgWidth, imgWidth * 0.62);
    } catch (e) {
      // If the evidence image can't be embedded, the rest of the report is still valid.
    }
  }

  doc.save(`${data.inspection_id}.pdf`);
  toast("PDF downloaded");
}

/* ============================================================
   HISTORY
   ============================================================ */
function renderHistory(filter = "all") {
  const listEl = $("#history-list");
  const emptyEl = $("#history-empty");
  const items = [...state.history]
    .filter((h) => filter === "all" || h.status === filter)
    .sort((a, b) => new Date(b.date) - new Date(a.date));

  listEl.innerHTML = "";
  emptyEl.classList.toggle("hidden", items.length > 0);
  emptyEl.textContent = filter === "all" ? "No scans yet." : "No scans match this filter.";

  items.forEach((h) => {
    const row = document.createElement("div");
    row.className = "hist-item";
    row.innerHTML = `
      <div class="hist-thumb">${ICONS.image}</div>
      <div class="hist-info">
        <div class="hn">${esc(h.product || "Unnamed product")}</div>
        <div class="hd">${h.netQuantity ? esc(h.netQuantity) + " · " : ""}${esc(fmtDate(h.date))}</div>
      </div>
      <div class="hist-right">
        <span class="status-chip ${h.status}"><span class="status-dot"></span>${statusLabel(h.status)}</span>
      </div>
    `;
    row.addEventListener("click", () => openHistoryEntry(h.id, "history"));
    listEl.appendChild(row);
  });
}

/* ============================================================
   REPORTS
   ============================================================ */
function renderReports() {
  const listEl = $("#reports-list");
  const emptyEl = $("#reports-empty");
  const items = state.history
    .filter((h) => h.reportGenerated)
    .sort((a, b) => new Date(b.date) - new Date(a.date));

  listEl.innerHTML = "";
  emptyEl.classList.toggle("hidden", items.length > 0);

  items.forEach((h) => {
    const row = document.createElement("div");
    row.className = "hist-item";
    row.innerHTML = `
      <div class="hist-thumb">${ICONS.image}</div>
      <div class="hist-info">
        <div class="hn">${esc(h.product || "Unnamed product")}</div>
        <div class="hd">${esc(h.id)} · ${esc(fmtDate(h.date))}</div>
      </div>
      <div class="hist-right">
        <span class="status-chip ${h.submitted ? "COMPLIANT" : "PENDING"}"><span class="status-dot"></span>${h.submitted ? "Submitted" : "Pending"}</span>
      </div>
    `;
    row.addEventListener("click", () => {
      state.currentHistoryId = h.id;
      state.currentRun = h.raw;
      state.resultOrigin = "reports";
      renderResult(h.raw);
      renderReport();
      showScreen("report");
    });
    listEl.appendChild(row);
  });
}

/* ============================================================
   PROFILE
   ============================================================ */
function renderProfile() {
  if (!state.officer) return;
  const initials = state.officer.name.trim().split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  $("#profile-avatar").textContent = initials || "O";
  $("#profile-name").textContent = state.officer.name;
  $("#profile-role").textContent = `Officer ID: ${state.officer.id}`;
  $("#profile-dept").textContent = state.officer.dept;
  $("#profile-sync-time").textContent = state.settings.lastSync
    ? `Last synced ${fmtDate(state.settings.lastSync)}`
    : "Not synced yet";
}

/* ============================================================
   Go
   ============================================================ */
document.addEventListener("DOMContentLoaded", boot);
})();
