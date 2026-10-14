"""Admission-controlled proxy in front of LM Studio: the deterministic part of the Resource Guardian.

Local agents (OpenCode) talk to http://127.0.0.1:1235/v1 instead of LM Studio's :1234. Every inference request
(/v1/chat/completions, /v1/completions, /v1/embeddings, /v1/responses) becomes a job in the guardian DB (store.STATE, outside the repo):
  queued -> running -> done | failed | timeout       or   queued -> rejected
At most max_concurrent_local jobs run at once (default 1). Before admitting, the resource policy is checked
(policy.py); while the level is restrict/block or the manual mode is "paused", jobs wait in the queue up to
queue_wait_s, then get HTTP 503. Mode "stopped" rejects new jobs at once. Every non-admit decision is logged.

Agent attribution: the model name the client asks for may be an alias from config.json "agents"
(e.g. "fo4-lead" -> the real LM Studio model id); the alias names the agent. Unknown names pass through as-is.
Usage: tokens from the API's `usage` field when present (streams ask for it via stream_options.include_usage),
otherwise estimated as characters/4 and labelled "estimate".

Bypass: anything that calls :1234 directly (LM Studio's own chat UI, other tools) is not controlled.

  python proxy.py [--port 1235] [--upstream http://127.0.0.1:1234]
"""
import argparse
import http.client
import json
import os
import signal
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardian    # noqa: E402
import policy      # noqa: E402
import resources   # noqa: E402
import store       # noqa: E402

INFER = ("/v1/chat/completions", "/v1/completions", "/v1/embeddings", "/v1/responses")
LOCK = threading.Condition()
STATE = {"running": 0, "shutting_down": False}
CFG = {}
UPSTREAM = None
SHUTDOWN = [None]


def _log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(os.path.join(store.STATE, "proxy.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _agent_and_model(name):
    agents = CFG.get("agents", {})
    if name in agents:
        return name, agents[name]
    return "unknown", name


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):          # quiet default access log; decisions go to the DB and proxy.log
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _upstream(self, method, path, body, headers):
        u = urllib.parse.urlparse(UPSTREAM)
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=CFG["request_timeout_s"])
        conn.request(method, path, body=body, headers=headers)
        return conn, conn.getresponse()

    def do_GET(self):
        if self.path.startswith("/guardian/status"):
            c = store.connect()
            self._send_json(200, {"mode": store.get_mode(c), "running": STATE["running"]})
            return
        try:
            conn, r = self._upstream("GET", self.path, None, {})
            data = r.read()
            if self.path.rstrip("/") == "/v1/models" and r.status == 200:    # advertise the agent aliases too
                obj = json.loads(data)
                for alias in CFG.get("agents", {}):
                    obj.setdefault("data", []).append({"id": alias, "object": "model", "owned_by": "guardian-alias"})
                data = json.dumps(obj).encode()
            self.send_response(r.status)
            self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()
        except OSError as e:
            self._send_json(502, {"error": f"upstream unreachable: {e}"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if self.path == "/guardian/shutdown":          # graceful stop (bound to 127.0.0.1 only)
            self._send_json(202, {"shutdown": "requested"})
            threading.Thread(target=SHUTDOWN[0], daemon=True).start()
            return
        if not self.path.startswith(INFER):
            self._send_json(404, {"error": "not an inference endpoint"})
            return
        try:
            req = json.loads(raw or b"{}")
        except ValueError:
            self._send_json(400, {"error": "invalid JSON"})
            return
        agent, real = _agent_and_model(req.get("model", ""))
        req["model"] = real
        stream = bool(req.get("stream"))
        if stream and self.path.startswith("/v1/chat/completions"):
            req.setdefault("stream_options", {})["include_usage"] = True
        c = store.connect()
        now = time.time()
        job = c.execute("INSERT INTO jobs (agent, model, kind, status, created, heartbeat, owner_pid) "
                        "VALUES (?,?,?,?,?,?,?)", (agent, real, self.path, "queued", now, now, os.getpid())).lastrowid
        decision = self._wait_for_admission(c, job)
        if decision != "admit":
            c.execute("UPDATE jobs SET status='rejected', finished=?, error=? WHERE id=?",
                      (time.time(), decision, job))
            self._send_json(503, {"error": f"guardian: {decision}", "job": job})
            return
        try:
            self._run(c, job, req, stream, now)
        finally:
            with LOCK:
                STATE["running"] -= 1
                LOCK.notify_all()

    def _wait_for_admission(self, c, job):
        deadline = time.time() + CFG["queue_wait_s"]
        last_logged = None
        while True:
            mode = store.get_mode(c)
            if mode == "stopped" or STATE["shutting_down"]:
                store.log_decision(c, job, "reject", "stopped", ["manual stop or shutdown"])
                return "rejected (stopped)"
            snap = resources.snapshot(CFG.get("simulate"))
            with LOCK:
                if mode == "paused":
                    d, lv, why = "queue", "paused", ["manual pause"]
                else:
                    d, lv, why = policy.admit(snap, CFG, STATE["running"])
                if d == "admit":
                    STATE["running"] += 1
                    store.log_decision(c, job, "admit", lv, why)
                    c.execute("UPDATE jobs SET status='running', started=?, heartbeat=?, queued_s=? WHERE id=?",
                              (time.time(), time.time(), time.time() - c.execute(
                                  "SELECT created FROM jobs WHERE id=?", (job,)).fetchone()[0], job))
                    return "admit"
            if (d, lv) != last_logged:
                store.log_decision(c, job, d, lv, why)
                _log(f"job {job} {d}: {lv}: {'; '.join(why)}")
                last_logged = (d, lv)
            c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time(), job))
            if time.time() > deadline:
                store.log_decision(c, job, "reject", lv, why + ["queue wait exceeded"])
                return f"rejected (waited {CFG['queue_wait_s']}s: {lv})"
            with LOCK:
                LOCK.wait(timeout=2.0)

    def _run(self, c, job, req, stream, created):
        body = json.dumps(req).encode()
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        t0 = time.time()
        attempts, conn, r = 0, None, None
        while True:                                   # bounded retry only before anything reached the client
            try:
                conn, r = self._upstream("POST", self.path, body, headers)
                break
            except OSError as e:
                attempts += 1
                if attempts > CFG.get("max_retries", 2):
                    c.execute("UPDATE jobs SET status='failed', finished=?, error=? WHERE id=?",
                              (time.time(), f"upstream: {e}", job))
                    self._send_json(502, {"error": f"upstream unreachable after {attempts} tries: {e}"})
                    return
                time.sleep(2 ** attempts)             # backoff 2 s, 4 s
        usage, chars = None, 0
        try:
            self.send_response(r.status)
            for k in ("Content-Type",):
                if r.getheader(k):
                    self.send_header(k, r.getheader(k))
            if stream:
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                last_hb = time.time()
                for line in r:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
                    self.wfile.flush()
                    if line.startswith(b"data: {"):
                        try:
                            ev = json.loads(line[6:])
                            usage = ev.get("usage") or usage
                            for ch in ev.get("choices") or []:
                                chars += len(json.dumps(ch.get("delta") or {}))
                        except ValueError:
                            pass
                    if time.time() - last_hb > 5:
                        c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time(), job))
                        last_hb = time.time()
                self.wfile.write(b"0\r\n\r\n")
            else:
                data = r.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                try:
                    usage = json.loads(data).get("usage")
                except ValueError:
                    pass
                chars = len(data)
            ok = r.status < 400
            if usage:
                pt, ct, src = usage.get("prompt_tokens"), usage.get("completion_tokens"), "api"
            else:
                pt, ct, src = len(body) // 4, chars // 4, "estimate"
            c.execute("UPDATE jobs SET status=?, finished=?, latency_s=?, prompt_tokens=?, completion_tokens=?, "
                      "tokens_source=?, error=? WHERE id=?",
                      ("done" if ok else "failed", time.time(), time.time() - t0, pt, ct, src,
                       None if ok else f"HTTP {r.status}", job))
            _log(f"job {job} {'done' if ok else 'failed'} {r.status} {time.time() - t0:.1f}s tokens {pt}/{ct} ({src})")
        except (OSError, http.client.HTTPException) as e:
            kind = "timeout" if "timed out" in str(e) else "failed"
            c.execute("UPDATE jobs SET status=?, finished=?, latency_s=?, error=? WHERE id=?",
                      (kind, time.time(), time.time() - t0, f"{type(e).__name__}: {e}", job))
            _log(f"job {job} {kind}: {e}")
        finally:
            if conn:
                conn.close()


