$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..")
Set-Location $RepoRoot

function Assert-Exists {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Message = "Required path is missing"
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Message`: $Path"
    }
}

function Assert-Matches {
    param(
        [Parameter(Mandatory = $true)][string]$PathPattern,
        [string]$Message = "Required path is missing"
    )
    if (-not (Test-Path -Path $PathPattern)) {
        throw "$Message`: $PathPattern"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs
    )

    & $Exe @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe failed with exit code $LASTEXITCODE"
    }
}

function Remove-InRepo {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $target = Join-Path $RepoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $target)) {
        return
    }
    $resolved = Resolve-Path -LiteralPath $target
    $repoFull = [System.IO.Path]::GetFullPath($RepoRoot.Path)
    $targetFull = [System.IO.Path]::GetFullPath($resolved.Path)
    if (-not $targetFull.StartsWith($repoFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside repository: $targetFull"
    }
    Remove-Item -LiteralPath $targetFull -Recurse -Force
}

Write-Host "Cleaning old build output..."
Remove-InRepo "build"
Remove-InRepo "dist"
Remove-InRepo "release"

Write-Host "Building frontend..."
Push-Location "ui"
try {
    if (Test-Path "node_modules") {
        Write-Host "Repairing existing ui/node_modules with npm install..."
        Invoke-Checked "npm" "install"
    } else {
        Invoke-Checked "npm" "ci"
    }
    Invoke-Checked "npm" "run" "build"
} finally {
    Pop-Location
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv..."
    Invoke-Checked "py" "-3.12" "-m" "venv" ".venv"
}

Write-Host "Installing Python dependencies..."
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "--upgrade" "pip"
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "-r" "requirements.txt"
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "pyinstaller"

Write-Host "Building PyInstaller onedir package..."
Invoke-Checked ".venv\Scripts\pyinstaller.exe" `
    "--noconfirm" `
    "--clean" `
    "--onedir" `
    "--name" "Orrery" `
    "--console" `
    "--icon" "assets\desktop\orrery.ico" `
    "--add-data" "assets;assets" `
    "--add-data" "ui\dist;ui\dist" `
    "--add-data" "skills;skills" `
    "--add-data" "sandbox;sandbox" `
    "--add-data" "backend\providers\model_manifest.json;backend\providers" `
    "--collect-all" "litellm" `
    "--collect-all" "fastembed" `
    "--collect-all" "webview" `
    "--collect-data" "procrastinate" `
    "--copy-metadata" "procrastinate" `
    "--collect-submodules" "keyring.backends" `
    "app.py"

$DistRoot = "dist\Orrery"
$ReleaseRoot = "release\Orrery-Windows"

Write-Host "Validating PyInstaller output..."
Assert-Exists "$DistRoot\Orrery.exe" "PyInstaller executable was not created"
Assert-Exists "$DistRoot\_internal" "PyInstaller onedir internal folder was not created"
Assert-Exists "$DistRoot\_internal\python312.dll" "PyInstaller Python runtime is missing"
Assert-Exists "$DistRoot\_internal\ui\dist" "Bundled frontend build is missing"
Assert-Exists "$DistRoot\_internal\skills" "Bundled skills folder is missing"
Assert-Exists "$DistRoot\_internal\assets" "Bundled assets folder is missing"
Assert-Exists "$DistRoot\_internal\procrastinate\sql\queries.sql" "Bundled Procrastinate SQL queries are missing"
Assert-Matches "$DistRoot\_internal\procrastinate-*.dist-info\METADATA" "Bundled Procrastinate package metadata is missing"

Write-Host "Creating release folder..."
New-Item -ItemType Directory -Force $ReleaseRoot | Out-Null
Copy-Item "$DistRoot\*" $ReleaseRoot -Recurse -Force
New-Item -ItemType Directory -Force "$ReleaseRoot\sandbox" | Out-Null
Copy-Item "docker-compose.yml" "$ReleaseRoot\docker-compose.yml" -Force
Copy-Item ".env.example" "$ReleaseRoot\.env.example" -Force
Copy-Item "sandbox\Dockerfile" "$ReleaseRoot\sandbox\Dockerfile" -Force

@'
@echo off
setlocal
cd /d "%~dp0"

