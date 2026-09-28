"""
SpiceUtils — application de bureau (WebView) qui :
  - heberge le serveur de separation de stems (onglet Serveur : start/stop, logs) ;
  - gere l'installation de nos extensions Spicetify (onglet Extensions) ;
  - permet le demarrage automatique au lancement du PC (onglet Reglages).

Fenetre WebView (HTML/CSS) + icone dans la barre des taches.
"""

import os
import threading
import time
from pathlib import Path

import webview

import server as server_mod
import settings as settings_mod
import extensions as ext_mod
import updater as updater_mod

UI_DIR = Path(__file__).with_name("ui")
ICON_PNG = Path(__file__).with_name("icon.png")
ICON_ICO = Path(__file__).with_name("icon.ico")
GITHUB_URL = "https://github.com/noahhrcy/SpiceUtils"

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
        # Read only the tail (the log file can grow large).
        try:
            with open(server_mod.LOG_FILE, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 12000))
                return f.read().decode("utf-8", errors="replace")[-8000:]
        except OSError:
            return ""

    def get_queue(self):
        return server_mod.queue_snapshot()

    def cancel_job(self, job_id):
        return server_mod.cancel(job_id)

    # Options d'extraction (Stem Extractor)
    def get_extract_config(self):
        return server_mod.get_config()

    def pick_output_dir(self):
        """Ouvre un selecteur de dossier ; enregistre le choix."""
        try:
            dirs = window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:
            dirs = None
        if dirs:
            path = dirs[0] if isinstance(dirs, (list, tuple)) else dirs
            return server_mod.set_config(output_dir=str(path))
        return server_mod.get_config()

    def open_output(self):
        try:
            os.startfile(str(server_mod.output_root()))  # noqa: S606 (Windows)
        except Exception:
            return {"ok": False}
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

    def check_extension_update(self, ext_id):
        try:
            return ext_mod.check_update(ext_id)
        except Exception as e:  # noqa: BLE001
            return {"update": False, "error": str(e)}

    def update_extension(self, ext_id):
        try:
            return ext_mod.update_extension(ext_id)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "log": str(e)}

    def get_repair_status(self):
        try:
            return ext_mod.repair_status()
        except Exception:  # noqa: BLE001
            return {"needs_repair": False}

    def repair_spicetify(self):
        return _repair(restart=True)

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

    # Mises a jour
    def get_app_version(self):
        return updater_mod.APP_VERSION

    def set_auto_update(self, enabled):
        s = settings_mod.load()
        s["auto_update"] = bool(enabled)
        settings_mod.save(s)
        return s

    def check_update_now(self):
        avail, tag = updater_mod.update_available()
        if avail and updater_mod.download_and_run():
            threading.Timer(1.5, _quit).start()
        return {"available": avail, "tag": tag, "current": updater_mod.APP_VERSION}

    def open_github(self):
        if GITHUB_URL:
            import webbrowser
            webbrowser.open(GITHUB_URL)
            return {"ok": True}
        return {"ok": False, "message": "GitHub link coming soon."}

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

    def on_repair(icon=None, item=None):
        threading.Thread(target=_repair, kwargs={"restart": True}, daemon=True).start()

    tray_icon = pystray.Icon(
        "spiceutils",
        _make_tray_image(),
        "SpiceUtils",
        menu=pystray.Menu(
            pystray.MenuItem("Open SpiceUtils", on_open, default=True),
            pystray.MenuItem("Repair Spicetify (restarts Spotify)", on_repair,
                             visible=lambda item: _REPAIR["needed"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: _quit()),
        ),
    )
    threading.Thread(target=tray_icon.run, daemon=True).start()


def _notify(title, msg):
    try:
        if tray_icon:
            tray_icon.notify(msg, title)
    except Exception:  # noqa: BLE001
        pass


def _js(code):
    try:
        if window:
            window.evaluate_js(code)
    except Exception:  # noqa: BLE001
        pass


# --- Spicetify watchdog -------------------------------------------------------
# A Spotify update silently removes Spicetify (and our extensions). We re-patch
# automatically: silently while Spotify is closed, otherwise we notify the user
# (tray + banner) and fix it as soon as Spotify is closed.

_REPAIR = {"needed": False, "lock": threading.Lock(), "notified": None, "failed": {}}


def _set_repair_needed(v):
    if _REPAIR["needed"] != v:
        _REPAIR["needed"] = v
        try:
            if tray_icon:
                tray_icon.update_menu()
        except Exception:  # noqa: BLE001
            pass
        _js(f"window.spiceRepairState && window.spiceRepairState({str(v).lower()})")


def _repair(restart=True):
    if not _REPAIR["lock"].acquire(blocking=False):
        return {"ok": False, "log": "A repair is already running."}
    try:
        server_mod.log("Spicetify: re-applying after a Spotify update...")
        r = ext_mod.repair(restart=restart)
        if r["ok"]:
            server_mod.log("Spicetify: repaired ✓ (extensions are back in Spotify)")
            _set_repair_needed(False)
        else:
            last = (r.get("log") or "").strip().splitlines()[-1:] or [""]
            server_mod.log(f"Spicetify repair failed: {last[0][:200]}")
        return r
    except Exception as e:  # noqa: BLE001
        server_mod.log(f"Spicetify repair failed: {e}")
        return {"ok": False, "log": str(e)}
    finally:
        _REPAIR["lock"].release()


def _spicetify_watchdog():
    time.sleep(5)
    while True:
        try:
            st = ext_mod.repair_status()
            _set_repair_needed(bool(st.get("needs_repair")))
            stamp = st.get("stamp")
            failed_at = _REPAIR["failed"].get(stamp, 0)
            if st.get("needs_repair") and st.get("auto") and time.time() - failed_at > 1800:
                if not st.get("running"):
                    if not _repair(restart=False)["ok"]:
                        _REPAIR["failed"][stamp] = time.time()   # back off 30 min
                elif _REPAIR["notified"] != stamp:
                    _REPAIR["notified"] = stamp
                    _notify("Spotify was updated",
                            "Spicetify will be re-applied when Spotify closes. "
                            "Or right-click the SpiceUtils tray icon > Repair Spicetify.")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(60)


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


def _auto_update_check():
    try:
        if not settings_mod.load().get("auto_update"):
            return
        avail, tag = updater_mod.update_available()
        if avail:
            if window:
                window.evaluate_js(
                    "window.spiceToast && window.spiceToast('Updating to " + str(tag) + "...')")
            if updater_mod.download_and_run():
                _quit()
    except Exception:
        pass


def on_start():
    _apply_native_icon()
    _start_tray()
    threading.Thread(target=_auto_update_check, daemon=True).start()
    threading.Thread(target=_spicetify_watchdog, daemon=True).start()
    # Demarrage auto du serveur a l'ouverture, si active dans les reglages.
    try:
        if settings_mod.load().get("autostart_server"):
            server.start()
    except Exception:
        pass


_instance_mutex = None  # garde une reference (sinon GC -> mutex libere)


def acquire_single_instance() -> bool:
    """Empeche deux instances de SpiceUtils (sinon conflit sur le port 8765)."""
    global _instance_mutex
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        k = ctypes.windll.kernel32
        _instance_mutex = k.CreateMutexW(None, False, "Global\\SpiceUtilsApp")
        return k.GetLastError() != ERROR_ALREADY_EXISTS
    except Exception:
        return True


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
    if not acquire_single_instance():
        # Une instance tourne deja : on ne lance pas de doublon.
        return
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
