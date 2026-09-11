(() => {
"use strict";

/* ============================================================
   Constants
   ============================================================ */
const REQUIRED_SLOTS = [
  { id: "front", label: "Front" },
  { id: "back", label: "Back" },
];

const OPTIONAL_SLOTS = [
  { id: "left", label: "Left" },
  { id: "right", label: "Right" },
  { id: "top", label: "Top" },
  { id: "bottom", label: "Bottom" },
];

const ALL_SLOTS = [...REQUIRED_SLOTS, ...OPTIONAL_SLOTS];

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
  officer: null, // set from the landing-page session on boot
  history: readJSON(STORAGE_KEYS.history, []),
  settings: readJSON(STORAGE_KEYS.settings, { defaultBackend: "auto", lastSync: null }),
  captureSlots: {},   // id -> { file, dataUrl, name }
  extraShots: [],      // [{ file, dataUrl, name }]
  currentRun: null,    // last /api/scan response
  currentHistoryId: null, // id of the history entry currently being viewed
  resultOrigin: "home", // where to go back to from result screen
  location: null,      // { lat, lng } if geolocation succeeded
  evidenceMode: "original",
  showOcrBoxes: false,
  activeEvidenceField: null,
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

const SIDES = ["front", "back", "left", "right", "top", "bottom"];
const SIDE_LABELS = { front: "Front", back: "Back", left: "Left", right: "Right", top: "Top", bottom: "Bottom" };
const MINI_RING_C = 2 * Math.PI * 26;

const FIND_ICON_SVGS = {
  product_name: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M14 3v5h5" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
  manufacturer: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M4 20V10l5 3v-3l5 3V7l5-3v16" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 20h18" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  address: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11Z" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="10" r="2.6" stroke="currentColor" stroke-width="1.6"/></svg>',
  net_quantity: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M20 8.5 12 4 4 8.5v7L12 20l8-4.5v-7Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M4 8.5 12 13l8-4.5M12 13v7" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  mrp: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="m4 4 7-.5L20 12.5 12.5 20 3.5 11 4 4Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="9" cy="9" r="1.6" stroke="currentColor" stroke-width="1.5"/></svg>',
  date: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><rect x="4" y="5" width="16" height="15" rx="2.5" stroke="currentColor" stroke-width="1.7"/><path d="M4 10h16M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  consumer_care: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M5 4h4l2 5-2.5 1.5a12 12 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
  readability: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M4 8V6a2 2 0 0 1 2-2h2M4 16v2a2 2 0 0 0 2 2h2M20 8V6a2 2 0 0 0-2-2h-2M20 16v2a2 2 0 0 1-2 2h-2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.7"/></svg>',
};

function findIconFor(id) {
  return FIND_ICON_SVGS[id] || FIND_ICON_SVGS.readability;
}

function imageSide(img) {
  const first = String(img.filename || "").toLowerCase().split("_")[0];
  return SIDES.includes(first) ? first : null;
}

function imageLabel(img, idx) {
  const side = imageSide(img);
  return side ? `${SIDE_LABELS[side]} side` : `Image ${idx + 1}`;
}

function activateResultTab(name) {
  $$(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
  requestAnimationFrame(moveTabSlider);
}

function moveTabSlider() {
  const active = $(".result-tabs .tab-btn.active");
  const slider = $("#tab-slider");
  if (!active || !slider) return;
  slider.style.left = active.offsetLeft + "px";
  slider.style.width = active.offsetWidth + "px";
}

function retakeFlow(side) {
  toast(side
    ? `Capture the ${side} side — this result is saved in History.`
    : "Starting a new capture — this result is saved in History.");
  startCaptureFlow("home");
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
  if (name === "result") requestAnimationFrame(moveTabSlider);
}

let toastTimer = null;
function toast(message, position) {
  const el = $("#toast");
  $("#toast-text").textContent = message;
  el.classList.toggle("top", position === "top");
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2400);
}

/* ============================================================
   Boot / auth
   ============================================================ */
function migrateStoredHistory() {
  // One-time cleanup: entries saved before the disclaimer rewording still
  // carry the old "Prototype scaffold only..." banner text. Rewrite them.
  const OLD_PHRASE = "Prototype scaffold only";
  let changed = false;
  state.history.forEach((h) => {
    if (h.raw && typeof h.raw.disclaimer === "string" && h.raw.disclaimer.includes(OLD_PHRASE)) {
      h.raw.disclaimer = "AI-assisted assessment — officer verification required before enforcement action.";
      h.raw.legal_notice = "This report is generated by an AI-assisted screening tool and does not constitute a legal finding. Verify every requirement, threshold, exception and effective date against the current official Legal Metrology rules and applicable amendments before real enforcement use.";
      changed = true;
    }
  });
  if (changed) writeJSON(STORAGE_KEYS.history, state.history);
}

const SESSION_KEY = "compliscan.session";

function authHeaders(extra = {}) {
  let token = "";
  try { token = JSON.parse(localStorage.getItem(SESSION_KEY) || "null")?.token || ""; } catch (e) { /* ignore */ }
  return { ...extra, ...(token ? { Authorization: "Bearer " + token } : {}) };
}

async function authFetch(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { ...(opts.headers || {}), ...authHeaders() },
  });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem(SESSION_KEY);
    location.href = "/login";
    throw new Error("Signed out — please sign in again.");
  }
  return res;
}

