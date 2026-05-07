# git-pulse

Read-only git remote pulse-check that fires on **Claude Code** session start.

When you open a project in Claude Code (CLI or the Anthropic app), this plugin
quietly inspects the configured remote, compares it to the SHA it last saw on
this machine, and injects a short summary into Claude's context — so the very
first thing Claude knows about your repo is **what changed, who pushed it, and
where you are relative to the default branch**.

It never fetches and never modifies your working tree. If sync is needed, the
hook tells you (and Claude) to run `git fetch`. The decision stays yours.

It is **multi-account aware**: if you have several GitHub identities registered
with `gh`, it will fall through them when the default credential helper can't
reach a private repo.

## Install

```bash
# In any Claude Code session:
/plugin marketplace add we-app/git-pulse
/plugin install git-pulse@git-pulse
```

That's it. Next time you start a session in a git repo, you'll see something like:

```
[git-pulse] acme/widgets  branch=main  via=gh:work-account
• Remote moved since last session here: a1b2c3d4e5 → f6g7h8i9j0  (last seen 2026-05-04T14:22:11+00:00)
  New commits (3 shown):
    - f6g7h8i9j0  alice: Fix login race when token expires mid-request
    - 9d8c7b6a5f  bob:   Bump axios to 1.7.4
    - 4e5d6c7b8a  alice: Add retry to flaky billing test
• 2 unpushed local commit(s) on main (vs cached origin/main).
• PR #421 OPEN  mergeable=MERGEABLE  CI: 6✓ 0✗ 1…  https://github.com/acme/widgets/pull/421
→ Run `git fetch` (or ask Claude to) to sync local refs. No fetch was performed.
```

On a clean repo, you'll just see:

```
[git-pulse] acme/widgets  branch=main
• Up to date with remote (a1b2c3d4e5).
```

## What it checks

| Check | What it shows |
|---|---|
| **Remote freshness** | Has the remote tip moved since you last opened this repo here? If yes, lists new commits with author + first line of message (via `gh api .../compare`). |
| **Unpushed local commits** | How many local commits aren't on the remote yet (based on cached upstream ref). |
| **Branch vs default** | Ahead/behind count of your branch vs `origin/HEAD` (or `main`/`master` fallback). Marked as based on local refs since last fetch. |
| **PR + CI status** | If `gh` is available and there's an open PR for the branch, shows PR number, state, mergeability, and CI rollup. |

All checks are individually toggleable in the config file.

## Config

`git-pulse` reads `~/.config/git-pulse/config.json` (or `$XDG_CONFIG_HOME/git-pulse/config.json`).
A starter is shipped at [`config.json.example`](./config.json.example):

```json
{
  "checks": {
    "remote_freshness": true,
    "pr_ci_status": true
  },
  "max_commits_shown": 5,
  "default_branch_fallback": ["main", "master", "trunk", "develop"],
  "gh_accounts_priority": []
}
```

- **`checks.*`** — toggle each check on/off.
- **`max_commits_shown`** — cap on how many new-commit lines to inject into context.
- **`default_branch_fallback`** — which branches to try as the default when `origin/HEAD` isn't set.
- **`gh_accounts_priority`** — preferred order for the `gh` multi-account fallback (e.g. `["work-account", "personal"]`).

## How it works

| Step | What it does |
|---|---|
| 1 | `SessionStart` hook fires (`startup` or `resume` matcher). |
| 2 | Script reads `cwd` from the hook's stdin JSON. |
| 3 | Bails silently if cwd isn't a git repo or has no remote. |
| 4 | Picks `origin` (or first remote), parses host/owner/repo. |
| 5 | Tries `git ls-remote` first (uses your normal credential helper). |
| 6 | If that fails on GitHub, iterates `gh auth status` accounts. |
| 7 | If the SHA changed, calls `gh api /compare` for author + message. |
| 8 | Computes unpushed count + branch-vs-default from cached refs. |
| 9 | Looks up open PR + CI rollup via `gh pr view --json`. |
| 10 | Writes one paragraph to stdout as `additionalContext`. |
| 11 | Updates the state file. |

## Hard rules baked into the script

- **Never crashes.** Top-level `try/except` swallows anything; SessionStart
  failures must not block your session.
- **Never fetches.** Only `ls-remote` and authenticated `gh api` reads. Any
  drift you see is reported, never reconciled, without your say-so.
- **Time-bounded.** Every git/network call has a timeout; the whole hook is
  capped at 30s by `hooks.json`.
- **No secrets in state.** Stored state is just `{remote_sha, branch,
  last_checked_at, account_used}` per repo, keyed by SHA-256 of the remote URL.

## State location

`$CLAUDE_PLUGIN_DATA/repos/<hash>.json`

The plugin manager guarantees that directory survives plugin updates.

## Debugging locally

You can run the hook by hand:

```bash
echo '{"cwd": "/path/to/your/repo"}' | python3 scripts/git-pulse.py | jq .
```

The output is a single JSON object containing `hookSpecificOutput.additionalContext`.

## License

MIT — do whatever, no warranty.
