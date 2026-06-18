"""
Mise a jour automatique de SpiceUtils via les releases GitHub.

Compare APP_VERSION a la derniere release ; si plus recente, telecharge le
SpiceUtils-Setup.exe joint et le lance (l'installeur gere l'elevation + la mise
a jour), puis l'app se ferme.
"""

import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

APP_VERSION = "1.1.6"
REPO = "noahhrcy/SpiceUtils"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _ver_tuple(s):
    s = (s or "").lstrip("vV").strip()
    parts = []
    for p in s.split("."):
        num = "".join(c for c in p if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def get_latest():
    """Renvoie (tag, setup_url) de la derniere release, ou (None, None)."""
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "SpiceUtils",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = data.get("tag_name")
    setup_url = None
    for a in data.get("assets", []):
        if a.get("name", "").lower().endswith(".exe"):
            setup_url = a.get("browser_download_url")
            break
    return tag, setup_url


def update_available():
    """(disponible: bool, tag: str|None)."""
    try:
        tag, setup_url = get_latest()
    except Exception:
        return False, None
    if tag and setup_url and _ver_tuple(tag) > _ver_tuple(APP_VERSION):
        return True, tag
    return False, None


def download_and_run() -> bool:
    """Telecharge l'installeur de la derniere release et le lance. True si lance."""
    try:
        tag, setup_url = get_latest()
        if not setup_url or _ver_tuple(tag) <= _ver_tuple(APP_VERSION):
            return False
        dst = Path(tempfile.gettempdir()) / "SpiceUtils-Setup-update.exe"
        req = urllib.request.Request(setup_url, headers={"User-Agent": "SpiceUtils"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
            f.write(r.read())
        # /SILENT : barre de progression visible, peu d'interaction. L'exe a un
        # manifeste admin -> Windows demande l'elevation (UAC).
        subprocess.Popen([str(dst), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                         creationflags=NO_WINDOW)
        return True
    except Exception:
        return False
