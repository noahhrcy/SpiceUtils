"""
Serveur local de separation de stems (coeur de l'extension Stem Extractor).

Expose une API HTTP locale consommee par l'extension Spicetify :
  POST /extract   {title, artist, uri} -> separe les stems dans Downloads/Stems
  GET  /health
  GET  /version

Pilote par SpiceUtils via la classe ServerController (start/stop a la demande).
"""

import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.serving import make_server

SERVER_VERSION = "2.7.0"
HOST = "127.0.0.1"
PORT = 8765

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SpiceUtils"
LOG_FILE = APP_DATA / "server.log"

# --- Configuration (output folder), persisted ---------------------------------
CONFIG_FILE = APP_DATA / "config.json"
DEFAULT_OUTPUT = str(Path.home() / "Downloads" / "Stems")

ALL_STEMS = ["vocals", "drums", "bass", "other"]

_config = {"output_dir": DEFAULT_OUTPUT}


def load_config():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        if data.get("output_dir"):
            _config["output_dir"] = data["output_dir"]
    except (OSError, ValueError):
        pass


def save_config():
    APP_DATA.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"output_dir": _config["output_dir"]}, indent=2),
                           encoding="utf-8")


def get_config():
    return {"output_dir": _config["output_dir"]}


def set_config(output_dir=None):
    if output_dir:
        _config["output_dir"] = output_dir
    save_config()
    return get_config()


def output_root() -> Path:
    """Configured output folder; falls back to Downloads/Stems if it is not
    reachable any more (unplugged drive, deleted network share...)."""
    root = Path(_config["output_dir"])
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except OSError:
        fallback = Path(DEFAULT_OUTPUT)
        if root != fallback:
            log(f"Output folder unavailable ({root}), using {fallback}")
            _config["output_dir"] = DEFAULT_OUTPUT
            try:
                save_config()
            except OSError:
                pass
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


load_config()

# Sous pythonw.exe, sys.executable pointe pythonw : on bascule sur python.exe
# pour les sous-processus (sinon sys.stdout=None fait planter demucs/tqdm).
PYTHON_EXE = sys.executable
if PYTHON_EXE.lower().endswith("pythonw.exe"):
    _cand = Path(PYTHON_EXE).with_name("python.exe")
    if _cand.exists():
        PYTHON_EXE = str(_cand)


_LOG_LOCK = threading.Lock()


def log(msg: str):
    """Ecrit une ligne horodatee dans le journal (lu par l'UI SpiceUtils)."""
    from datetime import datetime

    APP_DATA.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    try:
        with _LOG_LOCK, open(LOG_FILE, "a", encoding="utf-8") as f:   # threads: no interleaving
            f.write(line + "\n")
    except OSError:
        pass
    # Sous pythonw, sys.stdout vaut None -> print() leverait. On protege.
    try:
        print(line)
    except Exception:
        pass


def _trim_logs(max_bytes=2_000_000, keep=300_000):
    """Keep log files small (they are appended to forever otherwise)."""
    for f in (LOG_FILE, APP_DATA / "worker.log"):
        try:
            if f.stat().st_size > max_bytes:
                with open(f, "rb") as fh:
                    fh.seek(-keep, os.SEEK_END)
                    tail = fh.read()
                f.write_bytes(tail[tail.find(b"\n") + 1:])
        except OSError:
            pass


_trim_logs()


