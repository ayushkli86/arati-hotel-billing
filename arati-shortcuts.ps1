<# 
.SYNOPSIS
    Arati Hotel Billing - PowerShell shortcuts

.DESCRIPTION
    Provides convenient functions for managing the Arati Hotel Web Billing application.
    Add this to your PowerShell profile or dot-source it:
    . "C:\path\to\arati-hotel-billing\arati-shortcuts.ps1"
#>

$ARATI_ROOT = Split-Path -Parent $MyInvocation.MyCommand.Definition
$APP_HOME = "$env:LOCALAPPDATA\AratiHotel\WebBilling"

function Initialize-AratiDatabase {
    <#
    .SYNOPSIS
        Initialize/seed the Arati Hotel database
    #>
    if (-not (Test-Path "$APP_HOME\.venv\Scripts\python.exe")) {
        Write-Host "Creating web application virtual environment..." -ForegroundColor Yellow
        py -3.11 -m venv "$APP_HOME\.venv"
        if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }
    }

    $python = "$APP_HOME\.venv\Scripts\python.exe"
    & $python -c "import fastapi, sqlalchemy, jinja2, uvicorn, httpx, weasyprint, multipart, itsdangerous" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing web billing dependencies..." -ForegroundColor Yellow
        & $python -m pip install -r "$ARATI_ROOT\webapp\requirements.txt"
        if ($LASTEXITCODE -ne 0) { throw "Failed to install dependencies" }
    }

    Write-Host "Initializing database..." -ForegroundColor Yellow
    & $python -m webapp.seed
    if ($LASTEXITCODE -ne 0) { throw "Database initialization failed" }

    Write-Host "Database initialized successfully!" -ForegroundColor Green
}

function Start-AratiWeb {
    <#
    .SYNOPSIS
        Start the Arati Hotel Web Billing application
    #>
    if (-not (Test-Path "$APP_HOME\.venv\Scripts\python.exe")) {
        Write-Host "Creating web application virtual environment..." -ForegroundColor Yellow
        py -3.11 -m venv "$APP_HOME\.venv"
        if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }
    }

    $python = "$APP_HOME\.venv\Scripts\python.exe"
    & $python -c "import fastapi, sqlalchemy, jinja2, uvicorn, httpx, weasyprint, multipart, itsdangerous" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing web billing dependencies..." -ForegroundColor Yellow
        & $python -m pip install -r "$ARATI_ROOT\webapp\requirements.txt"
        if ($LASTEXITCODE -ne 0) { throw "Failed to install dependencies" }
    }

    Write-Host "Starting Arati Hotel Web Billing..." -ForegroundColor Yellow
    & $python -m webapp.launcher
    if ($LASTEXITCODE -ne 0) { throw "Failed to start web application" }
}

function Stop-AratiWeb {
    <#
    .SYNOPSIS
        Stop the Arati Hotel Web Billing application
    #>
    $processes = Get-Process -Name "python*" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "uvicorn webapp.main:app" }
    if ($processes) {
        $processes | Stop-Process -Force
        Write-Host "Arati Hotel Web Billing stopped" -ForegroundColor Green
    } else {
        Write-Host "No running instance found" -ForegroundColor Yellow
    }
}

function Get-AratiLogs {
    <#
    .SYNOPSIS
        View Arati Hotel Web Billing logs
    #>
    $logFile = "$ARATI_ROOT\.run\web.log"
    if (Test-Path $logFile) {
        Get-Content $logFile -Wait -Tail 50
    } else {
        Write-Host "No log file found at $logFile" -ForegroundColor Yellow
    }
}

function Get-AratiStatus {
    <#
    .SYNOPSIS
        Check if Arati Hotel Web Billing is running
    #>
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/login" -TimeoutSec 2 -ErrorAction Stop
        Write-Host "Arati Hotel Web Billing is RUNNING at http://127.0.0.1:8000" -ForegroundColor Green
    } catch {
        Write-Host "Arati Hotel Web Billing is NOT RUNNING" -ForegroundColor Red
    }
}

# Export aliases
Set-Alias -Name arati-db-init -Value Initialize-AratiDatabase
Set-Alias -Name arati-start -Value Start-AratiWeb
Set-Alias -Name arati-stop -Value Stop-AratiWeb
Set-Alias -Name arati-logs -Value Get-AratiLogs
Set-Alias -Name arati-status -Value Get-AratiStatus

Write-Host "Arati Hotel Billing shortcuts loaded:" -ForegroundColor Cyan
Write-Host "  arati-db-init  - Initialize/seed the database" -ForegroundColor Gray
Write-Host "  arati-start    - Start the web application" -ForegroundColor Gray
Write-Host "  arati-stop     - Stop the web application" -ForegroundColor Gray
Write-Host "  arati-logs     - View live logs" -ForegroundColor Gray
Write-Host "  arati-status   - Check if web app is running" -ForegroundColor Gray