# Make the app reachable from your phone anywhere, through Tailscale (private to your own devices).
#
#   powershell -ExecutionPolicy Bypass -File scripts\phone-access.ps1        # turn on (once; it stays on)
#   powershell -ExecutionPolicy Bypass -File scripts\phone-access.ps1 -Off   # turn off
#
# Needs Tailscale installed and signed in on this computer and the phone (same account), with
# MagicDNS and HTTPS certificates enabled at https://login.tailscale.com/admin/dns.
# Uses "tailscale serve" (your devices only). Never use "tailscale funnel" (public internet).

param([switch]$Off, [int]$Port = 8000)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts) { $ts = 'C:\Program Files\Tailscale\tailscale.exe' }
if (-not (Test-Path $ts)) {
    Show-Message 'Tailscale is not installed. Get it from https://tailscale.com/download, sign in, then run this again.' -IsError
    exit 1
}

$status = (& $ts status --json) | ConvertFrom-Json
if ($status.BackendState -ne 'Running') {
    Show-Message 'Tailscale is not signed in on this computer. Click the Tailscale icon in the taskbar tray, choose Log in, then run this again.' -IsError
    exit 1
}

if ($Off) {
    & $ts serve --https=443 off
    Show-Message 'Phone access through Tailscale is off.'
    exit 0
}

$dns = "$($status.Self.DNSName)".TrimEnd('.')
if (-not $dns) {
    Show-Message 'Tailscale has no name for this computer. Turn on MagicDNS at https://login.tailscale.com/admin/dns, then run this again.' -IsError
    exit 1
}

# --bg: keeps serving after this script ends and after restarts, until turned off with -Off.
& $ts serve --bg --https=443 "http://127.0.0.1:$Port"
if ($LASTEXITCODE -ne 0) {
    Show-Message 'Tailscale could not share the app. If it mentions HTTPS, turn on HTTPS certificates at https://login.tailscale.com/admin/dns.' -IsError
    exit 1
}

$url = "https://$dns/"
Write-Host ''
Write-Host "On your phone (Tailscale on, same account), open:  $url" -ForegroundColor Green
Write-Host 'The first visit can take up to a minute while Tailscale gets the HTTPS certificate.'
Write-Host 'The app must be running on this computer (Desktop shortcut). The QR code is on the System page.'
if (-not (Test-App $Port)) { Write-Host 'Note: the app is not running right now. Start it with the Desktop shortcut.' -ForegroundColor Yellow }