def main():
    global CFG, UPSTREAM
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=1235)
    ap.add_argument("--upstream", default="http://127.0.0.1:1234")
    ap.add_argument("--simulate", default="", help="testing only: vram_pct=97,ram_pct=50")
    ap.add_argument("--queue-wait", type=float, default=None, help="override queue_wait_s (tests)")
    ap.add_argument("--no-game-block", action="store_true", help="tests only: ignore the running-game rule")
    a = ap.parse_args()
    CFG = guardian.load_config()
    if os.path.exists(guardian.CONFIG):
        with open(guardian.CONFIG, encoding="utf-8") as f:
            CFG["agents"] = json.load(f).get("agents", {})
    CFG["simulate"] = guardian.parse_sim(a.simulate)
    if a.queue_wait is not None:
        CFG["queue_wait_s"] = a.queue_wait
    if a.no_game_block:
        CFG["game_blocks_inference"] = False
    UPSTREAM = a.upstream
    c = store.connect()
    n = store.recover_stale(c, 0)                     # this process owns the queue now: anything left is stale
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)   # bind fails if another proxy runs: single instance
    srv.daemon_threads = True
    with open(os.path.join(store.STATE, "proxy.pid"), "w") as f:
        f.write(str(os.getpid()))
    _log(f"proxy pid {os.getpid()} on :{a.port} -> {UPSTREAM}; recovered {n} stale jobs; "
         f"max_concurrent_local={CFG['max_concurrent_local']}" + (f"; SIMULATING {CFG['simulate']}" if CFG['simulate'] else ""))

    def shutdown(*_):
        STATE["shutting_down"] = True
        _log("shutdown requested: rejecting new jobs, waiting for running ones (max 60 s)")
        end = time.time() + 60
        with LOCK:
            LOCK.notify_all()
            while STATE["running"] > 0 and time.time() < end:
                LOCK.wait(timeout=1)
        store.recover_stale(store.connect(), 0)
        threading.Thread(target=srv.shutdown, daemon=True).start()

    SHUTDOWN[0] = shutdown
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, shutdown)
    try:
        srv.serve_forever(poll_interval=0.5)
    finally:
        os.remove(os.path.join(store.STATE, "proxy.pid")) if os.path.exists(os.path.join(store.STATE, "proxy.pid")) else None
        _log("proxy stopped")


if __name__ == "__main__":
    main()
