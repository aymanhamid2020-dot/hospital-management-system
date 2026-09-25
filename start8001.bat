@echo off
REM تشغيل خادم التطوير على المنفذ 8001 (الواجهة على http://127.0.0.1:8001/ui)
cd /d "%~dp0"
python -m uvicorn main:app --host 127.0.0.1 --port 8001
