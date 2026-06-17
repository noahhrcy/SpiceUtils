// stemExtractor.js — Extension Spicetify (livree par SpiceUtils)
// Ajoute un bouton "Extraire les stems" (barre de lecture + menu contextuel).
// Au clic : envoie le morceau au serveur local de SpiceUtils qui separe les
// stems (Demucs) et les ecrit dans le dossier Download de l'utilisateur.

(function stemExtractor() {
  if (!Spicetify || !Spicetify.Platform || !Spicetify.URI || !Spicetify.showNotification) {
    setTimeout(stemExtractor, 300);
    return;
  }

  const SERVER_URL = "http://127.0.0.1:8765";
  let backendReady = false;

  async function getTrackMeta(uris) {
    const uri = Array.isArray(uris) ? uris[0] : uris;
    const current = Spicetify.Player.data?.item;
    if (current && current.uri === uri) {
      return {
        uri,
        title: current.name,
        artist: (current.artists || []).map((a) => a.name).join(", "),
      };
    }
    const id = uri.split(":").pop();
    const res = await Spicetify.CosmosAsync.get(
      `https://api.spotify.com/v1/tracks/${id}`
    );
    return {
      uri,
      title: res.name,
      artist: (res.artists || []).map((a) => a.name).join(", "),
    };
  }

  // --- Barre de progression injectee dans l'UI Spotify ----------------------
  let progressEl = null;

  function ensureProgressUI() {
    if (progressEl) return progressEl;
    const css = `
      #stemx-progress{position:fixed;left:50%;bottom:96px;transform:translateX(-50%);
        width:380px;max-width:80vw;z-index:9999;padding:14px 18px;border-radius:14px;
        background:linear-gradient(160deg,rgba(46,28,68,.96),rgba(26,16,40,.96));
        border:1px solid rgba(157,92,255,.5);color:#ece4f7;font-family:inherit;
        box-shadow:0 20px 50px rgba(0,0,0,.55),0 0 30px rgba(126,63,224,.35);
        opacity:0;transition:opacity .25s,transform .25s;transform:translateX(-50%) translateY(10px)}
      #stemx-progress.show{opacity:1;transform:translateX(-50%) translateY(0)}
      #stemx-progress .sx-row{display:flex;align-items:center;gap:8px;margin-bottom:9px}
      #stemx-progress .sx-ic{width:22px;height:22px;border-radius:6px;flex:0 0 auto;
        background:linear-gradient(135deg,#2a1740,#46256f);display:flex;align-items:flex-end;
        justify-content:center;gap:2px;padding-bottom:4px}
      #stemx-progress .sx-ic i{width:2px;border-radius:1px;background:#c08bf0;animation:sxeq 1s ease-in-out infinite}
      #stemx-progress .sx-ic i:nth-child(1){height:6px}#stemx-progress .sx-ic i:nth-child(2){height:12px;animation-delay:.15s}
      #stemx-progress .sx-ic i:nth-child(3){height:8px;animation-delay:.3s}
      @keyframes sxeq{0%,100%{transform:scaleY(.5)}50%{transform:scaleY(1.2)}}
      #stemx-progress .sx-title{font-weight:600;font-size:13px;flex:1;white-space:nowrap;
        overflow:hidden;text-overflow:ellipsis}
      #stemx-progress .sx-pct{font-size:12px;color:#c08bf0;font-variant-numeric:tabular-nums}
      #stemx-progress .sx-bar{height:7px;border-radius:5px;background:rgba(157,92,255,.18);overflow:hidden}
      #stemx-progress .sx-fill{height:100%;width:0%;border-radius:5px;
        background:linear-gradient(90deg,#9d5cff,#e07be0);transition:width .35s ease}
      #stemx-progress .sx-phase{font-size:11px;color:#9a86b5;margin-top:6px}
      #stemx-progress .sx-list{margin-top:8px;border-top:1px solid rgba(157,92,255,.2);padding-top:6px;
        display:none;max-height:96px;overflow-y:auto}
      #stemx-progress .sx-list.show{display:block}
      #stemx-progress .sx-list-h{font-size:10px;color:#7e6a99;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
      #stemx-progress .sx-list-i{font-size:11px;color:#c8b8e6;padding:2px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #stemx-progress .sx-list-i::before{content:"•";color:#9d5cff;margin-right:6px}
      #stemx-progress.err{border-color:#c0445c}
      #stemx-progress.err .sx-fill{background:#c0445c}`;
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    const el = document.createElement("div");
    el.id = "stemx-progress";
    el.innerHTML =
      '<div class="sx-row"><div class="sx-ic"><i></i><i></i><i></i></div>' +
      '<span class="sx-title"></span><span class="sx-pct">0%</span></div>' +
      '<div class="sx-bar"><div class="sx-fill"></div></div>' +
      '<div class="sx-phase"></div>' +
      '<div class="sx-list"><div class="sx-list-h"></div></div>';
    document.body.appendChild(el);
    progressEl = el;
    return el;
  }

  const PHASES = { init: "Preparation…", download: "Telechargement de l'audio…",
    separate: "Separation des stems (Demucs)…", save: "Enregistrement…" };

  function showProgress(title) {
    const el = ensureProgressUI();
    el.classList.remove("err");
    el.querySelector(".sx-title").textContent = title;
    el.querySelector(".sx-pct").textContent = "0%";
    el.querySelector(".sx-fill").style.width = "0%";
    el.querySelector(".sx-phase").textContent = PHASES.init;
    requestAnimationFrame(() => el.classList.add("show"));
  }
  function updateProgress(pct, phase) {
    if (!progressEl) return;
    progressEl.querySelector(".sx-pct").textContent = Math.round(pct) + "%";
    progressEl.querySelector(".sx-fill").style.width = pct + "%";
    if (phase) progressEl.querySelector(".sx-phase").textContent = PHASES[phase] || phase;
  }
  function finishProgress(isError, msg) {
    if (!progressEl) return;
    if (isError) {
      progressEl.classList.add("err");
      progressEl.querySelector(".sx-phase").textContent = msg || "Echec";
    }
    const list = progressEl.querySelector(".sx-list");
    if (list) list.classList.remove("show");
    const el = progressEl;
    setTimeout(() => { el.classList.remove("show"); }, isError ? 3500 : 1400);
  }

  function fmtEta(sec) {
    if (sec == null || sec < 0) return "";
    sec = Math.round(sec);
    if (sec >= 60) return `~${Math.floor(sec / 60)}m${String(sec % 60).padStart(2, "0")}s restantes`;
    return `~${sec}s restantes`;
  }

  // Affiche la liste des morceaux en attente sous la barre.
  function renderQueueList(pending) {
    if (!progressEl) return;
    const list = progressEl.querySelector(".sx-list");
    if (!pending || pending.length === 0) { list.classList.remove("show"); return; }
    let html = `<div class="sx-list-h">En attente (${pending.length})</div>`;
    pending.forEach((t) => { html += `<div class="sx-list-i">${t}</div>`; });
    list.innerHTML = html;
    list.classList.add("show");
  }

  let queuePoller = null;

  async function extractStems(uris) {
    if (!backendReady) {
      Spicetify.showNotification(
        "Serveur SpiceUtils non detecte. Ouvrez SpiceUtils et demarrez le serveur.",
        true, 6000
      );
      checkServer(true);
      return;
    }

    let meta;
    try {
      meta = await getTrackMeta(uris);
    } catch (e) {
      Spicetify.showNotification("Impossible de lire les infos du morceau", true);
      console.error("[StemExtractor]", e);
      return;
    }

    try {
      const r = await fetch(`${SERVER_URL}/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(meta),
      });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const data = await r.json();
      ensureProgressUI();
      showProgress(meta.title);
      Spicetify.showNotification(
        data.position > 1
          ? `Ajoute a la file (#${data.position}) : ${meta.title}`
          : `Extraction : ${meta.title}`
      );
      startQueuePoller();
    } catch (e) {
      console.error("[StemExtractor]", e);
      ensureProgressUI();
      showProgress(meta.title);
      finishProgress(true, "Le serveur repond-il ?");
    }
  }

  // Poll global de la file : affiche le morceau en cours + le nombre en attente.
  function startQueuePoller() {
    if (queuePoller) return;
    queuePoller = setInterval(async () => {
      let q;
      try {
        const r = await fetch(`${SERVER_URL}/queue`);
        if (!r.ok) throw new Error("queue KO");
        q = await r.json();
      } catch (e) {
        clearInterval(queuePoller); queuePoller = null;
        finishProgress(true, "Connexion perdue");
        return;
      }
      if (q.active) {
        ensureProgressUI();
        progressEl.classList.remove("err");
        progressEl.classList.add("show");
        progressEl.querySelector(".sx-title").textContent = q.active.title;
        let phase;
        if (q.active.status === "queued") {
          updateProgress(0);
          phase = `En file (#${q.active.position})`;
        } else {
          updateProgress(q.active.percent || 0);
          phase = PHASES[q.active.phase] || q.active.phase || "";
          const eta = fmtEta(q.active.eta);
          if (eta) phase += "  ·  " + eta;
        }
        progressEl.querySelector(".sx-phase").textContent = phase;
        renderQueueList(q.pending);
      } else if (q.pending_count > 0) {
        // transition entre deux morceaux
        if (progressEl) {
          progressEl.querySelector(".sx-phase").textContent = "En attente…";
          renderQueueList(q.pending);
        }
      } else {
        // file vide -> on a fini
        clearInterval(queuePoller); queuePoller = null;
        if (q.last && q.last.status === "error") {
          finishProgress(true, q.last.error ? q.last.error.slice(0, 60) : "Echec");
          Spicetify.showNotification("Echec de l'extraction des stems", true);
        } else {
          updateProgress(100);
          finishProgress(false);
          Spicetify.showNotification("Stems prets ✓");
        }
      }
    }, 700);
  }

  const STEM_ICON =
    '<svg role="img" height="16" width="16" viewBox="0 0 16 16" fill="currentColor">' +
    '<rect x="1" y="6" width="2" height="4" rx="1"/>' +
    '<rect x="5" y="3" width="2" height="10" rx="1"/>' +
    '<rect x="9" y="1" width="2" height="14" rx="1"/>' +
    '<rect x="13" y="5" width="2" height="6" rx="1"/></svg>';

  new Spicetify.Playbar.Button(
    "Extraire les stems",
    STEM_ICON,
    () => {
      const cur = Spicetify.Player.data?.item;
      if (!cur) {
        Spicetify.showNotification("Aucun morceau en lecture", true);
        return;
      }
      extractStems(cur.uri);
    },
    false,
    false
  );

  new Spicetify.ContextMenu.Item(
    "Extraire les stems",
    (uris) => extractStems(uris),
    (uris) => uris.length === 1 && Spicetify.URI.isTrack(uris[0]),
    STEM_ICON
  ).register();

  async function checkServer(silent) {
    try {
      const r = await fetch(`${SERVER_URL}/version`);
      if (!r.ok) throw new Error("version KO");
      const data = await r.json();
      if (String(data.app || "").includes("stem-extractor")) {
        backendReady = true;
        console.log(`[StemExtractor] serveur SpiceUtils v${data.version} detecte`);
        return true;
      }
      throw new Error("reponse inattendue");
    } catch (e) {
      backendReady = false;
      if (!silent) {
        Spicetify.showNotification(
          "Stem Extractor : serveur SpiceUtils non demarre.",
          true,
          6000
        );
      }
      return false;
    }
  }

  checkServer(true).then((ok) => {
    if (!ok) {
      const id = setInterval(async () => {
        if (await checkServer(true)) clearInterval(id);
      }, 15000);
    }
  });

  console.log("[StemExtractor] extension chargee (SpiceUtils)");
})();
