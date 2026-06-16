"""
Reglages SpiceUtils (persistes en JSON) + gestion du demarrage automatique.

- settings.json dans %LOCALAPPDATA%\\SpiceUtils
- autostart de l'app au lancement du PC via la cle de registre HKCU\\...\\Run
  (pas de tache planifiee, conformement au choix utilisateur).
"""

import json
import os
import sys
from pathlib import Path

APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SpiceUtils"
SETTINGS_FILE = APP_DATA / "settings.json"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SpiceUtils"

DEFAULTS = {
    "autostart_app": False,      # lancer SpiceUtils au demarrage du PC
    "autostart_server": False,   # demarrer le serveur a l'ouverture de l'app
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    # L'etat reel de l'autostart est la verite du registre.
    data["autostart_app"] = _autostart_is_enabled()
    return data


def save(data: dict):
    APP_DATA.mkdir(parents=True, exist_ok=True)
    keep = {k: data.get(k, v) for k, v in DEFAULTS.items()}
    SETTINGS_FILE.write_text(json.dumps(keep, indent=2), encoding="utf-8")


def _launch_command() -> str:
    """Commande lancee au demarrage : pythonw.exe main.py (sans console)."""
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else py)
    main_py = str(Path(__file__).with_name("main.py"))
    return f'"{exe}" "{main_py}"'


def _autostart_is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool):
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except OSError:
                pass
