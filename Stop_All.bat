@echo off
echo Stopping SmartHR services...

taskkill /F /IM ngrok.exe >nul 2>&1
taskkill /F /IM streamlit.exe >nul 2>&1
taskkill /F /IM uvicorn.exe >nul 2>&1

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000"') do taskkill /F /PID %%P >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8501"') do taskkill /F /PID %%P >nul 2>&1

echo Done.
pause
