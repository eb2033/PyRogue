# Build PyRogue for the browser (itch.io HTML5) with pygbag and zip it.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_web.ps1
#
# Output (all under dist\, gitignored):
#   dist\PyRogue-web-<version>.zip   index.html at the zip root; upload it to itch.io
#
# Stages build\web\ (main.py from web\main.py, plus game\, render\, web\ and the
# assets the game loads at run time), runs `pygbag --build` with our own page
# template (packaging\web\index.tmpl), then packaging\web\make_runtime.py adds a
# slimmed copy of the pygbag runtime to the zip (rt\) so the player downloads
# 8 MB from one host instead of 11 MB from pygame-web.github.io, adds LICENSE,
# THIRD_PARTY_NOTICES.txt and licenses\ (from packaging\web\) at the zip root, and
# checks the zip (the script fails if any of those is missing). Needs network
# access once: pygbag fetches its favicon and make_runtime.py
# downloads the pinned runtime (cached in build\web-runtime-cache\).
#
# Uses $env:PYTHON if set, else .venv\Scripts\python.exe, else `python` on PATH.
# The interpreter needs requirements-dev.txt installed (pygbag). Owned by WS-C;
# mirrors packaging/build_web.sh -- keep the two in step. See packaging/NOTES.md.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Exe $($Arguments -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

if ($env:PYTHON) {
    $Py = $env:PYTHON
} elseif (Test-Path '.venv\Scripts\python.exe') {
    $Py = (Resolve-Path '.venv\Scripts\python.exe').Path
} else {
    $Py = 'python'
}

$Version = (& $Py packaging\version_info.py --print-version).Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { throw 'could not read game/version.py' }
$ZipName = "PyRogue-web-$Version.zip"
$Stage = 'build\web'

Write-Host "==> PyRogue $Version for the browser (python: $Py)"

if (-not (Test-Path 'web\main.py')) {
    throw 'web\main.py is missing; the browser entry point has not landed'
}

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage, 'dist' | Out-Null

Copy-Item web\main.py "$Stage\main.py"
# Packages that main.py imports. web\main.py itself is already copied to the top.
foreach ($Pkg in 'game', 'render', 'web') {
    New-Item -ItemType Directory -Force -Path "$Stage\$Pkg" | Out-Null
    Copy-Item -Recurse -Path "$Pkg\*" -Destination "$Stage\$Pkg" -Force
}
Remove-Item -Force "$Stage\web\main.py"

# Only what the game loads at run time (see render\tileset.py, render\ui.py,
# render\pygame_render.py). icon.png/icon.ico are the desktop window icon and
# assets\ASSETS.md is the provenance table; neither is read in the browser.
New-Item -ItemType Directory -Force -Path "$Stage\assets" | Out-Null
Copy-Item assets\tiles.json "$Stage\assets\"
foreach ($Dir in 'kenney', 'blood', 'fonts') {
    Copy-Item -Recurse -Path "assets\$Dir" -Destination "$Stage\assets\" -Force
}

# Keep the staged tree clean of bytecode caches.
Get-ChildItem -Recurse -Force -Directory -Filter __pycache__ -Path $Stage |
    Remove-Item -Recurse -Force
Get-ChildItem -Recurse -Force -File -Filter '*.pyc' -Path $Stage | Remove-Item -Force

Invoke-Checked $Py @('-m', 'pygbag', '--build', '--ume_block', '0', '--template', 'packaging\web\index.tmpl', '--title', 'PyRogue', $Stage)

$Built = "$Stage\build\web"
Invoke-Checked $Py @('packaging\web\make_runtime.py', $Built, "dist\$ZipName", '--cache', 'build\web-runtime-cache')

# The zip redistributes third-party binaries (rt\): fail unless it carries their notices.
Invoke-Checked $Py @('packaging\web\make_runtime.py', '--verify', "dist\$ZipName")

$ZipBytes = (Get-Item "dist\$ZipName").Length
Write-Host ("==> dist\{0} ({1:N1} MB)" -f $ZipName, ($ZipBytes / 1MB))
