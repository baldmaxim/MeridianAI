@echo off
chcp 65001 >nul
rem Установка агента распознавания Meridian. Двойной клик — всё, что нужно.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
