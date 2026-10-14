"""SQLite history for the Resource Guardian: local inference jobs, throttling decisions, resource samples and the
pause / stop switch. One file (guardian.db), WAL mode so the proxy and the status command can read and write at once.

Runtime state lives OUTSIDE the repository (%LOCALAPPDATA%\\fo4-ai-team\\state, or $FO4_AI_TEAM_STATE): logs hold
machine paths, and scripts/guard.py scans the whole working tree, ignored files included.
"""
import json
import os
import sqlite3
import time

STATE = os.environ.get("FO4_AI_TEAM_STATE") or os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "fo4-ai-team", "state")
DB = os.path.join(STATE, "guardian.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, model TEXT, kind TEXT, status TEXT,
  created REAL, started REAL, finished REAL, heartbeat REAL, queued_s REAL, latency_s REAL,
  prompt_tokens INTEGER, completion_tokens INTEGER, tokens_source TEXT, error TEXT, owner_pid INTEGER);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, job_id INTEGER, decision TEXT, level TEXT, reasons TEXT);
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, level TEXT, vram_pct REAL, ram_pct REAL, cpu_pct REAL,
  gpu_util REAL, lm_reachable INTEGER, simulated INTEGER);
CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY, value TEXT, t REAL);
"""


def connect():
    os.makedirs(STATE, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def get_mode(c):
    """running | paused | stopped (manual switch)."""
    r = c.execute("SELECT value FROM control WHERE key='mode'").fetchone()
    return r[0] if r else "running"


def set_mode(c, mode):
    c.execute("INSERT OR REPLACE INTO control VALUES ('mode', ?, ?)", (mode, time.time()))


def log_decision(c, job_id, decision, lv, reasons):
    c.execute("INSERT INTO decisions (t, job_id, decision, level, reasons) VALUES (?,?,?,?,?)",
              (time.time(), job_id, decision, lv, json.dumps(reasons)))


def log_sample(c, snap, lv):
    g = snap.get("gpu", {})
    c.execute("INSERT INTO samples (t, level, vram_pct, ram_pct, cpu_pct, gpu_util, lm_reachable, simulated) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (time.time(), lv, g.get("vram_pct"), snap["ram"]["used_pct"], snap["cpu"]["utilization_pct"],
               g.get("utilization_pct"), int(bool(snap["lmstudio"].get("reachable"))), int("simulated" in snap)))


def recover_stale(c, stale_after_s=120):
    """Restart recovery: jobs left 'running' or 'queued' by a proxy that died are marked 'abandoned'."""
    cut = time.time() - stale_after_s
    n = c.execute("UPDATE jobs SET status='abandoned', finished=?, error='proxy restarted or heartbeat lost' "
                  "WHERE status IN ('running','queued') AND COALESCE(heartbeat, created) < ?",
                  (time.time(), cut)).rowcount
    return n