echo Orrery Windows Preview
echo ======================
echo.

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

if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
  )
)

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker was not found in PATH.
  echo Start PostgreSQL with pgvector yourself, or install Docker Desktop and run this launcher again.
  echo.
) else (
  echo Starting included PostgreSQL database...
  docker compose up -d
  if errorlevel 1 goto setup_failed

  echo Checking PostgreSQL readiness...
  set PG_READY=0
  for /l %%i in (1,1,30) do (
    docker exec orrery-postgres pg_isready -U orrery -d orrery >nul 2>nul
    if not errorlevel 1 (
      set PG_READY=1
      goto postgres_ready
    )
    timeout /t 2 /nobreak >nul
  )
  :postgres_ready
  if not "%PG_READY%"=="1" goto setup_failed

  echo Building sandbox image for file generation...
  docker build -t orrery-sandbox:latest sandbox
  if errorlevel 1 goto setup_failed
  echo.
)

echo Starting Orrery...
echo.
".\Orrery.exe"
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Orrery exited with code %EXITCODE%.
  echo If you started this by double-clicking, run run-orrery.bat from PowerShell to keep the full log visible.
  pause
)
exit /b %EXITCODE%

:setup_failed
echo.
echo Setup failed. Check Docker Desktop, then run run-orrery.bat again.
pause
exit /b 1
'@ | Set-Content "$ReleaseRoot\run-orrery.bat" -Encoding ascii

@'
Orrery Windows Preview
======================

Requirements:
- Windows 10/11
- Microsoft Edge WebView2 Runtime
- Docker Desktop if using the included PostgreSQL database or sandboxed file generation
- PostgreSQL with pgvector, either your own server or the included docker-compose.yml

Quick start:
1. Extract the full Orrery-Windows.zip folder. Do not copy only Orrery.exe.
2. Double-click run-orrery.bat, or run this from PowerShell:
   .\run-orrery.bat
3. If prompted for a database URL, use:
   postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery

Notes:
- Orrery.exe is a PyInstaller onedir executable. It requires the _internal folder beside it.
- In PowerShell, run .\Orrery.exe or .\run-orrery.bat. PowerShell does not run current-folder programs by name only.
- run-orrery.bat copies .env.example to .env on first run, starts Docker Compose, builds the sandbox image, then launches Orrery.
- API keys and database URLs are stored in the Windows keychain.
- Orrery binds its API to localhost and uses a per-session token.
- The preview executable uses a console window so first-run database prompts and startup errors are visible.
'@ | Set-Content "$ReleaseRoot\README-WINDOWS.txt" -Encoding utf8

Write-Host "Validating release folder..."
Assert-Exists "$ReleaseRoot\Orrery.exe" "Release executable is missing"
Assert-Exists "$ReleaseRoot\_internal\python312.dll" "Release Python runtime is missing"
Assert-Exists "$ReleaseRoot\_internal\ui\dist" "Release frontend is missing"
Assert-Exists "$ReleaseRoot\_internal\procrastinate\sql\queries.sql" "Release Procrastinate SQL queries are missing"
Assert-Matches "$ReleaseRoot\_internal\procrastinate-*.dist-info\METADATA" "Release Procrastinate package metadata is missing"
Assert-Exists "$ReleaseRoot\docker-compose.yml" "Release docker-compose.yml is missing"
Assert-Exists "$ReleaseRoot\.env.example" "Release .env.example is missing"
Assert-Exists "$ReleaseRoot\sandbox\Dockerfile" "Release sandbox Dockerfile is missing"
Assert-Exists "$ReleaseRoot\run-orrery.bat" "Release launcher is missing"
Assert-Exists "$ReleaseRoot\README-WINDOWS.txt" "Release notes are missing"

Write-Host "Creating release zip..."
New-Item -ItemType Directory -Force "release" | Out-Null
Compress-Archive -Path $ReleaseRoot -DestinationPath "release\Orrery-Windows.zip" -Force
Assert-Exists "release\Orrery-Windows.zip" "Release zip was not created"

Write-Host ""
Write-Host "Built release\Orrery-Windows.zip"
Write-Host "Publish this zip as the Windows release asset. Do not publish dist\Orrery\Orrery.exe by itself."
