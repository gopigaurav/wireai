# Run after closing Cursor/terminals using this repo folder.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/rename-repo-folder.ps1

$parent = Split-Path -Parent $PSScriptRoot
$from = Join-Path $parent "voxprime"
$to = Join-Path $parent "groundwire"

if (Test-Path $to) {
    Write-Error "Already exists: $to"
    exit 1
}
if (-not (Test-Path $from)) {
    Write-Error "Not found: $from (maybe already renamed?)"
    exit 1
}

Rename-Item -LiteralPath $from -NewName "groundwire"
Write-Host "Renamed to $to"
Write-Host "Reopen the workspace: File -> Open Folder -> groundwire"
