# ============================================================================
#  SpiceUtils - post-install (appele par setup.exe / Inno Setup)
#
#  Installe Python + FFmpeg (winget) si absents, cree le venv + dependances.
#  PAS de tache planifiee : le demarrage auto est gere DANS l'app (registre Run).
#
#  Usage : postinstall.ps1 -AppDir "C:\Program Files\SpiceUtils"
# ============================================================================

param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = "Stop"
$Src = Join-Path $AppDir "app"

# Journalise toute l'installation dans un fichier (pour diagnostiquer les echecs
# meme apres fermeture de la console).
$LogDir = Join-Path $env:LOCALAPPDATA "SpiceUtils"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "install.log"
try { Start-Transcript -Path $LogFile -Force | Out-Null } catch {}

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    [!] $m"  -ForegroundColor Yellow }

function Have($cmd) { $null = Get-Command $cmd -ErrorAction SilentlyContinue; return $? }

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}

function Resolve-RealPython {
    foreach ($c in (Get-Command python, python3 -ErrorAction SilentlyContinue)) {
        $p = $c.Source
        if ($p -and ($p -notlike "*WindowsApps*")) {
            try { & $p --version *> $null; if ($?) { return $p } } catch {}
        }
    }
    $cands = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "C:\Python3*\python.exe"
    )
    foreach ($glob in $cands) {
        $hit = Get-ChildItem $glob -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

Write-Host "==================================================" -ForegroundColor Magenta
Write-Host "  SpiceUtils - installation des dependances" -ForegroundColor Magenta
Write-Host "  Cette fenetre se fermera automatiquement a la fin." -ForegroundColor Magenta
Write-Host "  L'installation de torch/demucs peut prendre plusieurs minutes." -ForegroundColor Magenta
Write-Host "==================================================" -ForegroundColor Magenta

if (-not (Have winget)) {
    throw "winget introuvable. Installe 'App Installer' (Microsoft Store) puis relance setup.exe."
}

# --- Python ---
Step "Python"
$Python = Resolve-RealPython
if (-not $Python) {
    Warn "Installation de Python via winget..."
    winget install --id Python.Python.3.12 -e --source winget `
        --accept-package-agreements --accept-source-agreements --silent
    Refresh-Path
    $Python = Resolve-RealPython
    if (-not $Python) {
        # winget peut croire Python deja installe (registration residuelle) alors
        # que les fichiers manquent : on force une vraie reinstallation.
        Warn "Python toujours absent - reinstallation forcee (--force)..."
        winget install --id Python.Python.3.12 -e --source winget `
            --accept-package-agreements --accept-source-agreements --silent --force
        Refresh-Path
        $Python = Resolve-RealPython
    }
    if (-not $Python) { throw "Python introuvable apres installation." }
}
Ok "Python : $Python"

# --- FFmpeg ---
Step "FFmpeg"
if (-not (Have ffmpeg)) {
    Warn "Installation de FFmpeg via winget..."
    winget install --id Gyan.FFmpeg -e --source winget `
        --accept-package-agreements --accept-source-agreements --silent
    Refresh-Path
}
if (Have ffmpeg) { Ok "FFmpeg present" } else { Warn "FFmpeg pas encore dans le PATH (OK apres reconnexion)." }

# --- venv + dependances ---
Step "Environnement Python + dependances (plusieurs minutes)"
$Venv       = Join-Path $Src ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Req        = Join-Path $Src "requirements.txt"
if (-not (Test-Path $VenvPython)) { & $Python -m venv $Venv }
& $VenvPython -m pip install --upgrade pip --retries 5 --timeout 60 --quiet

# Telechargements volumineux (torch ~200 Mo) : on tolere les coupures reseau
# avec des retries pip + plusieurs tentatives globales.
$ok = $false
for ($try = 1; $try -le 3; $try++) {
    Write-Host "    Installation des paquets (tentative $try/3)..." -ForegroundColor Cyan
    & $VenvPython -m pip install -r $Req --retries 5 --timeout 120
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Warn "Echec (reseau ?). Nouvelle tentative dans 8 s..."
    Start-Sleep -Seconds 8
}
if (-not $ok) {
    throw "Echec du telechargement des dependances apres 3 tentatives. Verifiez la connexion Internet (acces a pypi.org / files.pythonhosted.org) puis relancez l'installateur. Details : $LogFile"
}
Ok "Dependances installees"

Write-Host "`n=== SpiceUtils pret. ===" -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch {}
