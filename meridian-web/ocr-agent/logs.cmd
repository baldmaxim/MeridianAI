@echo off
chcp 65001 >nul
rem Журнал агента. Под pythonw консоли нет, и это единственное место, где видно, чем он занят.
if not exist "%~dp0logs\agent.log" (
  echo Журнала пока нет: агент ещё ни разу не запускался.
  pause
  exit /b 1
)
start "" notepad "%~dp0logs\agent.log"
