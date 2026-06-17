// spiceStats.js — Extension Spicetify (livree par SpiceUtils)
// Affiche le BPM et la tonalite (key) des morceaux :
//   - sur la barre de lecture (morceau en cours)
//   - a cote de chaque titre dans les listes (best-effort, selon le DOM Spotify)
// Source : API Spotify audio-features (via le token interne du client).

(function spiceStats() {
  if (!Spicetify || !Spicetify.Player || !Spicetify.CosmosAsync) {
    setTimeout(spiceStats, 300);
    return;
  }

  const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const cache = new Map(); // id -> features | null

  function fmtKey(key, mode) {
    if (key === undefined || key === null || key < 0) return "";
    return NOTES[key] + (mode === 1 ? " maj" : " min");
  }
  function fmtFeatures(f) {
    if (!f) return "";
    const bpm = f.tempo ? Math.round(f.tempo) + " BPM" : "";
    const k = fmtKey(f.key, f.mode);
    return [bpm, k].filter(Boolean).join(" · ");
  }

  async function getFeatures(id) {
    if (!id) return null;
    if (cache.has(id)) return cache.get(id);
    try {
      const f = await Spicetify.CosmosAsync.get(
        `https://api.spotify.com/v1/audio-features/${id}`
      );
      cache.set(id, f);
      return f;
    } catch (e) {
      cache.set(id, null); // evite de re-tenter en boucle
      return null;
    }
  }

  // --- Styles ---------------------------------------------------------------
  const style = document.createElement("style");
  style.textContent = `
    .spicestats-np { font-size: 11px; color: #c08bf0; margin-top: 2px; letter-spacing:.2px; }
    .spicestats-cell { font-size: 11px; color: #9a86b5; white-space: nowrap;
      align-self: center; padding: 0 14px; font-variant-numeric: tabular-nums; }
    .main-trackList-trackListRow:hover .spicestats-cell { color: #c08bf0; }`;
  document.head.appendChild(style);

  // --- Barre de lecture (morceau en cours) ----------------------------------
  async function updateNowPlaying() {
    const item = Spicetify.Player.data && Spicetify.Player.data.item;
    if (!item || !item.uri) return;
    const id = item.uri.split(":").pop();
    const txt = fmtFeatures(await getFeatures(id));

    const host =
      document.querySelector(".main-nowPlayingWidget-nowPlaying") ||
      document.querySelector(".main-nowPlayingBar-left");
    if (!host) return;
    let badge = document.getElementById("spicestats-np");
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "spicestats-np";
      badge.className = "spicestats-np";
      host.appendChild(badge);
    }
    badge.textContent = txt;
  }

  Spicetify.Player.addEventListener("songchange", updateNowPlaying);
  setTimeout(updateNowPlaying, 1500);

  // --- Listes de titres (best-effort) ---------------------------------------
  function processRow(row) {
    if (row.dataset.spicestats) return;
    const link = row.querySelector('a[href*="/track/"]');
    if (!link) return;
    const m = (link.getAttribute("href") || "").match(/\/track\/([A-Za-z0-9]+)/);
    if (!m) return;
    row.dataset.spicestats = "1";
    getFeatures(m[1]).then((f) => {
      const txt = fmtFeatures(f);
      if (!txt) return;
      const cell = document.createElement("div");
      cell.className = "spicestats-cell";
      cell.textContent = txt;
      const end = row.querySelector(".main-trackList-rowSectionEnd");
      if (end && end.parentNode) end.parentNode.insertBefore(cell, end);
      else row.appendChild(cell);
    });
  }

  function scan() {
    document.querySelectorAll(".main-trackList-trackListRow").forEach(processRow);
  }

  let scanTimer = null;
  const obs = new MutationObserver(() => {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, 250); // debounce
  });
  obs.observe(document.body, { childList: true, subtree: true });
  scan();

  console.log("[SpiceStats] extension chargee");
})();
