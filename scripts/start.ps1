# Start Chat With Your Bills: Ollama (if needed), the server (in the background), then the browser.
# Used by the desktop shortcut. Running it again while the app runs just opens the browser.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1 [-Lan] [-NoBrowser] [-Port 8000]
#
#   -Lan        also allow phones on the same Wi-Fi (random access key; QR code on the System page)
#   -NoBrowser  do not open the browser (used when starting with Windows)

param([switch]$Lan, [switch]$NoBrowser, [int]$Port = 8000)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$Url = "http://127.0.0.1:$Port"

function Open-App {
    if (-not $NoBrowser) {
        $page = '/'
        if ($Lan) { $page = '/#/system' }  # shows the phone link and QR code
        Start-Process ($Url + $page)
    }
}

if (-not (Test-Path $VenvPython)) {
    Show-Message "The app is not installed yet. Run scripts\install.ps1 first." -IsError
    exit 1
}

if (Test-App $Port) {
    Write-Host "Already running at $Url"
    if ($Lan) { Write-Host 'Note: it was started earlier; phone access only works if that start used -Lan.' }
    Open-App
    exit 0
}
if (Test-PortBusy $Port) {
    Show-Message "Port $Port is used by another program. Close it, or start with -Port 8001." -IsError
    exit 1
}

if (-not (Start-OllamaIfNeeded)) {
    Show-Message "Ollama is not installed or did not start. Install it from https://ollama.com, then try again." -IsError
    exit 1
}

$logs = Join-Path $Root 'data\logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs 'server.log'
$arguments = @('-m', 'app.cli', 'serve', '--port', "$Port", '--log-file', "`"$log`"")
if ($Lan) { $arguments += '--lan' }

# No output redirection here: the server writes its own log, so nothing waits on this script.
Start-Process $VenvPython -ArgumentList $arguments -WorkingDirectory $Root -WindowStyle Hidden | Out-Null

Write-Host 'Starting the server...'
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    if (Test-App $Port) {
        Write-Host "Running at $Url (logs: data\logs). Stop it with the 'Stop $AppTitle' shortcut or scripts\stop.ps1."
        Open-App
        exit 0
    }
}
$tail = ''
if (Test-Path $log) { $tail = (Get-Content $log -Tail 8) -join "`n" }
Show-Message "The server did not start within 90 seconds.`n`n$tail`n`nFull log: $log" -IsError
exit 1