def ensure_ffmpeg_on_path():
    """Localise FFmpeg (installe par winget) et l'ajoute au PATH du process."""
    from shutil import which

    # FFmpeg local a l'app (installe par postinstall) : prioritaire.
    app_ffmpeg = Path(__file__).resolve().parent.parent / "ffmpeg" / "bin"
    if (app_ffmpeg / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(app_ffmpeg) + os.pathsep + os.environ.get("PATH", "")
        log(f"FFmpeg (app-local) added to PATH: {app_ffmpeg}")
        return

    if which("ffmpeg") and which("ffprobe"):
        return

    local = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    pkg_root = Path(local) / "Microsoft" / "WinGet" / "Packages"
    if pkg_root.exists():
        for exe in pkg_root.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
            candidates.append(exe.parent)
    candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links")

    for d in candidates:
        if (d / "ffmpeg.exe").exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            log(f"FFmpeg added to PATH: {d}")
            return
    log("WARNING: FFmpeg not found")


# --- Pipeline d'extraction ---------------------------------------------------

# Empeche l'apparition de fenetres console lors des sous-processus (l'app
# tourne sous pythonw, sans console).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

PCT_RE = re.compile(r"(\d+(?:\.\d+)?)%")

# Sous-process en cours (pour pouvoir l'annuler) + drapeau d'annulation.
_CUR = {"proc": None, "cancel": False}


def _run_stream(cmd, label, on_pct=None, register=True):
    """Execute une commande en lisant sa sortie en continu (pour la progression).

    Lit caractere par caractere pour capter les barres tqdm (qui utilisent \\r).
    Appelle on_pct(float) a chaque pourcentage detecte.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=NO_WINDOW,
    )
    if register:
        _CUR["proc"] = proc
    tail, buf = [], ""
    for ch in iter(lambda: proc.stdout.read(1), ""):
        if ch in ("\r", "\n"):
            if buf:
                tail.append(buf)
                tail[:] = tail[-20:]
                if on_pct:
                    m = PCT_RE.search(buf)
                    if m:
                        try:
                            on_pct(float(m.group(1)))
                        except ValueError:
                            pass
                buf = ""
        else:
            buf += ch
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed (code {proc.returncode}):\n" + "\n".join(tail[-15:]))


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return name[:120] or "track"


# --- Download tools (yt-dlp + JS runtime), self-managed & self-healing ---------
# YouTube changes often and now requires a JS runtime (Deno). Everything lives in
# user-writable folders so it can be updated/repaired without admin rights (the
# venv is in Program Files). Fallback chain for yt-dlp:
#   1. standalone yt-dlp.exe (bin/)          - self-updates with -U
#   2. pip copy in pylib/ ("yt-dlp[default]") - if the exe is blocked/quarantined
#   3. yt-dlp bundled in the venv             - last resort (may be outdated)
# JS runtime: deno.exe (bin/) -> deno from PyPI (pylib/) -> Node.js if installed.
BIN_DIR = APP_DATA / "bin"
PYLIB = APP_DATA / "pylib"
YTDLP_EXE = BIN_DIR / "yt-dlp.exe"
DENO_EXE = BIN_DIR / "deno.exe"
_TOOLS_LOCK = threading.Lock()
_UPDATE_STAMP = BIN_DIR / "yt-dlp.updated"
_TOOLS = {"ytdlp": None, "js": None, "mode": None}


def _fetch(url: str, dst: Path):
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "SpiceUtils"})
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dst)


def _works(cmd, timeout=60) -> bool:
    """True if the tool starts and answers --version (not blocked by an AV, not corrupt)."""
    try:
        p = subprocess.run(cmd + ["--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=NO_WINDOW, timeout=timeout)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _pip_target(pkgs) -> bool:
    """Install/upgrade packages into the user-writable pylib/ folder."""
    try:
        p = subprocess.run([PYTHON_EXE, "-m", "pip", "install", "-U", "--quiet",
                            "--disable-pip-version-check", "--no-warn-script-location",
                            "--target", str(PYLIB), *pkgs],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
                           timeout=900)
        if p.returncode != 0:
            log(f"pip fallback failed: {(p.stdout or '').strip()[-200:]}")
        return p.returncode == 0
    except Exception as e:  # noqa: BLE001
        log(f"pip fallback failed: {e}")
        return False


def _pylib_ytdlp_cmd():
    boot = f"import sys; sys.path.insert(0, r'{PYLIB}'); from yt_dlp import main; main()"
    return [PYTHON_EXE, "-c", boot]


def _find_js_runtime():
    if DENO_EXE.exists() and _works([str(DENO_EXE)]):
        return f"deno:{DENO_EXE}"
    for p in PYLIB.glob("**/deno.exe"):
        if _works([str(p)]):
            return f"deno:{p}"
    node = shutil.which("node")
    if node and _works([node]):
        return f"node:{node}"
    return None


def ensure_tools(force=False):
    """Make sure a working, recent yt-dlp and a JS runtime are available."""
    with _TOOLS_LOCK:
        if _TOOLS["ytdlp"] and not force:
            _update_ytdlp_locked()
            return
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        PYLIB.mkdir(parents=True, exist_ok=True)
        if str(BIN_DIR) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")

        # --- yt-dlp ---
        if YTDLP_EXE.exists() and not _works([str(YTDLP_EXE)]):
            log("yt-dlp.exe is not runnable (antivirus/corruption?): re-downloading it")
            YTDLP_EXE.unlink(missing_ok=True)
        if not YTDLP_EXE.exists():
            try:
                log("Downloading yt-dlp...")
                _fetch("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe", YTDLP_EXE)
                _UPDATE_STAMP.write_text(str(time.time()))
                if not _works([str(YTDLP_EXE)]):
                    YTDLP_EXE.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                log(f"yt-dlp.exe download failed: {e}")
        if YTDLP_EXE.exists():
            _TOOLS["ytdlp"], _TOOLS["mode"] = [str(YTDLP_EXE)], "exe"
        else:
            if not (PYLIB / "yt_dlp").exists() or force:
                log("Installing yt-dlp in the user folder (fallback)...")
                if _pip_target(["yt-dlp[default]"]):
                    _UPDATE_STAMP.write_text(str(time.time()))   # fresh: no update needed
            if (PYLIB / "yt_dlp").exists() and _works(_pylib_ytdlp_cmd()):
                _TOOLS["ytdlp"], _TOOLS["mode"] = _pylib_ytdlp_cmd(), "pip"
            else:
                _TOOLS["ytdlp"], _TOOLS["mode"] = [PYTHON_EXE, "-m", "yt_dlp"], "bundled"
                log("WARNING: using the bundled (possibly outdated) yt-dlp")

        # --- JS runtime (YouTube challenges) ---
        if DENO_EXE.exists() and not _works([str(DENO_EXE)]):
            DENO_EXE.unlink(missing_ok=True)
        if not DENO_EXE.exists():
            try:
                import zipfile

                log("Downloading Deno (JS runtime for YouTube)...")
                z = BIN_DIR / "deno.zip"
                _fetch("https://github.com/denoland/deno/releases/latest/download/"
                       "deno-x86_64-pc-windows-msvc.zip", z)
                with zipfile.ZipFile(z) as zf:
                    zf.extract("deno.exe", BIN_DIR)
                z.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                log(f"Deno download failed: {e}")
        js = _find_js_runtime()
        if not js:
            log("Installing Deno from PyPI (fallback)...")
            _pip_target(["deno"])
            js = _find_js_runtime()
        _TOOLS["js"] = js
        if not js:
            log("WARNING: no JS runtime available, some YouTube downloads may fail")
        _update_ytdlp_locked()


def _update_ytdlp_locked(force=False):
    """Keep yt-dlp fresh: daily, or immediately when forced (after a failure)."""
    try:
        if not force and _UPDATE_STAMP.exists() and time.time() - _UPDATE_STAMP.stat().st_mtime < 86400:
            return
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        _UPDATE_STAMP.write_text(str(time.time()))
        if _TOOLS["mode"] == "exe":
            p = subprocess.run([str(YTDLP_EXE), "-U"], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                               errors="replace", creationflags=NO_WINDOW, timeout=180)
            last = (p.stdout or "").strip().splitlines()[-1:] or [""]
            log(f"yt-dlp update check: {last[0][:120]}")
        elif _TOOLS["mode"] in ("pip", "bundled"):
            if _pip_target(["yt-dlp[default]"]) and _works(_pylib_ytdlp_cmd()):
                _TOOLS["ytdlp"], _TOOLS["mode"] = _pylib_ytdlp_cmd(), "pip"
                log("yt-dlp (user folder) updated")
    except Exception as e:  # noqa: BLE001
        log(f"yt-dlp update failed: {e}")


def update_ytdlp(force=False):
    with _TOOLS_LOCK:
        _update_ytdlp_locked(force)


def _ytdlp_cmd(extra=None):
    cmd = list(_TOOLS["ytdlp"] or [PYTHON_EXE, "-m", "yt_dlp"])
    if _TOOLS["js"]:
        cmd += ["--js-runtimes", _TOOLS["js"]]
    return cmd + (extra or [])


_NET_ERRORS = ("getaddrinfo", "Failed to resolve", "timed out", "Connection refused",
               "Connection reset", "Network is unreachable", "No route to host",
               "Temporary failure", "Unable to download API page", "urlopen error")


def friendly_error(msg: str) -> str:
    """Short, human error for the UI / Spotify widget."""
    m = msg or ""
    if any(k in m for k in _NET_ERRORS):
        return "No internet connection (or YouTube unreachable)"
    if "403" in m or "Forbidden" in m:
        return "YouTube blocked the download (tools updated, try again later)"
    if "Sign in to confirm" in m or "not a bot" in m:
        return "YouTube asks for a bot check, try again in a few minutes"
    if "No space left" in m or "Errno 28" in m:
        return "Disk full"
    if "memory" in m.lower():
        return "Not enough memory to separate this track"
    if "produced no audio" in m or "no video results" in m.lower():
        return "Track not found on YouTube"
    return m.strip().splitlines()[-1][:160] if m.strip() else "Unknown error"


def download_audio(query: str, dest_dir: Path, on_pct=None, register=True) -> Path:
    ensure_tools()
    out_template = str(dest_dir / "source.%(ext)s")
    # Keep the original audio stream (no WAV re-encode): Demucs and the MP3
    # conversion both read it directly through FFmpeg -> saves time and disk.
    args = [f"ytsearch1:{query}",
            "-f", "bestaudio/best",
            "-o", out_template, "--no-playlist", "--no-warnings", "--newline",
            "--no-update", "--retries", "5", "--fragment-retries", "5",
            "--socket-timeout", "30"]

    def clean():
        for p in dest_dir.glob("source.*"):
            p.unlink(missing_ok=True)

    # Escalating recovery: plain -> refresh/update tools -> alternate YouTube clients.
    attempts = [
        ("", None),
        ("updating yt-dlp and retrying", "update"),
        ("retrying with alternate YouTube clients",
         ["--extractor-args", "youtube:player_client=default,tv,web_safari,mweb"]),
    ]
    last_err = None
    for i, (note, action) in enumerate(attempts):
        if register and _CUR.get("cancel"):
            raise RuntimeError("cancelled")
        if note:
            log(f"  yt-dlp failed, {note}...")
        extra = None
        if action == "update":
            if last_err and any(k in str(last_err) for k in _NET_ERRORS):
                time.sleep(5)                     # network hiccup: just wait a bit
            else:
                ensure_tools(force=True)          # re-check/repair tools...
                update_ytdlp(force=True)          # ...and get the latest yt-dlp
        elif isinstance(action, list):
            extra = action
        clean()
        try:
            _run_stream(_ytdlp_cmd(extra) + args, "yt-dlp", on_pct, register)
            break
        except RuntimeError as e:
            last_err = e
            if register and _CUR.get("cancel"):
                raise
    else:
        raise RuntimeError(friendly_error(str(last_err)))
    files = [p for p in dest_dir.glob("source.*") if p.suffix not in (".part", ".ytdl", ".tmp")]
    if not files:
        raise RuntimeError("Track not found on YouTube")
    return files[0]


def to_mp3(src: Path, dst: Path):
    """Convert the downloaded audio to a 320 kbps MP3 (full track download)."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-codec:a", "libmp3lame", "-b:a", "320k", str(dst)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    if proc.returncode != 0 or not dst.exists():
        raise RuntimeError("MP3 conversion failed: " + (proc.stdout or "")[-300:])


# --- Separation worker (persistent process, models kept in memory) -----------
WORKER_PY = Path(__file__).with_name("sep_worker.py")
WORKER_LOG = APP_DATA / "worker.log"
SEP_OVERLAP = 0.1        # chunk overlap (0.25 = demucs default; 0.1 is ~15% faster, inaudible)
SEP_THREADS = None       # torch threads (None = torch default); set from benchmark
WORKER_IDLE_S = 600      # free the RAM after 10 min without jobs
# Below-normal priority: the machine (and Spotify playback) stays smooth while
# separating; on an idle PC it runs just as fast.
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000)
# Models fetched ahead of time so the first extraction doesn't wait for them:
# htdemucs (2+ stems) and the vocals specialist (most common single stem).
WARM_MODELS = ("955717e8", "04573f0d")


