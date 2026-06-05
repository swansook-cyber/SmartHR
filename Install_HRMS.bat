@echo off
chcp 65001 >nul
set "PROJECT_DIR=%~dp0"

echo ===================================================
echo Aonang Fiore HRMS - Auto Installation Setup
echo ===================================================
echo Project: %PROJECT_DIR%
echo.

cd /d "%PROJECT_DIR%"

echo [1/3] Checking Python Installation...
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python launcher is not installed or not in PATH!
    echo Please install Python from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo [SUCCESS] Python is ready!

echo.
echo [2/3] Installing Required Libraries...
py -m pip install fastapi uvicorn streamlit pandas reportlab openpyxl requests sqlalchemy
if %errorlevel% neq 0 (
    echo [ERROR] Library installation failed. Please check the message above.
    pause
    exit /b 1
)

echo.
echo [3/3] Setup Completed!
echo.
echo System is now ready to use.
echo You can now double-click "Start_HRMS.bat" to run the system.
pause
