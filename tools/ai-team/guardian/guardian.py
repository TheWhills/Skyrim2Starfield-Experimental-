"""Resource Guardian command line (what the Lead and the owner call).

  python guardian.py status [--simulate vram_pct=97,ram_pct=50]   JSON: level, reasons, hardware, agents, queue
  python guardian.py report [--hours 24]                          JSON: local usage per agent + reliability notes
  python guardian.py pause | resume | stop                         manual switch read by the proxy
  python guardian.py recover                                       mark stale jobs abandoned (restart recovery)

Exit code of `status`: 0 normal/caution, 1 restrict, 2 block (so scripts can gate on it).
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy      # noqa: E402
import resources   # noqa: E402
import store       # noqa: E402

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")


def load_config():
    cfg = dict(policy.DEFAULTS)
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f).get("guardian", {}))
    return cfg


def parse_sim(s):
    if not s:
        return None
    return {k.strip(): float(v) for k, v in (kv.split("=") for kv in s.split(","))}


def status(args):
    cfg = load_config()
    c = store.connect()
    snap = resources.snapshot(parse_sim(args.simulate))
    lv, reasons = policy.level(snap, cfg)
    store.log_sample(c, snap, lv)
    jobs = {s: n for s, n in c.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}
    running = c.execute("SELECT id, agent, model, started FROM jobs WHERE status='running'").fetchall()
    queued = c.execute("SELECT id, agent, model, created FROM jobs WHERE status='queued'").fetchall()
    recent_fail = c.execute("SELECT id, agent, status, error, finished FROM jobs WHERE status IN "
                            "('failed','timeout','rejected','abandoned') ORDER BY id DESC LIMIT 5").fetchall()
    out = {"level": lv, "reasons": reasons, "mode": store.get_mode(c),
           "admission_if_new_job": policy.admit(snap, cfg, len(running))[0],
           "limits": {k: cfg[k] for k in ("max_concurrent_local", "caution_pct", "restrict_pct", "vram_block_pct",
                                          "ram_block_pct", "vram_restrict_with_model_pct", "game_blocks_inference")},
           "running": [dict(zip(("id", "agent", "model", "started"), r)) for r in running],
           "queued": [dict(zip(("id", "agent", "model", "created"), r)) for r in queued],
           "job_counts": jobs,
           "recent_failures": [dict(zip(("id", "agent", "status", "error", "finished"), r)) for r in recent_fail],
           "snapshot": snap}
    print(json.dumps(out, indent=1))
    return {"normal": 0, "caution": 0, "restrict": 1, "block": 2}[lv]


def report(args):
    c = store.connect()
    since = time.time() - args.hours * 3600
    rows = c.execute(
        "SELECT agent, COUNT(*), SUM(status='done'), SUM(status!='done'), SUM(prompt_tokens), SUM(completion_tokens), "
        "AVG(latency_s), SUM(latency_s), AVG(queued_s), GROUP_CONCAT(DISTINCT tokens_source) "
        "FROM jobs WHERE created >= ? GROUP BY agent", (since,)).fetchall()
    keys = ("agent", "requests", "succeeded", "failed_or_rejected", "prompt_tokens", "completion_tokens",
            "avg_latency_s", "inference_time_s", "avg_queue_wait_s", "token_sources")
    throttles = c.execute("SELECT decision, level, COUNT(*) FROM decisions WHERE t >= ? AND decision != 'admit' "
                          "GROUP BY decision, level", (since,)).fetchall()
    out = {"window_hours": args.hours,
           "local": [dict(zip(keys, r)) for r in rows],
           "throttling": [dict(zip(("decision", "level", "count"), r)) for r in throttles],
           "reliability": {
               "local_tokens": "measured when LM Studio returns `usage` (token_sources='api'); "
                               "'estimate' = characters/4 when it does not",
               "remote": "see remote_usage.py: only what local session logs and GitHub expose; no subscription "
                         "or billing data is available to this tool"}}
    print(json.dumps(out, indent=1))
    return 0


def switch(mode):
    c = store.connect()
    store.set_mode(c, mode)
    print(json.dumps({"mode": mode}))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--simulate", default="", help="testing only, e.g. vram_pct=97,ram_pct=50")
    r = sub.add_parser("report")
    r.add_argument("--hours", type=float, default=24)
    for m in ("pause", "resume", "stop", "recover"):
        sub.add_parser(m)
    sd = sub.add_parser("shutdown")
    sd.add_argument("--port", type=int, default=1235)
    a = ap.parse_args()
    if a.cmd == "status":
        return status(a)
    if a.cmd == "report":
        return report(a)
    if a.cmd == "shutdown":
        import urllib.request
        try:
            urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{a.port}/guardian/shutdown", data=b"{}",
                                                          method="POST"), timeout=5)
            print(json.dumps({"shutdown": "requested", "port": a.port}))
            return 0
        except OSError as e:
            print(json.dumps({"shutdown": "proxy not reachable", "error": str(e)}))
            return 1
    if a.cmd == "recover":
        print(json.dumps({"abandoned": store.recover_stale(store.connect(), 0)}))
        return 0
    return switch({"pause": "paused", "resume": "running", "stop": "stopped"}[a.cmd])


if __name__ == "__main__":
    sys.exit(main())
