# Compile SpiceUtils.iss en setup.exe. Installe Inno Setup via winget si absent.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-ISCC {
    $cands = @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$iscc = Find-ISCC
if (-not $iscc) {
    Write-Host "Inno Setup absent - installation via winget..." -ForegroundColor Yellow
    winget install --id JRSoftware.InnoSetup -e --source winget `
        --accept-package-agreements --accept-source-agreements
    $iscc = Find-ISCC
    if (-not $iscc) { throw "ISCC.exe introuvable apres installation d'Inno Setup." }
}

Write-Host "Compilation avec $iscc ..." -ForegroundColor Cyan
& $iscc (Join-Path $here "SpiceUtils.iss")
Write-Host "OK -> $here\Output\SpiceUtils-Setup.exe" -ForegroundColor Green
