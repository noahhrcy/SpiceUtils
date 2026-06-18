# SpiceUtils

Application de bureau (Windows 10/11) qui sert de **hub d'extensions Spicetify**
et héberge un **serveur local de séparation de stems**. Interface WebView au
thème sombre violet/mauve, icône dans la barre des tâches.

## Fonctionnalités

### Application
- **Accueil** : logo + accès rapide aux extensions et au dépôt GitHub.
- **Onglet Extensions** : installe/désinstalle nos extensions Spicetify en un
  clic (installe Spicetify automatiquement s'il est absent).
- **Onglet Serveur** : démarrer/arrêter le serveur, statut, version, dossier de
  sortie, **file d'attente** (annulation/retrait des extractions) et **journal**
  en direct.
- **Onglet Réglages** : lancer SpiceUtils au démarrage de Windows, démarrer le
  serveur à l'ouverture, **mises à jour automatiques** + bouton « Vérifier ».
- **Fermeture** : si le serveur tourne, choix entre *laisser tourner en
  arrière-plan* (barre des tâches) ou *arrêter et quitter*.
- **Mise à jour automatique** via les *releases* GitHub : l'app télécharge et
  installe la nouvelle version, puis se relance.
- Instance unique (mutex) ; icône d'app personnalisée.

### Extension : Stem Extractor
- Bouton dans Spotify (barre de lecture + clic droit) qui sépare les stems
  (voix / batterie / basse / autres) avec **Demucs**.
- Au clic : choix **Extraction Rapide** (htdemucs) ou **Extraction Qualité**
  (htdemucs_ft, plus lent mais meilleur).
- **File d'attente** : plusieurs morceaux s'enchaînent ; barre de progression
  dans Spotify avec **% + temps restant estimé (ETA)** + liste des morceaux en
  attente ; possibilité d'**annuler** l'extraction en cours ou de **retirer** un
  morceau de la file (depuis Spotify ou depuis l'app).
- **Dossier de sortie configurable** (par défaut `Téléchargements/Stems`).

## Installation

Lancer **`SpiceUtils-Setup.exe`** (Windows 10 1809+ / 11, 64-bit). Il installe,
sans winget ni MSI (donc sans dialogue « ressource réseau ») :
- un **Python autonome** (`{app}\python`) et **FFmpeg** statique (`{app}\ffmpeg`) ;
- le **runtime WebView2** s'il manque (fréquent sur Windows 10) ;
- l'environnement Python + dépendances (Flask, yt-dlp, Demucs, torch…) ;
- l'application, les raccourcis, puis lance SpiceUtils.

Prérequis : une connexion Internet (les composants sont téléchargés).

Ensuite, dans l'app : onglet **Extensions** → installer **Stem Extractor**
(Spicetify est installé automatiquement si absent) → onglet **Serveur** →
**Démarrer**. Le bouton apparaît alors dans Spotify.

## Mise à jour

Automatique au lancement (réglage activable/désactivable), ou via
**Réglages → Vérifier les mises à jour**. À noter : une mise à jour de
**Spicetify** n'impacte pas le serveur ; seules les extensions peuvent nécessiter
une réinstallation (gérée par l'app).

## Désinstallation

Paramètres Windows → Applications → SpiceUtils → Désinstaller (arrête l'app,
retire l'autostart, supprime le venv, Python et FFmpeg embarqués).

## Développement

```
app/
  main.py          app WebView (pont JS, tray, cycle de vie, mises à jour)
  server.py        serveur Flask + file d'attente + pipeline stems (Demucs)
  extensions.py    gestionnaire d'extensions (CLI spicetify, auto-install)
  settings.py      réglages JSON + autostart (registre)
  updater.py       mise à jour via releases GitHub
  ui/              interface HTML/CSS/JS (thème sombre violet)
  extensions/      extensions embarquées (manifest.json + .js)
installer/         Inno Setup (.iss) + post/pre-install + build + images
```

Construire l'installeur :

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```
