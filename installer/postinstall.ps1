# ============================================================================
#  SpiceUtils - post-install (appele par setup.exe / Inno Setup)
#
#  Installation AUTONOME par poste, sans winget ni MSI (donc jamais de dialogue
#  "ressource reseau") :
#    - Python autonome (python-build-standalone) extrait dans {app}\python
#    - FFmpeg statique extrait dans {app}\ffmpeg
#    - venv + dependances (pip, avec retries reseau)
#
#  Tout est journalise dans %LOCALAPPDATA%\SpiceUtils\install.log
#
#  Usage : postinstall.ps1 -AppDir "C:\Program Files\SpiceUtils"
# ============================================================================

param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Src   = Join-Path $AppDir "app"
$PyDir = Join-Path $AppDir "python"
$FfDir = Join-Path $AppDir "ffmpeg"
$Tmp   = Join-Path $env:TEMP ("spiceutils_" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

$LogDir = Join-Path $env:LOCALAPPDATA "SpiceUtils"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
try { Start-Transcript -Path (Join-Path $LogDir "install.log") -Force | Out-Null } catch {}

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    [ok] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    [!] $m"  -ForegroundColor Yellow }

# Telechargement robuste via curl (suit les redirections, retries reseau).
function Download($url, $out) {
    Write-Host "    telechargement: $url"
    curl.exe -L --retry 5 --retry-delay 3 --connect-timeout 30 --fail -o $out $url
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $out)) {
        throw "Echec du telechargement (reseau ?) : $url"
    }
}

Write-Host "==================================================" -ForegroundColor Magenta
Write-Host "  SpiceUtils - installation (autonome, sans winget)" -ForegroundColor Magenta
Write-Host "  Cette fenetre se fermera automatiquement a la fin." -ForegroundColor Magenta
Write-Host "==================================================" -ForegroundColor Magenta

# --- 1) Python autonome ------------------------------------------------------
Step "Python autonome"
$PyExe = Join-Path $PyDir "python.exe"
if (-not (Test-Path $PyExe)) {
    # URL via l'API GitHub (derniere 3.12 install_only), repli sur une URL fixe.
    $url = $null
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" `
            -Headers @{ "User-Agent" = "spiceutils" } -TimeoutSec 30
        $asset = $rel.assets | Where-Object {
            $_.name -match '^cpython-3\.12\.\d+\+.*-x86_64-pc-windows-msvc-install_only\.tar\.gz$'
        } | Select-Object -First 1
        if ($asset) { $url = $asset.browser_download_url }
    } catch { Warn "API GitHub indisponible, URL de repli." }
    if (-not $url) {
        $url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260610/cpython-3.12.13%2B20260610-x86_64-pc-windows-msvc-install_only.tar.gz"
    }
    $arc = Join-Path $Tmp "python.tar.gz"
    Download $url $arc
    # L'archive "install_only" se decompresse en un dossier "python/".
    tar.exe -xf $arc -C $AppDir
    if (-not (Test-Path $PyExe)) { throw "Python autonome introuvable apres extraction." }
}
& $PyExe --version
Ok "Python : $PyExe"

# --- 2) FFmpeg statique ------------------------------------------------------
Step "FFmpeg"
$FfExe = Join-Path $FfDir "bin\ffmpeg.exe"
if (-not (Test-Path $FfExe)) {
    $zip = Join-Path $Tmp "ffmpeg.zip"
    Download "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $zip
    Expand-Archive -Path $zip -DestinationPath $Tmp -Force
    $inner = Get-ChildItem $Tmp -Directory | Where-Object { $_.Name -like "ffmpeg-*win64*" } | Select-Object -First 1
    if (-not $inner) { throw "Dossier FFmpeg introuvable apres extraction." }
    $dstBin = Join-Path $FfDir "bin"
    New-Item -ItemType Directory -Force -Path $dstBin | Out-Null
    Copy-Item (Join-Path $inner.FullName "bin\*") -Destination $dstBin -Recurse -Force
    if (-not (Test-Path $FfExe)) { throw "ffmpeg.exe introuvable apres extraction." }
}
Ok "FFmpeg : $FfExe"

# --- 3) venv + dependances ---------------------------------------------------
Step "Environnement Python + dependances (plusieurs minutes)"
$Venv       = Join-Path $Src ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Req        = Join-Path $Src "requirements.txt"
if (-not (Test-Path $VenvPython)) { & $PyExe -m venv $Venv }
& $VenvPython -m pip install --upgrade pip --retries 5 --timeout 60 --quiet

# Telechargements volumineux (torch ~200 Mo) : on tolere les coupures reseau.
$ok = $false
for ($try = 1; $try -le 3; $try++) {
    Write-Host "    Installation des paquets (tentative $try/3)..." -ForegroundColor Cyan
    & $VenvPython -m pip install -r $Req --retries 5 --timeout 120
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Warn "Echec (reseau ?). Nouvelle tentative dans 8 s..."
    Start-Sleep -Seconds 8
}
if (-not $ok) {
    throw "Echec du telechargement des dependances apres 3 tentatives. Verifiez la connexion (acces a pypi.org / files.pythonhosted.org) puis relancez l'installateur."
}
Ok "Dependances installees"

Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "`n=== SpiceUtils pret. ===" -ForegroundColor Green
try { Stop-Transcript | Out-Null } catch {}
