#!/usr/bin/env bash
# git-pulse installer (curl | bash compatible)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/we-app/git-pulse/main/install.sh | bash
# or, with a downloaded copy:
#   bash install.sh
#
# Installs the git-pulse Claude Code plugin into ~/.claude/git-pulse/
# and registers SessionStart + UserPromptSubmit hooks in
# ~/.claude/settings.json. Works in both Claude Code CLI and the
# Claude Code Desktop app — they share the same config directory.
#
# Idempotent: re-running upgrades the install and replaces any
# prior git-pulse hook entries cleanly.

set -euo pipefail

REPO_URL="${GIT_PULSE_REPO:-https://github.com/we-app/git-pulse.git}"
INSTALL_DIR="${GIT_PULSE_INSTALL_DIR:-$HOME/.claude/git-pulse}"
SETTINGS="${GIT_PULSE_SETTINGS:-$HOME/.claude/settings.json}"

bold() { printf "\033[1m%s\033[0m\n" "$*"; }
info() { printf "  %s\n" "$*"; }
fail() { printf "\033[31merror:\033[0m %s\n" "$*" >&2; exit 1; }

require() {
    command -v "$1" >/dev/null 2>&1 || fail "required tool not found in PATH: $1"
}

bold "git-pulse installer"

require git
require python3

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing install at $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch --quiet origin main
    git -C "$INSTALL_DIR" reset --hard --quiet origin/main
else
    info "Cloning into $INSTALL_DIR"
    if [ -e "$INSTALL_DIR" ]; then rm -rf "$INSTALL_DIR"; fi
    git clone --quiet --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

SCRIPT="$INSTALL_DIR/git-pulse/scripts/git-pulse.py"
[ -f "$SCRIPT" ] || fail "expected script not found: $SCRIPT"

mkdir -p "$(dirname "$SETTINGS")"

python3 - "$SETTINGS" "$SCRIPT" <<'PY'
import json, sys, pathlib

settings_path = pathlib.Path(sys.argv[1])
script = sys.argv[2]

settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
hooks = settings.setdefault("hooks", {})

def filter_existing(entries, marker):
    return [e for e in entries if marker not in json.dumps(e)]

ss = hooks.setdefault("SessionStart", [])
ss[:] = filter_existing(ss, "git-pulse")
ss.append({
    "matcher": "startup|resume|clear|compact",
    "hooks": [{
        "type": "command",
        "command": f'python3 "{script}" session-start',
        "timeout": 30,
    }],
})

ups = hooks.setdefault("UserPromptSubmit", [])
ups[:] = filter_existing(ups, "git-pulse")
ups.append({
    "hooks": [{
        "type": "command",
        "command": f'python3 "{script}" user-prompt-submit',
        "timeout": 30,
    }],
})

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
PY

bold ""
bold "✓ git-pulse installed."
info "Script:   $SCRIPT"
info "Hooks:    $SETTINGS"
info ""
info "Next: restart your Claude Code session (CLI or Desktop app)."
info "Open any git repo and you'll see a git-pulse summary on the first message."
info ""
info "To upgrade later:  bash $INSTALL_DIR/install.sh"
info "To uninstall:      bash $INSTALL_DIR/dist/uninstall.sh"
