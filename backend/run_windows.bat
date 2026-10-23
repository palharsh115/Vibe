@echo off
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
set TOKEN_SECRET=local-development-secret-change-before-deployment
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
