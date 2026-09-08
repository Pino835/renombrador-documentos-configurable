@echo off
cd /d "%~dp0_sistema"
powershell -NoProfile -ExecutionPolicy Bypass -File "instalar_python.ps1"
pause
