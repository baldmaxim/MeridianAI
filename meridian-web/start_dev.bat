@echo off
setlocal
echo Starting Meridian Web (dev mode)...
echo.

set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

:: 1. Dev-инфраструктура (PostgreSQL + MinIO) — §7/§15
echo [1/3] Starting dev infrastructure (PostgreSQL + MinIO)...
docker compose -f "%ROOT%docker-compose.dev.yml" up -d --wait
if errorlevel 1 (
  echo ERROR: docker compose failed. Is Docker Desktop running?
  pause
  exit /b 1
)

:: 2. Миграции БД отдельным шагом (§8) — НЕ из app-контейнера
echo [2/3] Applying database migrations (alembic upgrade head)...
pushd "%ROOT%backend"
"%PY%" -m alembic upgrade head
if errorlevel 1 (
  echo ERROR: alembic upgrade failed.
  popd
  pause
  exit /b 1
)
popd

:: 3. Backend + frontend
echo [3/3] Launching backend + frontend...
start "Meridian Backend" cmd /k "cd /d %ROOT%backend && %PY% -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload --no-access-log"
start "Meridian Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev -- --port 5173"

timeout /t 3 /nobreak > nul
echo.
echo Backend:  http://localhost:8001
echo Frontend: http://localhost:5173
echo MinIO:    http://localhost:9001  (minioadmin/minioadmin)
echo.
echo Login: admin@test.com / admin123
echo.
endlocal
pause
