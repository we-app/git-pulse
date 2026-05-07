#!/usr/bin/env python3
"""
git-pulse — Claude Code SessionStart hook.

Read-only summary of what changed on the remote since the last time this repo
was opened in Claude Code on this machine. Designed to give the user (and
Claude) an at-a-glance picture of who pushed what, plus open PR / CI state,
WITHOUT touching the working tree (no fetch, no merge).

Design rules:
  - Never block, never error loudly. SessionStart hooks must be fast & quiet.
  - Time-bounded: every git/network call has a timeout.
  - Read-only: ls-remote and gh API calls only. The user is asked to fetch.
  - Multi-account aware: tries the default credential helper first; falls back
    to gh accounts when reachable.
  - State is per-remote-URL, stored in $CLAUDE_PLUGIN_DATA so it survives
    plugin updates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------- subprocess helpers ----------

def run(cmd, cwd=None, timeout=10, env=None):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd, timeout=timeout, env=env,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def ok(r):
    return r is not None and r.returncode == 0


# ---------- config ----------

DEFAULT_CONFIG = {
    "checks": {
        "remote_freshness": True,
        "pr_ci_status": True,
    },
    "max_commits_shown": 5,
    "default_branch_fallback": ["main", "master", "trunk", "develop"],
    "gh_accounts_priority": [],
}


def config_path():
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg) / "git-pulse" / "config.json"


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text())
            if isinstance(user, dict):
                if isinstance(user.get("checks"), dict):
                    cfg["checks"].update(user["checks"])
                for k in ("max_commits_shown", "default_branch_fallback", "gh_accounts_priority"):
                    if k in user:
                        cfg[k] = user[k]
        except Exception:
            pass
    return cfg


# ---------- git inspection ----------

def is_git_repo(cwd):
    r = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd)
    return ok(r) and r.stdout.strip() == "true"


def get_remotes(cwd):
    r = run(["git", "remote", "-v"], cwd=cwd)
    if not ok(r):
        return []
    seen = {}
    for line in r.stdout.strip().splitlines():
        m = re.match(r"(\S+)\s+(\S+)\s+\((fetch|push)\)", line)
        if m and m.group(3) == "fetch":
            seen.setdefault(m.group(1), m.group(2))
    return list(seen.items())


def parse_remote(url):
    m = re.match(r"git@([^:]+):([^/]+)/(.+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = re.match(r"https?://(?:[^@/]+@)?([^/]+)/([^/]+)/(.+?)(?:\.git)?/?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None, None, None


def current_branch(cwd):
    r = run(["git", "branch", "--show-current"], cwd=cwd)
    return r.stdout.strip() if ok(r) else None


def local_head(cwd):
    r = run(["git", "rev-parse", "HEAD"], cwd=cwd)
    return r.stdout.strip() if ok(r) else None


def upstream_ref(cwd):
    """e.g. 'origin/main' if HEAD has a tracking branch, else None."""
    r = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=cwd)
    return r.stdout.strip() if ok(r) and r.stdout.strip() else None


def count_ahead_behind(cwd, base, head):
    """Return (ahead, behind) of `head` relative to `base`. Uses cached refs."""
    r = run(["git", "rev-list", "--left-right", "--count", f"{base}...{head}"], cwd=cwd)
    if ok(r):
        parts = r.stdout.strip().split()
        if len(parts) == 2:
            try:
                return int(parts[1]), int(parts[0])  # ahead of base, behind base
            except ValueError:
                pass
    return None, None


def detect_default_branch(cwd, remote_name, fallback):
    """Try origin/HEAD symbolic ref; else first match from fallback list."""
    r = run(["git", "symbolic-ref", "--short", f"refs/remotes/{remote_name}/HEAD"], cwd=cwd)
    if ok(r) and r.stdout.strip():
        return r.stdout.strip().split("/", 1)[1]
    for cand in fallback:
        rr = run(["git", "rev-parse", "--verify", f"refs/remotes/{remote_name}/{cand}"], cwd=cwd)
        if ok(rr):
            return cand
    return None


def last_fetch_time(cwd, remote_name):
    """mtime of FETCH_HEAD or refs/remotes/<remote>; None if unknown."""
    git_dir = run(["git", "rev-parse", "--git-dir"], cwd=cwd)
    if not ok(git_dir):
        return None
    gdir = Path(cwd) / git_dir.stdout.strip() if not Path(git_dir.stdout.strip()).is_absolute() else Path(git_dir.stdout.strip())
    candidates = [gdir / "FETCH_HEAD", gdir / "refs" / "remotes" / remote_name]
    times = []
    for c in candidates:
        try:
            if c.exists():
                times.append(c.stat().st_mtime)
        except Exception:
            pass
    if not times:
        return None
    return datetime.fromtimestamp(max(times), tz=timezone.utc)


# ---------- multi-account aware remote query ----------

def gh_accounts(host, priority):
    if not host or not host.endswith("github.com"):
        return []
    r = run(["gh", "auth", "status", "--hostname", host])
    if not r:
        return []
    text = (r.stdout or "") + (r.stderr or "")
    found = list({m.group(1) for m in re.finditer(r"account\s+([A-Za-z0-9_\-]+)", text)})
    # priority first, then the rest in their natural order
    ordered = [a for a in priority if a in found] + [a for a in found if a not in priority]
    return ordered


def remote_head_via_git(remote_url, cwd, branch=None, timeout=15):
    ref = f"refs/heads/{branch}" if branch else "HEAD"
    r = run(["git", "ls-remote", remote_url, ref], cwd=cwd, timeout=timeout)
    if ok(r) and r.stdout.strip():
        return r.stdout.split()[0]
    return None


def gh_switch(host, account):
    return ok(run(["gh", "auth", "switch", "--hostname", host, "--user", account]))


def remote_head_via_gh(host, owner, repo, branch, account):
    if not gh_switch(host, account):
        return None
    ref = f"heads/{branch}" if branch else "HEAD"
    r = run(["gh", "api", f"repos/{owner}/{repo}/commits/{ref}", "--jq", ".sha",
             "--hostname", host], timeout=15)
    if ok(r) and r.stdout.strip():
        return r.stdout.strip()
    return None


def find_remote_head(remote_url, host, owner, repo, branch, cwd, accounts):
    sha = remote_head_via_git(remote_url, cwd, branch)
    if sha:
        return sha, "default"
    if owner and repo and host and host.endswith("github.com"):
        for acct in accounts:
            sha = remote_head_via_gh(host, owner, repo, branch, acct)
            if sha:
                return sha, f"gh:{acct}"
    return None, None


# ---------- GitHub enrichment ----------

def gh_compare(host, owner, repo, base, head, max_commits):
    """List commits between base..head via gh API. Returns list of dicts."""
    r = run(["gh", "api", f"repos/{owner}/{repo}/compare/{base}...{head}",
             "--hostname", host], timeout=15)
    if not ok(r):
        return []
    try:
        data = json.loads(r.stdout)
    except Exception:
        return []
    out = []
    for c in (data.get("commits") or [])[-max_commits:]:
        sha = (c.get("sha") or "")[:10]
        commit = c.get("commit") or {}
        author = ((c.get("author") or {}).get("login")
                  or (commit.get("author") or {}).get("name")
                  or "?")
        msg = (commit.get("message") or "").splitlines()[0] if commit.get("message") else ""
        out.append({"sha": sha, "author": author, "message": msg})
    return out


def gh_pr_for_branch(host, owner, repo, branch):
    if not branch:
        return None
    r = run(["gh", "pr", "view", branch, "--repo", f"{owner}/{repo}",
             "--json", "number,state,title,isDraft,mergeable,statusCheckRollup,url"],
            timeout=10)
    if not ok(r):
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def summarize_checks(checks):
    """Reduce a statusCheckRollup list to (passed, failed, pending)."""
    passed = failed = pending = 0
    for c in checks or []:
        # Workflow runs use 'conclusion' + 'status'; status checks use 'state'.
        concl = (c.get("conclusion") or c.get("state") or "").lower()
        status = (c.get("status") or "").lower()
        if status in ("queued", "in_progress", "pending") and not concl:
            pending += 1
        elif concl in ("success", "neutral", "skipped"):
            passed += 1
        elif concl in ("failure", "cancelled", "timed_out", "action_required", "error"):
            failed += 1
        else:
            pending += 1
    return passed, failed, pending


# ---------- state ----------

def state_dir():
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/git-pulse-data")
    p = Path(base) / "repos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def state_path(remote_url):
    key = hashlib.sha256(remote_url.encode("utf-8")).hexdigest()[:16]
    return state_dir() / f"{key}.json"


def load_state(remote_url):
    p = state_path(remote_url)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def save_state(remote_url, state):
    try:
        state_path(remote_url).write_text(json.dumps(state))
    except Exception:
        pass


# ---------- output ----------

def emit(text):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))
    sys.exit(0)


def fmt_age(dt):
    if not dt:
        return "unknown"
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60: return f"{s}s ago"
    if s < 3600: return f"{s // 60}m ago"
    if s < 86400: return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


# ---------- main ----------

def main():
    cfg = load_config()

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    if not is_git_repo(cwd):
        emit(f"[git-pulse {ts}] {cwd} is not a git repository — nothing to check. (hook fired OK)")

    remotes = get_remotes(cwd)
    if not remotes:
        emit(f"[git-pulse {ts}] git repo at {cwd} has no remotes configured — nothing to check. (hook fired OK)")

    name, url = next(((n, u) for n, u in remotes if n == "origin"), remotes[0])
    host, owner, repo = parse_remote(url)
    branch = current_branch(cwd)
    here = local_head(cwd)
    accounts = gh_accounts(host, cfg.get("gh_accounts_priority") or [])

    lines = []
    title = f"{owner}/{repo}" if owner and repo else url
    header = f"[git-pulse {ts}] {title}"
    if branch:
        header += f"  branch={branch}"
    lines.append(header)

    remote_sha = None
    account_used = None

    if cfg["checks"].get("remote_freshness", True):
        remote_sha, account_used = find_remote_head(url, host, owner, repo, branch, cwd, accounts)
        if account_used and account_used != "default":
            lines[0] += f"  via={account_used}"

        prev = load_state(url)
        last_seen = prev.get("remote_sha")
        last_checked = prev.get("last_checked_at")
        fetch_age = last_fetch_time(cwd, name)

        if remote_sha is None:
            lines.append("• Could not reach remote (offline, no creds, or private). Freshness skipped.")
        else:
            # Section: remote drift since last session
            if last_seen and last_seen != remote_sha:
                lines.append(f"• Remote moved since last session here: {last_seen[:10]} → {remote_sha[:10]}"
                             + (f"  (last seen {last_checked})" if last_checked else ""))
                if host and host.endswith("github.com") and owner and repo:
                    commits = gh_compare(host, owner, repo, last_seen, remote_sha,
                                         cfg.get("max_commits_shown", 5))
                    if commits:
                        lines.append(f"  New commits ({len(commits)} shown):")
                        for c in commits:
                            msg = c["message"][:80]
                            lines.append(f"    - {c['sha']}  {c['author']}: {msg}")
                    else:
                        lines.append("  (Could not list commits — likely a private repo or auth scope.)")
            elif here and here != remote_sha:
                lines.append(f"• Local HEAD differs from remote: {here[:10]} vs {remote_sha[:10]}.")
            else:
                lines.append(f"• Up to date with remote ({remote_sha[:10]}).")

            # Section: unpushed local commits (cached upstream)
            up = upstream_ref(cwd)
            if up:
                ahead, behind = count_ahead_behind(cwd, up, "HEAD")
                if ahead:
                    lines.append(f"• {ahead} unpushed local commit(s) on {branch} (vs cached {up}).")

            # Section: behind/ahead vs default branch (cached)
            default_b = detect_default_branch(cwd, name, cfg.get("default_branch_fallback", []))
            if default_b and branch and branch != default_b:
                ahead, behind = count_ahead_behind(cwd, f"{name}/{default_b}", "HEAD")
                if ahead is not None and behind is not None and (ahead or behind):
                    lines.append(f"• {branch} is {ahead} ahead / {behind} behind {name}/{default_b} "
                                 f"(based on local refs, last fetched {fmt_age(fetch_age)}).")

    if cfg["checks"].get("pr_ci_status", True) and host and host.endswith("github.com") and owner and repo:
        # gh_pr_for_branch may need an authenticated account; try default first, then fall back.
        pr = gh_pr_for_branch(host, owner, repo, branch)
        if pr is None and accounts:
            for acct in accounts:
                if gh_switch(host, acct):
                    pr = gh_pr_for_branch(host, owner, repo, branch)
                    if pr:
                        break
        if pr:
            state = pr.get("state", "?")
            num = pr.get("number")
            draft = " (draft)" if pr.get("isDraft") else ""
            mergeable = pr.get("mergeable") or "?"
            url_pr = pr.get("url") or ""
            passed, failed, pending = summarize_checks(pr.get("statusCheckRollup"))
            ci = f"CI: {passed}✓ {failed}✗ {pending}…" if (passed + failed + pending) else "CI: none"
            lines.append(f"• PR #{num} {state}{draft}  mergeable={mergeable}  {ci}  {url_pr}")
        # Silent if no PR — don't add noise.

    # Trailing nudge — fetch is the user's call.
    needs_sync = any(("Remote moved" in l) or ("differs from remote" in l) or ("unpushed local" in l) for l in lines)
    if needs_sync:
        lines.append("→ Run `git fetch` (or ask Claude to) to sync local refs. No fetch was performed.")

    save_state(url, {
        "remote_sha": remote_sha or load_state(url).get("remote_sha"),
        "branch": branch,
        "last_checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "account_used": account_used,
    })

    if len(lines) == 1:
        lines.append("• Nothing to report — all checks ran clean.")
    lines.append("· git-pulse hook fired OK ·")
    emit("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Still emit something so the user knows the hook ran but stumbled.
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        try:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": f"[git-pulse {ts}] hook fired but errored: {type(e).__name__}: {e}",
                }
            }))
        except Exception:
            pass
        sys.exit(0)
