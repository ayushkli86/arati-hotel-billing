@echo off
setlocal enabledelayedexpansion

:: Check for admin privileges
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================
echo   Arati Hotel Billing - One-Click Installer
echo ============================================
echo.
echo This will install everything needed for Arati Hotel Billing on Windows:
echo   - Python 3.11 (if not installed)
echo   - Google Chrome (if not installed) 
echo   - GTK3 Runtime for PDF generation
echo   - Virtual environment and dependencies
echo   - Database initialization
echo   - Start Menu and Desktop shortcuts
echo.
echo This may take 5-15 minutes depending on internet speed.
echo.
pause

cd /d "%~dp0"

powershell -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"

echo.
echo ============================================
echo   Installation Complete!
echo ============================================
echo.
echo You can launch Arati Hotel Billing from:
echo   - Start Menu > Arati Hotel > Arati Hotel Billing
echo   - Desktop shortcut
echo.
pause
