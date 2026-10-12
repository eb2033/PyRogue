# Build PyRogue for Windows with PyInstaller and zip it.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
# Output (all under dist\, gitignored):
#   dist\PyRogue\                          the onedir bundle; run dist\PyRogue\PyRogue.exe
#   dist\PyRogue-windows-<version>.zip     the bundle + LICENSE + README.txt
#
# Uses $env:PYTHON if set, else .venv\Scripts\python.exe, else `python` on PATH.
# The interpreter needs requirements.txt and requirements-dev.txt installed.
# Owned by WS-E; mirrors packaging/build.sh -- keep the two in step. See
# packaging/NOTES.md.

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
$Platform = 'windows'
$ZipName = "PyRogue-$Platform-$Version.zip"

Write-Host "==> PyRogue $Version for $Platform (python: $Py)"

foreach ($dir in 'build', 'dist') {
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
}

Invoke-Checked $Py @('-m', 'PyInstaller', '--noconfirm', '--clean',
    '--distpath', 'dist', '--workpath', 'build', 'packaging\pyrogue.spec')

$Bundle = 'dist\PyRogue'
if (-not (Test-Path "$Bundle\PyRogue.exe")) {
    throw "$Bundle\PyRogue.exe was not produced"
}

Copy-Item LICENSE, packaging\README.txt -Destination $Bundle

Invoke-Checked $Py @('packaging\make_zip.py', $Bundle, "dist\$ZipName")

$Bytes = (Get-ChildItem -Recurse -File $Bundle | Measure-Object -Sum Length).Sum
$ZipBytes = (Get-Item "dist\$ZipName").Length
Write-Host ("==> {0} ({1:N1} MB unzipped)" -f $Bundle, ($Bytes / 1MB))
Write-Host ("==> dist\{0} ({1:N1} MB)" -f $ZipName, ($ZipBytes / 1MB))
