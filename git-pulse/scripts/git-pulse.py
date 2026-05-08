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

def gh_compare_full(host, owner, repo, base, head):
    """Full compare result via gh API. Returns dict (commits, files, ahead_by, ...) or None."""
    r = run(["gh", "api", f"repos/{owner}/{repo}/compare/{base}...{head}",
             "--hostname", host], timeout=20)
    if not ok(r):
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def humanize_iso_age(iso_ts):
    """ISO datetime string → 'Nh ago' / 'Nd ago' / etc. '?' on failure."""
    if not iso_ts:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        s = int((datetime.now(timezone.utc) - dt).total_seconds())
        if s < 60: return f"{s}s ago"
        if s < 3600: return f"{s // 60}m ago"
        if s < 86400: return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return "?"


def coarse_age(iso_ts):
    """Plain-English coarse span from a single ISO ts ('a week', '~3 months')."""
    if not iso_ts:
        return "an unknown amount of time"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        s = int((datetime.now(timezone.utc) - dt).total_seconds())
        if s < 3600: return "less than an hour"
        if s < 86400: return f"{s // 3600} hours"
        if s < 604800:
            d = s // 86400
            return "a day" if d == 1 else f"{d} days"
        if s < 2592000:
            w = s // 604800
            return "a week" if w == 1 else f"{w} weeks"
        if s < 31536000:
            m = s // 2592000
            return "a month" if m == 1 else f"~{m} months"
        y = s // 31536000
        return "a year" if y == 1 else f"~{y} years"
    except Exception:
        return "an unknown amount of time"


def short_age(iso_ts):
    """Compact label without 'ago' suffix. Uses days under 30 (so 20d not 2w),
    months under a year, years above. Stays consistent with humanize_iso_age."""
    if not iso_ts:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        s = int((datetime.now(timezone.utc) - dt).total_seconds())
        if s < 3600: return f"{max(1, s // 60)}m"
        if s < 86400: return f"{s // 3600}h"
        if s < 86400 * 30: return f"{s // 86400}d"
        if s < 86400 * 365: return f"{s // 2592000}mo"
        return f"{s // 31536000}y"
    except Exception:
        return "?"


CONVENTIONAL_LABELS = {
    # singular, plural — we look up the right form by count.
    "feat":     ("new feature",     "new features"),
    "fix":      ("bug fix",         "bug fixes"),
    "docs":     ("doc update",      "doc updates"),
    "chore":    ("config/chore",    "config/chores"),
    "refactor": ("refactor",        "refactors"),
    "test":     ("test change",     "test changes"),
    "perf":     ("perf change",     "perf changes"),
    "style":    ("formatting fix",  "formatting fixes"),
    "build":    ("build change",    "build changes"),
    "ci":       ("CI change",       "CI changes"),
    "revert":   ("revert",          "reverts"),
    "other":    ("other change",    "other changes"),
}


def _label(t, n):
    sing, plur = CONVENTIONAL_LABELS.get(t, (t, t))
    return f"{n} {sing if n == 1 else plur}"


