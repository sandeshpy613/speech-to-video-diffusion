@echo off
:start
echo [1/3] Checking environment...
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate

echo [2/3] Syncing dependencies...
pip install -r requirements.txt

echo [3/3] Starting Titan Research Engine (Port 3000)...
echo TIP: Using Port 3000 as per research requirements.
python app.py

echo.
echo [!] Server stopped. Auto-restarting in 5 seconds...
timeout /t 5
goto start
