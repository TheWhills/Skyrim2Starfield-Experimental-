"""One entry point for the Lead and the owner.

  python team.py board            GitHub tasks by state: available, in progress, blocked, research, pending review,
                                  recently completed (from labels, open PRs and closed issues; live from `gh`)
  python team.py status [--hours 24] [--no-remote]
                                  hardware + guardian level, running/queued local jobs, recent failures, local usage
                                  per agent, remote usage (measured where logs exist), warnings. JSON.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "dasscooby/fo4-to-starfield"


def _gh(args):
    out = subprocess.run(["gh"] + args + ["--repo", REPO], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return json.loads(out.stdout or "[]")


def board():
    issues = _gh(["issue", "list", "--state", "open", "--limit", "200", "--json", "number,title,labels,updatedAt"])
    closed = _gh(["issue", "list", "--state", "closed", "--limit", "20", "--json", "number,title,closedAt"])
    prs = _gh(["pr", "list", "--state", "open", "--json", "number,title,headRefName,labels,isDraft"])
    lab = lambda i: {l["name"] for l in i.get("labels", [])}
    short = lambda i: {"number": i["number"], "title": i["title"], "labels": sorted(lab(i))}
    out = {"source": "live (gh)", "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "available": [short(i) for i in issues if "ready" in lab(i) and not lab(i) & {"in-progress", "blocked"}
                         and "spike" not in lab(i)],
           "in_progress": [short(i) for i in issues if "in-progress" in lab(i)],
           "blocked": [short(i) for i in issues if "blocked" in lab(i)],
           "research": [short(i) for i in issues if "spike" in lab(i) and "in-progress" not in lab(i)],
           "pending_review": [short(i) for i in issues if "needs-qa" in lab(i)]
                             + [{"pr": p["number"], "title": p["title"], "branch": p["headRefName"]} for p in prs],
           "owner_inbox": [short(i) for i in issues if not lab(i)],
           "recently_completed": [{"number": i["number"], "title": i["title"], "closed": i["closedAt"]} for i in closed],
           "contributions_7d": contributions(issues, prs)}
    print(json.dumps(out, indent=1))


ROLES = ("Lead (local)", "Implement (local)", "Research (local)", "QA (local)", "ChatGPT", "Claude", "Codex", "Grok")


def contributions(issues, prs):
    """Commits on origin/main in the last 7 days by subject prefix, plus open issues/PRs by agent: label."""
    root = os.path.dirname(os.path.dirname(HERE))
    log = subprocess.run(["git", "-C", root, "log", "origin/main", "--since=7.days", "--format=%s"],
                         capture_output=True, text=True, timeout=60).stdout.splitlines()
    commits = {}
    for s in log:
        role = next((r for r in ROLES if s.lower().startswith(r.lower())), "untagged")
        commits[role] = commits.get(role, 0) + 1
    labelled = {}
    for i in list(issues) + list(prs):
        for l in i.get("labels", []):
            if l["name"].startswith("agent:"):
                labelled[l["name"]] = labelled.get(l["name"], 0) + 1
    return {"source": "live (git log origin/main, gh labels)", "commits_by_prefix": commits,
            "open_items_by_agent_label": labelled,
            "note": "untagged = no role prefix; see AGENTS.md 'Label what you contribute'"}


def _py(script, *args):
    out = subprocess.run([sys.executable, os.path.join(HERE, script)] + list(args), capture_output=True, text=True,
                         timeout=300)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {"error": out.stderr.strip()[-500:]}


def status(hours, remote):
    g = _py(os.path.join("guardian", "guardian.py"), "status")
    local = _py(os.path.join("guardian", "guardian.py"), "report", "--hours", str(hours))
    snap = g.get("snapshot", {})
    warnings = list(g.get("reasons", [])) if g.get("level") in ("restrict", "block") else []
    if g.get("mode") != "running":
        warnings.append(f"guardian mode is {g.get('mode')}")
    if not snap.get("lmstudio", {}).get("loaded"):
        warnings.append("no model loaded in LM Studio")
    out = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "hardware": {"level": g.get("level"), "mode": g.get("mode"),
                        "gpu_util_pct": snap.get("gpu", {}).get("utilization_pct"),
                        "vram_pct": snap.get("gpu", {}).get("vram_pct"), "ram_pct": snap.get("ram", {}).get("used_pct"),
                        "cpu_pct": snap.get("cpu", {}).get("utilization_pct"),
                        "lmstudio_loaded": snap.get("lmstudio", {}).get("loaded")},
           "active_agent_processes": snap.get("agents", {}).get("processes"),
           "local_jobs": {"running": g.get("running"), "queued": g.get("queued"), "counts": g.get("job_counts"),
                          "recent_failures": g.get("recent_failures")},
           "local_usage": local, "warnings": warnings}
    if remote:
        out["remote_usage"] = _py("remote_usage.py", "--hours", str(hours))
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board")
    s = sub.add_parser("status")
    s.add_argument("--hours", type=float, default=24)
    s.add_argument("--no-remote", action="store_true")
    a = ap.parse_args()
    if a.cmd == "board":
        board()
    else:
        status(a.hours, not a.no_remote)


if __name__ == "__main__":
    main()
