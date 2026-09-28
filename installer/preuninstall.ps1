# Cleanup before uninstall: stop SpiceUtils (app, server, separation worker,
# downloaders), remove the auto-start entry and the tools it downloaded.
$ErrorActionPreference = "SilentlyContinue"

# Every process running from the SpiceUtils folders (venv python, bundled
# python, yt-dlp/deno in %LOCALAPPDATA%\SpiceUtils\bin).
$appDir = Split-Path -Parent $PSScriptRoot
$data = Join-Path $env:LOCALAPPDATA "SpiceUtils"
Get-CimInstance Win32_Process |
    Where-Object { $_.ExecutablePath -like "$appDir\*" -or $_.ExecutablePath -like "$data\*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Remove auto-start (HKCU\...\Run\SpiceUtils).
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "SpiceUtils" -ErrorAction SilentlyContinue

# Downloaded tools (yt-dlp, Deno, fallback packages). Settings/logs are kept.
Remove-Item (Join-Path $data "bin")   -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $data "pylib") -Recurse -Force -ErrorAction SilentlyContinue
