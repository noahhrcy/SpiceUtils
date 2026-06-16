"""
SpiceUtils — application de bureau (WebView) qui :
  - heberge le serveur de separation de stems (onglet Serveur : start/stop, logs) ;
  - gere l'installation de nos extensions Spicetify (onglet Extensions) ;
  - permet le demarrage automatique au lancement du PC (onglet Reglages).

Fenetre WebView (HTML/CSS) + icone dans la barre des taches.
"""

import os
import sys
import threading
from pathlib import Path

import webview

import server as server_mod
import settings as settings_mod
import extensions as ext_mod

UI_DIR = Path(__file__).with_name("ui")
ICON_PNG = Path(__file__).with_name("icon.png")
ICON_ICO = Path(__file__).with_name("icon.ico")
GITHUB_URL = ""  # a renseigner plus tard (page du repo)

server = server_mod.ServerController()
window = None
tray_icon = None
_really_quit = False


# --- API exposee au JavaScript (pywebview.api.<methode>) ----------------------

class Api:
    # Serveur
    def get_status(self):
        return server.status()

    def start_server(self):
        return server.start()

    def stop_server(self):
        return server.stop()

    def get_logs(self):
        try:
            return server_mod.LOG_FILE.read_text(encoding="utf-8", errors="replace")[-8000:]
        except OSError:
            return ""

    def open_output(self):
        server_mod.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        os.startfile(str(server_mod.OUTPUT_ROOT))  # noqa: S606 (Windows)
        return {"ok": True}

    # Extensions
    def spicetify_available(self):
        return ext_mod.spicetify_available()

    def list_extensions(self):
        return ext_mod.list_extensions()

    def install_extension(self, ext_id):
        try:
            return ext_mod.install(ext_id)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "log": str(e)}

    def uninstall_extension(self, ext_id):
        try:
            return ext_mod.uninstall(ext_id)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "log": str(e)}

    # Reglages
    def get_settings(self):
        return settings_mod.load()

    def set_autostart_app(self, enabled):
        settings_mod.set_autostart(bool(enabled))
        s = settings_mod.load()
        settings_mod.save(s)
        return s

    def set_autostart_server(self, enabled):
        s = settings_mod.load()
        s["autostart_server"] = bool(enabled)
        settings_mod.save(s)
        return s

    def open_github(self):
        if GITHUB_URL:
            import webbrowser
            webbrowser.open(GITHUB_URL)
            return {"ok": True}
        return {"ok": False, "message": "Lien GitHub bientot disponible."}

    # Fenetre / app
    def hide_window(self):
        if window:
            window.hide()
        return {"ok": True}

    def quit_app(self):
        _quit()
        return {"ok": True}


# --- Icone barre des taches ---------------------------------------------------

def _make_tray_image():
    from PIL import Image, ImageDraw

    # Meme image que l'icone d'application.
    if ICON_PNG.exists():
        try:
            return Image.open(ICON_PNG)
        except OSError:
            pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=14, fill="#241439")
    for x, top in [(12, 30), (24, 16), (36, 10), (48, 22)]:
        d.rounded_rectangle([x, top, x + 8, 54], radius=4, fill="#c08bf0")
    return img


def _start_tray():
    global tray_icon
    import pystray

    def on_open(icon=None, item=None):
        if window:
            window.show()

    tray_icon = pystray.Icon(
        "spiceutils",
        _make_tray_image(),
        "SpiceUtils",
        menu=pystray.Menu(
            pystray.MenuItem("Ouvrir SpiceUtils", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda icon, item: _quit()),
        ),
    )
    threading.Thread(target=tray_icon.run, daemon=True).start()


def _stop_tray():
    global tray_icon
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass
        tray_icon = None


# --- Cycle de vie -------------------------------------------------------------

def _quit():
    global _really_quit
    _really_quit = True
    try:
        server.stop()
    except Exception:
        pass
    _stop_tray()
    if window:
        window.destroy()


def on_closing():
    """Fermeture : si le serveur tourne, on affiche notre modal HTML stylise
    (boutons "Laisser tourner" / "Eteindre") au lieu du dialogue natif."""
    global _really_quit
    if _really_quit:
        return True
    if server.is_running():
        # IMPORTANT : evaluate_js ne doit PAS etre appele depuis le thread GUI
        # (le handler 'closing' s'y execute) sinon la fenetre se fige
        # ("Ne repond pas"). On le delegue a un thread -> l'UI reste reactive.
        threading.Thread(
            target=lambda: window.evaluate_js(
                "window.spiceShowCloseDialog && window.spiceShowCloseDialog()"
            ),
            daemon=True,
        ).start()
        return False  # annule la fermeture native, le modal prend le relais
    _stop_tray()
    return True


def on_start():
    _apply_native_icon()
    _start_tray()
    # Demarrage auto du serveur a l'ouverture, si active dans les reglages.
    try:
        if settings_mod.load().get("autostart_server"):
            server.start()
    except Exception:
        pass


def _set_app_user_model_id():
    """Identite distincte -> la barre des taches utilise NOTRE icone, pas
    celle de pythonw.exe (sinon une fiche Python s'affiche)."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SpiceUtils.App")
    except Exception:
        pass


def _apply_native_icon():
    """Force l'icone de la fenetre (barre des taches) via le backend natif."""
    try:
        if not (window and ICON_ICO.exists()):
            return
        native = getattr(window, "native", None)
        if native is None:
            return
        import clr  # noqa: F401  (pythonnet, fourni par pywebview)
        from System.Drawing import Icon  # type: ignore
        native.Icon = Icon(str(ICON_ICO))
    except Exception:
        pass


def main():
    global window
    _set_app_user_model_id()
    window = webview.create_window(
        "SpiceUtils",
        url=str(UI_DIR / "index.html"),
        js_api=Api(),
        width=940,
        height=680,
        min_size=(760, 560),
        background_color="#150d1f",
    )
    window.events.closing += on_closing
    icon = str(ICON_ICO) if ICON_ICO.exists() else None
    if icon:
        webview.start(on_start, icon=icon)
    else:
        webview.start(on_start)
    os._exit(0)


if __name__ == "__main__":
    main()
