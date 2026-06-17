"""
Serveur local de separation de stems (coeur de l'extension Stem Extractor).

Expose une API HTTP locale consommee par l'extension Spicetify :
  POST /extract   {title, artist, uri} -> separe les stems dans Downloads/Stems
  GET  /health
  GET  /version

Pilote par SpiceUtils via la classe ServerController (start/stop a la demande).
"""

import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.serving import make_server

SERVER_VERSION = "2.1.0"
HOST = "127.0.0.1"
PORT = 8765

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SpiceUtils"
LOG_FILE = APP_DATA / "server.log"

DOWNLOADS = Path.home() / "Downloads"
OUTPUT_ROOT = DOWNLOADS / "Stems"

DEMUCS_MODEL = "htdemucs"  # 4 stems : vocals / drums / bass / other

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
    print(line)


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


def separate_stems(audio_path: Path, out_dir: Path, on_pct=None) -> Path:
    _run_stream([
        PYTHON_EXE, "-m", "demucs", "-n", DEMUCS_MODEL,
        "-o", str(out_dir), str(audio_path),
    ], "demucs", on_pct)
    stem_dir = out_dir / DEMUCS_MODEL / audio_path.stem
    if not stem_dir.exists():
        raise RuntimeError("Demucs n'a pas genere les stems attendus")
    return stem_dir


# --- Application Flask --------------------------------------------------------

app = Flask(__name__)
CORS(app)


import uuid

JOBS = {}
JOBS_LOCK = threading.Lock()


def _set(job_id, **kw):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kw)


def _run_job(job_id, query, final_dir):
    """Pipeline complet en arriere-plan, avec mise a jour de la progression.

    Phases : telechargement (0-25%), separation (25-95%), copie (95-100%)."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _set(job_id, phase="download", percent=1)
            audio = download_audio(query, tmp, on_pct=lambda p: _set(job_id, percent=round(p * 0.25)))
            log(f"Audio telecharge : {audio.name}")

            _set(job_id, phase="separate", percent=25)
            stem_dir = separate_stems(audio, tmp, on_pct=lambda p: _set(job_id, percent=round(25 + p * 0.70)))

            _set(job_id, phase="save", percent=96)
            for f in stem_dir.glob("*.wav"):
                (final_dir / f.name).write_bytes(f.read_bytes())
    except Exception as e:  # noqa: BLE001
        log(f"ECHEC : {e}")
        _set(job_id, status="error", error=str(e), percent=100)
        return
    log(f"Termine -> {final_dir}")
    _set(job_id, status="done", percent=100, output_dir=str(final_dir))


@app.route("/extract", methods=["POST"])
def extract():
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    if not title:
        return jsonify(error="titre manquant"), 400

    query = f"{title} {artist}".strip()
    folder = safe_name(f"{artist} - {title}" if artist else title)
    final_dir = OUTPUT_ROOT / folder
    final_dir.mkdir(parents=True, exist_ok=True)
    log(f"Extraction : {query!r}")

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "phase": "init", "percent": 0,
                        "title": title, "output_dir": None, "error": None}
    threading.Thread(target=_run_job, args=(job_id, query, final_dir), daemon=True).start()
    return jsonify(job_id=job_id), 202


@app.route("/progress/<job_id>", methods=["GET"])
def progress(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error="job inconnu"), 404
        return jsonify(dict(job, job_id=job_id))


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="up", output_root=str(OUTPUT_ROOT))


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
            OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
            try:
                self._srv = make_server(HOST, PORT, app, threaded=True)
            except OSError as e:
                log(f"Impossible de demarrer (port {PORT}) : {e}")
                return {"ok": False, "message": f"port {PORT} occupe ?"}
            self._thread = threading.Thread(
                target=self._srv.serve_forever, daemon=True
            )
            self._thread.start()
            log(f"Serveur demarre sur http://{HOST}:{PORT}")
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
            "output_root": str(OUTPUT_ROOT),
        }


if __name__ == "__main__":
    # Mode autonome (debug) : demarre le serveur et bloque.
    ctrl = ServerController()
    ctrl.start()
    threading.Event().wait()
