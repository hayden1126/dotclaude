# chrome-debug.ps1 — launch Windows Chrome with a remote-debugging port so that
# chrome-devtools-mcp running inside WSL can attach via --browserUrl (Strategy B
# in docs/chrome-devtools-wsl.md). Works because WSL networkingMode=mirrored
# shares localhost between Windows and WSL.
#
# Usage (from Windows PowerShell, or a desktop shortcut):
#   powershell -ExecutionPolicy Bypass -File chrome-debug.ps1
#   powershell -ExecutionPolicy Bypass -File chrome-debug.ps1 -Port 9222
#   # real profile (quit Chrome first): -UserDataDir "$env:LocalAppData\Google\Chrome\User Data"

param(
  [int]$Port = 9222,
  [string]$UserDataDir = "$env:TEMP\chrome-debug-$Port",
  [string]$ChromePath
)

if (-not $ChromePath) {
  $candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
  )
  $ChromePath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $ChromePath) {
  Write-Error "Chrome not found in the usual locations. Pass -ChromePath 'C:\path\to\chrome.exe'."
  exit 1
}

Write-Host "Launching Chrome on debug port $Port"
Write-Host "  binary : $ChromePath"
Write-Host "  profile: $UserDataDir"
Write-Host "Attach from WSL with --browserUrl=http://localhost:$Port"

& $ChromePath `
  --remote-debugging-port=$Port `
  --user-data-dir="$UserDataDir" `
  --no-first-run `
  --no-default-browser-check
