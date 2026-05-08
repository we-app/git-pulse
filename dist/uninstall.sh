#!/usr/bin/env bash
# git-pulse uninstaller — removes hooks from ~/.claude/settings.json
# and deletes the install directory.

set -euo pipefail

INSTALL_DIR="${GIT_PULSE_INSTALL_DIR:-$HOME/.claude/git-pulse}"
SETTINGS="${GIT_PULSE_SETTINGS:-$HOME/.claude/settings.json}"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
info() { printf "  %s\n" "$*"; }

bold "git-pulse uninstaller"

if [ -f "$SETTINGS" ]; then
    python3 - "$SETTINGS" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
if not p.exists():
    sys.exit(0)
try:
    s = json.loads(p.read_text())
except Exception:
    sys.exit(0)
hooks = s.get("hooks") or {}
changed = False
for evt in ("SessionStart", "UserPromptSubmit"):
    if evt not in hooks:
        continue
    before = hooks[evt]
    after = [e for e in before if "git-pulse" not in json.dumps(e)]
    if after != before:
        changed = True
        if after:
            hooks[evt] = after
        else:
            del hooks[evt]
if not hooks:
    s.pop("hooks", None)
if changed:
    p.write_text(json.dumps(s, indent=2) + "\n")
    print(f"removed git-pulse hooks from {p}")
else:
    print(f"no git-pulse hooks found in {p}")
PY
else
    info "no settings file at $SETTINGS"
fi

if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    info "removed $INSTALL_DIR"
fi

# Optional: clean state directory ($CLAUDE_PLUGIN_DATA fallback)
STATE_DIR="$HOME/.claude/git-pulse-data"
if [ -d "$STATE_DIR" ]; then
    info "leaving state at $STATE_DIR (last-seen SHAs). Delete manually if you want a clean slate."
fi

bold ""
bold "✓ git-pulse uninstalled."
info "Restart Claude Code to drop the hooks from the running session."
