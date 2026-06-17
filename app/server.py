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
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.serving import make_server

SERVER_VERSION = "2.5.0"
HOST = "127.0.0.1"
PORT = 8765

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SpiceUtils"
LOG_FILE = APP_DATA / "server.log"

# --- Configuration (dossier de sortie + qualite), persistee --------------------
CONFIG_FILE = APP_DATA / "config.json"
DEFAULT_OUTPUT = str(Path.home() / "Downloads" / "Stems")

# Deux profils : "quality" (htdemucs_ft, bag de 4, overlap 0.5) et "fast"
# (htdemucs, 1 modele, overlap 0.25, ~4x plus rapide).
QUALITY_PROFILES = {
    "quality": {"model": "htdemucs_ft", "segments": 4, "overlap": "0.5", "label": "Qualite"},
    "fast":    {"model": "htdemucs",    "segments": 1, "overlap": "0.25", "label": "Rapide"},
}

_config = {"output_dir": DEFAULT_OUTPUT, "quality": "quality"}


def load_config():
    try:
        _config.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        pass
    if _config.get("quality") not in QUALITY_PROFILES:
        _config["quality"] = "quality"


def save_config():
    APP_DATA.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(
        {"output_dir": _config["output_dir"], "quality": _config["quality"]},
        indent=2), encoding="utf-8")


def get_config():
    p = QUALITY_PROFILES[_config["quality"]]
    return {"output_dir": _config["output_dir"], "quality": _config["quality"],
            "quality_label": p["label"]}


def set_config(output_dir=None, quality=None):
    if output_dir:
        _config["output_dir"] = output_dir
    if quality in QUALITY_PROFILES:
        _config["quality"] = quality
    save_config()
    return get_config()


def output_root() -> Path:
    return Path(_config["output_dir"])


def current_profile() -> dict:
    return QUALITY_PROFILES[_config["quality"]]


load_config()

# Sous pythonw.exe, sys.executable pointe pythonw : on bascule sur python.exe
# pour les sous-processus (sinon sys.stdout=None fait planter demucs/tqdm).
PYTHON_EXE = sys.executable
if PYTHON_EXE.lower().endswith("pythonw.exe"):
    _cand = Path(PYTHON_EXE).with_name("python.exe")
    if _cand.exists():
        PYTHON_EXE = str(_cand)


def log(msg: str):
    """Ecrit une ligne horodatee dans le journal (lu par l'UI SpiceUtils)."""
    from datetime import datetime

    APP_DATA.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    # Sous pythonw, sys.stdout vaut None -> print() leverait. On protege.
    try:
        print(line)
    except Exception:
        pass