async function boot() {
  migrateStoredHistory();
  wireStaticEvents();
  renderCaptureGrid();

  // Auth lives on the landing page (/). This app needs a valid officer session.
  let me = null;
  try {
    const res = await authFetch("/api/auth/me");
    me = await res.json();
  } catch (e) { /* authFetch already redirected on 401 */ return; }
  if (!me || me.role !== "officer") {
    localStorage.removeItem(SESSION_KEY);
    location.href = "/login";
    return;
  }
  state.officer = { id: me.id, name: me.name, dept: me.dept || "Legal Metrology Department" };
  enterApp();
}

function enterApp() {
  renderProfile();
  renderHome();
  showScreen("home");
  tryGeolocate();
}

async function logout() {
  try { await authFetch("/api/auth/logout", { method: "POST" }); } catch (e) { /* ignore */ }
  localStorage.removeItem(SESSION_KEY);
  location.href = "/";
}

function tryGeolocate() {
  const fallback = { lat: 28.6139, lng: 77.2090 };
  function apply(pos) {
    const loc = { lat: pos.coords.latitude, lng: pos.coords.longitude };
    // Guard against cached stale fixes and absurd accuracy claims.
    if (!isFinite(loc.lat) || !isFinite(loc.lng)) return;
    state.location = loc;
    updateLocationUI();
    reverseGeocodeCity(loc.lat, loc.lng).then((city) => {
      if (city) { state.city = city; updateLocationUI(); }
    }).catch(() => {});
  }
  function onError() {
    if (!state.location) {
      state.locationError = true;
      updateLocationUI();
    }
  }
  if (!navigator.geolocation) { onError(); return; }
  navigator.geolocation.watchPosition(apply, onError, { enableHighAccuracy: true, maximumAge: 30000, timeout: 8000 });
  navigator.geolocation.getCurrentPosition(apply, onError, { enableHighAccuracy: false, maximumAge: 60000, timeout: 8000 });
}

function updateLocationUI() {
  const badge = $("#loc-badge");
  if (!badge) return;
  if (state.location) {
    const city = state.city ? `${state.city} · ` : "";
    badge.className = "loc-badge ok";
    badge.textContent = `GPS ${city}${state.location.lat.toFixed(4)}, ${state.location.lng.toFixed(4)}`;
  } else if (state.locationError) {
    badge.className = "loc-badge warn";
    badge.textContent = "GPS unavailable — allow location for heatmap";
  } else {
    badge.className = "loc-badge";
    badge.textContent = "Acquiring GPS…";
  }
}