def model_label(stems) -> str:
    """1 stem -> htdemucs_ft specialist sub-model; 2+ stems -> htdemucs."""
    return "htdemucs_ft specialist" if len(stems) == 1 else "htdemucs"


def _torch_checkpoints() -> Path:
    home = os.environ.get("TORCH_HOME") or str(
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "torch")
    return Path(home) / "hub" / "checkpoints"


def warm_models():
    """Download missing model checkpoints in the background (low priority)."""
    ck = _torch_checkpoints()
    missing = [s for s in WARM_MODELS if not any(ck.glob(f"{s}-*.th"))]
    if not missing:
        return
    log("Downloading separation models in the background...")
    code = ("from demucs.pretrained import get_model\n"
            f"for s in {missing!r}: get_model(s)")
    try:
        p = subprocess.run([PYTHON_EXE, "-c", code], stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW | BELOW_NORMAL,
                           timeout=1800)
        log("Separation models ready" if p.returncode == 0
            else f"Model pre-download failed (will retry on use): {(p.stderr or '')[-200:]}")
    except Exception as e:  # noqa: BLE001
        log(f"Model pre-download failed (will retry on use): {e}")


class WorkerDied(RuntimeError):
    pass


class SepWorker:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.last_used = time.time()
        self.device = None
        threading.Thread(target=self._idle_reaper, daemon=True).start()

    def _ensure(self):
        if self.proc and self.proc.poll() is None:
            return
        APP_DATA.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [PYTHON_EXE, str(WORKER_PY)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=open(WORKER_LOG, "a", encoding="utf-8"),
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=NO_WINDOW | BELOW_NORMAL, cwd=str(WORKER_PY.parent),
        )

    def _call(self, payload, on_pct=None, track=False):
        with self.lock:
            self._ensure()
            if track:
                _CUR["proc"] = self.proc          # lets cancel() kill it
            self.last_used = time.time()
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
            for line in self.proc.stdout:
                line = line.strip()
                if line.startswith("PROGRESS"):
                    if on_pct:
                        try:
                            on_pct(float(line.split()[1]))
                        except (IndexError, ValueError):
                            pass
                elif line.startswith("DONE"):
                    self.last_used = time.time()
                    return json.loads(line[4:].strip() or "{}")
                elif line.startswith("ERROR"):
                    raise RuntimeError("separation: " + line[5:].strip())
            raise WorkerDied("separation engine stopped unexpectedly")

    def preload(self, stems):
        """Load the model in the background (e.g. while the audio downloads)."""
        def run():
            try:
                self._call({"cmd": "preload", "stems": list(stems)})
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=run, daemon=True).start()

    def separate(self, audio: Path, out_dir: Path, stems, on_pct=None):
        payload = {"cmd": "separate", "audio": str(audio), "out": str(out_dir),
                   "stems": stems, "overlap": SEP_OVERLAP, "threads": SEP_THREADS}
        try:
            res = self._call(payload, on_pct=on_pct, track=True)
        except WorkerDied:
            if _CUR.get("cancel"):
                raise
            # Crashed (out of memory, driver...): restart a fresh worker, retry once.
            log("  separation engine crashed, restarting it and retrying...")
            res = self._call(payload, on_pct=on_pct, track=True)
        if res.get("device") and res["device"] != self.device:
            self.device = res["device"]
            log(f"  separation device: {'NVIDIA GPU (CUDA)' if self.device == 'cuda' else 'CPU'}")
        return res

    def _idle_reaper(self):
        while True:
            time.sleep(60)
            if (self.proc and self.proc.poll() is None and not self.lock.locked()
                    and time.time() - self.last_used > WORKER_IDLE_S):
                try:
                    self.proc.terminate()
                except Exception:  # noqa: BLE001
                    pass


