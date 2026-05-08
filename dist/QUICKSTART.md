# git-pulse — Quickstart

Get a friendly summary of what changed in your repo every time you open a Claude Code session.
Works in both the **Claude Code CLI** and the **Claude Code Desktop app**.

## Install in 30 seconds

### macOS / Linux

Open a terminal and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/we-app/git-pulse/main/install.sh | bash
```

### Windows

Open PowerShell and paste:

```powershell
irm https://raw.githubusercontent.com/we-app/git-pulse/main/install.ps1 | iex
```

That's it. **Restart Claude Code** — the next time you open any git project, the very first message you send will return a "what's new since you were last here" summary.

## What it shows

When the remote has moved, you'll get something like:

```
[git-pulse · 14:22 UTC] acme/widgets  ·  branch: main

There are 23 changes on the remote that you don't have locally yet — pushed over the last ~3 months.

Who's been working:  alice (17), bob (6)
Type of changes:     11 bug fixes, 3 config/chores, 2 doc updates, 1 new feature
Total impact:        27 files changed, +981 / −157 lines
Latest:              "fix: handle expired auth tokens" — 2d ago

Knowledge / docs added or changed (worth reading first):
  ·  [new    ]  docs/auth-flow.md   (+165 / −0)

PRs / issues referenced: #421, #438

Recent activity (newest first):
  ·  2d   alice   fix: handle expired auth tokens
  ·  3d   bob     chore: bump axios to 1.7.4
  ...

→ Ask Claude to run `git fetch` and/or `git pull` to bring this in sync.
```

Claude will start its first reply with a 2-3 sentence plain-English summary so you don't have to read the whole table.

## Uninstall

### macOS / Linux

```bash
bash ~/.claude/git-pulse/dist/uninstall.sh
```

### Windows

```powershell
pwsh -File "$env:USERPROFILE\.claude\git-pulse\dist\uninstall.ps1"
```

## Requirements

- `git` and `python3` in your PATH (most developer machines already have these)
- Claude Code CLI v2.x or later, **or** the Claude Code Desktop app
- For richest output (commit list with authors / PR refs): `gh` CLI installed and authenticated

## Where things live

| What | Path |
|---|---|
| Plugin source | `~/.claude/git-pulse/` |
| Hook registration | `~/.claude/settings.json` |
| Last-seen state | `~/.claude/git-pulse-data/` |

## Troubleshooting

- **No output appears:** make sure you fully restarted Claude Code (closing the CLI tab or quitting the Desktop app), and that you're inside a git repository with a configured remote.
- **"hook fired but errored":** open `~/.claude/git-pulse/git-pulse/scripts/git-pulse.py` and run it manually with `echo '{"cwd": "."}' | python3 git-pulse.py session-start` to see the error message.
- **You want to upgrade:** re-run the install command above; it's idempotent.
