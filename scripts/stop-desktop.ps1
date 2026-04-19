$ErrorActionPreference = "Stop"

Write-Host "Stopping Desktop Assistant processes..."

$LinuxRoot = "/home/cmcd9/repos/desktop-assistant"
$StopCmd = @"
bash $LinuxRoot/scripts/stop-desktop.sh
"@

& wsl.exe -d Ubuntu-24.04 bash -lc $StopCmd

Write-Host ""
Write-Host "Desktop Assistant stop command completed."

