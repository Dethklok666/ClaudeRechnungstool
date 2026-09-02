# Einmaliges Setup für das Whatnot Rechnungstool auf einem neuen Windows-Rechner.
# Installiert bei Bedarf Python und Google Chrome, legt eine virtuelle
# Umgebung an und installiert die Python-Abhängigkeiten. Danach: login_setup.bat
# einmalig ausführen, anschließend start.bat zum Starten der App.

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step($text) {
    Write-Host ""
    Write-Host "== $text ==" -ForegroundColor Cyan
}

function Find-RealPython {
    # python.exe ohne echte Installation zeigt unter Windows 10/11 auf einen
    # Microsoft-Store-Alias-Stub, der keine funktionierende Installation ist.
    # Deshalb gezielt nach echten Installationen suchen statt "python --version"
    # zu vertrauen.
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $found = Get-Command python.exe -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch "WindowsApps" } |
        Select-Object -First 1
    if ($found) { return $found.Source }
    return $null
}

function Find-Chrome {
    $candidates = @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

Write-Host "Whatnot Rechnungstool - Setup" -ForegroundColor Green
Write-Host "Projektordner: $projectDir"

$wingetCmd = Get-Command winget -ErrorAction SilentlyContinue

# --- Python ---
Write-Step "Pruefe Python"
$pythonExe = Find-RealPython
if (-not $pythonExe) {
    Write-Host "Python nicht gefunden, installiere Python 3.12 ..." -ForegroundColor Yellow
    if ($wingetCmd) {
        winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements -e
    } else {
        Write-Host "winget nicht verfuegbar, lade Python-Installer direkt herunter ..." -ForegroundColor Yellow
        $installerPath = Join-Path $env:TEMP "python-installer.exe"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $installerPath
        Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1" -Wait
        Remove-Item $installerPath -ErrorAction SilentlyContinue
    }
    $pythonExe = Find-RealPython
    if (-not $pythonExe) {
        throw "Python-Installation fehlgeschlagen. Bitte manuell installieren: https://www.python.org/downloads/ und dieses Skript erneut ausfuehren."
    }
    Write-Host "Python installiert: $pythonExe" -ForegroundColor Green
} else {
    Write-Host "Python gefunden: $pythonExe" -ForegroundColor Green
}

# --- Chrome ---
Write-Step "Pruefe Google Chrome"
$chromeExe = Find-Chrome
if (-not $chromeExe) {
    Write-Host "Chrome nicht gefunden, installiere ..." -ForegroundColor Yellow
    if ($wingetCmd) {
        winget install --id Google.Chrome --source winget --accept-package-agreements --accept-source-agreements -e
    } else {
        Write-Host "winget nicht verfuegbar. Bitte Chrome manuell installieren: https://www.google.com/chrome/" -ForegroundColor Red
    }
    $chromeExe = Find-Chrome
    if (-not $chromeExe) {
        Write-Host "Chrome wurde nicht gefunden. Bitte manuell installieren, bevor die App gestartet wird." -ForegroundColor Red
    } else {
        Write-Host "Chrome installiert: $chromeExe" -ForegroundColor Green
    }
} else {
    Write-Host "Chrome gefunden: $chromeExe" -ForegroundColor Green
}

# --- Virtuelle Umgebung ---
Write-Step "Virtuelle Umgebung"
$venvDir = Join-Path $projectDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Erstelle virtuelle Umgebung ..." -ForegroundColor Yellow
    & $pythonExe -m venv $venvDir
} else {
    Write-Host "Virtuelle Umgebung existiert bereits." -ForegroundColor Green
}

# --- Abhaengigkeiten ---
Write-Step "Installiere Python-Abhaengigkeiten"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $projectDir "requirements.txt")

Write-Step "Fertig"
Write-Host "Naechste Schritte:" -ForegroundColor Green
Write-Host "  1. login_setup.bat doppelklicken und einmalig bei Whatnot einloggen."
Write-Host "  2. start.bat doppelklicken, um das Tool zu starten."
