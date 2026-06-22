@echo off
cd /d "%~dp0"
echo ==============================================
echo   BEVERAGE LINE — FULL SYSTEM LAUNCH
echo ==============================================
echo.
echo Starting local backend + dashboard...
echo   [1] Local Backend   (engine + MQTT -> HiveMQ Cloud)
echo   [2] Local Dashboard (http://localhost:8501, remote mode via MQTT)
echo   [3] Cloud Monitor   (Streamlit Community Cloud)
echo.
echo The cloud monitor opens in your browser:
echo   https://beverage-digital-twin.streamlit.app/
echo.
echo Close each terminal window to stop that process.
echo ==============================================
echo.

start "Local Backend"   cmd /k "cd /d %~dp0 && python local_backend.py"
timeout /t 2 /nobreak >nul
start "Local Dashboard" cmd /k "cd /d %~dp0 && set DASHBOARD_MODE=remote&& python -m streamlit run dashboard/app.py --server.port 8501 --server.headless true"
timeout /t 5 /nobreak >nul
start "" "http://localhost:8501"
start "" "https://beverage-digital-twin.streamlit.app/"

echo All launched.
pause
