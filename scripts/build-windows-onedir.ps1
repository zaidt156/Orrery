$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..")
Set-Location $RepoRoot

$RequiredPythonVersion = "3.12.0"

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

function Assert-VenvPythonVersion {
    $version = & ".venv\Scripts\python.exe" -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read Python version from .venv"
    }
    if ($version.Trim() -ne $RequiredPythonVersion) {
        throw "Windows release builds currently require Python $RequiredPythonVersion. Found $($version.Trim()). Recreate .venv with Python $RequiredPythonVersion before building."
    }
}

function New-ReleaseVenv {
    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python) {
        & "python" "-m" "venv" ".venv"
    } else {
        & "py" "-3.12" "-m" "venv" ".venv"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create .venv. Install Python $RequiredPythonVersion and try again."
    }
}

function Invoke-PackagingProbe {
    param([Parameter(Mandatory = $true)][string]$ExePath)

    Write-Host "Running packaged desktop runtime probe..."
    & $ExePath "--packaging-probe"
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged desktop runtime probe failed for $ExePath"
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
    New-ReleaseVenv
}
Assert-VenvPythonVersion

Write-Host "Installing Python dependencies..."
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "--upgrade" "pip"
$RequirementsFile = if (Test-Path "requirements.lock.txt") { "requirements.lock.txt" } else { "requirements.txt" }
Write-Host "Installing from $RequirementsFile..."
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "-r" $RequirementsFile
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "pyinstaller"

$PythonnetHookDir = (& ".venv\Scripts\python.exe" -c "import pathlib, pythonnet; print(pathlib.Path(pythonnet.__file__).resolve().parent / '_pyinstaller')")
if ($LASTEXITCODE -ne 0) { throw "Could not resolve pythonnet PyInstaller hook path" }
$WebviewHookDir = (& ".venv\Scripts\python.exe" -c "import pathlib, webview; print(pathlib.Path(webview.__file__).resolve().parent / '__pyinstaller')")
if ($LASTEXITCODE -ne 0) { throw "Could not resolve pywebview PyInstaller hook path" }

Write-Host "Building PyInstaller onedir package..."
Invoke-Checked ".venv\Scripts\pyinstaller.exe" `
    "--noconfirm" `
    "--clean" `
    "--onedir" `
    "--name" "Orrery" `
    "--console" `
    "--icon" "assets\desktop\orrery.ico" `
    "--additional-hooks-dir" $PythonnetHookDir `
    "--additional-hooks-dir" $WebviewHookDir `
    "--add-data" "assets;assets" `
    "--add-data" "ui\dist;ui\dist" `
    "--add-data" "skills;skills" `
    "--add-data" "sandbox;sandbox" `
    "--add-data" "backend\providers\model_manifest.json;backend\providers" `
    "--collect-all" "litellm" `
    "--collect-all" "fastembed" `
    "--collect-all" "webview" `
    "--collect-all" "pythonnet" `
    "--collect-all" "clr_loader" `
    "--collect-data" "procrastinate" `
    "--copy-metadata" "procrastinate" `
    "--copy-metadata" "pywebview" `
    "--copy-metadata" "pythonnet" `
    "--copy-metadata" "clr_loader" `
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
Assert-Exists "$DistRoot\_internal\pythonnet\runtime\Python.Runtime.dll" "Bundled pythonnet runtime is missing"
Assert-Exists "$DistRoot\_internal\clr_loader\ffi\dlls\amd64\ClrLoader.dll" "Bundled clr_loader native bridge is missing"
Assert-Matches "$DistRoot\_internal\pythonnet-*.dist-info\METADATA" "Bundled pythonnet package metadata is missing"
Assert-Matches "$DistRoot\_internal\clr_loader-*.dist-info\METADATA" "Bundled clr_loader package metadata is missing"
Invoke-PackagingProbe "$DistRoot\Orrery.exe"

Write-Host "Creating release folder..."
New-Item -ItemType Directory -Force $ReleaseRoot | Out-Null
Copy-Item "$DistRoot\*" $ReleaseRoot -Recurse -Force
New-Item -ItemType Directory -Force "$ReleaseRoot\sandbox" | Out-Null
Copy-Item "docker-compose.yml" "$ReleaseRoot\docker-compose.yml" -Force
Copy-Item ".env.example" "$ReleaseRoot\.env.example" -Force
Copy-Item "sandbox\Dockerfile" "$ReleaseRoot\sandbox\Dockerfile" -Force
Copy-Item "scripts\windows\setup-orrery.bat" "$ReleaseRoot\setup-orrery.bat" -Force
Copy-Item "scripts\windows\run-orrery.bat" "$ReleaseRoot\run-orrery.bat" -Force
Copy-Item "scripts\windows\README-WINDOWS.txt" "$ReleaseRoot\README-WINDOWS.txt" -Force

Write-Host "Validating release folder..."
Assert-Exists "$ReleaseRoot\Orrery.exe" "Release executable is missing"
Assert-Exists "$ReleaseRoot\_internal\python312.dll" "Release Python runtime is missing"
Assert-Exists "$ReleaseRoot\_internal\ui\dist" "Release frontend is missing"
Assert-Exists "$ReleaseRoot\_internal\procrastinate\sql\queries.sql" "Release Procrastinate SQL queries are missing"
Assert-Matches "$ReleaseRoot\_internal\procrastinate-*.dist-info\METADATA" "Release Procrastinate package metadata is missing"
Assert-Exists "$ReleaseRoot\_internal\pythonnet\runtime\Python.Runtime.dll" "Release pythonnet runtime is missing"
Assert-Exists "$ReleaseRoot\_internal\clr_loader\ffi\dlls\amd64\ClrLoader.dll" "Release clr_loader native bridge is missing"
Assert-Matches "$ReleaseRoot\_internal\pythonnet-*.dist-info\METADATA" "Release pythonnet package metadata is missing"
Assert-Matches "$ReleaseRoot\_internal\clr_loader-*.dist-info\METADATA" "Release clr_loader package metadata is missing"
Assert-Exists "$ReleaseRoot\docker-compose.yml" "Release docker-compose.yml is missing"
Assert-Exists "$ReleaseRoot\.env.example" "Release .env.example is missing"
Assert-Exists "$ReleaseRoot\sandbox\Dockerfile" "Release sandbox Dockerfile is missing"
Assert-Exists "$ReleaseRoot\setup-orrery.bat" "Release setup launcher is missing"
Assert-Exists "$ReleaseRoot\run-orrery.bat" "Release launcher is missing"
Assert-Exists "$ReleaseRoot\README-WINDOWS.txt" "Release notes are missing"
Invoke-PackagingProbe "$ReleaseRoot\Orrery.exe"

Write-Host "Creating release zip..."
New-Item -ItemType Directory -Force "release" | Out-Null
Compress-Archive -Path $ReleaseRoot -DestinationPath "release\Orrery-Windows.zip" -Force
Assert-Exists "release\Orrery-Windows.zip" "Release zip was not created"

Write-Host ""
Write-Host "Built release\Orrery-Windows.zip"
Write-Host "Publish this zip as the Windows release asset. Do not publish dist\Orrery\Orrery.exe by itself."
