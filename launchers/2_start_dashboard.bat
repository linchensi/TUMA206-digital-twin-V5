@echo off
cd /d "%~dp0"
cd ..
echo =====================================
echo   LOCAL DASHBOARD — SCHEMATIC/TRENDS/ALARMS
echo   http://localhost:8501
echo =====================================
echo.
set DASHBOARD_MODE=remote
start "Local Dashboard" cmd /k "python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true"
timeout /t 5 /nobreak >nul
start "" "http://localhost:8501"
pause
