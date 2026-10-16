@echo off
rem Select Python 3.10+ with Tk; this does not install or change anything.
setlocal
cd /d "%~dp0"
if exist "SDL2.dll" if not defined FOLLOWSPOT_SDL2 set "FOLLOWSPOT_SDL2=%CD%\SDL2.dll"

set "FOLLOWSPOT_PYTHON="
for %%P in (".venv\Scripts\python.exe" "python.exe" "py.exe") do (
  if not defined FOLLOWSPOT_PYTHON (
    %%P -c "import sys; sys.exit(1) if sys.version_info < (3, 10) else None; import tkinter, _tkinter" >nul 2>&1
    if not errorlevel 1 set "FOLLOWSPOT_PYTHON=%%~P"
  )
)

if not defined FOLLOWSPOT_PYTHON (
  echo No Python 3.10 or newer with Tk support was found.
  echo Install Python 3.10 or newer from python.org and keep "tcl/tk and IDLE" ticked.
  pause
  exit /b 1
)

"%FOLLOWSPOT_PYTHON%" "%CD%\followspot.py" %*
set "FOLLOWSPOT_RESULT=%errorlevel%"
if not "%FOLLOWSPOT_RESULT%"=="0" (
  echo Followspot exited with an error. See the message above and README.md.
  pause
)
exit /b %FOLLOWSPOT_RESULT%
