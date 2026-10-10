# Install Chat With Your Bills on this computer (safe to run again: it only does what is missing).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-Autostart] [-NoShortcuts] [-SkipModels]
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -RemoveShortcuts
#
#   1. Python virtual environment (.venv) with the packages in requirements.txt
#   2. Ollama check, and the models (qwen3:4b ~2.5 GB, glm-ocr ~2.2 GB; skipped if present)
#   3. Self-check (python -m app.cli check; also downloads the OCR model files)
#   4. Shortcuts: Desktop + Start menu; with -Autostart also start with Windows (no browser)

param([switch]$Autostart, [switch]$NoShortcuts, [switch]$SkipModels, [switch]$RemoveShortcuts)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$Desktop = [Environment]::GetFolderPath('Desktop')
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) $AppTitle
$StartupLink = Join-Path ([Environment]::GetFolderPath('Startup')) "$AppTitle.lnk"

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

function New-Shortcut([string]$Path, [string]$ScriptArgs, [string]$Description) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden $ScriptArgs"
    $link.WorkingDirectory = $Root
    $link.IconLocation = Join-Path $PSScriptRoot 'app.ico'
    $link.Description = $Description
    $link.WindowStyle = 7  # minimized: no console window flashing up
    $link.Save()
}

if ($RemoveShortcuts) {
    foreach ($p in @((Join-Path $Desktop "$AppTitle.lnk"), $StartupLink)) { Remove-Item $p -ErrorAction SilentlyContinue }
    Remove-Item $StartMenu -Recurse -ErrorAction SilentlyContinue
    Write-Host 'Shortcuts removed. (The app folder, its data and Ollama are untouched.)'
    exit 0
}

# ---------------------------------------------------------------- 1. Python
Step 'Python'
if (-not (Test-Path $VenvPython)) {
    $python = $null
    try { $python = (& py -3.14 -c 'import sys; print(sys.executable)' 2>$null) } catch { }
    if (-not $python) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) {
            $ok = & $cmd.Source -c 'import sys; print(sys.version_info >= (3, 12))'
            if ($ok -eq 'True') { $python = $cmd.Source }
        }
    }
    if (-not $python) {
        Show-Message 'Python 3.14 is needed. Install it from https://www.python.org/downloads/ (tick "Add to PATH"), then run this again.' -IsError
        exit 1
    }
    Write-Host "Creating .venv with $python"
    & $python -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { Show-Message 'Could not create the virtual environment.' -IsError; exit 1 }
}
Write-Host 'Installing packages (first time: a few minutes)...'
& $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    $hint = ''
    # Some package files are ~130 characters deep inside .venv; Windows limits paths to 260 by default.
    if ($Root.Length -gt 100) { $hint = "`n`nThe project folder path is long ($($Root.Length) characters). Move the folder somewhere shorter (for example C:\dev\chat_with_your_bills) or enable Windows long paths, then run this again." }
    Show-Message "Installing the Python packages failed; see the messages above.$hint" -IsError
    exit 1
}

# ---------------------------------------------------------------- 2. Ollama and models
Step 'Ollama'
$ollama = Get-OllamaExe
if (-not $ollama) {
    Show-Message ("Ollama (runs the AI models locally) is not installed.`n`nInstall it from https://ollama.com/download " +
        "or with: winget install Ollama.Ollama`nthen run this script again.") -IsError
    exit 1
}
if (-not (Start-OllamaIfNeeded)) { Show-Message 'Ollama is installed but did not start. Start the Ollama app, then run this again.' -IsError; exit 1 }
Write-Host "Ollama is running ($ollama)"

if (-not $SkipModels) {
    $installed = (& $ollama list) -join "`n"
    foreach ($model in @('qwen3:4b', 'glm-ocr')) {
        $name = $model
        if ($model -notlike "*:*") { $name = "${model}:latest" }
        if ($installed -like "*$name*") { Write-Host "$model already installed"; continue }
        Write-Host "Downloading $model (this can take a while)..."
        & $ollama pull $model
        if ($LASTEXITCODE -ne 0) { Show-Message "Downloading $model failed. Check the internet connection and run this again." -IsError; exit 1 }
    }
}

# ---------------------------------------------------------------- 3. Self-check
Step 'Self-check'
Push-Location $Root
try { & $VenvPython -m app.cli check } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Show-Message 'The self-check found a problem; see the messages above.' -IsError; exit 1 }

# ---------------------------------------------------------------- 4. Shortcuts
if (-not $NoShortcuts) {
    Step 'Shortcuts'
    $start = "-File `"$PSScriptRoot\start.ps1`""
    New-Item -ItemType Directory -Force $StartMenu | Out-Null
    New-Shortcut (Join-Path $Desktop "$AppTitle.lnk") $start 'Start Chat With Your Bills and open it in the browser'
    New-Shortcut (Join-Path $StartMenu "$AppTitle.lnk") $start 'Start Chat With Your Bills and open it in the browser'
    New-Shortcut (Join-Path $StartMenu "$AppTitle (phone access).lnk") "$start -Lan" 'Start with access for phones on the same Wi-Fi'
    New-Shortcut (Join-Path $StartMenu "Stop $AppTitle.lnk") "-File `"$PSScriptRoot\stop.ps1`"" 'Stop the Chat With Your Bills server'
    Write-Host "Desktop: $AppTitle; Start menu: $AppTitle (start, phone access, stop)"
    if ($Autostart) {
        New-Shortcut $StartupLink "$start -NoBrowser" 'Start Chat With Your Bills when Windows starts'
        Write-Host 'It will also start when you sign in to Windows (remove with -RemoveShortcuts).'
    }
}

Write-Host "`nDone. Double-click '$AppTitle' on the desktop to start." -ForegroundColor Green
