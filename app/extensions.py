"""
Gestionnaire d'extensions Spicetify pour SpiceUtils.

Les extensions sont embarquees dans  app/extensions/<id>/  avec un manifest.json
et un fichier .js. On les installe/desinstalle via la CLI spicetify (copie du .js
dans le dossier Extensions + spicetify config + spicetify apply).

Une source distante (GitHub) pourra etre ajoutee plus tard sans changer l'UI.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

EXT_DIR = Path(__file__).with_name("extensions")
STATE_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SpiceUtils" / "ext_state.json"

# Empeche l'apparition de fenetres console (l'app tourne sous pythonw).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _save_state(s: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(s), encoding="utf-8")
    except OSError:
        pass


def _ver_tuple(v):
    out = []
    for p in str(v or "0").split("."):
        n = "".join(c for c in p if c.isdigit())
        out.append(int(n) if n else 0)
    return tuple(out) or (0,)


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SpiceUtils"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def _spicetify_exe() -> str | None:
    """Localise spicetify.exe (PATH ou emplacements connus)."""
    found = shutil.which("spicetify")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    for cand in (
        Path(local) / "spicetify" / "spicetify.exe",
        Path(roaming) / "spicetify" / "spicetify.exe",
    ):
        if cand.exists():
            return str(cand)
    return None


def spicetify_available() -> bool:
    return _spicetify_exe() is not None


def ensure_spicetify() -> str:
    """Renvoie le chemin de spicetify, en l'installant d'abord s'il est absent.

    Installe via le script officiel, puis initialise (backup apply) pour que
    'apply' fonctionne sur une installation toute neuve.
    """
    exe = _spicetify_exe()
    if exe:
        return exe

    script = (
        "$ErrorActionPreference='Stop';"
        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
        "iwr -useb https://raw.githubusercontent.com/spicetify/cli/main/install.ps1 | iex"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    exe = _spicetify_exe()
    if not exe:
        raise RuntimeError("Automatic Spicetify installation failed.")
    # Initialise Spicetify (patch Spotify) sur une install neuve.
    subprocess.run(
        [exe, "backup", "apply"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    return exe


def _run(*args) -> subprocess.CompletedProcess:
    exe = _spicetify_exe()
    if not exe:
        raise RuntimeError("Spicetify not found. Install it from spicetify.app.")
    return subprocess.run(
        [exe, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )


def _extensions_dir() -> Path:
    """Dossier Extensions de Spicetify (via 'spicetify path userdata')."""
    proc = _run("path", "userdata")
    out = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout or "")  # retire les codes ANSI
    # On garde la ligne qui ressemble a un chemin Windows (ignore avertissements).
    paths = [ln.strip() for ln in out.splitlines() if re.match(r"^[A-Za-z]:\\", ln.strip())]
    if not paths:
        raise RuntimeError("Spicetify path not found: " + out.strip()[:200])
    d = Path(paths[-1]) / "Extensions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_extensions() -> list[dict]:
    """Liste les extensions embarquees + leur etat d'installation."""
    out = []
    try:
        installed_dir = _extensions_dir()
    except Exception:
        installed_dir = None

    st = _state()
    for manifest_path in sorted(EXT_DIR.glob("*/manifest.json")):
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        js = manifest_path.parent / m["file"]
        installed = bool(installed_dir and (installed_dir / m["file"]).exists())
        out.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "description": m.get("description", ""),
            "version": m.get("version", ""),
            "author": m.get("author", ""),
            "file": m["file"],
            "update_url": m.get("update_url"),
            "available": js.exists(),
            "installed": installed,
            "installed_version": st.get(m["id"]) if installed else None,
        })
    return out


def _find(ext_id: str) -> dict:
    for e in list_extensions():
        if e["id"] == ext_id:
            return e
    raise ValueError(f"Unknown extension: {ext_id}")


def install(ext_id: str) -> dict:
    e = _find(ext_id)
    ensure_spicetify()  # installe Spicetify a la volee s'il est absent
    src = EXT_DIR / ext_id / e["file"]
    dst = _extensions_dir() / e["file"]
    shutil.copyfile(src, dst)
    _run("config", "extensions", e["file"])
    proc = _run("apply")
    ok = proc.returncode == 0
    if ok:
        st = _state(); st[ext_id] = e["version"]; _save_state(st)
    return {"ok": ok, "log": (proc.stdout or "").strip()[-1200:]}


def uninstall(ext_id: str) -> dict:
    e = _find(ext_id)
    # Le suffixe '-' retire l'extension de la liste de config Spicetify.
    _run("config", "extensions", f"{e['file']}-")
    dst = _extensions_dir() / e["file"]
    if dst.exists():
        dst.unlink()
    proc = _run("apply")
    st = _state(); st.pop(ext_id, None); _save_state(st)
    ok = proc.returncode == 0
    return {"ok": ok, "log": (proc.stdout or "").strip()[-1200:]}


def check_update(ext_id: str) -> dict:
    """Compare la version installee a celle publiee sur le repo de l'extension."""
    e = _find(ext_id)
    if not e.get("update_url") or not e.get("installed"):
        return {"update": False}
    cur = e.get("installed_version") or e.get("version")
    try:
        meta = json.loads(_http(e["update_url"]).decode("utf-8"))
    except Exception:
        return {"update": False, "error": "network"}
    remote = meta.get("version")
    return {"update": _ver_tuple(remote) > _ver_tuple(cur), "remote": remote, "current": cur}


def update_extension(ext_id: str) -> dict:
    """Telecharge la derniere version depuis le repo et la reinstalle."""
    e = _find(ext_id)
    if not e.get("update_url"):
        return {"ok": False, "log": "no update source"}
    try:
        meta = json.loads(_http(e["update_url"]).decode("utf-8"))
        base = e["update_url"].rsplit("/", 1)[0]
        js = _http(base + "/" + meta["file"]).decode("utf-8")
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "log": f"download: {ex}"}
    ensure_spicetify()
    dst = _extensions_dir() / meta["file"]
    dst.write_text(js, encoding="utf-8")
    _run("config", "extensions", meta["file"])
    proc = _run("apply")
    ok = proc.returncode == 0
    if ok:
        st = _state(); st[ext_id] = meta.get("version"); _save_state(st)
    return {"ok": ok, "version": meta.get("version"), "log": (proc.stdout or "").strip()[-800:]}
