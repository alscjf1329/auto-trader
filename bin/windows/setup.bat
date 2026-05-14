@echo off
cd /d "%~dp0..\.."

echo === Setup virtual environment ===

if not exist "venv" (
    echo Creating venv...
    python -m venv venv
)

call venv\Scripts\activate

echo Installing packages...
pip install -r requirements.txt

echo === Done ===
pause
