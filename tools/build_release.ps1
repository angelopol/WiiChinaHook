# Build the Windows release: dist\WiiChinaHook\ (one-folder app) and
# dist\WiiChinaHook-<version>-win64.zip. Needs: pip install -e .[gui,release]
# Usage: powershell -ExecutionPolicy Bypass -File tools\build_release.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venv = Test-Path ".venv\Scripts\python.exe"
$python = if ($venv) { ".venv\Scripts\python.exe" } else { "python" }
$flet = if ($venv) { ".venv\Scripts\flet.exe" } else { "flet" }
$version = (Select-String -Path src\wiichinahook\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$fileVersion = "$version.0"
Write-Host "Building WiiChinaHook $version"

Remove-Item -Recurse -Force "build", "dist\WiiChinaHook" -ErrorAction SilentlyContinue

# One folder (-D) instead of one file: starts faster (nothing to unpack on every
# launch, which matters when it starts with Windows) and keeps the LGPL libraries
# as replaceable files.
& $flet pack tools\gui_entry.py `
    --name WiiChinaHook `
    --icon src\wiichinahook\gui\assets\icon.ico `
    -D --distpath dist -y `
    --add-data "src\wiichinahook\gui\assets:wiichinahook\gui\assets" "docs\guides:wiichinahook\gui\guides" `
    --product-name WiiChinaHook `
    --file-description "WiiChinaHook - Wiimote clones for Dolphin, Cemu and Xbox games" `
    --product-version $version --file-version $fileVersion `
    --copyright "Copyright (c) 2026 Angelo Polgrossi. MIT License." `
    --pyinstaller-build-args=--collect-all=vgamepad --pyinstaller-build-args=--collect-all=libusb_package `
    --pyinstaller-build-args=--collect-submodules=bumble --pyinstaller-build-args=--noupx --pyinstaller-build-args=--paths=src
if ($LASTEXITCODE -ne 0) { throw "flet pack failed ($LASTEXITCODE)" }

$app = "dist\WiiChinaHook"
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md, README.md, README.es.md $app
New-Item -ItemType Directory -Force "$app\docs" | Out-Null
Copy-Item -Recurse -Force docs\guides "$app\docs\guides"

$zip = "dist\WiiChinaHook-$version-win64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
& $python tools\zip_release.py $app $zip
if ($LASTEXITCODE -ne 0) { throw "zip failed" }
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $zip)" | Out-File -Encoding ascii "$zip.sha256"
Write-Host "Done: $zip"
Write-Host "SHA-256: $hash"
