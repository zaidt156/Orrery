# Create the Python virtual environment OUTSIDE OneDrive and junction it in.
#
# Same reason as node_modules: OneDrive syncing thousands of venv files is slow
# and can corrupt them. The real venv lives at %LOCALAPPDATA%\orrery\.venv and
# the project's ".venv" is a junction to it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup\setup-venv.ps1

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$link        = Join-Path $projectRoot '.venv'
$targetRoot  = Join-Path $env:LOCALAPPDATA 'orrery'
$target      = Join-Path $targetRoot '.venv'

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

# Create the venv at the external location if it isn't there yet.
if (-not (Test-Path -LiteralPath (Join-Path $target 'Scripts\python.exe'))) {
    Write-Host "Creating virtual environment at $target ..."
    py -3.12 -m venv $target
}

# (Re)create the junction.
$item = Get-Item -LiteralPath $link -ErrorAction SilentlyContinue
if ($item -and $item.LinkType -ne 'Junction') {
    Remove-Item -LiteralPath $link -Recurse -Force
    $item = $null
}
if (-not $item) {
    New-Item -ItemType Junction -Path $link -Target $target | Out-Null
}
Write-Host "Linked $link -> $target"
Write-Host "Activate with:  .\.venv\Scripts\Activate.ps1"
