# Keep ui/node_modules OUT of OneDrive.
#
# This project lives under OneDrive, which syncs/locks files mid-write and
# corrupts node_modules (partial extractions -> "Cannot find module"). This
# script moves ui/node_modules to %LOCALAPPDATA%\orrery\node_modules and
# replaces it with a directory junction.
#
# Run it after EVERY `npm install` (npm recreates a real folder, clobbering the
# junction). It is wired to `npm run relink-deps` in ui/package.json.

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$uiDir       = Join-Path $projectRoot 'ui'
$link        = Join-Path $uiDir 'node_modules'
$targetRoot  = Join-Path $env:LOCALAPPDATA 'orrery'
# The junction target MUST itself be named node_modules, or Node's realpath-based
# resolution fails for nested deps (e.g. vite -> esbuild).
$target      = Join-Path $targetRoot 'node_modules'

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

$item = Get-Item -LiteralPath $link -ErrorAction SilentlyContinue
if ($item -and $item.LinkType -eq 'Junction') {
    Write-Host "OK: node_modules already junctioned -> $($item.Target)"
    exit 0
}

if (Test-Path -LiteralPath $link) {
    # A real node_modules exists (fresh npm install). Move it out.
    if (Test-Path -LiteralPath $target) {
        Write-Host "Replacing previous external node_modules ..."
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    Write-Host "Moving fresh node_modules out of OneDrive ..."
    Move-Item -LiteralPath $link -Destination $target
} elseif (-not (Test-Path -LiteralPath $target)) {
    New-Item -ItemType Directory -Force -Path $target | Out-Null
}

New-Item -ItemType Junction -Path $link -Target $target | Out-Null
Write-Host "Linked $link -> $target"
