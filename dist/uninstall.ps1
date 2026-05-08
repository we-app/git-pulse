# git-pulse uninstaller (Windows / PowerShell)

$ErrorActionPreference = 'Stop'

$installDir   = if ($env:GIT_PULSE_INSTALL_DIR) { $env:GIT_PULSE_INSTALL_DIR } else { Join-Path $env:USERPROFILE '.claude\git-pulse' }
$settingsFile = if ($env:GIT_PULSE_SETTINGS)    { $env:GIT_PULSE_SETTINGS }    else { Join-Path $env:USERPROFILE '.claude\settings.json' }

Write-Host "git-pulse uninstaller" -ForegroundColor Cyan

$pythonCmd = $null
foreach ($c in @('python3','python')) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $pythonCmd = $c; break }
}

if ((Test-Path $settingsFile) -and $pythonCmd) {
    $pyCode = @'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
if not p.exists(): sys.exit(0)
try: s = json.loads(p.read_text(encoding="utf-8"))
except Exception: sys.exit(0)
hooks = s.get("hooks") or {}
changed = False
for evt in ("SessionStart","UserPromptSubmit"):
    if evt not in hooks: continue
    after = [e for e in hooks[evt] if "git-pulse" not in json.dumps(e)]
    if after != hooks[evt]:
        changed = True
        if after: hooks[evt] = after
        else:     del hooks[evt]
if not hooks: s.pop("hooks", None)
if changed:
    p.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    print(f"removed git-pulse hooks from {p}")
else:
    print(f"no git-pulse hooks found in {p}")
'@
    $tempPy = (New-TemporaryFile).FullName + ".py"
    Set-Content -Path $tempPy -Value $pyCode -Encoding UTF8
    & $pythonCmd $tempPy $settingsFile
    Remove-Item $tempPy -Force
} else {
    Write-Host "  no settings file or python; skipping settings cleanup"
}

if (Test-Path $installDir) {
    Remove-Item -Recurse -Force $installDir
    Write-Host "  removed $installDir"
}

$stateDir = Join-Path $env:USERPROFILE '.claude\git-pulse-data'
if (Test-Path $stateDir) {
    Write-Host "  leaving state at $stateDir (last-seen SHAs). Delete manually if you want a clean slate."
}

Write-Host ""
Write-Host "✓ git-pulse uninstalled." -ForegroundColor Green
Write-Host "  Restart Claude Code to drop the hooks from the running session."