def ensure_ffmpeg_on_path():
    """Localise FFmpeg (installe par winget) et l'ajoute au PATH du process."""
    from shutil import which

    # FFmpeg local a l'app (installe par postinstall) : prioritaire.
    app_ffmpeg = Path(__file__).resolve().parent.parent / "ffmpeg" / "bin"
    if (app_ffmpeg / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(app_ffmpeg) + os.pathsep + os.environ.get("PATH", "")
        log(f"FFmpeg (local app) ajoute au PATH : {app_ffmpeg}")
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
            log(f"FFmpeg ajoute au PATH : {d}")
            return
    log("AVERTISSEMENT : FFmpeg introuvable")


# --- Pipeline d'extraction ---------------------------------------------------

# Empeche l'apparition de fenetres console lors des sous-processus (l'app
# tourne sous pythonw, sans console).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

PCT_RE = re.compile(r"(\d+(?:\.\d+)?)%")

# Sous-process en cours (pour pouvoir l'annuler) + drapeau d'annulation.
_CUR = {"proc": None, "cancel": False}


def _run_stream(cmd, label, on_pct=None):
    """Execute une commande en lisant sa sortie en continu (pour la progression).

    Lit caractere par caractere pour capter les barres tqdm (qui utilisent \\r).
    Appelle on_pct(float) a chaque pourcentage detecte.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=NO_WINDOW,
    )
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
        raise RuntimeError(f"{label} a echoue (code {proc.returncode}) :\n" + "\n".join(tail[-15:]))


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return name[:120] or "track"


def download_audio(query: str, dest_dir: Path, on_pct=None) -> Path:
    out_template = str(dest_dir / "source.%(ext)s")
    _run_stream([
        PYTHON_EXE, "-m", "yt_dlp", f"ytsearch1:{query}",
        "-x", "--audio-format", "wav", "--audio-quality", "0",
        "-o", out_template, "--no-playlist", "--no-warnings", "--newline",
    ], "yt-dlp", on_pct)
    wavs = list(dest_dir.glob("source.wav")) or list(dest_dir.glob("source.*"))
    if not wavs:
        raise RuntimeError("yt-dlp n'a produit aucun fichier audio")
    return wavs[0]


def separate_stems(audio_path: Path, out_dir: Path, prof=None, on_pct=None) -> Path:
    prof = prof or current_profile()
    model, segments, overlap = prof["model"], prof["segments"], prof["overlap"]
    # Un modele "bag" (qualite) affiche N barres. On lisse la progression :
    # chaque modele = 1/segments du total.
    state = {"seg": -1, "last": 101.0}

    def wrapped(p):
        if p < state["last"] - 5:   # le % est reparti a ~0 -> nouveau modele
            state["seg"] += 1
        state["last"] = p
        if on_pct:
            seg = max(state["seg"], 0)
            overall = (seg + p / 100.0) / segments * 100.0
            on_pct(min(overall, 100.0))

    _run_stream([
        PYTHON_EXE, "-m", "demucs", "-n", model,
        "--overlap", overlap,
        "-o", str(out_dir), str(audio_path),
    ], "demucs", wrapped)
    stem_dir = out_dir / model / audio_path.stem
    if not stem_dir.exists():
        raise RuntimeError("Demucs n'a pas genere les stems attendus")
    return stem_dir


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
    prof = QUALITY_PROFILES.get(job.get("quality"), current_profile())
    t0 = time.time()
    sep = {"start": None}
    _CUR["cancel"] = False
    _set(job_id, status="running", phase="download", percent=1, eta=None)
    log(f"▶ Demarrage : '{title}'  (qualite={prof['label']}, modele={prof['model']})")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            t_dl = time.time()
            audio = download_audio(query, tmp, on_pct=lambda p: _set(job_id, percent=round(p * 0.25)))
            log(f"  ↓ Audio recupere en {_fmt_dur(time.time() - t_dl)} ({audio.name})")

            _set(job_id, phase="separate", percent=25)
            log(f"  ♫ Separation des stems ({prof['model']}, overlap {prof['overlap']})...")
            sep["start"] = time.time()

            def on_sep(p):
                pct = 25 + p * 0.70
                eta = None
                frac = p / 100.0
                if frac > 0.03:
                    el = time.time() - sep["start"]
                    eta = round(el * (1 - frac) / frac)
                _set(job_id, percent=round(pct), eta=eta)

            stem_dir = separate_stems(audio, tmp, prof, on_pct=on_sep)

            _set(job_id, phase="save", percent=96, eta=0)
            final_dir.mkdir(parents=True, exist_ok=True)
            n = 0
            for f in stem_dir.glob("*.wav"):
                (final_dir / f.name).write_bytes(f.read_bytes())
                n += 1
    except Exception as e:  # noqa: BLE001
        if _CUR.get("cancel"):
            log(f"⊘ Annule : '{title}'")
            _set(job_id, status="cancelled", percent=0, eta=None)
        else:
            log(f"✗ ECHEC '{title}' : {e}")
            _set(job_id, status="error", error=str(e), percent=100, eta=None)
        return
    log(f"✓ Termine '{title}' en {_fmt_dur(time.time() - t0)} → {n} stems dans {final_dir}")
    _set(job_id, status="done", percent=100, eta=0, output_dir=str(final_dir))


def cancel(job_id) -> dict:
    """Annule un job : retire de la file s'il attend, sinon stoppe celui en cours."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {"ok": False, "message": "inconnu"}
        if job_id in PENDING:
            PENDING.remove(job_id)
            job["status"] = "cancelled"
            log(f"⊘ Retire de la file : '{job['title']}'")
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
    return {"ok": False, "message": "deja termine"}


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
            JOB_QUEUE.task_done()
            continue
        try:
            _process(job_id)
        except BaseException as e:  # noqa: BLE001 - on veut tout tracer
            import traceback
            log(f"✗ WORKER ERREUR ({job_id}) : {e}")
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
        return jsonify(error="titre manquant"), 400

    quality = data.get("quality") if data.get("quality") in QUALITY_PROFILES else None
    query = f"{title} {artist}".strip()
    folder = safe_name(f"{artist} - {title}" if artist else title)
    final_dir = output_root() / folder

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "queued", "phase": "queued", "percent": 0,
                        "title": title, "output_dir": None, "error": None, "eta": None,
                        "quality": quality, "_query": query, "_dir": str(final_dir)}
        PENDING.append(job_id)
        position = len(PENDING)
    JOB_QUEUE.put(job_id)
    log(f"➕ En file (#{position}) : '{title}'")
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
    """Etat global de la file (pour l'affichage de l'extension)."""
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
                return {"ok": True, "message": "deja demarre"}
            ensure_ffmpeg_on_path()
            output_root().mkdir(parents=True, exist_ok=True)
            try:
                self._srv = make_server(HOST, PORT, app, threaded=True)
            except OSError as e:
                log(f"Impossible de demarrer (port {PORT}) : {e}")
                return {"ok": False, "message": f"port {PORT} occupe ?"}
            self._thread = threading.Thread(
                target=self._srv.serve_forever, daemon=True
            )
            self._thread.start()
            cfg = get_config()
            log(f"● Serveur v{SERVER_VERSION} demarre sur http://{HOST}:{PORT}")
            log(f"  sortie : {cfg['output_dir']}  |  qualite : {cfg['quality_label']}")
            return {"ok": True, "message": "demarre"}

    def stop(self) -> dict:
        with self._lock:
            if not self.is_running():
                return {"ok": True, "message": "deja arrete"}
            self._srv.shutdown()
            self._thread.join(timeout=5)
            self._srv = None
            self._thread = None
            log("Serveur arrete")
            return {"ok": True, "message": "arrete"}

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