SEP = SepWorker()


# --- Application Flask --------------------------------------------------------

app = Flask(__name__)
CORS(app)


import queue as _queue
import uuid

# File d'attente : un seul stem traite a la fois (dans l'ordre d'ajout).
JOBS = {}                       # job_id -> dict d'etat
PENDING = []                    # job_id en attente (ordonnes)
ACTIVE = {"id": None}           # job_id en cours
LAST = {"id": None}             # dernier job termine (done/error)
JOBS_LOCK = threading.Lock()
JOB_QUEUE = _queue.Queue()


def _set(job_id, **kw):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kw)


def _fmt_dur(s):
    s = int(s)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _process(job_id):
    job = JOBS.get(job_id)
    if not job:
        return
    query, final_dir = job["_query"], Path(job["_dir"])
    title = job["title"]
    stems = job.get("stems") or []
    full = bool(job.get("full_track"))
    t0 = time.time()
    sep = {"start": None}
    _CUR["cancel"] = False
    # Download share of the progress bar: small if we also separate.
    dl_share = 25 if stems else 90
    _set(job_id, status="running", phase="download", percent=1, eta=None)
    what = (", ".join(stems) if stems else "no stems") + (" + full track" if full else "")
    log(f"▶ Starting: '{title}'  ({what})")
    if stems:
        SEP.preload(stems)   # load the model while the audio downloads
    tmp = Path(tempfile.mkdtemp(prefix="spiceutils_"))
    try:
        audio = _take_prefetch(job)
        if audio:
            log("  ↓ Audio already prefetched")
        else:
            t_dl = time.time()
            audio = download_audio(query, tmp,
                                   on_pct=lambda p: _set(job_id, percent=round(p * dl_share / 100)))
            log(f"  ↓ Audio fetched in {_fmt_dur(time.time() - t_dl)} ({audio.suffix[1:]})")
        final_dir.mkdir(parents=True, exist_ok=True)
        n = 0

        # Network is free now: fetch the next queued track while we separate.
        _prefetch_next()

        mp3_err = []
        mp3_thread = None
        if full:
            mp3 = final_dir / (final_dir.name + ".mp3")

            def conv():
                try:
                    to_mp3(audio, mp3)
                except Exception as ex:  # noqa: BLE001
                    mp3_err.append(ex)
            if stems:
                mp3_thread = threading.Thread(target=conv, daemon=True)   # in parallel
                mp3_thread.start()
            else:
                _set(job_id, phase="save", percent=dl_share)
                conv()

        if stems:
            _set(job_id, phase="separate", percent=25)
            log(f"  ♫ Separating stems ({model_label(stems)}, overlap {SEP_OVERLAP})...")
            sep["start"] = time.time()

            def on_sep(p):
                pct = 25 + p * 0.70
                eta = None
                frac = p / 100.0
                if frac > 0.03:
                    el = time.time() - sep["start"]
                    eta = round(el * (1 - frac) / frac)
                _set(job_id, percent=round(pct), eta=eta)

            res = SEP.separate(audio, final_dir, stems, on_pct=on_sep)
            n = len(res.get("files", []))
            log(f"  ♫ Separated in {_fmt_dur(time.time() - sep['start'])}")
            _set(job_id, phase="save", percent=97, eta=0)

        if mp3_thread:
            mp3_thread.join()
        if mp3_err:
            raise mp3_err[0]
        if full:
            log(f"  ♪ Full track saved: {final_dir.name}.mp3")
    except Exception as e:  # noqa: BLE001
        if _CUR.get("cancel"):
            log(f"⊘ Cancelled: '{title}'")
            _set(job_id, status="cancelled", percent=0, eta=None)
        else:
            log(f"✗ FAILED '{title}': {e}")
            _set(job_id, status="error", error=friendly_error(str(e)), percent=100, eta=None)
        return
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _drop_prefetch(job)
    extra = " + full track" if full else ""
    log(f"✓ Done '{title}' in {_fmt_dur(time.time() - t0)} → {n} stems{extra} in {final_dir}")
    _set(job_id, status="done", percent=100, eta=0, output_dir=str(final_dir))


