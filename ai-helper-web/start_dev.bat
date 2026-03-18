@echo off
echo Starting AI Helper Web (dev mode)...
echo.

:: Start backend in new window
start "AI Helper Backend" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

:: Start frontend in new window
start "AI Helper Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --port 5173"

timeout /t 3 /nobreak > nul
echo.
echo Backend:  http://localhost:8001
echo Frontend: http://localhost:5173
echo.
echo Login: admin@test.com / admin123
echo.
pause
