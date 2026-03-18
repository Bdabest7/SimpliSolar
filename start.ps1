# SimpliSolar - Start / Restart Script
# Double-click start.bat  OR  run:  .\start.ps1
#
# Re-running while the app is already up will restart both services.

$BACKEND_PORT  = 8001
$FRONTEND_PORT = 5173
$ROOT          = $PSScriptRoot

# ── Helpers ───────────────────────────────────────────────────────────────────

function Kill-Port($port) {
    $hits = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    $pids = ($hits | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique)
    foreach ($p in $pids) {
        if ($p -gt 0) {
            Write-Host "  Killing PID $p on port $port" -ForegroundColor Yellow
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-Http($url, $timeoutSec = 40) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 600
    }
    return $false
}

# ── Stop any running instances ────────────────────────────────────────────────

Write-Host ""
Write-Host "  SimpliSolar" -ForegroundColor Cyan
Write-Host "  ===========" -ForegroundColor Cyan
Write-Host ""
Write-Host "Stopping any running instances..." -ForegroundColor Gray

Kill-Port $BACKEND_PORT
Kill-Port $FRONTEND_PORT
Start-Sleep -Milliseconds 800

# ── Start Backend ─────────────────────────────────────────────────────────────

Write-Host "Starting backend on port $BACKEND_PORT..." -ForegroundColor Green

# Use cmd /K so the window stays open on error and shows the full output.
# /D disables AutoRun registry commands; /K runs and keeps the window open.
Start-Process cmd -ArgumentList "/K", "cd /d `"$ROOT`" && python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port $BACKEND_PORT" -WindowStyle Normal

Write-Host "  Waiting for backend health check..." -ForegroundColor Gray
if (Wait-Http "http://127.0.0.1:$BACKEND_PORT/api/health" 40) {
    Write-Host "  Backend is up." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  ERROR: Backend did not respond within 40s." -ForegroundColor Red
    Write-Host "  Check the backend terminal window for errors." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Common causes:" -ForegroundColor Yellow
    Write-Host "    - Missing Python packages  ->  run: pip install -e ." -ForegroundColor Yellow
    Write-Host "    - Import error in backend code (check the window)" -ForegroundColor Yellow
    Write-Host "    - Port $BACKEND_PORT still held by another process" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Start Frontend ────────────────────────────────────────────────────────────

Write-Host "Starting frontend on port $FRONTEND_PORT..." -ForegroundColor Green

Start-Process cmd -ArgumentList "/K", "cd /d `"$ROOT\frontend`" && npm run dev" -WindowStyle Normal

Write-Host "  Waiting for frontend..." -ForegroundColor Gray
if (Wait-Http "http://127.0.0.1:$FRONTEND_PORT" 40) {
    Write-Host "  Frontend is up." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  ERROR: Frontend did not start within 40s." -ForegroundColor Red
    Write-Host "  Check the frontend terminal window for errors." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Common causes:" -ForegroundColor Yellow
    Write-Host "    - npm not installed  ->  install Node.js from nodejs.org" -ForegroundColor Yellow
    Write-Host "    - Missing packages   ->  run: cd frontend && npm install" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Done ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  SimpliSolar is running at http://localhost:$FRONTEND_PORT" -ForegroundColor Cyan
Write-Host "  Opening browser..." -ForegroundColor Gray
Start-Process "http://localhost:$FRONTEND_PORT"
Write-Host ""
Write-Host "  Close the backend and frontend windows to stop." -ForegroundColor Gray
Write-Host "  Run start.bat again at any time to restart." -ForegroundColor Gray
Write-Host ""
