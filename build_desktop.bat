@echo off
REM =====================================================
REM  Desktop build: dist\HospitalMS.exe
REM  Local server + auto-open browser (SQLite next to exe)
REM =====================================================
setlocal
cd /d "%~dp0"

echo [1/2] Installing PyInstaller ...
pip install pyinstaller
if errorlevel 1 goto :fail_pip

echo [2/2] Building HospitalMS.exe (onefile, ~1-3 min) ...
python -m PyInstaller --noconfirm --clean --onefile --name HospitalMS --add-data "static;static" --collect-all uvicorn desktop.py
if errorlevel 1 goto :fail_build

echo.
echo OK: dist\HospitalMS.exe  (double-click to run)
exit /b 0

:fail_pip
echo FAILED: pip install pyinstaller
exit /b 1

:fail_build
echo FAILED: pyinstaller build
exit /b 1
