@echo off
echo ===================================================
echo Aonang Fiore HRMS - Database Backup Utility
echo ===================================================
echo.

:: กำหนดเป้าหมายไปที่หน้าจอ Desktop ของคอมพิวเตอร์เครื่องปัจจุบัน
set DEST_DIR=%USERPROFILE%\Desktop\HRMS_Backup

echo [1/2] Checking backup folder...
if not exist "%DEST_DIR%" (
    mkdir "%DEST_DIR%"
    echo Created folder: %DEST_DIR%
) else (
    echo Backup folder already exists on Desktop.
)

echo.
echo [2/2] Backing up payroll.db...
if exist payroll.db (
    copy payroll.db "%DEST_DIR%\payroll.db" /Y
    echo.
    echo [SUCCESS] Backup complete! 
    echo Your database has been safely copied to:
    echo %DEST_DIR%
) else (
    echo.
    echo [ERROR] Cannot find payroll.db in this folder!
    echo Please make sure this .bat file is in the same folder as your database.
)

echo.
pause