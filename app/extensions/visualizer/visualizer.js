// visualizer.js — Spicetify extension (shipped by SpiceUtils)
// Fullscreen music visualizer: flowing forms reacting to beats/loudness, synced
// to playback via Spotify's audio-analysis. Falls back to a smooth generative
// animation if the analysis API is unavailable.

(function visualizer() {
  if (window.__spiceVizLoaded) return;
  if (!Spicetify || !Spicetify.Player || !Spicetify.CosmosAsync || !Spicetify.Playbar) {
    setTimeout(visualizer, 300);
    return;
  }
  window.__spiceVizLoaded = true;

  let overlay = null, canvas = null, ctx = null, raf = null;
  let analysis = null, analysisFor = null;
  let energy = 0, beatPulse = 0, beatIdx = 0;
  const PALETTE = [[157, 92, 255], [192, 139, 240], [224, 123, 224], [92, 107, 255]];

  // --- audio-analysis (real reactivity); null if API unavailable -------------
  async function loadAnalysis() {
    const item = Spicetify.Player.data && Spicetify.Player.data.item;
    if (!item || !item.uri) return;
    const id = item.uri.split(":").pop();
    if (analysisFor === id) return;
    analysisFor = id;
    analysis = null; beatIdx = 0;
    try {
      const a = await Spicetify.CosmosAsync.get(`https://api.spotify.com/v1/audio-analysis/${id}`);
      if (a && a.segments && a.segments.length) analysis = a;
    } catch (e) {
      analysis = null; // deprecated/unavailable -> generative fallback
    }
  }

  function segLoudness(tSec) {
    const segs = analysis.segments;
    // recherche lineaire avancante (lecture sequentielle)
    let lo = 0, hi = segs.length - 1, mid;
    while (lo < hi) { mid = (lo + hi + 1) >> 1; if (segs[mid].start <= tSec) lo = mid; else hi = mid - 1; }
    const l = segs[lo].loudness_max; // dB ~ [-60..0]
    return Math.max(0, Math.min(1, (l + 55) / 55));
  }

  function updateEnergy(now) {
    const playing = !(Spicetify.Player.data && Spicetify.Player.data.is_paused);
    const tSec = (Spicetify.Player.getProgress() || 0) / 1000;
    let target;
    if (analysis) {
      target = segLoudness(tSec);
      const beats = analysis.beats;
      while (beatIdx < beats.length && beats[beatIdx].start <= tSec) {
        beatPulse = 1; beatIdx++;
      }
      // resync index if user seeked
      if (beatIdx > 0 && beats[beatIdx - 1] && beats[beatIdx - 1].start > tSec + 1) beatIdx = 0;
    } else {
      // generative: pseudo-beat ~2 Hz + slow swell
      target = 0.45 + 0.35 * (0.5 + 0.5 * Math.sin(now / 380));
      if (Math.sin(now / 250) > 0.96) beatPulse = 1;
    }
    if (!playing) target *= 0.25;
    energy += (target - energy) * 0.12;
    beatPulse *= 0.9;
  }

  // --- render ---------------------------------------------------------------
  function draw(now) {
    raf = requestAnimationFrame(draw);
    if (!ctx) return;
    updateEnergy(now);
    const W = canvas.width, H = canvas.height, cx = W / 2, cy = H / 2;
    const t = now / 1000;
    const e = energy + beatPulse * 0.6;

    // fade trail
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "rgba(12,7,20,0.22)";
    ctx.fillRect(0, 0, W, H);

    ctx.globalCompositeOperation = "lighter";

    // drifting blobs
    const blobs = 5;
    for (let i = 0; i < blobs; i++) {
      const ph = (i / blobs) * Math.PI * 2;
      const r = Math.min(W, H) * (0.12 + 0.05 * i) * (0.7 + e * 0.9);
      const x = cx + Math.cos(t * (0.3 + i * 0.07) + ph) * W * 0.22;
      const y = cy + Math.sin(t * (0.27 + i * 0.06) + ph * 1.3) * H * 0.22;
      const c = PALETTE[i % PALETTE.length];
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},${0.5 * (0.5 + e)})`);
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    }

    // pulsing waveform ring (uses segment pitches if available)
    const baseR = Math.min(W, H) * (0.18 + e * 0.16);
    const pitches = analysis ? currentPitches() : null;
    const N = 120;
    ctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * Math.PI * 2;
      let m = pitches ? pitches[Math.floor((i / N) * 12) % 12] : (0.5 + 0.5 * Math.sin(a * 6 + t * 2));
      const rr = baseR * (1 + 0.35 * m * (0.5 + e) + 0.06 * Math.sin(a * 9 + t * 3));
      const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath();
    ctx.lineWidth = 2 + e * 4;
    ctx.strokeStyle = `rgba(224,123,224,${0.5 + e * 0.5})`;
    ctx.shadowBlur = 30 + e * 50; ctx.shadowColor = "rgba(157,92,255,0.9)";
    ctx.stroke();
    ctx.shadowBlur = 0;

    // core
    const cr = baseR * 0.45 * (1 + beatPulse * 0.5);
    const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, cr);
    cg.addColorStop(0, `rgba(255,255,255,${0.25 + e * 0.4})`);
    cg.addColorStop(0.5, "rgba(157,92,255,0.35)");
    cg.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = cg;
    ctx.beginPath(); ctx.arc(cx, cy, cr, 0, Math.PI * 2); ctx.fill();
  }

  function currentPitches() {
    const tSec = (Spicetify.Player.getProgress() || 0) / 1000;
    const segs = analysis.segments;
    let lo = 0, hi = segs.length - 1, mid;
    while (lo < hi) { mid = (lo + hi + 1) >> 1; if (segs[mid].start <= tSec) lo = mid; else hi = mid - 1; }
    return segs[lo].pitches;
  }

  function resize() {
    if (!canvas) return;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }

  function open() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.id = "spice-viz";
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:9998;background:#0c0714;cursor:pointer;";
    canvas = document.createElement("canvas");
    overlay.appendChild(canvas);
    const hint = document.createElement("div");
    hint.textContent = "Click or press Esc to close";
    hint.style.cssText =
      "position:fixed;bottom:18px;left:50%;transform:translateX(-50%);color:#9a86b5;" +
      "font-size:12px;font-family:inherit;z-index:9999;pointer-events:none;opacity:.8";
    overlay.appendChild(hint);
    document.body.appendChild(overlay);
    ctx = canvas.getContext("2d");
    resize();
    window.addEventListener("resize", resize);
    overlay.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    loadAnalysis();
    raf = requestAnimationFrame(draw);
  }

  function close() {
    if (!overlay) return;
    cancelAnimationFrame(raf); raf = null;
    window.removeEventListener("resize", resize);
    document.removeEventListener("keydown", onKey);
    overlay.remove(); overlay = null; canvas = null; ctx = null;
  }
  function onKey(e) { if (e.key === "Escape") close(); }

  Spicetify.Player.addEventListener("songchange", () => { if (overlay) loadAnalysis(); });

  const ICON =
    '<svg role="img" height="16" width="16" viewBox="0 0 16 16" fill="currentColor">' +
    '<circle cx="8" cy="8" r="2"/><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 2a5 5 0 1 1 0 10A5 5 0 0 1 8 3z" opacity=".55"/></svg>';

  new Spicetify.Playbar.Button("Visualizer", ICON, () => (overlay ? close() : open()), false, false);

  console.log("[Visualizer] extension loaded (SpiceUtils)");
})();
