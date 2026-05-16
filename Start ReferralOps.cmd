@echo off
setlocal

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_judge_demo.ps1"
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo ReferralOps launcher failed with exit code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%
