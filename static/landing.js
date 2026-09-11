(() => {
"use strict";
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const SESSION_KEY = "compliscan.session";
const DEST = { officer: "/inspect", supervisor: "/supervise" };

let role = "officer";

function setRole(next) {
  role = next;
  $$(".role-btn").forEach((b) => b.classList.toggle("active", b.dataset.role === role));
  $("#role-tabs").classList.toggle("sup", role === "supervisor");
  const isSup = role === "supervisor";
  $("#li-id-label").textContent = isSup ? "Supervisor ID" : "Officer ID";
  $("#li-secret-label").textContent = isSup ? "Password" : "Full name";
  const secret = $("#li-secret");
  secret.type = isSup ? "password" : "text";
  secret.placeholder = isSup ? "Enter your password" : "Enter your full name";
  secret.value = "";
  $("#signin-btn").textContent = isSup ? "Sign in as Supervisor" : "Sign in as Officer";
  $("#demo-hint").innerHTML = isSup
    ? `Use the Supervisor ID and password issued.`
    : `Use the Officer ID and full name your supervisor registered.`;
  hideError();
}

function showError(msg) {
  const el = $("#form-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}
function hideError() { $("#form-error").classList.add("hidden"); }

async function tryResume() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(SESSION_KEY) || "null"); } catch (e) { /* ignore */ }
  if (!saved || !saved.token) return;
  try {
    const res = await fetch("/api/auth/me", { headers: { Authorization: "Bearer " + saved.token } });
    if (!res.ok) throw new Error("expired");
    const me = await res.json();
    // Don't auto-redirect — let the user choose. Show a continue banner.
    const hint = document.getElementById("demo-hint");
    if (hint) {
      const dest = DEST[me.role] || "/login";
      const label = me.role === "supervisor" ? "Supervisor" : "Officer";
      hint.innerHTML = `Signed in as <b>${me.name}</b> (${label}) — <a href="${dest}" id="resume-continue" style="color:var(--blue-600); font-weight:700;">Continue to ${label === "Supervisor" ? "dashboard" : "app"}</a> · <a href="#" id="resume-signout" style="color:var(--muted);">Sign out</a>`;
      const go = document.getElementById("resume-continue");
      if (go) go.addEventListener("click", (e) => { e.preventDefault(); location.href = dest; });
      const out = document.getElementById("resume-signout");
      if (out) out.addEventListener("click", (e) => { e.preventDefault(); localStorage.removeItem(SESSION_KEY); location.reload(); });
    }
  } catch (e) {
    localStorage.removeItem(SESSION_KEY);
  }
}

function boot() {
  setRole("officer");
  $$(".role-btn").forEach((b) => b.addEventListener("click", () => setRole(b.dataset.role)));
  $("#landing-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError();
    const btn = $("#signin-btn");
    btn.disabled = true;
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role,
          id: $("#li-id").value.trim(),
          secret: $("#li-secret").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Sign-in failed");
      localStorage.setItem(SESSION_KEY, JSON.stringify({
        token: data.token, role: data.role, id: data.id, name: data.name, dept: data.dept || null,
      }));
      location.href = DEST[data.role] || "/login";
    } catch (err) {
      showError(err.message || "Sign-in failed — please try again.");
    } finally {
      btn.disabled = false;
    }
  });
  tryResume();
}

document.addEventListener("DOMContentLoaded", boot);
})();
