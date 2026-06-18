# SpiceUtils

Desktop application (Windows 10/11) that acts as a **Spicetify extensions hub**
and hosts a **local stem-separation server**. WebView UI with a dark
purple/mauve theme and a system tray icon.

## Features

### Application
- **Home**: logo + quick access to extensions and the GitHub repo.
- **Extensions tab**: install/uninstall our Spicetify extensions in one click
  (Spicetify is installed automatically if missing).
- **Server tab**: start/stop the server, status, version, output folder,
  **queue** (cancel/remove extractions) and a live **log**.
- **Settings tab**: launch SpiceUtils on Windows startup, start the server when
  the app opens, **automatic updates** + a "Check" button.
- **On close**: if the server is running, choose between *keep running in the
  background* (system tray) or *stop and quit*.
- **Auto-update** via GitHub releases: the app downloads and installs the new
  version, then relaunches.
- Single instance (mutex); custom app icon.

### Extension: Stem Extractor
- Button in Spotify (playbar + right-click) that separates stems
  (vocals / drums / bass / other) using **Demucs**.
- On click: choose **Fast extraction** (htdemucs) or **Quality extraction**
  (htdemucs_ft, slower but better).
- **Queue**: multiple tracks run one after another; progress bar in Spotify with
  **% + estimated time left (ETA)** + the list of queued tracks; you can
  **cancel** the running extraction or **remove** a track from the queue (from
  Spotify or from the app).
- **Configurable output folder** (default `Downloads/Stems`).

## Installation

Run **`SpiceUtils-Setup.exe`** (Windows 10 1809+ / 11, 64-bit). It installs,
without winget or MSI (so no "network resource" dialog):
- a **standalone Python** (`{app}\python`) and a static **FFmpeg** (`{app}\ffmpeg`);
- the **WebView2 runtime** if missing (common on Windows 10);
- the Python environment + dependencies (Flask, yt-dlp, Demucs, torch…);
- the application, the shortcuts, then launches SpiceUtils.

Requirement: an Internet connection (components are downloaded).

Then, in the app: **Extensions** tab → install **Stem Extractor** (Spicetify is
installed automatically if missing) → **Server** tab → **Start**. The button
then appears in Spotify.

## Updates

Automatic on launch (toggle in Settings), or via **Settings → Check for
updates**. Note: a **Spicetify** update does not affect the server; only the
extensions may need a reinstall (handled by the app).

## Uninstall

Windows Settings → Apps → SpiceUtils → Uninstall (stops the app, removes
auto-start, deletes the venv, the bundled Python and FFmpeg).

## Development

```
app/
  main.py          WebView app (JS bridge, tray, lifecycle, updates)
  server.py        Flask server + queue + stems pipeline (Demucs)
  extensions.py    extension manager (spicetify CLI, auto-install, updates)
  settings.py      JSON settings + auto-start (registry)
  updater.py       update via GitHub releases
  ui/              HTML/CSS/JS interface (dark purple theme)
  extensions/      bundled extensions (manifest.json + .js)
installer/         Inno Setup (.iss) + post/pre-install + build + images
```

Build the installer:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```
