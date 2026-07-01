@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "Orrery.exe" (
  echo Missing Orrery.exe. Extract the full Orrery-Windows.zip package and try again.
  pause
  exit /b 1
)

if not exist ".env" (
  echo Orrery has not been configured in this extracted folder yet.
  echo Opening setup...
  echo.
  call "%~dp0setup-orrery.bat"
  exit /b %ERRORLEVEL%
)

".\Orrery.exe" --packaging-probe
if errorlevel 1 (
  echo.
  echo This Orrery package failed its desktop runtime check.
  echo Download the latest Orrery-Windows.zip and extract the full folder.
  pause
  exit /b 1
)

".\Orrery.exe"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Orrery exited with code %EXITCODE%.
  echo If you need to change database/sandbox setup, run setup-orrery.bat.
  pause
)
exit /b %EXITCODE%
