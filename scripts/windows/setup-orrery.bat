@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "DEFAULT_DB_URL=postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery"

call :check_package || exit /b 1
call :ensure_env

:menu
cls
echo Orrery Windows Setup
echo ====================
echo.
echo Choose how this machine should run Orrery:
echo.
echo   1. Use the included Docker PostgreSQL database, build sandbox, then start Orrery
echo   2. Use my own PostgreSQL database URL, then start Orrery
echo   3. Build or refresh the file-generation sandbox image only
echo   4. Start Orrery only
echo   5. Quit
echo.
set /p "CHOICE=Select 1-5: "

if "%CHOICE%"=="1" goto included_db
if "%CHOICE%"=="2" goto custom_db
if "%CHOICE%"=="3" goto sandbox_only
if "%CHOICE%"=="4" goto start_only
if "%CHOICE%"=="5" exit /b 0
goto menu

:included_db
call :write_database_url "%DEFAULT_DB_URL%"
call :require_docker || goto setup_failed
call :start_postgres || goto setup_failed
call :build_sandbox || goto setup_failed
call :start_orrery
exit /b %ERRORLEVEL%

:custom_db
echo.
echo Paste your PostgreSQL URL.
echo Example:
echo   postgresql+psycopg://user:password@host:5432/database
echo.
set /p "CUSTOM_DB_URL=Database URL: "
if "%CUSTOM_DB_URL%"=="" (
  echo No database URL entered.
  pause
  goto menu
)
call :write_database_url "%CUSTOM_DB_URL%"
echo.
echo Saved DATABASE_URL to .env for this extracted Orrery folder.
echo If you prefer the Windows keychain later, change it inside Orrery Settings.
echo.
set /p "BUILD_SANDBOX=Build the local file-generation sandbox now? [Y/n]: "
if /i not "%BUILD_SANDBOX%"=="n" (
  call :require_docker || goto setup_failed
  call :build_sandbox || goto setup_failed
)
call :start_orrery
exit /b %ERRORLEVEL%

:sandbox_only
call :require_docker || goto setup_failed
call :build_sandbox || goto setup_failed
echo.
echo Sandbox image is ready.
pause
goto menu

:start_only
call :start_orrery
exit /b %ERRORLEVEL%

:check_package
if not exist "Orrery.exe" (
  echo Missing Orrery.exe. Extract the full Orrery-Windows.zip package and try again.
  pause
  exit /b 1
)
if not exist "_internal\python312.dll" (
  echo Missing _internal\python312.dll.
  echo This package is incomplete. Download Orrery-Windows.zip again and extract the full folder.
  pause
  exit /b 1
)
if not exist "_internal\PySide6" (
  echo Missing Qt desktop runtime.
  echo This package is incomplete. Download Orrery-Windows.zip again and extract the full folder.
  pause
  exit /b 1
)
if not exist "_internal\pptx" (
  echo Missing PowerPoint generation support.
  echo This package is incomplete. Download Orrery-Windows.zip again and extract the full folder.
  pause
  exit /b 1
)
exit /b 0

:ensure_env
if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
  ) else (
    echo ORRERY_DEV=0> ".env"
  )
)
exit /b 0

:write_database_url
set "URL=%~1"
(
  echo # Orrery Windows package settings
  echo DATABASE_URL=%URL%
  echo ORRERY_DEV=0
) > ".env"
exit /b 0

:require_docker
where docker >nul 2>nul
if errorlevel 1 (
  echo.
  echo Docker was not found in PATH.
  echo Install/start Docker Desktop, or choose option 2 and use your own PostgreSQL server.
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo.
  echo Docker Desktop is installed but not running.
  echo Start Docker Desktop and run setup-orrery.bat again.
  pause
  exit /b 1
)
exit /b 0

:start_postgres
echo.
echo Starting included PostgreSQL database...
docker compose up -d
if errorlevel 1 exit /b 1

echo Checking PostgreSQL readiness...
set "PG_READY=0"
for /l %%i in (1,1,45) do (
  docker exec orrery-postgres pg_isready -U orrery -d orrery >nul 2>nul
  if not errorlevel 1 (
    set "PG_READY=1"
    goto postgres_ready
  )
  timeout /t 2 /nobreak >nul
)
:postgres_ready
if not "%PG_READY%"=="1" (
  echo PostgreSQL did not become ready in time.
  exit /b 1
)
exit /b 0

:build_sandbox
echo.
echo Building file-generation sandbox image...
docker build -t orrery-sandbox:latest sandbox
if errorlevel 1 exit /b 1
exit /b 0

:start_orrery
echo.
echo Checking packaged desktop runtime...
".\Orrery.exe" --packaging-probe
if errorlevel 1 (
  echo.
  echo This Orrery package failed its desktop runtime check.
  echo Download the latest Orrery-Windows.zip and extract the full folder.
  pause
  exit /b 1
)

echo.
echo Starting Orrery...
echo.
".\Orrery.exe"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Orrery exited with code %EXITCODE%.
  echo Keep this window open and copy the error if you need to report it.
  pause
)
exit /b %EXITCODE%

:setup_failed
echo.
echo Setup failed. Check the message above, then run setup-orrery.bat again.
pause
exit /b 1
