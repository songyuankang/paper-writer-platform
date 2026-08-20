$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiDirectory = Join-Path $Root 'paper-writer-api'
$WebDirectory = Join-Path $Root 'paper-writer-web'
$ApiPython = Join-Path $ApiDirectory '.venv\Scripts\python.exe'
$NpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $NpmCommand) { $NpmCommand = Get-Command npm -ErrorAction Stop }
$LogDirectory = Join-Path $env:LOCALAPPDATA 'paper-writer-platform\logs'
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

if (-not (Test-Path $ApiPython)) { throw "Backend virtual environment was not found: $ApiPython" }

$env:PAPER_WRITER_CORS_ORIGINS = 'http://localhost:4173,http://127.0.0.1:4173'
function Test-ListeningPort([int]$Port) { return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) }

$started = @()
if (Test-ListeningPort 8000) {
    $started += 'Backend already listens on 127.0.0.1:8000.'
} else {
    $apiOut = Join-Path $LogDirectory 'api.stdout.log'
    $apiErr = Join-Path $LogDirectory 'api.stderr.log'
    $api = Start-Process -FilePath $ApiPython -ArgumentList '-m uvicorn app.main:app --host 127.0.0.1 --port 8000' -WorkingDirectory $ApiDirectory -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -PassThru
    $started += "Backend started as an independent process, PID $($api.Id)."
}

if (Test-ListeningPort 4173) {
    $started += 'Frontend already listens on 127.0.0.1:4173.'
} else {
    $webOut = Join-Path $LogDirectory 'web.stdout.log'
    $webErr = Join-Path $LogDirectory 'web.stderr.log'
    $web = Start-Process -FilePath $NpmCommand.Source -ArgumentList 'run preview -- --host 127.0.0.1 --port 4173' -WorkingDirectory $WebDirectory -RedirectStandardOutput $webOut -RedirectStandardError $webErr -PassThru
    $started += "Frontend started as an independent process, PID $($web.Id)."
}

Start-Sleep -Seconds 3
$apiState = if (Test-ListeningPort 8000) { 'listening' } else { 'not listening; inspect api.stderr.log' }
$webState = if (Test-ListeningPort 4173) { 'listening' } else { 'not listening; inspect web.stderr.log' }
$started | ForEach-Object { Write-Output $_ }
Write-Output "Backend 8000: $apiState"
Write-Output "Frontend 4173: $webState"
Write-Output "Log directory: $LogDirectory"
if ($apiState -ne 'listening' -or $webState -ne 'listening') { exit 1 }
