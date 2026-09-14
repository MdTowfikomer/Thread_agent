@echo off
echo ===================================================
echo   THREAD: AI-Powered Organizational Memory Agent
echo   Starting FastAPI Backend + Vite React Frontend
echo ===================================================

start "Thread Backend (FastAPI)" cmd /k "cd backend && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload"
start "Thread Frontend (Vite React)" cmd /k "cd frontend && npm run dev"

echo.
echo [OK] Backend starting at http://localhost:8000
echo [OK] Frontend starting at http://localhost:5173
echo ===================================================
pause
