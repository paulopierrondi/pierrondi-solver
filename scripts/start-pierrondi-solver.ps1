# Always-on launcher for pierrondi-solver on Windows.
# Idempotent: exits 0 when the loopback service already answers on the port.
# Recreates the local venv if it disappeared, then starts uvicorn detached.
# Secrets come only from the user environment; this script never prints values.
param(
    [int]$Port = 8791,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$LogDir = Join-Path $Root "data"
$Extras = "[dev,mcp,local-solve,nodriver]"

function Test-ServiceUp {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        return ($r.status -eq "ok")
    } catch { return $false }
}

if (Test-ServiceUp) {
    Write-Output "solver_start: service already up on 127.0.0.1:$Port"
    exit 0
}
if ($CheckOnly) {
    Write-Output "solver_start: service down on 127.0.0.1:$Port"
    exit 1
}

if (-not (Test-Path $VenvPython)) {
    Write-Output "solver_start: recreating venv"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        & uv venv $VenvDir --python 3.13
        & uv pip install --python $VenvDir -e "$Root$Extras"
    } else {
        & py -3.13 -m venv $VenvDir
        & $VenvPython -m pip install -U pip setuptools wheel
        & $VenvPython -m pip install -e "$Root$Extras"
    }
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "solver_start: python still missing after install"
    exit 127
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$proc = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "pierrondi_solver.main:app",
        "--app-dir", (Join-Path $Root "src"),
        "--host", "127.0.0.1", "--port", "$Port" `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "service.log") `
    -RedirectStandardError (Join-Path $LogDir "service.err.log") `
    -PassThru

Start-Sleep -Seconds 5
if (Test-ServiceUp) {
    Write-Output "solver_start: service up on 127.0.0.1:$Port (pid $($proc.Id))"
    exit 0
}
Write-Output "solver_start: service did not answer in 5s; check $LogDir\service.err.log"
exit 1
