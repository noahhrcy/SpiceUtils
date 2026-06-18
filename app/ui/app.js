// SpiceUtils — logique de l'interface (pont pywebview.api)

let api = null;
let logTimer = null;
let statusTimer = null;

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.from(document.querySelectorAll(sel)); }

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add("hidden"), 2600);
}

// --- Navigation onglets ---
function showTab(name) {
  // La vue Serveur n'a pas d'item de nav : on garde "Extensions" surligne.
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
  if (!r.ok) toast(r.message || "Bientot disponible");
});

// Icone "extraction" (couches separees + fleche descendante), dans le theme.
const EXTRACT_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="#c08bf0" stroke-width="1.7" ' +
  'stroke-linecap="round" stroke-linejoin="round" width="26" height="26">' +
  '<path d="M12 3 4 6.5 12 10l8-3.5L12 3z"/>' +
  '<path d="M4 11.5 12 15l8-3.5"/>' +
  '<path d="M12 14v7"/><path d="m8.5 17.5 3.5 3.5 3.5-3.5"/></svg>';

// Icone personnalisee par extension (sinon barres d'egaliseur par defaut).
const EXT_ICONS = { stemExtractor: EXTRACT_SVG };

// --- Serveur ---
async function refreshStatus() {
  if (!api) return;
  const s = await api.get_status();
  const running = s.running;
  $("#server-dot").className = "dot " + (running ? "on" : "off");
  $("#server-state").textContent = running ? "En ligne" : "Arrete";
  $("#server-addr").textContent = `http://${s.host}:${s.port}`;
  $("#server-ver").textContent = s.version;
  $("#server-out").textContent = s.output_root;
  $("#btn-start").disabled = running;
  $("#btn-stop").disabled = !running;
  $("#footer-status").className = "dot " + (running ? "on" : "off");
  $("#footer-label").textContent = running ? "Serveur en ligne" : "Serveur arrete";
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
    const lbl = a.status === "queued" ? `en file` : `${a.phase || ""} ${a.percent || 0}%`;
    rows.push(`<div class="q-row q-active"><span class="q-t">▶ ${a.title}</span>
      <span class="muted">${lbl}</span>
      <button class="link q-cancel" data-id="${a.job_id}">Annuler</button></div>`);
  }
  (q.pending || []).forEach((p) => {
    rows.push(`<div class="q-row"><span class="q-t">• ${p.title}</span>
      <button class="link q-cancel" data-id="${p.job_id}">Retirer</button></div>`);
  });
  box.innerHTML = rows.length ? rows.join("") : '<span class="muted">File vide.</span>';
  box.querySelectorAll(".q-cancel").forEach((b) => {
    b.addEventListener("click", async () => { b.disabled = true; await api.cancel_job(b.dataset.id); refreshQueue(); });
  });
}

async function refreshLogs() {
  if (!api) return;
  const txt = await api.get_logs();
  const box = $("#logbox");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  box.textContent = txt || "(aucune activite pour le moment)";
  if (atBottom) box.scrollTop = box.scrollHeight;
}

$("#btn-start").addEventListener("click", async () => {
  const r = await api.start_server();
  toast(r.ok ? "Serveur demarre" : "Echec : " + r.message);
  refreshStatus();
});
$("#btn-stop").addEventListener("click", async () => {
  await api.stop_server();
  toast("Serveur arrete");
  refreshStatus();
});
$("#btn-open-out").addEventListener("click", () => api.open_output());

