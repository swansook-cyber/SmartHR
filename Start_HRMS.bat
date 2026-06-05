@echo off
chcp 65001 >nul
set "PROJECT_DIR=%~dp0"

echo =========================================
echo Starting Aonang Fiore HRMS System...
echo =========================================
echo Project: %PROJECT_DIR%
echo.

cd /d "%PROJECT_DIR%"

echo [1/2] Starting Backend API...
start "HRMS_Backend" /D "%PROJECT_DIR%" cmd /k "py -m uvicorn main:app --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak >nul

echo [2/2] Starting Frontend Web...
start "HRMS_Frontend" /D "%PROJECT_DIR%" cmd /k "py -m streamlit run frontend.py --server.address 0.0.0.0 --server.port 8501"

timeout /t 3 /nobreak >nul
start "" "http://localhost:8501"

echo System startup commands have been sent.
exit /b
