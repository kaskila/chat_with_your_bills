# Stop the Chat With Your Bills server (Ollama keeps running; quit it from its tray icon if wanted).
#
#   powershell -ExecutionPolicy Bypass -File scripts\stop.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$servers = @(Get-ServerProcesses)
if ($servers.Count -eq 0) {
    Show-Message "$AppTitle is not running."
    exit 0
}
foreach ($p in $servers) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Show-Message "$AppTitle stopped. Receipts still being processed will be marked as interrupted; reprocess them after the next start."
