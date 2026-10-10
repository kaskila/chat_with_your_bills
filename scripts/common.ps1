# Shared helpers for install.ps1, start.ps1 and stop.ps1 (Windows PowerShell 5.1 and later).

$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$OllamaUrl = 'http://localhost:11434'
$AppTitle = 'Chat With Your Bills'

function Show-Message([string]$Text, [switch]$IsError) {
    # Shortcuts run without a visible console, so problems are shown in a window too.
    Write-Host $Text
    if ($env:BILLS_NO_POPUP -or -not [Environment]::UserInteractive) { return }
    $icon = 64
    if ($IsError) { $icon = 16 }
    try { (New-Object -ComObject WScript.Shell).Popup($Text, 0, $AppTitle, $icon) | Out-Null } catch { }
}

function Get-OllamaExe {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $default = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $default) { return $default }
    return $null
}

function Test-Ollama {
    try { Invoke-RestMethod "$OllamaUrl/api/tags" -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}

function Start-OllamaIfNeeded {
    # Returns $true when Ollama answers (starting it if needed), $false otherwise.
    if (Test-Ollama) { return $true }
    $exe = Get-OllamaExe
    if (-not $exe) { return $false }
    $tray = Join-Path (Split-Path $exe) 'ollama app.exe'
    if (Test-Path $tray) {
        Start-Process $tray  # the normal Ollama app (tray icon); it starts the server
    } else {
        Start-Process $exe -ArgumentList 'serve' -WindowStyle Hidden
    }
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Ollama) { return $true }
    }
    return $false
}

function Test-App([int]$Port) {
    # $true if Chat With Your Bills answers on this port.
    try {
        $page = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
        return $page.Content -like "*$AppTitle*"
    } catch { return $false }
}

function Test-PortBusy([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $client.Close() }
}

function Get-ServerProcesses {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*-m app.cli serve*' }
}
