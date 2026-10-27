@echo off
rem Opens Clip Scout in your browser. The first run sets up Python and the packages Clip Scout needs (a one-time
rem download of a few GB). A release folder carries its own uv in uv\; a clone of the repo uses the uv on PATH.
setlocal
pushd "%~dp0"
if not exist "pyproject.toml" goto :not_extracted
if exist "uv\uv.exe" set "PATH=%CD%\uv;%PATH%"
rem uv's download cache is on C:. When this folder is on another drive, uv can't hard-link from the cache and warns
rem as it falls back to copying, which reads like an error on the first start: copy without the warning.
if not defined UV_LINK_MODE set "UV_LINK_MODE=copy"
where uv >nul 2>nul || goto :no_uv
where ffmpeg >nul 2>nul && where ffprobe >nul 2>nul || call :get_ffmpeg || exit /b 1
uv run --all-extras scout serve
if errorlevel 1 pause
exit /b

:not_extracted
echo Clip Scout has to be extracted before it runs. Right-click the zip, choose Extract All, then
echo double-click Clip Scout.bat in the extracted folder.
pause
exit /b 1

:no_uv
echo Clip Scout needs uv. Install it with:
echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
pause
exit /b 1

:get_ffmpeg
echo Clip Scout needs ffmpeg and ffprobe, and they aren't installed.
where winget >nul 2>nul || goto :ffmpeg_download
set "answer=Y"
set /p "answer=Install ffmpeg (it includes ffprobe) now with winget? [Y/n] "
if /i not "%answer:~0,1%"=="Y" goto :ffmpeg_by_hand
winget install --id Gyan.FFmpeg -e --source winget
set "installed=%errorlevel%"
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links;%ProgramFiles%\WinGet\Links"
where ffmpeg >nul 2>nul && where ffprobe >nul 2>nul && exit /b 0
if not "%installed%"=="0" goto :winget_failed
echo ffmpeg isn't on PATH yet. Close this window and open Clip Scout again.
pause
exit /b 1

:winget_failed
echo winget couldn't install ffmpeg (error %installed%). Open Clip Scout again to retry.
:ffmpeg_download
echo To install ffmpeg by hand, download the release essentials zip from https://www.gyan.dev/ffmpeg/builds/,
echo extract it and add its bin folder to your PATH. Then open Clip Scout again.
pause
exit /b 1

:ffmpeg_by_hand
echo Install ffmpeg (for example: winget install Gyan.FFmpeg), then open Clip Scout again.
pause
exit /b 1