async function reverseGeocodeCity(lat, lng) {
  try {
    const url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=10&addressdetails=1`;
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const data = await res.json();
    const addr = data.address || {};
    return addr.city || addr.town || addr.village || addr.county || addr.state_district || null;
  } catch (e) { return null; }
}

/* ============================================================
   Static event wiring (elements that always exist)
   ============================================================ */
function wireStaticEvents() {
  // Auth is handled by the landing page (/); this app boots from its session.

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
  $("#qa-history").addEventListener("click", () => { renderHistory(); showScreen("history"); });
  $("#qa-reports").addEventListener("click", () => { renderReports(); showScreen("reports"); });

  // Capture
  $("#capture-back").addEventListener("click", () => navigateToTab(state.resultOrigin === "history" ? "history" : "home"));
  $("#btn-proceed-analysis").addEventListener("click", onProceedToAnalysis);

  // Result
  $("#result-back").addEventListener("click", () => navigateToTab(state.resultOrigin));
  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => activateResultTab(btn.dataset.tab));
  });
  window.addEventListener("resize", () => {
    if ($("#screen-result").classList.contains("active")) moveTabSlider();
  });
  $("#btn-review-findings").addEventListener("click", () => {
    activateResultTab("details");
    $("#screen-result").scrollTop = 0;
  });
  $("#btn-generate-report").addEventListener("click", () => {
    markCurrentReportGenerated();
    renderReport();
    showScreen("report");
  });
  $("#btn-retake-sides").addEventListener("click", () => retakeFlow());
  $("#btn-add-retake").addEventListener("click", () => retakeFlow());
  $("#sum-view-more").addEventListener("click", () => {
    const extra = $("#sum-prod-extra");
    const btn = $("#sum-view-more");
    const open = extra.classList.toggle("open");
    btn.classList.toggle("open", open);
    btn.firstChild.textContent = open ? "View less " : "View more ";
  });
  $("#ev-select").addEventListener("change", (e) => {
    state.evidenceIdx = Number(e.target.value) || 0;
    renderEvidence(state.currentRun ? state.currentRun.images || [] : []);
  });
  $("#ev-prev").addEventListener("click", () => stepEvidence(-1));
  $("#ev-next").addEventListener("click", () => stepEvidence(1));
  $$(".ev-mode-btn").forEach((btn) => btn.addEventListener("click", () => {
    state.evidenceMode = btn.dataset.evidenceMode;
    renderEvidence(state.currentRun ? state.currentRun.images || [] : []);
  }));
  $("#ev-show-ocr").addEventListener("change", (e) => {
    state.showOcrBoxes = e.target.checked;
    renderEvidence(state.currentRun ? state.currentRun.images || [] : []);
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
    const order = ["paddle"];
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
  renderSideStrip();
  updateCaptureState();
  $("#capture-hint").textContent = "Start with front and back. The app will request a close-up only when evidence is insufficient.";
  showScreen("capture");
}

function renderCaptureGrid() {
  const grid = $("#capture-grid-required");
  grid.innerHTML = "";
  REQUIRED_SLOTS.forEach((slot) => {
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
  if (REQUIRED_SLOTS.some((s) => s.id === slot.id)) renderSlotFilled(slot);
  else renderSideStrip();
  updateCaptureState();
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
    // re-render any already-filled required slots after the full grid reset
    REQUIRED_SLOTS.forEach((s) => { if (state.captureSlots[s.id]) renderSlotFilled(s); });
    updateCaptureState();
  });
}

async function onExtraShotChosen(e) {
  const file = e.target.files[0];
  if (!file) return;
  const dataUrl = await fileToDataUrl(file);
  state.extraShots.push({ file, dataUrl, name: `extra_${state.extraShots.length + 1}_${file.name}` });
  e.target.value = "";
  renderSideStrip();
  updateCaptureState();
}

function renderSideStrip() {
  const strip = $("#side-strip");
  strip.innerHTML = "";
  OPTIONAL_SLOTS.forEach((slot) => {
    const shot = state.captureSlots[slot.id];
    const el = document.createElement("label");
    el.className = "mini-slot" + (shot ? " filled" : "");
    el.dataset.slot = slot.id;
    if (shot) {
      el.innerHTML = `
        <img class="ms-preview" src="${shot.dataUrl}" alt="${esc(slot.label)} preview">
        <span class="ms-check">${ICONS.check}</span>
        <button type="button" class="ms-remove" aria-label="Remove ${esc(slot.label)}">${ICONS.cross}</button>
        <input type="file" accept="image/*" capture="environment">`;
      el.querySelector("input").addEventListener("change", (e) => onSlotChosen(slot, e));
      el.querySelector(".ms-remove").addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        delete state.captureSlots[slot.id];
        renderSideStrip();
        updateCaptureState();
      });
    } else {
      el.innerHTML = `
        <input type="file" accept="image/*" capture="environment">
        <span class="ms-icon">${ICONS.camera}</span>
        <span class="ms-label">${slot.label}</span>`;
      el.querySelector("input").addEventListener("change", (e) => onSlotChosen(slot, e));
    }
    strip.appendChild(el);
  });
  state.extraShots.forEach((shot, idx) => {
    const tile = document.createElement("div");
    tile.className = "extra-shot";
    tile.innerHTML = `<img src="${shot.dataUrl}" alt="Close-up ${idx + 1}"><button type="button" aria-label="Remove close-up">${ICONS.cross}</button>`;
    tile.querySelector("button").addEventListener("click", () => {
      state.extraShots.splice(idx, 1);
      renderSideStrip();
      updateCaptureState();
    });
    strip.appendChild(tile);
  });
  const addTile = document.createElement("label");
  addTile.className = "add-shot-tile";
  addTile.title = "Add close-up";
  addTile.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><input type="file" accept="image/*" capture="environment">`;
  addTile.querySelector("input").addEventListener("change", onExtraShotChosen);
  strip.appendChild(addTile);
}

function collectAllShots() {
  const slotShots = ALL_SLOTS.filter((s) => state.captureSlots[s.id]).map((s) => state.captureSlots[s.id]);
  return [...slotShots, ...state.extraShots];
}

function updateCaptureState() {
  const hasFront = !!state.captureSlots.front;
  const hasBack = !!state.captureSlots.back;
  const note = $("#coverage-note");
  const proceedBtn = $("#btn-proceed-analysis");

  if (hasFront && hasBack) {
    note.className = "coverage-note ok";
    note.innerHTML = `${ICONS.check}<span><b>Coverage sufficient for analysis.</b> Front and back captured.</span>`;
    proceedBtn.disabled = false;
  } else if (hasFront || hasBack) {
    note.className = "coverage-note warn";
    note.innerHTML = hasFront
      ? `${ICONS.warn}<span><b>Back side recommended.</b> You can analyze now; add it for stronger declaration coverage.</span>`
      : `${ICONS.warn}<span><b>Front side recommended.</b> You can analyze now; add it to identify the product more reliably.</span>`;
    proceedBtn.disabled = false;
  } else {
    note.className = "coverage-note";
    note.innerHTML = `<span>Capture the <b>front</b> and <b>back</b> of the package to proceed.</span>`;
    proceedBtn.disabled = true;
  }

  const count = collectAllShots().length;
  $("#capture-count").textContent = count === 0 ? "0 images captured" : `${count} image${count > 1 ? "s" : ""} captured`;
}

function onProceedToAnalysis() {
  const shots = collectAllShots();
  if (!shots.length) return;
  runAnalysis(shots);
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

async function runAnalysis(shots) {
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
    formData.append("backend", "paddle");
    // Officer identity comes from the signed-in session, not the client.
    if (state.location) {
      formData.append("lat", String(state.location.lat));
      formData.append("lng", String(state.location.lng));
    }
    if (state.city) formData.append("city", state.city);

    const response = await authFetch("/api/scan", { method: "POST", body: formData });
    const data = await response.json();
    clearInterval(stepTimer);
    if (!response.ok || data.error) {
      const detail = (data.warnings && data.warnings[0]) || data.error || "Scan failed";
      throw new Error(detail);
    }

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
    runId: (data.result_file || "").split("/")[2] || null,
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

  const recommendation = c.capture_recommendation;
  if (recommendation && recommendation.capture_required) {
    $("#capture-hint").textContent = recommendation.capture_instruction || recommendation.reason;
  }

  renderResult(data);
  showScreen("result");
}

function stripBoxesForStorage(data) {
  // Keep enough raw evidence for the offline history viewer, while preventing
  // unusually dense labels from exhausting local browser storage.
  const clone = JSON.parse(JSON.stringify(data));
  (clone.images || []).forEach((img) => {
    img.boxes = (img.boxes || []).slice(0, 200).map(({ text, confidence, bbox }) => ({ text, confidence, bbox }));
  });
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
  state.evidenceIdx = 0;
  state.evidenceMode = "original";
  state.showOcrBoxes = false;
  state.activeEvidenceField = null;
  activateResultTab("summary");
  renderSummary(data);
  renderFindings(data.compliance);
  renderEvidence(data.images || []);
}

/* ---------------- Summary ---------------- */
function renderSummary(data) {
  $("#tab-summary").classList.remove("enter");
  const c = data.compliance;
  const fields = c.fields || {};
  const images = data.images || [];
  const entry = currentEntry();
  const locText = state.location
    ? `${state.location.lat.toFixed(4)}, ${state.location.lng.toFixed(4)}`
    : "Location unavailable";

  $("#sum-id").textContent = data.inspection_id;
  $("#sum-sub").textContent = `${fmtDate(entry ? entry.date : new Date().toISOString())} · ${locText}`;

  const total = c.summary.total_checks || (c.summary.passed + c.summary.failed + c.summary.review);
  const verdict = $("#sum-verdict");
  if (c.overall_status === "NON-COMPLIANT") {
    verdict.className = "verdict bad";
    verdict.innerHTML = `<div class="verdict-ic">${ICONS.warn}</div><div><h2>Action Required</h2><div class="v-sub">${c.summary.failed} of ${total} checks need attention</div><div class="v-desc">Some mandatory declarations are missing or unclear. Review the findings below.</div></div>`;
  } else if (c.overall_status === "REVIEW") {
    verdict.className = "verdict warn";
    verdict.innerHTML = `<div class="verdict-ic">${ICONS.warn}</div><div><h2>Needs Review</h2><div class="v-sub">${c.summary.review} of ${total} checks need a second look</div><div class="v-desc">Some declarations need officer verification. Review the findings below.</div></div>`;
  } else {
    verdict.className = "verdict ok";
    verdict.innerHTML = `<div class="verdict-ic">${ICONS.check}</div><div><h2>Compliant</h2><div class="v-sub">All ${total} checks passed</div><div class="v-desc">All mandatory declarations were extracted with sufficient confidence.</div></div>`;
  }

  $("#sum-pass").textContent = c.summary.passed;
  $("#sum-fail").textContent = c.summary.failed;
  $("#sum-review").textContent = c.summary.review;

  // Product card
  const firstImg = images[0];
  $("#sum-thumb").innerHTML = firstImg
    ? `<img src="${firstImg.annotated_url}" alt="Product thumbnail">`
    : ICONS.image;
  $("#sum-product-name").textContent = (fields.product_name && fields.product_name.value) || "Product name not detected";

  const rowsEl = $("#sum-prod-rows");
  rowsEl.innerHTML = "";
  const prodRows = [
    { k: "Manufacturer", f: fields.manufacturer },
    { k: "Net Quantity", f: fields.net_quantity },
    { k: "MRP", f: fields.mrp, money: true },
  ];
  const extraRows = [
    { k: "Address", f: fields.address },
    { k: "Packing date", f: fields.date },
    { k: "Consumer care", f: fields.consumer_care },
    { k: "Country of origin", f: fields.country_of_origin },
  ];
  prodRows.forEach((r) => rowsEl.appendChild(buildProdRow(r.k, r.f, r.money)));
  const extraWrap = document.createElement("div");
  extraWrap.className = "prod-extra";
  extraWrap.id = "sum-prod-extra";
  extraRows.forEach((r) => extraWrap.appendChild(buildProdRow(r.k, r.f, r.money)));
  rowsEl.appendChild(extraWrap);
  const moreBtn = $("#sum-view-more");
  moreBtn.classList.remove("open");
  moreBtn.firstChild.textContent = "View more ";

  // Scan quality
  const qualities = images.map((img) => img.quality).filter(Boolean);
  const avg = (fn) => qualities.length ? Math.round(qualities.reduce((a, q) => a + fn(q), 0) / qualities.length) : 0;
  const imgQ = avg((q) => q.sharpness_score || 0);
  const textQ = avg((q) => q.contrast_score || 0);
  const ocrConfs = Object.keys(fields)
    .filter((k) => k !== "readability" && fields[k] && fields[k].detected)
    .map((k) => (fields[k].confidence || 0) * 100);
  const ocrQ = ocrConfs.length ? Math.round(ocrConfs.reduce((a, b) => a + b, 0) / ocrConfs.length) : 0;
  setMiniRing("ring-img", imgQ);
  setMiniRing("ring-text", textQ);
  setMiniRing("ring-ocr", ocrQ);
  const meanQ = Math.round((imgQ + textQ + ocrQ) / 3);
  const chip = $("#sum-quality-chip");
  if (meanQ >= 75) {
    chip.className = "mini-chip";
    chip.textContent = "Good";
    $("#sum-quality-sub").textContent = "Images are clear and readable";
  } else if (meanQ >= 50) {
    chip.className = "mini-chip amber";
    chip.textContent = "Fair";
    $("#sum-quality-sub").textContent = "Most images are readable, some could be clearer";
  } else {
    chip.className = "mini-chip red";
    chip.textContent = "Poor";
    $("#sum-quality-sub").textContent = "Images are unclear — consider retaking";
  }
  const glareQ = avg((q) => q.glare_score || 0);
  let tip;
  if (qualities.length && glareQ < 60) {
    tip = "Tip: Avoid glare and shadows on the package for cleaner extraction.";
  } else if (imgQ <= textQ && imgQ <= ocrQ) {
    tip = "Tip: Hold the camera steady and fill the frame with the package.";
  } else if (ocrQ <= textQ) {
    tip = "Tip: Capture right and top views to improve detection of MRP and net quantity.";
  } else {
    tip = "Tip: Front and back covers are enough when all declarations are visible.";
  }
  $("#sum-tip").innerHTML = `${ICONS.warn}<span><b>${esc(tip.split(":")[0])}:</b>${esc(tip.split(":").slice(1).join(":"))}</span>`;

  // Coverage
  const captured = new Set(images.map(imageSide).filter(Boolean));
  $("#sum-cov-chip").textContent = `${captured.size} / 6`;
  $("#sum-cov-chip").className = "mini-chip " + (captured.size >= 6 ? "" : "blue");
  const covGrid = $("#sum-cov-grid");
  covGrid.innerHTML = "";
  SIDES.forEach((side) => {
    const hit = captured.has(side);
    const cell = document.createElement("div");
    cell.className = "cov-side";
    cell.innerHTML = `<div class="cov-dot ${hit ? "hit" : "miss"}">${hit ? ICONS.check : ICONS.cross}</div><span>${SIDE_LABELS[side]}</span>`;
    covGrid.appendChild(cell);
  });

  const panel = $("#tab-summary");
  void panel.offsetWidth;
  panel.classList.add("enter");
}

function buildProdRow(label, f, money) {
  const row = document.createElement("div");
  row.className = "kv-row";
  if (!f || !f.detected || f.value == null) {
    row.innerHTML = `<span class="k">${esc(label)}</span><span class="v missing">Not detected</span>`;
  } else if (money && (f.confidence || 0) < 0.6) {
    row.innerHTML = `<span class="k">${esc(label)}</span><span class="v unconfirmed">₹${esc(f.value)} (not confirmed)</span>`;
  } else {
    row.innerHTML = `<span class="k">${esc(label)}</span><span class="v">${money ? "₹" : ""}${esc(f.value)}</span>`;
  }
  return row;
}

function setMiniRing(id, pct) {
  const ring = document.getElementById(id);
  if (!ring) return;
  const clamped = Math.min(100, Math.max(0, pct));
  ring.classList.remove("ok", "mid", "low");
  ring.classList.add(clamped >= 75 ? "ok" : clamped >= 50 ? "mid" : "low");
  ring.style.strokeDasharray = String(MINI_RING_C);
  ring.style.strokeDashoffset = String(MINI_RING_C);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    ring.style.strokeDashoffset = String(MINI_RING_C * (1 - clamped / 100));
  }));
  const label = document.getElementById(id + "-t");
  if (label) label.textContent = `${Math.round(clamped)}%`;
}

