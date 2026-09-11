@echo off
chcp 65001 >nul
rem Проверка связи: сервер Meridian и LM Studio. Очередь не трогает.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m meridian_ocr_agent --check --verbose
echo.
pause