def render_compare(cmp, cfg, here, remote_sha):
    """Prose-style summary of a gh compare payload. Returns list[str]."""
    from collections import Counter
    out = []
    commits = cmp.get("commits") or []
    files = cmp.get("files") or []
    ahead_by = cmp.get("ahead_by", len(commits))
    files_count = len(files)
    added = sum((f.get("additions") or 0) for f in files)
    removed = sum((f.get("deletions") or 0) for f in files)

    if not commits:
        out.append("You're out of sync with the remote, but I couldn't read the commit history.")
        return out

    # Tally authors & change types
    authors = Counter()
    type_buckets = Counter()
    for c in commits:
        author = ((c.get("author") or {}).get("login")
                  or (c.get("commit") or {}).get("author", {}).get("name") or "?")
        authors[author] += 1
        msg_full = ((c.get("commit") or {}).get("message") or "")
        first = msg_full.splitlines()[0] if msg_full else ""
        m = re.match(r"^([a-z]+)(?:\([^)]+\))?!?:\s", first.lower())
        type_buckets[m.group(1) if m else "other"] += 1

    top_a = authors.most_common(3)
    if len(top_a) == 1:
        who = f"{top_a[0][0]} ({top_a[0][1]} commits)" if top_a[0][1] != 1 else f"{top_a[0][0]} (1 commit)"
    elif len(authors) <= 3:
        who = ", ".join(f"{n} ({c})" for n, c in top_a)
    else:
        who = ", ".join(f"{n} ({c})" for n, c in top_a) + f", and {len(authors) - 3} other(s)"

    type_parts = [_label(t, n) for t, n in type_buckets.most_common(5)]
    type_str = ", ".join(type_parts) if type_parts else "various changes"

    oldest_iso = (commits[0].get("commit") or {}).get("author", {}).get("date", "")
    newest_iso = (commits[-1].get("commit") or {}).get("author", {}).get("date", "")
    span = coarse_age(oldest_iso)
    latest_msg = ((commits[-1].get("commit") or {}).get("message") or "").splitlines()[0]
    latest_age = humanize_iso_age(newest_iso)

    # Lead sentence — friendly, framed as "what you're missing", not "you are behind"
    change_word = "change" if ahead_by == 1 else "changes"
    out.append(f"There are {ahead_by} {change_word} on the remote that you don't have locally yet — pushed over the last {span}.")
    out.append("")
    out.append(f"Who's been working:  {who}")
    out.append(f"Type of changes:     {type_str}")
    if files_count:
        out.append(f"Total impact:        {files_count} files changed, +{added} / −{removed} lines")
    out.append(f"Latest:              \"{latest_msg[:80]}\" — {latest_age}")
    out.append("")

    cap = cfg.get("max_commits_shown", 5)
    shown = commits[-cap:]  # API returns oldest-first; tail = newest
    out.append("Recent activity (newest first):")
    for c in reversed(shown):
        commit = c.get("commit") or {}
        author = ((c.get("author") or {}).get("login")
                  or (commit.get("author") or {}).get("name") or "?")
        date_str = (commit.get("author") or {}).get("date", "")
        age = short_age(date_str)
        msg = (commit.get("message") or "").splitlines()[0] if commit.get("message") else ""
        if len(msg) > 60:
            msg = msg[:59] + "…"
        out.append(f"  ·  {age:<5}  {author:<14}  {msg}")
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

def _emit(payload):
    print(json.dumps(payload))
    sys.exit(0)


def emit_session_start(full_text, teaser):
    # systemMessage = compact one-line teaser shown by Claude Code in its
    # hook-output preamble. The full report goes into additionalContext so
    # Claude has it for context, but is gently asked to defer surfacing to
    # the UserPromptSubmit hook (which renders prominently in chat) — this
    # avoids the user seeing the same body 2-3 times.
    instruction = (
        "GIT-PULSE SESSION-START SNAPSHOT (for your context only).\n\n"
        "A separate UserPromptSubmit hook will surface the full report on "
        "the user's first message; do NOT pre-empt it by reproducing the "
        "report yourself unless the user explicitly asks for repo status. "
        "Just absorb this as background context.\n\n"
        "--- BEGIN REPORT ---\n"
        f"{full_text}\n"
        "--- END REPORT ---"
    )
    _emit({
        "systemMessage": teaser,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": instruction,
        },
    })


def emit_user_prompt_submit(full_text):
    # No systemMessage here — it would render as a "UserPromptSubmit says:"
    # preamble that duplicates what Claude is about to print in chat.
    # additionalContext steers Claude to surface the full report as the
    # opening of its first chat reply.
    instruction = (
        "GIT-PULSE FIRST-PROMPT REPORT — surface this in chat NOW.\n\n"
        "Begin your response by printing the report below verbatim as a "
        "fenced code block. After the code block, add one short sentence "
        "acknowledging anything actionable (e.g. 'You are 4 commits behind "
        "origin/main — want me to fetch?'). Then answer the user's actual "
        "question. Do not skip or summarize the report — the user has not "
        "seen its contents yet.\n\n"
        "--- BEGIN REPORT ---\n"
        f"{full_text}\n"
        "--- END REPORT ---"
    )
    _emit({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": instruction,
        },
    })


