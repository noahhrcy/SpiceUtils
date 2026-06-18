// stemExtractor.js — Spicetify extension (shipped by SpiceUtils)
// Adds an "Extract stems" button (playbar + context menu).
// On click: sends the track to the local SpiceUtils server which separates the
// stems (Demucs) and saves them to the user's chosen output folder.

(function stemExtractor() {
  // De-dup: if the extension is loaded twice (e.g. installed via both SpiceUtils
  // and the Marketplace), only initialize once (otherwise duplicate button/menu).
  if (window.__stemExtractorLoaded) return;
  if (!Spicetify || !Spicetify.Platform || !Spicetify.URI || !Spicetify.showNotification) {
    setTimeout(stemExtractor, 300);
    return;
  }
  window.__stemExtractorLoaded = true;

  const SERVER_URL = "http://127.0.0.1:8765";
  const SPICEUTILS_RELEASES = "https://github.com/noahhrcy/SpiceUtils/releases";
  let backendReady = false;

  // "SpiceUtils required" dialog with a button to the download page.
  function showNotInstalled() {
    const box = document.createElement("div");
    box.style.cssText = "font-family:inherit;color:var(--spice-text,#ece4f7);line-height:1.5";
    box.innerHTML =
      "<p>The <b>Stem Extractor</b> extension needs the <b>SpiceUtils</b> " +
      "application (with its server running) to extract stems.</p>" +
      "<p style='color:#9a86b5;font-size:13px'>Install SpiceUtils, open it, " +
      "then start the server (Server tab).</p>";
    const btn = document.createElement("button");
    btn.textContent = "Download SpiceUtils";
    btn.style.cssText =
      "margin-top:10px;padding:10px 18px;border:none;border-radius:20px;cursor:pointer;" +
      "font-weight:600;color:#fff;background:linear-gradient(135deg,#7e3fe0,#9d5cff)";
    btn.onclick = () => {
      try { window.open(SPICEUTILS_RELEASES, "_blank"); }
      catch (e) {
        try { Spicetify.Platform.ClipboardAPI.copy(SPICEUTILS_RELEASES); } catch (_) {}
        Spicetify.showNotification("Link copied: " + SPICEUTILS_RELEASES);
      }
    };
    box.appendChild(btn);
    Spicetify.PopupModal.display({ title: "SpiceUtils required", content: box });
  }

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
      #stemx-progress .sx-list-i{font-size:11px;color:#c8b8e6;padding:2px 0;display:flex;align-items:center;gap:6px}
      #stemx-progress .sx-list-i span{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #stemx-progress .sx-list-i span::before{content:"•";color:#9d5cff;margin-right:6px}
      #stemx-progress .sx-x,#stemx-progress .sx-cancel{background:none;border:none;color:#9a86b5;cursor:pointer;
        font-size:12px;padding:0 4px;line-height:1}
      #stemx-progress .sx-x:hover,#stemx-progress .sx-cancel:hover{color:#e07be0}
      #stemx-progress .sx-cancel{margin-left:8px;display:none}
      #stemx-progress .sx-cancel.show{display:inline}
      #stemx-progress.err{border-color:#c0445c}
      #stemx-progress.err .sx-fill{background:#c0445c}`;
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    const el = document.createElement("div");
    el.id = "stemx-progress";
    el.innerHTML =
      '<div class="sx-row"><div class="sx-ic"><i></i><i></i><i></i></div>' +
      '<span class="sx-title"></span><span class="sx-pct">0%</span>' +
      '<button class="sx-cancel" title="Cancel the running extraction">✕</button></div>' +
      '<div class="sx-bar"><div class="sx-fill"></div></div>' +
      '<div class="sx-phase"></div>' +
      '<div class="sx-list"><div class="sx-list-h"></div></div>';
    document.body.appendChild(el);
    progressEl = el;
    return el;
  }

  const PHASES = { init: "Preparing…", download: "Downloading audio…",
    separate: "Separating stems (Demucs)…", save: "Saving…" };

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
      progressEl.querySelector(".sx-phase").textContent = msg || "Failed";
    }
    const list = progressEl.querySelector(".sx-list");
    if (list) list.classList.remove("show");
    const cx = progressEl.querySelector(".sx-cancel");
    if (cx) { cx.classList.remove("show"); cx.disabled = false; }
    const el = progressEl;
    setTimeout(() => { el.classList.remove("show"); }, isError ? 3500 : 1400);
  }

  function fmtEta(sec) {
    if (sec == null || sec < 0) return "";
    sec = Math.round(sec);
    if (sec >= 60) return `~${Math.floor(sec / 60)}m${String(sec % 60).padStart(2, "0")}s left`;
    return `~${sec}s left`;
  }

  // Show the list of queued tracks below the bar.
  function renderQueueList(pending) {
    if (!progressEl) return;
    const list = progressEl.querySelector(".sx-list");
    if (!pending || pending.length === 0) { list.innerHTML = ""; list.classList.remove("show"); return; }
    list.innerHTML = `<div class="sx-list-h">Queued (${pending.length})</div>`;
    pending.forEach((p) => {
      const row = document.createElement("div");
      row.className = "sx-list-i";
      const s = document.createElement("span");
      s.textContent = p.title;
      const x = document.createElement("button");
      x.className = "sx-x"; x.textContent = "✕"; x.title = "Remove from queue";
      x.onclick = () => { cancelJob(p.job_id); x.disabled = true; };
      row.appendChild(s); row.appendChild(x);
      list.appendChild(row);
    });
    list.classList.add("show");
  }

  let queuePoller = null;

  async function cancelJob(jobId) {
    try { await fetch(`${SERVER_URL}/cancel/${jobId}`, { method: "POST" }); } catch (e) {}
  }

  async function extractStems(uris, mode) {
    if (!backendReady) {
      await checkServer(true);
      if (!backendReady) { showNotInstalled(); return; }
    }

    let meta;
    try {
      meta = await getTrackMeta(uris);
    } catch (e) {
      Spicetify.showNotification("Could not read track info", true);
      console.error("[StemExtractor]", e);
      return;
    }
    if (mode) meta.quality = mode;

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
          ? `Queued (#${data.position}): ${meta.title}`
          : `Extracting: ${meta.title}`
      );
      startQueuePoller();
    } catch (e) {
      console.error("[StemExtractor]", e);
      ensureProgressUI();
      showProgress(meta.title);
      finishProgress(true, "Is the server running?");
    }
  }

  // Global queue poll: shows the current track + the number queued.
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
        finishProgress(true, "Connection lost");
        return;
      }
      if (q.active) {
        ensureProgressUI();
        progressEl.classList.remove("err");
        progressEl.classList.add("show");
        progressEl.querySelector(".sx-title").textContent = q.active.title;
        const cx = progressEl.querySelector(".sx-cancel");
        cx.classList.add("show");
        cx.onclick = () => { cancelJob(q.active.job_id); cx.disabled = true; };
        let phase;
        if (q.active.status === "queued") {
          updateProgress(0);
          phase = `Queued (#${q.active.position})`;
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
          progressEl.querySelector(".sx-phase").textContent = "Waiting…";
          renderQueueList(q.pending);
        }
      } else {
        // file vide -> on a fini
        clearInterval(queuePoller); queuePoller = null;
        if (q.last && q.last.status === "error") {
          finishProgress(true, q.last.error ? q.last.error.slice(0, 60) : "Failed");
          Spicetify.showNotification("Stem extraction failed", true);
        } else {
          updateProgress(100);
          finishProgress(false);
          Spicetify.showNotification("Stems ready ✓");
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

  // Petit menu de choix du mode (Rapide / Qualite) au clic sur le bouton.
  const menuStyle = document.createElement("style");
  menuStyle.textContent = `
    #stemx-menu{position:fixed;z-index:10000;
      background:linear-gradient(160deg,rgba(46,28,68,.98),rgba(26,16,40,.98));
      border:1px solid rgba(157,92,255,.5);border-radius:14px;padding:8px;
      box-shadow:0 16px 40px rgba(0,0,0,.55),0 0 24px rgba(126,63,224,.3);
      display:flex;flex-direction:column;gap:8px;animation:stemxin .15s ease}
    @keyframes stemxin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
    #stemx-menu button{background:var(--spice-card,#241439);color:#ece4f7;border:1px solid rgba(157,92,255,.3);
      border-radius:10px;padding:10px 16px;font-size:13px;cursor:pointer;font-family:inherit;white-space:nowrap}
    #stemx-menu button:hover{filter:brightness(1.12)}
    #stemx-menu .fast{background:linear-gradient(135deg,#c0445c,#8a2f44);border:none}
    #stemx-menu .qual{background:linear-gradient(135deg,#7e3fe0,#9d5cff);border:none}`;
  document.head.appendChild(menuStyle);

  // Affiche le menu juste AU-DESSUS du bouton (anchor).
  function showModeMenu(uris, anchor) {
    const old = document.getElementById("stemx-menu");
    if (old) { old.remove(); return; }
    const m = document.createElement("div");
    m.id = "stemx-menu";
    const fast = document.createElement("button");
    fast.className = "fast"; fast.textContent = "⚡ Fast extraction";
    const qual = document.createElement("button");
    qual.className = "qual"; qual.textContent = "✨ Quality extraction";
    fast.onclick = () => { m.remove(); extractStems(uris, "fast"); };
    qual.onclick = () => { m.remove(); extractStems(uris, "quality"); };
    m.appendChild(fast); m.appendChild(qual);
    m.style.visibility = "hidden";
    document.body.appendChild(m);
    // Positionne au-dessus et centre sur le bouton.
    const r = anchor && anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : null;
    if (r) {
      const mw = m.offsetWidth;
      let left = r.left + r.width / 2 - mw / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - mw - 8));
      m.style.left = left + "px";
      m.style.bottom = (window.innerHeight - r.top + 8) + "px";
    } else {
      m.style.left = "50%"; m.style.transform = "translateX(-50%)"; m.style.bottom = "90px";
    }
    m.style.visibility = "visible";
    setTimeout(() => {
      const close = (e) => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("click", close); } };
      document.addEventListener("click", close);
    }, 50);
  }

  const pbButton = new Spicetify.Playbar.Button(
    "Extract stems",
    STEM_ICON,
    async (self) => {
      const cur = Spicetify.Player.data?.item;
      if (!cur) {
        Spicetify.showNotification("No track playing", true);
        return;
      }
      if (!backendReady) {
        await checkServer(true);
        if (!backendReady) { showNotInstalled(); return; }
      }
      const anchor = (self && self.element) || pbButton.element;
      showModeMenu(cur.uri, anchor);
    },
    false,
    false
  );

  new Spicetify.ContextMenu.Item(
    "Extract stems (Fast)",
    (uris) => extractStems(uris, "fast"),
    (uris) => uris.length === 1 && Spicetify.URI.isTrack(uris[0]),
    STEM_ICON
  ).register();
  new Spicetify.ContextMenu.Item(
    "Extract stems (Quality)",
    (uris) => extractStems(uris, "quality"),
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
        console.log(`[StemExtractor] SpiceUtils server v${data.version} detected`);
        return true;
      }
      throw new Error("unexpected response");
    } catch (e) {
      backendReady = false;
      if (!silent) {
        Spicetify.showNotification(
          "Stem Extractor: SpiceUtils server not running.",
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

  console.log("[StemExtractor] extension loaded (SpiceUtils)");
})();