/* ---------------- Findings ---------------- */
function renderFindings(c) {
  const el = $("#findings-list");
  el.innerHTML = "";

  const fails = (c.checks || []).filter((r) => r.status === "FAIL");
  const conflicts = (c.conflicts || []).map((conf) => ({
    id: "conflict",
    label: "MRP consistency",
    status: "FAIL",
    reason: conf.message,
    field: { value: conf.values.map((v) => "₹" + v).join(", "), detected: true, confidence: null },
  }));
  const attention = [...fails, ...conflicts];
  const reviews = (c.checks || []).filter((r) => r.status === "REVIEW" || r.status === "NOT_ASSESSABLE");
  const verified = (c.checks || []).filter((r) => r.status === "PASS");

  if (attention.length) {
    el.appendChild(buildFindGroup("bad", "Needs Attention", attention.length,
      "Review and resolve these issues", attention));
  }
  if (reviews.length) {
    el.appendChild(buildFindGroup("warn", "Needs Review", reviews.length,
      "Detected with low confidence — officer verification recommended", reviews));
  }
  if (verified.length) {
    el.appendChild(buildFindGroup("ok", "Verified", verified.length,
      "Extracted with sufficient confidence", verified));
  }
}

function buildFindGroup(tone, title, count, sub, items) {
  const group = document.createElement("div");
  group.className = "find-group";
  const icon = tone === "bad" ? ICONS.cross : tone === "warn" ? ICONS.warn : ICONS.check;
  group.innerHTML = `
    <div class="find-group-head">
      <div class="find-group-ic ${tone}">${icon}</div>
      <h3>${esc(title)} (${count})</h3>
    </div>
    <div class="find-group-sub">${esc(sub)}</div>
  `;
  items.forEach((row) => group.appendChild(buildFindCard(row)));
  return group;
}

