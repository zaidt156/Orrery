$ErrorActionPreference = "Stop"

# Builds the installable Windows app: a PyInstaller backend-only bundle (OrreryBackend) wrapped by
# the Electron shell, packaged with electron-builder into an NSIS installer (Start Menu + Desktop
# shortcuts, per-user install, in-app updates via electron-updater).
#
# Output: desktop\electron\dist\Orrery-<version>-win-<arch>.exe
#
# The zip release (build-windows-onedir.ps1) remains the portable, no-install option.

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..")
Set-Location $RepoRoot

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

function Assert-Exists {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Message = "Required path is missing"
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Message`: $Path"
    }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "No .venv found. Run scripts\build-windows-onedir.ps1 once (or create .venv with Python 3.12) first."
}

Write-Host "Building frontend..."
Push-Location "ui"
try {
    if (Test-Path "node_modules") {
        Invoke-Checked "npm" "install"
    } else {
        Invoke-Checked "npm" "ci"
    }
    Invoke-Checked "npm" "run" "build"
} finally {
    Pop-Location
}

Write-Host "Installing Python dependencies..."
$RequirementsFile = if (Test-Path "requirements.lock.txt") { "requirements.lock.txt" } else { "requirements.txt" }
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "-r" $RequirementsFile
Invoke-Checked ".venv\Scripts\python.exe" "-m" "pip" "install" "pyinstaller"

Write-Host "Building PyInstaller backend-only bundle (OrreryBackend)..."
if (Test-Path "dist\OrreryBackend") { Remove-Item "dist\OrreryBackend" -Recurse -Force }
Invoke-Checked ".venv\Scripts\pyinstaller.exe" `
    "--noconfirm" `
    "--clean" `
    "--onedir" `
    "--name" "OrreryBackend" `
    "--console" `
    "--icon" "assets\desktop\orrery.ico" `
    "--add-data" "assets;assets" `
    "--add-data" "ui\dist;ui\dist" `
    "--add-data" "skills;skills" `
    "--add-data" "sandbox;sandbox" `
    "--add-data" "backend\providers\model_manifest.json;backend\providers" `
    "--collect-all" "litellm" `
    "--collect-all" "tiktoken" `
    "--collect-submodules" "tiktoken_ext" `
    "--collect-all" "fastembed" `
    "--collect-all" "pptx" `
    "--collect-data" "procrastinate" `
    "--copy-metadata" "procrastinate" `
    "--copy-metadata" "pywebview" `
    "--copy-metadata" "python-pptx" `
    "--exclude-module" "PySide6" `
    "--exclude-module" "shiboken6" `
    "--exclude-module" "qtpy" `
    "--exclude-module" "PyQt5" `
    "--exclude-module" "webview.platforms.winforms" `
    "--exclude-module" "webview.platforms.edgechromium" `
    "--exclude-module" "webview.platforms.mshtml" `
    "--exclude-module" "webview.platforms.android" `
    "--exclude-module" "webview.platforms.gtk" `
    "--exclude-module" "webview.platforms.cocoa" `
    "--exclude-module" "webview.platforms.qt" `
    "--exclude-module" "webview.platforms.cef" `
    "--exclude-module" "pythonnet" `
    "--exclude-module" "clr" `
    "--exclude-module" "clr_loader" `
    "--collect-submodules" "keyring.backends" `
    "app.py"

Assert-Exists "dist\OrreryBackend\OrreryBackend.exe" "Backend executable was not created"
Assert-Exists "dist\OrreryBackend\_internal\ui\dist" "Bundled frontend build is missing"
Assert-Exists "dist\OrreryBackend\_internal\procrastinate\sql\queries.sql" "Bundled Procrastinate SQL is missing"

Write-Host "Running backend packaging probe..."
& "dist\OrreryBackend\OrreryBackend.exe" "--packaging-probe" "--backend-only"
if ($LASTEXITCODE -ne 0) {
    throw "Backend packaging probe failed"
}

Write-Host "Building Electron NSIS installer..."
Push-Location "desktop\electron"
try {
    if (Test-Path "node_modules") {
        Invoke-Checked "npm" "install"
    } else {
        Invoke-Checked "npm" "ci"
    }
    Invoke-Checked "npx" "electron-builder" "--win" "nsis" "--publish" "never"
} finally {
    Pop-Location
}

$Installer = Get-ChildItem "desktop\electron\dist" -Filter "Orrery-*-win-*.exe" | Select-Object -First 1
if (-not $Installer) {
    throw "electron-builder did not produce an installer in desktop\electron\dist"
}

Write-Host ""
Write-Host "Built installer: $($Installer.FullName)"
Write-Host "Users double-click it once; Orrery installs per-user with Start Menu and Desktop shortcuts."