def fmt_age(dt):
    if not dt:
        return "unknown"
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60: return f"{s}s ago"
    if s < 3600: return f"{s // 60}m ago"
    if s < 86400: return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


# ---------- "have I emitted for this cwd yet" flag ----------
#
# We gate on cwd (sha256-keyed), not session_id. Empirically Claude Code
# passes a fresh session_id to UserPromptSubmit on every prompt, so a
# session_id-based gate fires every time. cwd is stable across all prompts
# in a project, so one flag-per-cwd is the correct level.
# SessionStart resets this flag so each new session-start re-emits once.

def cwd_flag_path(cwd):
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/git-pulse-data")
    p = Path(base) / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((cwd or "unknown").encode("utf-8")).hexdigest()[:16]
    return p / f"cwd-{key}.flag"


def has_cwd_flag(cwd):
    return cwd_flag_path(cwd).exists()


def set_cwd_flag(cwd):
    try:
        cwd_flag_path(cwd).write_text(
            datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
    except Exception:
        pass


def clear_cwd_flag(cwd):
    try:
        p = cwd_flag_path(cwd)
        if p.exists():
            p.unlink()
    except Exception:
        pass


# ---------- report building ----------

def build_report_text(cwd, cfg, persist_state):
    """Build the human-readable report. Returns (full_text, teaser).
    teaser is a single line summary suitable for systemMessage; full_text is
    the rich multi-line block for in-chat surfacing.
    """
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    if not is_git_repo(cwd):
        msg = f"[git-pulse · {ts}] {cwd} — not a git repository, nothing to check."
        return msg, msg

    remotes = get_remotes(cwd)
    if not remotes:
        msg = f"[git-pulse · {ts}] {cwd} — git repo with no remote, nothing to check."
        return msg, msg

    name, url = next(((n, u) for n, u in remotes if n == "origin"), remotes[0])
    host, owner, repo = parse_remote(url)
    branch = current_branch(cwd)
    here = local_head(cwd)
    accounts = gh_accounts(host, cfg.get("gh_accounts_priority") or [])

    lines = []
    title = f"{owner}/{repo}" if owner and repo else url
    header = f"[git-pulse · {ts}] {title}"
    if branch:
        header += f"  ·  branch: {branch}"
    lines.append(header)
    lines.append("")  # blank line under the header for breathing room

    remote_sha = None
    account_used = None
    status = "checked"

    if cfg["checks"].get("remote_freshness", True):
        remote_sha, account_used = find_remote_head(url, host, owner, repo, branch, cwd, accounts)

        prev = load_state(url)
        last_seen = prev.get("remote_sha")
        fetch_age = last_fetch_time(cwd, name)

        if remote_sha is None:
            lines.append("I couldn't reach the remote (you may be offline, or this is a private repo I can't access).")
            status = "remote unreachable"
        elif here == remote_sha:
            lines.append("You're up to date — nothing has changed on the remote since you were last here.")
            status = "up to date"
        else:
            cmp = None
            if host and host.endswith("github.com") and owner and repo:
                cmp = gh_compare_full(host, owner, repo, here, remote_sha)
            if cmp:
                lines.extend(render_compare(cmp, cfg, here, remote_sha))
                status = f"{cmp.get('ahead_by', '?')} change(s) behind"
            else:
                lines.append(f"You're out of sync with the remote, but I couldn't read the commit history "
                             "(non-GitHub remote, offline, or a private repo I can't access).")
                status = "out of sync"

            up = upstream_ref(cwd)
            if up:
                ahead, _behind = count_ahead_behind(cwd, up, "HEAD")
                if ahead:
                    lines.append("")
                    lines.append(f"You also have {ahead} commit(s) of your own that aren't pushed yet.")

            default_b = detect_default_branch(cwd, name, cfg.get("default_branch_fallback", []))
            if default_b and branch and branch != default_b:
                ahead, behind = count_ahead_behind(cwd, f"{name}/{default_b}", "HEAD")
                if ahead is not None and behind is not None and (ahead or behind):
                    lines.append(f"Your branch ({branch}) is {ahead} ahead and {behind} behind {default_b}.")

    if cfg["checks"].get("pr_ci_status", True) and host and host.endswith("github.com") and owner and repo:
        pr = gh_pr_for_branch(host, owner, repo, branch)
        if pr is None and accounts:
            for acct in accounts:
                if gh_switch(host, acct):
                    pr = gh_pr_for_branch(host, owner, repo, branch)
                    if pr:
                        break
        if pr:
            state = (pr.get("state") or "?").lower()
            num = pr.get("number")
            draft = " (draft)" if pr.get("isDraft") else ""
            url_pr = pr.get("url") or ""
            passed, failed, pending = summarize_checks(pr.get("statusCheckRollup"))
            if passed + failed + pending:
                ci_words = []
                if passed: ci_words.append(f"{passed} passing")
                if failed: ci_words.append(f"{failed} failing")
                if pending: ci_words.append(f"{pending} running")
                ci = ", ".join(ci_words)
            else:
                ci = "no CI checks"
            lines.append("")
            lines.append(f"Open PR #{num} ({state}{draft}) · CI: {ci}")
            if url_pr:
                lines.append(f"  {url_pr}")

    # Action-oriented closing line for any out-of-sync state
    needs_sync = any(("don't have locally" in l)
                     or ("out of sync" in l)
                     or ("aren't pushed yet" in l) for l in lines)
    if needs_sync:
        lines.append("")
        lines.append("→ Ask Claude to run `git fetch` and/or `git pull` to bring this in sync.")

    # Discreet provenance trailer for multi-account users (only if non-default)
    if account_used and account_used != "default":
        lines.append(f"(checked via {account_used})")

    if persist_state:
        save_state(url, {
            "remote_sha": remote_sha or load_state(url).get("remote_sha"),
            "branch": branch,
            "last_checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "account_used": account_used,
        })

    teaser_repo = f"{owner}/{repo}" if owner and repo else url
    teaser = f"[git-pulse · {ts}] {teaser_repo}"
    if branch:
        teaser += f" · {branch}"
    teaser += f" · {status}"

    return "\n".join(lines), teaser


# ---------- per-event entrypoints ----------

def run_session_start(payload, cfg):
    cwd = payload.get("cwd") or os.getcwd()
    # Reset the cwd flag so the next UserPromptSubmit emits exactly once.
    clear_cwd_flag(cwd)
    full_text, teaser = build_report_text(cwd, cfg, persist_state=False)
    emit_session_start(full_text, teaser)


def run_user_prompt_submit(payload, cfg):
    cwd = payload.get("cwd") or os.getcwd()
    if has_cwd_flag(cwd):
        sys.exit(0)
    set_cwd_flag(cwd)
    full_text, _teaser = build_report_text(cwd, cfg, persist_state=True)
    emit_user_prompt_submit(full_text)


# ---------- main ----------

def main():
    cfg = load_config()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}

    mode = sys.argv[1] if len(sys.argv) > 1 else "session-start"
    if mode == "session-start":
        run_session_start(payload, cfg)
    elif mode == "user-prompt-submit":
        run_user_prompt_submit(payload, cfg)
    else:
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        try:
            msg = f"[git-pulse {ts}] hook fired but errored: {type(e).__name__}: {e}"
            mode = sys.argv[1] if len(sys.argv) > 1 else "session-start"
            event = "UserPromptSubmit" if mode == "user-prompt-submit" else "SessionStart"
            instruction = (
                f"GIT-PULSE {event.upper()} REPORT — the hook errored. "
                "Begin your reply with this fenced code block:\n\n"
                f"```\n{msg}\n```"
            )
            print(json.dumps({
                "systemMessage": msg,
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": instruction,
                },
            }))
        except Exception:
            pass
        sys.exit(0)
