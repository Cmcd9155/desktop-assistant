$ErrorActionPreference = "Stop"

$LinuxRoot = "/home/cmcd9/repos/desktop-assistant"
$UiUrl = "http://127.0.0.1:5173"

Write-Host "Launching Desktop Assistant stack in WSL..."
& wsl.exe -d Ubuntu-24.04 bash -lc "cd $LinuxRoot && ./scripts/launch-desktop.sh --no-open"

if ($LASTEXITCODE -ne 0) {
  throw "WSL launcher failed with exit code $LASTEXITCODE"
}

if (Get-Command msedge.exe -ErrorAction SilentlyContinue) {
  Start-Process "msedge.exe" "--app=$UiUrl"
} elseif (Get-Command chrome.exe -ErrorAction SilentlyContinue) {
  Start-Process "chrome.exe" "--app=$UiUrl"
} else {
  Start-Process $UiUrl
}

