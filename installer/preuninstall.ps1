# Nettoyage avant desinstallation : arrete SpiceUtils (et son serveur) +
# retire l'entree de demarrage automatique du registre.
$ErrorActionPreference = "SilentlyContinue"

# Stoppe les process pythonw qui executent SpiceUtils.
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*SpiceUtils*main.py*" -or $_.CommandLine -like "*SpiceUtils*server.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Retire l'autostart (HKCU\...\Run\SpiceUtils).
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "SpiceUtils" -ErrorAction SilentlyContinue
