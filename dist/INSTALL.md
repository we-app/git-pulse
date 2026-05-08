# git-pulse — Install Guide

Three install paths, same end-state. Pick the one your situation calls for.

## Path A — One-liner (recommended)

The fastest. Works for both Claude Code CLI and Desktop app.

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/we-app/git-pulse/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/we-app/git-pulse/main/install.ps1 | iex
```

The script clones the repo to `~/.claude/git-pulse/` and adds two hooks to `~/.claude/settings.json`. Idempotent — re-run any time to upgrade.

## Path B — From the .zip you received

If someone handed you a `git-pulse-vX.Y.Z.zip`:

```bash
unzip git-pulse-vX.Y.Z.zip
cd git-pulse-vX.Y.Z
bash install.sh                 # macOS / Linux
# or
pwsh -File dist/install.ps1     # Windows
```

Same outcome as Path A. The script reads from the local folder instead of cloning from GitHub.

## Path C — Manual (if scripts are blocked)

1. Clone or unzip the repo to `~/.claude/git-pulse/` (or anywhere stable).
2. Open `~/.claude/settings.json`. Create it as `{}` if missing.
3. Add (merging with any existing `hooks` block):

   ```json
   {
     "hooks": {
       "SessionStart": [
         {
           "matcher": "startup|resume|clear|compact",
           "hooks": [{
             "type": "command",
             "command": "python3 \"/absolute/path/to/git-pulse/scripts/git-pulse.py\" session-start",
             "timeout": 30
           }]
         }
       ],
       "UserPromptSubmit": [
         {
           "hooks": [{
             "type": "command",
             "command": "python3 \"/absolute/path/to/git-pulse/scripts/git-pulse.py\" user-prompt-submit",
             "timeout": 30
           }]
         }
       ]
     }
   }
   ```

4. Save. Restart Claude Code.

## What happens when you restart

- Open a Claude Code session in any git repository with a configured remote.
- Type any message (e.g. `hi`).
- Claude's first reply opens with a `[git-pulse · ts]` block summarizing what changed on the remote, who pushed it, what files were touched, plus a 2-3 sentence plain-English narrative.
- Subsequent messages in that session are silent — git-pulse only fires once per session.
- Next time you open the same project (fresh session), it fires again with whatever changed since.

## Requirements

- `git` and `python3` in your PATH (already on most developer machines).
- Claude Code CLI v2.x+ or the Desktop app.
- Optional: `gh` (GitHub CLI), authenticated. Required for the rich content (author names, PR refs, doc-file detection). Without it, you'll still get a basic "remote moved" notice.

## Verifying it's working

After install, in any git repo:

```bash
echo '{"cwd": "'$PWD'"}' | python3 ~/.claude/git-pulse/git-pulse/scripts/git-pulse.py user-prompt-submit
```

You should see a JSON blob containing `additionalContext` with the report. That confirms the script itself runs cleanly.

## Uninstall

```bash
bash ~/.claude/git-pulse/dist/uninstall.sh                # macOS / Linux
pwsh -File "$env:USERPROFILE\.claude\git-pulse\dist\uninstall.ps1"   # Windows
```

Removes hooks from `settings.json` and deletes `~/.claude/git-pulse/`. Last-seen state at `~/.claude/git-pulse-data/` is preserved (delete manually for a clean slate).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| No output in any session | Claude Code wasn't fully restarted; or `cwd` is not a git repo. |
| "hook fired but errored: ..." | Run the manual command above to see the underlying Python error. |
| `python3: command not found` | Install Python 3 (`brew install python` / `apt install python3` / [python.org](https://python.org)). |
| Output but no "rich" content (no authors, no PRs) | Install and authenticate `gh`: `brew install gh && gh auth login`. |
