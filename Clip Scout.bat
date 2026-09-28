@echo off
rem Opens Clip Scout in your browser. First run installs everything it needs (a few minutes).
cd /d "%~dp0"
where uv >nul 2>nul || (
  echo Clip Scout needs uv. Install it with:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  pause
  exit /b 1
)
uv run --all-extras scout serve
if errorlevel 1 pause