function buildFindCard(row) {
  const tone = row.status === "FAIL" ? "bad" : (row.status === "REVIEW" || row.status === "NOT_ASSESSABLE") ? "warn" : "ok";
  const chip = row.status === "FAIL" ? "Required" : row.status === "NOT_ASSESSABLE" ? "Capture needed" : row.status === "REVIEW" ? "Unclear" : "Verified";
  const f = row.field || {};
  const confPct = f.confidence == null ? null : Math.round(f.confidence * 100);

  const card = document.createElement("div");
  card.className = "find-card";
  card.innerHTML = `
    <button class="find-row" type="button">
      <div class="find-ic ${tone}">${findIconFor(row.id)}</div>
      <div class="find-main">
        <div class="find-top">
          <div class="find-label">${esc(row.label)}</div>
          <span class="find-chip ${tone}">${chip}</span>
        </div>
        <div class="find-reason">${esc(row.reason)}</div>
        ${confPct == null ? "" : `<div class="find-conf">Confidence: ${confPct}%</div>`}
      </div>
      <svg class="find-chev" width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="m9 6 6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <div class="find-detail">
      ${f.detected && f.value != null
        ? `<div>Detected value:</div><div class="detected"><b>${esc(row.id === "mrp" ? "₹" + f.value : f.value)}</b>${confPct == null ? "" : ` · ${confPct}% confidence`}</div>`
        : `<div>No value was extracted from the provided images.</div>`}
    </div>
  `;
  const btn = card.querySelector(".find-row");
  const detail = card.querySelector(".find-detail");
  btn.addEventListener("click", () => {
    btn.classList.toggle("open");
    detail.classList.toggle("open");
  });
  return card;
}