# --- Prefetch: download the next queued track while the current one separates -
def _prefetch_next():
    with JOBS_LOCK:
        nxt = next((JOBS[i] for i in PENDING
                    if i in JOBS and JOBS[i].get("status") == "queued"), None)
        if not nxt or "_pre" in nxt:
            return
        pre = {"dir": Path(tempfile.mkdtemp(prefix="spiceutils_pre_")),
               "audio": None, "done": threading.Event()}
        nxt["_pre"] = pre

    def run():
        try:
            pre["audio"] = download_audio(nxt["_query"], pre["dir"], register=False)
            log(f"  ⇣ Prefetched next track: '{nxt['title']}'")
        except Exception as e:  # noqa: BLE001
            log(f"  prefetch failed for '{nxt['title']}' (will retry normally): {e}")
        finally:
            pre["done"].set()

    threading.Thread(target=run, daemon=True).start()


def _take_prefetch(job):
    pre = job.get("_pre")
    if not pre:
        return None
    pre["done"].wait()   # finishing a download already in progress beats restarting it
    audio = pre["audio"]
    return audio if audio and audio.exists() else None


def _drop_prefetch(job):
    pre = job.pop("_pre", None) if job else None
    if not pre:
        return

    def clean():
        pre["done"].wait(timeout=900)
        shutil.rmtree(pre["dir"], ignore_errors=True)

    threading.Thread(target=clean, daemon=True).start()


