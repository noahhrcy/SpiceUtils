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
      '<div class="sx-phase"></div>';
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
    const el = progressEl;
    setTimeout(() => { el.classList.remove("show"); }, isError ? 3500 : 1400);
  }

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

    showProgress(meta.title);
    try {
      const r = await fetch(`${SERVER_URL}/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(meta),
      });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const { job_id } = await r.json();
      pollProgress(job_id, meta.title);
    } catch (e) {
      console.error("[StemExtractor]", e);
      updateProgress(0, "save");
      finishProgress(true, "Le serveur repond-il ?");
    }
  }

  function pollProgress(jobId, title) {
    const timer = setInterval(async () => {
      try {
        const r = await fetch(`${SERVER_URL}/progress/${jobId}`);
        if (!r.ok) throw new Error("progress KO");
        const p = await r.json();
        updateProgress(p.percent || 0, p.phase);
        if (p.status === "done") {
          clearInterval(timer);
          updateProgress(100, "save");
          finishProgress(false);
          Spicetify.showNotification(`Stems prets ✓ ${title}`);
        } else if (p.status === "error") {
          clearInterval(timer);
          finishProgress(true, p.error ? p.error.slice(0, 60) : "Echec");
          Spicetify.showNotification("Echec de l'extraction des stems", true);
        }
      } catch (e) {
        clearInterval(timer);
        finishProgress(true, "Connexion perdue");
      }
    }, 600);
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
