@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Bitte zuerst install.bat ausfuehren.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0setup_login.py"