def cancel(job_id) -> dict:
    """Cancel a job: remove it from the queue if waiting, otherwise stop the running one."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {"ok": False, "message": "unknown"}
        if job_id in PENDING:
            PENDING.remove(job_id)
            job["status"] = "cancelled"
            log(f"⊘ Removed from queue: '{job['title']}'")
            return {"ok": True}
        if ACTIVE["id"] == job_id:
            _CUR["cancel"] = True
            proc = _CUR.get("proc")
    if ACTIVE["id"] == job_id and proc:
        try:
            proc.terminate()
        except Exception:
            pass
        return {"ok": True}
    return {"ok": False, "message": "already finished"}


def _worker():
    while True:
        job_id = JOB_QUEUE.get()
        with JOBS_LOCK:
            cancelled = JOBS.get(job_id, {}).get("status") == "cancelled"
            if job_id in PENDING:
                PENDING.remove(job_id)
            if not cancelled:
                ACTIVE["id"] = job_id
        if cancelled:
            _drop_prefetch(JOBS.get(job_id))
            JOB_QUEUE.task_done()
            continue
        try:
            _process(job_id)
        except BaseException as e:  # noqa: BLE001 - trace everything
            import traceback
            log(f"✗ WORKER ERROR ({job_id}): {e}")
            log(traceback.format_exc())
            _set(job_id, status="error", error=str(e), percent=100)
        finally:
            with JOBS_LOCK:
                ACTIVE["id"] = None
                LAST["id"] = job_id
            JOB_QUEUE.task_done()


# Worker independant du cycle Flask (vit toute la duree du process).
threading.Thread(target=_worker, daemon=True).start()


@app.route("/extract", methods=["POST"])
def extract():
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    if not title:
        return jsonify(error="missing title"), 400

    # Stems to keep (default: all 4) + optional full-track MP3.
    raw = data.get("stems")
    stems = ALL_STEMS[:] if raw is None else [s for s in raw if s in ALL_STEMS]
    full_track = bool(data.get("full_track"))
    if not stems and not full_track:
        return jsonify(error="nothing selected"), 400

    query = f"{title} {artist}".strip()
    folder = safe_name(f"{artist} - {title}" if artist else title)
    final_dir = output_root() / folder

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "queued", "phase": "queued", "percent": 0,
                        "title": title, "output_dir": None, "error": None, "eta": None,
                        "stems": stems, "full_track": full_track,
                        "_query": query, "_dir": str(final_dir)}
        PENDING.append(job_id)
        position = len(PENDING)
    JOB_QUEUE.put(job_id)
    log(f"➕ Queued (#{position}): '{title}'")
    return jsonify(job_id=job_id, position=position), 202


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel_route(job_id):
    return jsonify(cancel(job_id))


def _job_view(job_id, job):
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    out["job_id"] = job_id
    if job["status"] == "queued":
        out["position"] = (PENDING.index(job_id) + 1) if job_id in PENDING else 0
    return out


@app.route("/progress/<job_id>", methods=["GET"])
def progress(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error="job inconnu"), 404
        return jsonify(_job_view(job_id, job))


def queue_snapshot():
    with JOBS_LOCK:
        active = JOBS.get(ACTIVE["id"]) if ACTIVE["id"] else None
        last = JOBS.get(LAST["id"]) if LAST["id"] else None
        return {
            "active": _job_view(ACTIVE["id"], active) if active else None,
            "pending": [{"job_id": i, "title": JOBS[i]["title"]} for i in PENDING if i in JOBS],
            "pending_count": len(PENDING),
            "last": _job_view(LAST["id"], last) if last else None,
        }


@app.route("/queue", methods=["GET"])
def queue_state():
    """Global queue state (for the extension display)."""
    return jsonify(queue_snapshot())


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="up", output_root=str(output_root()))


@app.route("/version", methods=["GET"])
def version():
    return jsonify(app="spiceutils-stem-extractor", version=SERVER_VERSION)


# --- Controleur start/stop (utilise par SpiceUtils) --------------------------

class ServerController:
    """Demarre/arrete le serveur Flask dans un thread, a la demande."""

    def __init__(self):
        self._srv = None
        self._thread = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> dict:
        with self._lock:
            if self.is_running():
                return {"ok": True, "message": "already running"}
            ensure_ffmpeg_on_path()
            # Prepare/repair/refresh yt-dlp + Deno and fetch the models in the
            # background (first run downloads them), so the first extraction is fast.
            threading.Thread(target=lambda: (ensure_tools(), warm_models()), daemon=True).start()
            output_root()
            try:
                self._srv = make_server(HOST, PORT, app, threaded=True)
            except OSError as e:
                log(f"Cannot start (port {PORT}): {e}")
                return {"ok": False, "message": f"port {PORT} in use?"}
            self._thread = threading.Thread(
                target=self._srv.serve_forever, daemon=True
            )
            self._thread.start()
            cfg = get_config()
            log(f"● Server v{SERVER_VERSION} started at http://{HOST}:{PORT}")
            log(f"  output: {cfg['output_dir']}")
            return {"ok": True, "message": "started"}

    def stop(self) -> dict:
        with self._lock:
            if not self.is_running():
                return {"ok": True, "message": "already stopped"}
            self._srv.shutdown()
            self._thread.join(timeout=5)
            self._srv = None
            self._thread = None
            log("Server stopped")
            return {"ok": True, "message": "stopped"}

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "host": HOST,
            "port": PORT,
            "version": SERVER_VERSION,
            "output_root": str(output_root()),
            "config": get_config(),
        }


if __name__ == "__main__":
    # Mode autonome (debug) : demarre le serveur et bloque.
    ctrl = ServerController()
    ctrl.start()
    threading.Event().wait()
