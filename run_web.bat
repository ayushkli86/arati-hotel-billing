@echo off
setlocal
cd /d "%~dp0"

set "APP_HOME=%LOCALAPPDATA%\AratiHotel\WebBilling"
if not exist "%APP_HOME%" mkdir "%APP_HOME%"

if not exist "%APP_HOME%\.venv\Scripts\python.exe" (
    py -3.11 -m venv "%APP_HOME%\.venv"
    if errorlevel 1 goto :failed
)

"%APP_HOME%\.venv\Scripts\python.exe" -c "import fastapi, sqlalchemy, jinja2, uvicorn, httpx, weasyprint, multipart, itsdangerous" >nul 2>&1
if errorlevel 1 (
    echo Installing web billing dependencies. An internet connection is required for setup.
    "%APP_HOME%\.venv\Scripts\python.exe" -m pip install -r webapp\requirements.txt
    if errorlevel 1 goto :failed
)

"%APP_HOME%\.venv\Scripts\python.exe" -m webapp.seed
if errorlevel 1 goto :failed
"%APP_HOME%\.venv\Scripts\python.exe" -m webapp.launcher
if errorlevel 1 goto :failed
exit /b 0

:failed
echo Arati Hotel Web Billing could not start. Review the error above.
pause
exit /b 1
