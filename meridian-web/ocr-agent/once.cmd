@echo off
chcp 65001 >nul
rem Один настоящий заход с подробным выводом: берёт скан из очереди и распознаёт его.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m meridian_ocr_agent --once --verbose
echo.
pause