// --- Extensions ---
async function loadExtensions() {
  if (!api) return;
  const avail = await api.spicetify_available();
  $("#spicetify-warning").classList.toggle("hidden", avail);

  const list = await api.list_extensions();
  const root = $("#ext-list");
  root.innerHTML = "";
  list.forEach(async (e) => {
    const card = document.createElement("div");
    card.className = "ext-card";
    // Stem Extractor depend du serveur : on prolonge sa carte d'un bas dedie.
    const hasServer = e.id === "stemExtractor";
    const customIcon = EXT_ICONS[e.id];
    const iconHtml = customIcon || "<span></span><span></span><span></span><span></span>";
    card.innerHTML = `
      <div class="ext-main">
        <div class="ext-icon${customIcon ? " svg" : ""}">${iconHtml}</div>
        <div class="ext-info">
          <div><span class="name">${e.name}</span><span class="ver">v${e.version}</span>
            ${e.installed ? '<span class="badge">Installee</span>' : ""}</div>
          <div class="desc">${e.description}</div>
        </div>
        <div class="ext-cta"></div>
      </div>
      ${hasServer ? `
      <div class="ext-extend">
        <div class="ext-opts">
          <button class="btn opt-folder" title="Dossier de sortie">Dossier</button>
          <button class="btn opt-quality">Qualite</button>
        </div>
        <button class="btn ext-server-btn">Serveur</button>
      </div>` : ""}`;
    const cta = card.querySelector(".ext-cta");
    const btn = document.createElement("button");
    btn.className = "btn" + (e.installed ? "" : " primary");
    btn.textContent = e.installed ? "Desinstaller" : "Installer";
    btn.style.marginTop = "0";
    btn.disabled = !avail || !e.available;
    btn.addEventListener("click", () => toggleExtension(e, btn));
    cta.appendChild(btn);
    // Bouton "Mettre a jour" si une version plus recente est dispo sur le repo.
    if (e.installed && e.update_url) {
      api.check_extension_update(e.id).then((u) => {
        if (!u || !u.update) return;
        const ub = document.createElement("button");
        ub.className = "btn primary";
        ub.style.marginTop = "0"; ub.style.marginRight = "8px";
        ub.textContent = `Mettre à jour → ${u.remote}`;
        ub.addEventListener("click", async () => {
          ub.disabled = true; ub.textContent = "Mise à jour…";
          const r = await api.update_extension(e.id);
          toast(r.ok ? `Extension mise à jour (${r.version})` : "Échec de la mise à jour");
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
    // Options d'extraction (dossier de sortie + qualite/rapide).
    const optFolder = card.querySelector(".opt-folder");
    const optQuality = card.querySelector(".opt-quality");
    if (optFolder && optQuality) {
      const applyCfg = (cfg) => {
        optFolder.innerHTML = '<span class="oic">📁</span> Choisir le dossier';
        optFolder.title = "Dossier de sortie : " + cfg.output_dir;
        optQuality.innerHTML = cfg.quality === "fast"
          ? '<span class="oic">⚡</span> Mode : Rapide' : '<span class="oic">✨</span> Mode : Qualité';
        optQuality.title = cfg.quality === "fast"
          ? "Extraction rapide (htdemucs)" : "Extraction qualitative (htdemucs_ft, plus lent)";
      };
      applyCfg(await api.get_extract_config());
      optFolder.addEventListener("click", async () => {
        applyCfg(await api.pick_output_dir());
        toast("Dossier de sortie mis a jour");
        refreshStatus();
      });
      optQuality.addEventListener("click", async () => {
        const cur = await api.get_extract_config();
        const cfg = await api.set_quality(cur.quality === "fast" ? "quality" : "fast");
        applyCfg(cfg);
        toast(cfg.quality === "fast" ? "Mode rapide" : "Mode qualite");
      });
    }
    root.appendChild(card);
  });
}

// Vert si le serveur tourne ; rouge + icone de telechargement sinon.
function applyServerBtnState(btn, running) {
  btn.classList.toggle("srv-on", running);
  btn.classList.toggle("srv-off", !running);
  btn.innerHTML = running ? "Serveur" : '<span class="dl-ic">⬇</span> Serveur';
}

async function toggleExtension(e, btn) {
  btn.disabled = true;
  btn.textContent = e.installed ? "Desinstallation…" : "Installation…";
  const r = e.installed
    ? await api.uninstall_extension(e.id)
    : await api.install_extension(e.id);
  if (r.ok) {
    toast(e.installed ? `${e.name} desinstallee` : `${e.name} installee ✓`);
  } else {
    toast("Echec — voir details");
    console.error(r.log);
  }
  loadExtensions();
}

// --- Reglages ---
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
  toast(ev.target.checked ? "Demarrage auto active" : "Demarrage auto desactive");
});
$("#set-autostart-server").addEventListener("change", async (ev) => {
  await api.set_autostart_server(ev.target.checked);
  toast("Reglage enregistre");
});
$("#set-auto-update").addEventListener("change", async (ev) => {
  await api.set_auto_update(ev.target.checked);
  toast(ev.target.checked ? "Mises a jour auto activees" : "Mises a jour auto desactivees");
});
$("#btn-check-update").addEventListener("click", async () => {
  toast("Verification...");
  const r = await api.check_update_now();
  toast(r.available ? `Mise a jour ${r.tag} en cours...` : "SpiceUtils est a jour");
});
$("#btn-quit").addEventListener("click", () => api.quit_app());

// Toast declenchable depuis Python (evaluate_js).
window.spiceToast = (msg) => toast(msg);

// --- Modal de fermeture (appele depuis Python via evaluate_js) ---
function hideCloseModal() { $("#close-modal").classList.add("hidden"); }

window.spiceShowCloseDialog = function () {
  $("#close-modal").classList.remove("hidden");
};

$("#modal-keep").addEventListener("click", async () => {
  hideCloseModal();
  await api.hide_window();        // laisse le serveur tourner, reduit dans le tray
});
$("#modal-off").addEventListener("click", async () => {
  hideCloseModal();
  await api.quit_app();           // arrete le serveur et quitte
});
$("#modal-cancel").addEventListener("click", hideCloseModal);
$("#close-modal").addEventListener("click", (e) => {
  if (e.target.id === "close-modal") hideCloseModal();  // clic sur le fond = annuler
});

// --- Init ---
window.addEventListener("pywebviewready", () => {
  api = window.pywebview.api;
  refreshStatus();
  refreshLogs();
  logTimer = setInterval(refreshLogs, 1500);
  statusTimer = setInterval(() => {
    refreshStatus();
    if ($("#tab-server").classList.contains("active")) refreshQueue();
  }, 2500);
});
