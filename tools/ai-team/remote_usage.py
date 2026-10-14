"""Remote AI usage from what is actually on this PC, with the source and reliability of every figure.

Reads only numeric usage fields (never conversation text) from the agents' own local logs:
  Codex CLI   ~/.codex/sessions/**/*.jsonl  token_count events: tokens per session + plan rate-limit percentages
  Claude Code ~/.claude/projects/**/*.jsonl message.usage: tokens per assistant message (deduplicated by id)
  Grok CLI    ~/.grok/sessions/**/updates.jsonl turn_completed usage; signals.json context use
  ChatGPT app no local usage record found: reported as unavailable (nothing is estimated)
GitHub activity per role prefix on issue #32 (needs `gh`): comment counts, not usage.

  python remote_usage.py [--hours 24] [--no-github]
Nothing here is billing data: subscription quotas and costs are not exposed to this tool except the rate-limit
percentages Codex writes into its own session log.
"""
import argparse
import glob
import json
import os
import subprocess
import time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
ROLES = ("Lead (local)", "Implement (local)", "Research (local)", "QA (local)", "ChatGPT", "Claude", "Codex", "Grok")


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def codex(since):
    files = glob.glob(os.path.join(HOME, ".codex", "sessions", "**", "*.jsonl"), recursive=True)
    sessions, tokens, latest_limits, latest_t = 0, {"input": 0, "cached_input": 0, "output": 0}, None, 0
    for f in files:
        if os.path.getmtime(f) < since:
            continue
        last = None
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"token_count"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                p = ev.get("payload", {})
                t = _ts(ev.get("timestamp")) or 0
                if p.get("type") == "token_count" and t >= since:
                    last = (p.get("info") or {}).get("total_token_usage") or last
                    if p.get("rate_limits") and t > latest_t:
                        latest_limits, latest_t = p["rate_limits"], t
        if last:
            sessions += 1
            tokens["input"] += last.get("input_tokens", 0)
            tokens["cached_input"] += last.get("cached_input_tokens", 0)
            tokens["output"] += last.get("output_tokens", 0)
    lim = None
    if latest_limits:
        lim = {k: {"used_percent": v.get("used_percent"), "window_minutes": v.get("window_minutes")}
               for k, v in latest_limits.items() if isinstance(v, dict) and "used_percent" in v}
        lim["plan_type"] = latest_limits.get("plan_type")
    return {"source": "measured (Codex session logs, cumulative per session active in window)",
            "sessions": sessions, "tokens": tokens, "rate_limits_latest": lim,
            "note": "session totals include tokens from before the window if a session started earlier"}


def claude(since):
    files = glob.glob(os.path.join(HOME, ".claude", "projects", "**", "*.jsonl"), recursive=True)
    seen, tok, msgs = set(), {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}, 0
    for f in files:
        if os.path.getmtime(f) < since:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                m = ev.get("message") or {}
                u, mid = m.get("usage"), m.get("id")
                if not u or not mid or mid in seen or (_ts(ev.get("timestamp")) or 0) < since:
                    continue
                seen.add(mid)
                msgs += 1
                tok["input"] += u.get("input_tokens", 0)
                tok["cache_read"] += u.get("cache_read_input_tokens", 0)
                tok["cache_write"] += u.get("cache_creation_input_tokens", 0)
                tok["output"] += u.get("output_tokens", 0)
    return {"source": "measured (Claude Code session logs, per assistant message, deduplicated)",
            "assistant_messages": msgs, "tokens": tok,
            "note": "plan quota usage is not recorded locally; no percentage available"}


def grok(since):
    files = glob.glob(os.path.join(HOME, ".grok", "sessions", "**", "updates.jsonl"), recursive=True)
    tok, turns = {"input": 0, "output": 0}, 0
    ctx = []
    for f in files:
        if os.path.getmtime(f) < since:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"turn_completed"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if (ev.get("timestamp") or 0) < since:
                    continue
                u = ((ev.get("params") or {}).get("update") or {}).get("usage") or {}
                turns += 1
                tok["input"] += u.get("inputTokens", 0)
                tok["output"] += u.get("outputTokens", 0)
        sig = os.path.join(os.path.dirname(f), "signals.json")
        if os.path.exists(sig):
            try:
                s = json.load(open(sig, encoding="utf-8"))
                ctx.append({"context_pct": s.get("contextWindowUsage"), "compactions": s.get("compactionCount")})
            except ValueError:
                pass
    return {"source": "measured (Grok session updates.jsonl turn_completed usage)", "turns": turns, "tokens": tok,
            "active_sessions_context": ctx, "note": "plan quota not recorded locally"}


def github(since):
    try:
        out = subprocess.run(["gh", "issue", "view", "32", "--repo", "dasscooby/fo4-to-starfield", "--json", "comments"],
                             capture_output=True, text=True, timeout=60).stdout
        comments = json.loads(out)["comments"]
    except Exception as e:                              # noqa: BLE001
        return {"source": "gh", "error": str(e)}
    counts = {}
    for c in comments:
        if (_ts(c.get("createdAt")) or 0) < since:
            continue
        head = c.get("body", "").replace("ï»¿", "").lstrip("﻿ *").lower()
        role = next((r for r in ROLES if head.startswith(r.lower())), "untagged")
        counts[role] = counts.get(role, 0) + 1
    return {"source": "measured (issue #32 comments by role prefix)", "comments_by_role": counts,
            "note": "activity, not usage"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--no-github", action="store_true")
    a = ap.parse_args()
    since = time.time() - a.hours * 3600
    out = {"window_hours": a.hours, "codex": codex(since), "claude": claude(since), "grok": grok(since),
           "chatgpt_app": {"source": "unavailable", "note": "no local usage record found; nothing estimated"}}
    if not a.no_github:
        out["github"] = github(since)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
