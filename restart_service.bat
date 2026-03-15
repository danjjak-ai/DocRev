@echo off
setlocal enabledelayedexpansion

:: ==========================================
:: SET YOUR GEMINI API KEY IN .env FILE
:: ==========================================

echo [DocRev] Cleaning up existing processes...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM pythonw.exe 2>nul

echo [DocRev] Checking environment variables...
if not exist ".env" (
    echo [WARNING] .env file not found. AI features may not work.
    echo Please create a .env file based on .env.example.
)

echo [DocRev] Initializing configuration directories...
if not exist "config" mkdir config
if not exist "config\ng_words" mkdir config\ng_words
if not exist "config\prompts" mkdir config\prompts
if not exist "config\ReferenceDoc" mkdir config\ReferenceDoc

echo [DocRev] Checking virtual environment...
if not exist ".venv" (
    echo [DocRev] Creating virtual environment...
    python -m venv .venv
)

echo [DocRev] Ensuring dependencies...
.\.venv\Scripts\python.exe -m pip install flask flask-cors pymupdf google-genai langchain langchain-community chromadb sentence-transformers langchain-huggingface langchain-chroma langchain-text-splitters python-dotenv gunicorn --quiet

echo [DocRev] Opening Application...
start "" "pdf_comment_workspace.html"

echo [DocRev] Starting Backend Server...
echo ======================================================
echo Backend Logs (Press Ctrl+C to stop):
echo ======================================================
.\.venv\Scripts\python.exe backend.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Backend crashed with exit code %ERRORLEVEL%.
    echo Check for missing packages or API key issues above.
    pause
)
