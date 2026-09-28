// SpiceUtils — UI logic (pywebview.api bridge)

let api = null;
let logTimer = null;
let statusTimer = null;

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.from(document.querySelectorAll(sel)); }
// Track titles come from Spotify metadata: never inject them as raw HTML.
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add("hidden"), 2600);
}

// --- Tab navigation ---
function showTab(name) {
  // The Server view has no nav item: keep "Extensions" highlighted.
  const navName = name === "server" ? "extensions" : name;
  $all(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === navName));
  $all(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + name));
  if (name === "extensions") loadExtensions();
  if (name === "server") { refreshStatus(); refreshQueue(); }
  if (name === "settings") loadSettings();
}

$all(".nav-item").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$all("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));
$("#btn-back-ext").addEventListener("click", () => showTab("extensions"));
$("#btn-github").addEventListener("click", async () => {
  const r = await api.open_github();
  if (!r.ok) toast(r.message || "Coming soon");
});

// "Extraction" icon (separated layers + down arrow), themed.
const EXTRACT_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="#c08bf0" stroke-width="1.7" ' +
  'stroke-linecap="round" stroke-linejoin="round" width="26" height="26">' +
  '<path d="M12 3 4 6.5 12 10l8-3.5L12 3z"/>' +
  '<path d="M4 11.5 12 15l8-3.5"/>' +
  '<path d="M12 14v7"/><path d="m8.5 17.5 3.5 3.5 3.5-3.5"/></svg>';

// Custom icon per extension (otherwise default equalizer bars).
const EXT_ICONS = { stemExtractor: EXTRACT_SVG };

// --- Server ---
async function refreshStatus() {
  if (!api) return;
  const s = await api.get_status();
  const running = s.running;
  $("#server-dot").className = "dot " + (running ? "on" : "off");
  $("#server-state").textContent = running ? "Online" : "Stopped";
  $("#server-addr").textContent = `http://${s.host}:${s.port}`;
  $("#server-ver").textContent = s.version;
  $("#server-out").textContent = s.output_root;
  $("#btn-start").disabled = running;
  $("#btn-stop").disabled = !running;
  $("#footer-status").className = "dot " + (running ? "on" : "off");
  $("#footer-label").textContent = running ? "Server online" : "Server stopped";
  const sb = $(".ext-server-btn");
  if (sb) applyServerBtnState(sb, running);
}

async function refreshQueue() {
  if (!api) return;
  const q = await api.get_queue();
  const box = $("#queue-box");
  const rows = [];
  if (q.active) {
    const a = q.active;
    const lbl = a.status === "queued" ? `queued` : `${a.phase || ""} ${a.percent || 0}%`;
    rows.push(`<div class="q-row q-active"><span class="q-t">▶ ${esc(a.title)}</span>
      <span class="muted">${esc(lbl)}</span>
      <button class="link q-cancel" data-id="${esc(a.job_id)}">Cancel</button></div>`);
  }
  (q.pending || []).forEach((p) => {
    rows.push(`<div class="q-row"><span class="q-t">• ${esc(p.title)}</span>
      <button class="link q-cancel" data-id="${esc(p.job_id)}">Remove</button></div>`);
  });
  box.innerHTML = rows.length ? rows.join("") : '<span class="muted">Queue empty.</span>';
  box.querySelectorAll(".q-cancel").forEach((b) => {
    b.addEventListener("click", async () => { b.disabled = true; await api.cancel_job(b.dataset.id); refreshQueue(); });
  });
}

async function refreshLogs() {
  if (!api) return;
  const txt = await api.get_logs();
  const box = $("#logbox");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  box.textContent = txt || "(no activity yet)";
  if (atBottom) box.scrollTop = box.scrollHeight;
}

$("#btn-start").addEventListener("click", async () => {
  const r = await api.start_server();
  toast(r.ok ? "Server started" : "Failed: " + r.message);
  refreshStatus();
});
$("#btn-stop").addEventListener("click", async () => {
  await api.stop_server();
  toast("Server stopped");
  refreshStatus();
});
$("#btn-open-out").addEventListener("click", () => api.open_output());

// --- Extensions ---
let extLoadSeq = 0;

async function refreshRepair() {
  const r = await api.get_repair_status();
  window.spiceRepairState(!!(r && r.needs_repair));
  const w = $("#spotify-warning");
  const msg = r && r.spotify === "store"
    ? "You have the Microsoft Store version of Spotify, which Spicetify does not support. " +
      "Uninstall it and install Spotify from spotify.com/download."
    : r && r.spotify === "missing"
      ? "Spotify (desktop app) was not found. Install it from spotify.com/download."
      : "";
  w.textContent = msg;
  w.classList.toggle("hidden", !msg);
}

window.spiceRepairState = (needed) => $("#repair-banner").classList.toggle("hidden", !needed);

$("#btn-repair").addEventListener("click", async () => {
  const b = $("#btn-repair");
  b.disabled = true; b.textContent = "Repairing…";
  const r = await api.repair_spicetify();
  b.disabled = false; b.textContent = "Repair now";
  toast(r.ok ? "Spicetify repaired ✓" : "Repair failed — see Server log");
  loadExtensions();
});

async function loadExtensions() {
  if (!api) return;
  const seq = ++extLoadSeq;          // ignore results of an older, slower refresh
  const avail = await api.spicetify_available();
  $("#spicetify-warning").classList.toggle("hidden", avail);
  refreshRepair();

  const list = await api.list_extensions();
  if (seq !== extLoadSeq) return;
  const root = $("#ext-list");
  root.innerHTML = "";
  list.forEach(async (e) => {
    const card = document.createElement("div");
    root.appendChild(card);          // keep the manifest order
    card.className = "ext-card";
    // Stem Extractor depends on the server: extend its card with a dedicated bar.
    const hasServer = e.id === "stemExtractor";
    const customIcon = EXT_ICONS[e.id];
    const iconHtml = customIcon || "<span></span><span></span><span></span><span></span>";
    card.innerHTML = `
      <div class="ext-main">
        <div class="ext-icon${customIcon ? " svg" : ""}">${iconHtml}</div>
        <div class="ext-info">
          <div><span class="name">${esc(e.name)}</span><span class="ver">v${esc(e.version)}</span>
            ${e.installed ? '<span class="badge">Installed</span>' : ""}</div>
          <div class="desc">${esc(e.description)}</div>
        </div>
        <div class="ext-cta"></div>
      </div>
      ${hasServer ? `
      <div class="ext-extend">
        <div class="ext-opts">
          <button class="btn opt-folder" title="Output folder">Folder</button>
        </div>
        <button class="btn ext-server-btn">Server</button>
      </div>` : ""}`;
    const cta = card.querySelector(".ext-cta");
    const btn = document.createElement("button");
    btn.className = "btn" + (e.installed ? "" : " primary");
    btn.textContent = e.installed ? "Uninstall" : "Install";
    btn.style.marginTop = "0";
    btn.disabled = !e.available;     // Spicetify itself is installed on demand
    btn.addEventListener("click", () => toggleExtension(e, btn));
    cta.appendChild(btn);
    // "Update" button if a newer version is available on the repo.
    if (e.installed && e.update_url) {
      api.check_extension_update(e.id).then((u) => {
        if (!u || !u.update) return;
        const ub = document.createElement("button");
        ub.className = "btn primary";
        ub.style.marginTop = "0"; ub.style.marginRight = "8px";
        ub.textContent = `Update → ${u.remote}`;
        ub.addEventListener("click", async () => {
          ub.disabled = true; ub.textContent = "Updating…";
          const r = await api.update_extension(e.id);
          toast(r.ok ? `Extension updated (${r.version})` : "Update failed");
          loadExtensions();
        });
        cta.insertBefore(ub, cta.firstChild);
      });
    }
    const srvBtn = card.querySelector(".ext-server-btn");
    if (srvBtn) {
      srvBtn.addEventListener("click", () => showTab("server"));
      const st = await api.get_status();
      applyServerBtnState(srvBtn, st.running);
    }
    // Extraction option: output folder.
    const optFolder = card.querySelector(".opt-folder");
    if (optFolder) {
      const applyCfg = (cfg) => {
        optFolder.innerHTML = '<span class="oic">📁</span> Choose folder';
        optFolder.title = "Output folder: " + cfg.output_dir;
      };
      applyCfg(await api.get_extract_config());
      optFolder.addEventListener("click", async () => {
        applyCfg(await api.pick_output_dir());
        toast("Output folder updated");
        refreshStatus();
      });
    }
  });
}

// Green if the server is running; red + download icon otherwise.
function applyServerBtnState(btn, running) {
  btn.classList.toggle("srv-on", running);
  btn.classList.toggle("srv-off", !running);
  btn.innerHTML = running ? "Server" : '<span class="dl-ic">⬇</span> Server';
}

async function toggleExtension(e, btn) {
  btn.disabled = true;
  btn.textContent = e.installed ? "Uninstalling…" : "Installing…";
  const r = e.installed
    ? await api.uninstall_extension(e.id)
    : await api.install_extension(e.id);
  if (r.ok) {
    toast(e.installed ? `${e.name} uninstalled` : `${e.name} installed ✓`);
  } else {
    const last = String(r.log || "").trim().split("\n").pop() || "unknown error";
    toast("Failed: " + last.slice(0, 120));
    console.error(r.log);
  }
  loadExtensions();
}

// --- Settings ---
async function loadSettings() {
  if (!api) return;
  const s = await api.get_settings();
  $("#set-autostart-app").checked = !!s.autostart_app;
  $("#set-autostart-server").checked = !!s.autostart_server;
  $("#set-auto-update").checked = !!s.auto_update;
  $("#app-version").textContent = await api.get_app_version();
}

$("#set-autostart-app").addEventListener("change", async (ev) => {
  await api.set_autostart_app(ev.target.checked);
  toast(ev.target.checked ? "Auto-start enabled" : "Auto-start disabled");
});
$("#set-autostart-server").addEventListener("change", async (ev) => {
  await api.set_autostart_server(ev.target.checked);
  toast("Setting saved");
});
$("#set-auto-update").addEventListener("change", async (ev) => {
  await api.set_auto_update(ev.target.checked);
  toast(ev.target.checked ? "Auto-updates enabled" : "Auto-updates disabled");
});
$("#btn-check-update").addEventListener("click", async () => {
  toast("Checking...");
  const r = await api.check_update_now();
  toast(r.available ? `Updating to ${r.tag}...` : "SpiceUtils is up to date");
});
$("#btn-quit").addEventListener("click", () => api.quit_app());

// Toast triggerable from Python (evaluate_js).
window.spiceToast = (msg) => toast(msg);

// --- Close modal (called from Python via evaluate_js) ---
function hideCloseModal() { $("#close-modal").classList.add("hidden"); }

window.spiceShowCloseDialog = function () {
  $("#close-modal").classList.remove("hidden");
};

$("#modal-keep").addEventListener("click", async () => {
  hideCloseModal();
  await api.hide_window();        // keep the server running, minimize to tray
});
$("#modal-off").addEventListener("click", async () => {
  hideCloseModal();
  await api.quit_app();           // stop the server and quit
});
$("#modal-cancel").addEventListener("click", hideCloseModal);
$("#close-modal").addEventListener("click", (e) => {
  if (e.target.id === "close-modal") hideCloseModal();  // click on backdrop = cancel
});

// --- Init ---
window.addEventListener("pywebviewready", () => {
  api = window.pywebview.api;
  refreshStatus();
  refreshLogs();
  // Poll the log/queue only while the Server view is visible.
  const serverVisible = () => $("#tab-server").classList.contains("active");
  logTimer = setInterval(() => { if (serverVisible()) refreshLogs(); }, 1500);
  statusTimer = setInterval(() => {
    refreshStatus();
    if (serverVisible()) refreshQueue();
  }, 2500);
});
