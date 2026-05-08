# git-pulse installer (Windows / PowerShell)
#
# Usage:
#   irm https://raw.githubusercontent.com/we-app/git-pulse/main/install.ps1 | iex
# or, with a downloaded copy:
#   pwsh -File install.ps1
#
# Installs into %USERPROFILE%\.claude\git-pulse and registers hooks
# in %USERPROFILE%\.claude\settings.json. Works for both Claude Code
# CLI and Desktop app on Windows.

$ErrorActionPreference = 'Stop'

$repoUrl     = if ($env:GIT_PULSE_REPO)         { $env:GIT_PULSE_REPO }         else { 'https://github.com/we-app/git-pulse.git' }
$installDir  = if ($env:GIT_PULSE_INSTALL_DIR)  { $env:GIT_PULSE_INSTALL_DIR }  else { Join-Path $env:USERPROFILE '.claude\git-pulse' }
$settingsFile= if ($env:GIT_PULSE_SETTINGS)     { $env:GIT_PULSE_SETTINGS }     else { Join-Path $env:USERPROFILE '.claude\settings.json' }

Write-Host "git-pulse installer" -ForegroundColor Cyan

# Require git + python (python3 or python)
$pythonCmd = $null
foreach ($c in @('python3','python')) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $pythonCmd = $c; break }
}
if (-not $pythonCmd) { throw "python (3.x) is required and was not found in PATH" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required and was not found in PATH" }

# Clone or update
if (Test-Path (Join-Path $installDir '.git')) {
    Write-Host "  Updating $installDir"
    git -C $installDir fetch --quiet origin main
    git -C $installDir reset --hard --quiet origin/main
} else {
    Write-Host "  Cloning into $installDir"
    if (Test-Path $installDir) { Remove-Item -Recurse -Force $installDir }
    New-Item -ItemType Directory -Force -Path (Split-Path $installDir) | Out-Null
    git clone --quiet --depth 1 $repoUrl $installDir
}

$script = Join-Path $installDir 'git-pulse\scripts\git-pulse.py'
if (-not (Test-Path $script)) { throw "expected script not found: $script" }

# Make sure settings dir exists
$settingsDir = Split-Path $settingsFile
if (-not (Test-Path $settingsDir)) { New-Item -ItemType Directory -Force -Path $settingsDir | Out-Null }

# Inject hooks via a small Python helper (safe JSON merge)
$pyCode = @'
import json, sys, pathlib
settings_path = pathlib.Path(sys.argv[1])
script = sys.argv[2]
py_cmd = sys.argv[3]

settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
hooks = settings.setdefault("hooks", {})

def filter_existing(entries, marker):
    return [e for e in entries if marker not in json.dumps(e)]

ss = hooks.setdefault("SessionStart", [])
ss[:] = filter_existing(ss, "git-pulse")
ss.append({
    "matcher": "startup|resume|clear|compact",
    "hooks": [{
        "type": "command",
        "command": f'{py_cmd} "{script}" session-start',
        "timeout": 30,
    }],
})

ups = hooks.setdefault("UserPromptSubmit", [])
ups[:] = filter_existing(ups, "git-pulse")
ups.append({
    "hooks": [{
        "type": "command",
        "command": f'{py_cmd} "{script}" user-prompt-submit',
        "timeout": 30,
    }],
})

settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
'@

$tempPy = New-TemporaryFile
Rename-Item $tempPy.FullName "$($tempPy.FullName).py" -Force
$tempPy = "$($tempPy.FullName).py"
Set-Content -Path $tempPy -Value $pyCode -Encoding UTF8

& $pythonCmd $tempPy $settingsFile $script $pythonCmd
Remove-Item $tempPy -Force

Write-Host ""
Write-Host "✓ git-pulse installed." -ForegroundColor Green
Write-Host "  Script:  $script"
Write-Host "  Hooks:   $settingsFile"
Write-Host ""
Write-Host "  Restart your Claude Code session (CLI or Desktop app) to activate."
Write-Host "  Upgrade later: pwsh -File `"$installDir\install.ps1`""
Write-Host "  Uninstall:     pwsh -File `"$installDir\dist\uninstall.ps1`""
