# Lance ODACEA en développement : backend Python (FastAPI) + front Next, ensemble.
#
#   Backend  : http://127.0.0.1:8000   (backend/, uvicorn --reload)
#   Front    : http://localhost:9000   (web/, next dev)  ← ouvrez celui-ci
#
# Le front proxifie le backend via /api/py/* (même origine). Le backend s'ouvre
# dans une fenêtre dédiée (ses logs y restent visibles) ; le front tourne dans
# cette fenêtre-ci. Ctrl+C ici arrête le front PUIS le backend.
#
# Usage :  powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
#   ou, si les scripts sont autorisés :  .\start-dev.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Port du backend ; le front lit ODACEA_API_URL pour proxifier (défaut 8000).
$BackendPort = 8000
$env:ODACEA_API_URL = "http://127.0.0.1:$BackendPort"

# ── Vérifications légères ────────────────────────────────────────────────────
foreach ($cmd in @("python", "npm")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "✗ '$cmd' introuvable dans le PATH." -ForegroundColor Red
        exit 1
    }
}
if (-not (Test-Path (Join-Path $root "web\node_modules"))) {
    Write-Host "ℹ  web/node_modules absent — lancez 'npm install' dans web/ d'abord." -ForegroundColor Yellow
}

# ── Backend (fenêtre dédiée) ─────────────────────────────────────────────────
Write-Host "▶ Backend FastAPI sur http://127.0.0.1:$BackendPort …" -ForegroundColor Cyan
$backend = Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "api.main:app", "--port", "$BackendPort", "--reload" `
    -WorkingDirectory (Join-Path $root "backend") `
    -PassThru

try {
    # ── Front (fenêtre courante) ─────────────────────────────────────────────
    Write-Host "▶ Front Next sur http://localhost:9000  (Ctrl+C pour tout arrêter)" -ForegroundColor Cyan
    Push-Location (Join-Path $root "web")
    npm run dev
}
finally {
    Pop-Location
    if ($backend -and -not $backend.HasExited) {
        Write-Host "■ Arrêt du backend (PID $($backend.Id)) …" -ForegroundColor Yellow
        # /T : tue aussi le worker enfant lancé par uvicorn --reload.
        taskkill /PID $backend.Id /T /F 2>$null | Out-Null
    }
}
