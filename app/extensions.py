"""
Gestionnaire d'extensions Spicetify pour SpiceUtils.

Les extensions sont embarquees dans  app/extensions/<id>/  avec un manifest.json
et un fichier .js. On les installe/desinstalle via la CLI spicetify (copie du .js
dans le dossier Extensions + spicetify config + spicetify apply).

Une source distante (GitHub) pourra etre ajoutee plus tard sans changer l'UI.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

EXT_DIR = Path(__file__).with_name("extensions")

# Empeche l'apparition de fenetres console (l'app tourne sous pythonw).
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


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
        raise RuntimeError("Echec de l'installation automatique de Spicetify.")
    # Initialise Spicetify (patch Spotify) sur une install neuve.
    subprocess.run(
        [exe, "backup", "apply"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    return exe


def _run(*args) -> subprocess.CompletedProcess:
    exe = _spicetify_exe()
    if not exe:
        raise RuntimeError("Spicetify introuvable. Installe-le depuis spicetify.app.")
    return subprocess.run(
        [exe, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )


def _extensions_dir() -> Path:
    """Dossier Extensions de Spicetify (via 'spicetify path userdata')."""
    proc = _run("path", "userdata")
    userdata = (proc.stdout or "").strip().splitlines()[-1].strip()
    d = Path(userdata) / "Extensions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_extensions() -> list[dict]:
    """Liste les extensions embarquees + leur etat d'installation."""
    out = []
    try:
        installed_dir = _extensions_dir()
    except Exception:
        installed_dir = None

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
            "available": js.exists(),
            "installed": installed,
        })
    return out


def _find(ext_id: str) -> dict:
    for e in list_extensions():
        if e["id"] == ext_id:
            return e
    raise ValueError(f"Extension inconnue : {ext_id}")


def install(ext_id: str) -> dict:
    e = _find(ext_id)
    ensure_spicetify()  # installe Spicetify a la volee s'il est absent
    src = EXT_DIR / ext_id / e["file"]
    dst = _extensions_dir() / e["file"]
    shutil.copyfile(src, dst)
    _run("config", "extensions", e["file"])
    proc = _run("apply")
    ok = proc.returncode == 0
    return {"ok": ok, "log": (proc.stdout or "").strip()[-1200:]}


def uninstall(ext_id: str) -> dict:
    e = _find(ext_id)
    # Le suffixe '-' retire l'extension de la liste de config Spicetify.
    _run("config", "extensions", f"{e['file']}-")
    dst = _extensions_dir() / e["file"]
    if dst.exists():
        dst.unlink()
    proc = _run("apply")
    ok = proc.returncode == 0
    return {"ok": ok, "log": (proc.stdout or "").strip()[-1200:]}