/* ---------------- Evidence ---------------- */
function renderEvidence(images) {
  const select = $("#ev-select");
  const viewer = $("#ev-image");
  const extracted = $("#ev-extracted");
  const grid = $("#ev-grid");
  const overlay = $("#ev-overlay");

  if (!images.length) {
    select.innerHTML = `<option>No images</option>`;
    $("#ev-count").textContent = "0 / 0";
    viewer.removeAttribute("src");
    overlay.innerHTML = "";
    extracted.innerHTML = `<div class="empty-note">No annotated images available.</div>`;
    grid.innerHTML = "";
    return;
  }

  state.evidenceIdx = Math.min(state.evidenceIdx || 0, images.length - 1);
  const idx = state.evidenceIdx;
  const img = images[idx];

  select.innerHTML = "";
  images.forEach((im, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = imageLabel(im, i);
    select.appendChild(opt);
  });
  select.value = String(idx);
  $("#ev-count").textContent = `${idx + 1} / ${images.length}`;
  const isAnnotated = state.evidenceMode === "annotated";
  const source = isAnnotated ? img.annotated_url : (img.original_url || img.annotated_url);
  viewer.src = source;
  viewer.alt = `${isAnnotated ? "Annotated" : "Original"} evidence — ${imageLabel(img, idx)}`;
  $$(".ev-mode-btn").forEach((button) => button.classList.toggle("active", button.dataset.evidenceMode === state.evidenceMode));
  $("#ev-show-ocr").checked = state.showOcrBoxes;
  const viewerWrap = $("#ev-viewer");
  viewerWrap.classList.remove("swap");
  void viewerWrap.offsetWidth;
  viewerWrap.classList.add("swap");
  $("#ev-extract-title").textContent = `Extracted Text (${imageLabel(img, idx)})`;
  $("#ev-full").href = source;

  extracted.innerHTML = "";
  const imgFields = img.fields || {};
  let shown = 0;
  Object.keys(FIELD_LABELS).forEach((key) => {
    if (key === "readability") return;
    const f = imgFields[key];
    if (!f) return;
    shown += 1;
    const row = document.createElement("div");
    row.className = "ext-row evidence-field" + (state.activeEvidenceField === key ? " selected" : "");
    const confPct = Math.round((f.confidence || 0) * 100);
    const pill = !f.detected
      ? `<span class="conf-pill na">—</span>`
      : `<span class="conf-pill ${confPct >= 90 ? "high" : confPct >= 60 ? "mid" : "low"}">${confPct}%</span>`;
    const val = !f.detected || f.value == null
      ? `<span class="v" style="color:var(--muted);font-weight:400;">Not detected</span>`
      : `<span class="v">${key === "mrp" ? "₹" : ""}${esc(f.value)}</span>`;
    row.innerHTML = `<span class="k">${esc(FIELD_LABELS[key])}</span>${val}${pill}`;
    if (f.detected && f.bbox) {
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.title = "Show this declaration on the image";
      const spotlight = () => { state.activeEvidenceField = state.activeEvidenceField === key ? null : key; renderEvidence(images); };
      row.addEventListener("click", spotlight);
      row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); spotlight(); } });
    }
    extracted.appendChild(row);
  });
  if (!shown) extracted.innerHTML = `<div class="empty-note">No text extracted from this image.</div>`;

  renderEvidenceOverlay(img, imgFields, overlay);

  const captured = new Set(images.map(imageSide).filter(Boolean));
  $("#ev-all-title").textContent = `All Images (${images.length})`;
  $("#ev-all-chip").textContent = `${captured.size} / 6 captured`;
  grid.innerHTML = "";
  images.forEach((im, i) => {
    const side = imageSide(im);
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "ev-thumb" + (i === idx ? " selected" : "");
    tile.innerHTML = `
      <img src="${im.annotated_url}" alt="${esc(imageLabel(im, i))}">
      <span class="ev-tick">${ICONS.check}</span>
      <span class="ev-tag">${side ? esc(SIDE_LABELS[side]) : "✓"}</span>`;
    tile.addEventListener("click", () => { state.evidenceIdx = i; renderEvidence(images); });
    grid.appendChild(tile);
  });
  SIDES.filter((s) => !captured.has(s)).forEach((side) => {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "ev-add";
    tile.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>${SIDE_LABELS[side]}</span>`;
    tile.addEventListener("click", () => retakeFlow(SIDE_LABELS[side]));
    grid.appendChild(tile);
  });
}

function renderEvidenceOverlay(img, fields, overlay) {
  overlay.innerHTML = "";
  const width = Number(img.quality?.width) || 0;
  const height = Number(img.quality?.height) || 0;
  if (!width || !height) return;
  const addBox = (bbox, className, title) => {
    if (!Array.isArray(bbox) || bbox.length !== 4) return;
    const [x1, y1, x2, y2] = bbox.map(Number);
    if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return;
    const box = document.createElement("span");
    box.className = `evidence-box ${className}`;
    box.style.left = `${(x1 / width) * 100}%`;
    box.style.top = `${(y1 / height) * 100}%`;
    box.style.width = `${((x2 - x1) / width) * 100}%`;
    box.style.height = `${((y2 - y1) / height) * 100}%`;
    box.title = title || "Detected OCR text";
    overlay.appendChild(box);
  };
  if (state.showOcrBoxes) (img.boxes || []).slice(0, 200).forEach((box) => addBox(box.bbox, "ocr", `${box.text || "OCR text"} (${Math.round((box.confidence || 0) * 100)}%)`));
  if (state.activeEvidenceField && fields[state.activeEvidenceField]?.bbox) {
    addBox(fields[state.activeEvidenceField].bbox, "field", `${FIELD_LABELS[state.activeEvidenceField]} evidence`);
  }
}

function stepEvidence(dir) {
  const images = state.currentRun ? state.currentRun.images || [] : [];
  if (!images.length) return;
  state.evidenceIdx = ((state.evidenceIdx || 0) + dir + images.length) % images.length;
  renderEvidence(images);
}

function markCurrentReportGenerated() {
  const entry = state.history.find((h) => h.id === state.currentHistoryId);
  if (entry) {
    entry.reportGenerated = true;
    writeJSON(STORAGE_KEYS.history, state.history);
    // Mirror to the shared database so supervisors see it.
    if (entry.runId) authFetch(`/api/inspection/${entry.runId}/report`, { method: "POST" }).catch(() => {});
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
  // Mirror to the shared database so the case shows as submitted on the dashboard.
  if (entry.runId) authFetch(`/api/inspection/${entry.runId}/submit`, { method: "POST" }).catch(() => {});
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
  const discLines = doc.splitTextToSize(data.disclaimer || "", pageWidth - margin * 2);
  doc.text(discLines, margin, y);
  y += discLines.length * 12 + 6;
  if (data.legal_notice) {
    doc.setFontSize(8);
    const legalLines = doc.splitTextToSize(data.legal_notice, pageWidth - margin * 2);
    if (y + legalLines.length * 10 > 780) { doc.addPage(); y = 56; }
    doc.text(legalLines, margin, y);
    y += legalLines.length * 10 + 8;
  }

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
