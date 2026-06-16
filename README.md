# SpiceUtils

Application de bureau (WebView, thème sombre violet/mauve) qui sert de **hub
d'extensions Spicetify** et héberge le **serveur de séparation de stems**.

## Fonctionnalités

- **Onglet Serveur** : démarrer/arrêter le serveur local (Demucs), voir le statut,
  le port, le dossier de sortie et le journal en direct.
- **Onglet Extensions** : installer/désinstaller nos extensions Spicetify en un
  clic (embarquées dans l'app). Inclut **Stem Extractor**.
- **Onglet Réglages** : lancer SpiceUtils au démarrage du PC (registre `HKCU\Run`,
  pas de tâche planifiée) ; démarrer le serveur à l'ouverture de l'app.
- **Fermeture** : si le serveur tourne, choix entre *le laisser actif en
  arrière-plan* (icône barre des tâches) ou *arrêter & quitter*.

## Installation

Lancer **`SpiceUtils-Setup.exe`** (admin). Il installe automatiquement :
Python + FFmpeg (via winget), l'environnement Python + dépendances, l'application,
les raccourcis, et propose de lancer SpiceUtils. Prérequis : `winget` (Windows 11).

Ensuite : ouvrir SpiceUtils → onglet **Extensions** → **Installer** Stem Extractor →
onglet **Serveur** → **Démarrer**. Dans Spotify, le bouton « Extraire les stems »
apparaît (barre de lecture + clic droit).

## Construire le setup.exe

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

## Structure

```
app/
  main.py          app WebView (pont JS, tray, cycle de vie)
  server.py        serveur Flask + ServerController (start/stop) + pipeline stems
  extensions.py    gestionnaire d'extensions (CLI spicetify)
  settings.py      réglages JSON + autostart registre
  ui/              interface HTML/CSS/JS (thème sombre violet)
  extensions/      extensions embarquées (manifest.json + .js)
installer/         Inno Setup (.iss) + post/pre-install + build
```

## Désinstallation

Paramètres Windows → Applications → SpiceUtils → Désinstaller (arrête l'app,
retire l'autostart et le venv ; Python/FFmpeg/Spicetify sont conservés).
