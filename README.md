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
- On click: a small menu with **checkboxes** to pick the stems you want, plus an
  option to **download the full track** (MP3). The choice is remembered.
- **Queue**: multiple tracks run one after another; progress bar in Spotify with
  **% + estimated time left (ETA)** + the list of queued tracks; you can
  **cancel** the running extraction or **remove** a track from the queue (from
  Spotify or from the app).
- **Configurable output folder** (default `Downloads/Stems`).

#### How extraction works (and why it's fast)
- The audio is fetched with yt-dlp in its original format (no WAV re-encode).
- Separation uses **Demucs** in a **persistent worker process**: models stay in
  memory between jobs (no torch import / model reload per track) and are freed
  after 10 min idle. The model is pre-loaded while the audio downloads.
- **1 stem ticked** → the `htdemucs_ft` model *specialised* for that stem
  (≈20 % lighter than a 4-stem pass, and better quality for that stem).
- **2+ stems** → `htdemucs` (one pass gives all 4 sources; only ticked ones are saved).
- Chunk overlap 0.1 instead of 0.25 (≈25 % less compute, no audible difference).
- While a track separates, the **next queued track is already downloading**;
  the full-track MP3 is encoded in parallel with the separation.
- **NVIDIA GPU** detected at install → the CUDA build of torch is installed and
  separation runs on the GPU (≈10× faster); any GPU problem falls back to CPU.
- The separation runs at *below normal* priority, so Spotify playback stays smooth.
- Models are downloaded in the background when the server starts, so the first
  extraction doesn't wait for them.

### Self-healing (no manual fix needed)
- **YouTube changes / HTTP 403**: yt-dlp updates itself daily and immediately
  after a failure, then the download is retried (with alternate YouTube clients
  as a last resort). If the standalone yt-dlp is blocked by an antivirus, a copy
  is installed in the user folder instead.
- **Spotify updates** remove Spicetify (the Extract button disappears and
  Spicetify reports "Spotify version and backup version are mismatched").
  SpiceUtils detects it and re-applies Spicetify + the extensions automatically
  (silently when Spotify is closed; otherwise a notification, a *Repair now*
  button in the Extensions tab and a tray menu entry).
- A corrupted model download is deleted and fetched again; a crashed
  separation is restarted and retried once; an unavailable output folder falls
  back to `Downloads/Stems`.
- Errors are shown in plain words in Spotify (no internet, track not found…).

## Installation

Run **`SpiceUtils-Setup.exe`** (Windows 10 1809+ / 11, 64-bit). It installs,
without winget or MSI (so no "network resource" dialog):
- a **standalone Python** (`{app}\python`) and a static **FFmpeg** (`{app}\ffmpeg`);
- the **WebView2 runtime** if missing (common on Windows 10);
- the Python environment + dependencies (Flask, yt-dlp, Demucs, torch…);
- the application, the shortcuts, then launches SpiceUtils.

Requirement: an Internet connection (components are downloaded).

With an NVIDIA GPU (driver 452+, 3 GB+ VRAM) the installer also fetches the
CUDA build of torch (~2.5 GB download).

On first server start, SpiceUtils also fetches the standalone **yt-dlp** and
**Deno** (JS runtime YouTube now requires) into `%LOCALAPPDATA%\SpiceUtils\bin`,
plus the separation models.

Then, in the app: **Extensions** tab → install **Stem Extractor** (Spicetify is
installed automatically if missing). The server starts with the app (Settings),
and the button appears in Spotify.

Note: Spicetify does not support the Microsoft Store version of Spotify; the app
tells you if that's the one installed.

## Updates

Automatic on launch (toggle in Settings), or via **Settings → Check for
updates**. Spotify updates are handled automatically (see *Self-healing*).

## Uninstall

Windows Settings → Apps → SpiceUtils → Uninstall (stops the app, removes
auto-start, deletes the venv, the bundled Python and FFmpeg, and the downloaded
yt-dlp/Deno).

## Development

```
app/
  main.py          WebView app (JS bridge, tray, lifecycle, updates)
  server.py        Flask server + queue + download tools (yt-dlp/Deno, self-repair)
  sep_worker.py    persistent Demucs worker (GPU/CPU, specialist models)
  extensions.py    extension manager (spicetify CLI, auto-install, updates, Spotify re-patch)
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
