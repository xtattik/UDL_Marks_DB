@echo off
cd /d "%~dp0"

:: Use venv if present, otherwise fall back to system Python
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo No .venv found - using system Python
    echo Tip: run  python -m venv .venv  to create one
)

:: Install/update dependencies quietly
pip install -q -r requirements.txt

:: Open browser after a short delay (app needs a moment to start)
start "" /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:5000"

:: Launch app
python app.py
pause
