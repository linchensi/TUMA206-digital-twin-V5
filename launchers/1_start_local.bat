@echo off
cd /d "%~dp0"
cd ..
echo =====================================
echo   LOCAL BACKEND — engine + MQTT
echo =====================================
echo.
python local_backend.py
pause
