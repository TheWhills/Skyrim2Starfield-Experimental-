"""Resource sampling for the Resource Guardian (Windows, standard library only).

Every value carries how it was obtained: "measured" (read from the OS, nvidia-smi or the LM Studio API) or
"estimated". Nothing here starts or stops work; admission decisions are in policy.py.
"""
import csv
import ctypes
import io
import json
import subprocess
import time
import urllib.request
from ctypes import wintypes

LMSTUDIO = "http://127.0.0.1:1234"
WATCHED = ("opencode", "codex", "grok", "claude", "lm studio", "lms", "llmster", "starfield", "python")


def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def gpu():
    """nvidia-smi: utilisation, VRAM and the processes using the GPU. None if unavailable."""
    out = _run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"])
    if not out:
        return {"available": False, "source": "nvidia-smi not available"}
    name, util, used, total = [x.strip() for x in out.strip().splitlines()[0].split(",")]
    procs = []
    pout = _run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"])
    for row in csv.reader(io.StringIO(pout or "")):
        if len(row) >= 3:
            procs.append({"pid": int(row[0]), "name": row[1].strip().split("\\")[-1],
                          "vram_mib": None if "N/A" in row[2] else int(row[2])})
    return {"available": True, "source": "measured (nvidia-smi)", "name": name,
            "utilization_pct": float(util), "vram_used_mib": int(used), "vram_total_mib": int(total),
            "vram_pct": round(100.0 * int(used) / int(total), 1),
            "compute_processes": procs,
            "note": "per-process VRAM is often N/A on Windows (WDDM); graphics apps like Starfield are not listed"}


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ram():
    m = _MEMSTATUS()
    m.dwLength = ctypes.sizeof(_MEMSTATUS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    used = m.ullTotalPhys - m.ullAvailPhys
    return {"source": "measured (GlobalMemoryStatusEx)", "used_gib": round(used / 2**30, 2),
            "total_gib": round(m.ullTotalPhys / 2**30, 2), "used_pct": round(100.0 * used / m.ullTotalPhys, 1)}


def _times():
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    v = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime
    return v(idle), v(kernel), v(user)


def cpu(interval=0.25):
    i0, k0, u0 = _times()
    time.sleep(interval)
    i1, k1, u1 = _times()
    total = (k1 - k0) + (u1 - u0)                       # kernel time includes idle time
    busy = total - (i1 - i0)
    return {"source": f"measured (GetSystemTimes over {interval}s)",
            "utilization_pct": round(100.0 * busy / total, 1) if total else 0.0}


def _get(url, timeout=2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def lmstudio(base=LMSTUDIO):
    """Server reachability and loaded models (LM Studio's REST API v0 lists state; /v1/models is the fallback)."""
    t0 = time.perf_counter()
    try:
        data = _get(base + "/api/v0/models")
        latency = round((time.perf_counter() - t0) * 1000, 1)
        models = [{"id": m.get("id"), "state": m.get("state"), "type": m.get("type"),
                   "max_context_length": m.get("max_context_length"),
                   "loaded_context_length": m.get("loaded_context_length")} for m in data.get("data", [])]
        return {"reachable": True, "source": "measured (/api/v0/models)", "latency_ms": latency,
                "loaded": [m for m in models if m["state"] == "loaded"], "downloaded": len(models)}
    except Exception as e:                              # noqa: BLE001
        try:
            data = _get(base + "/v1/models")
            return {"reachable": True, "source": "measured (/v1/models; no load state)",
                    "loaded": [{"id": m.get("id")} for m in data.get("data", [])]}
        except Exception:                               # noqa: BLE001
            return {"reachable": False, "source": "measured", "error": f"{type(e).__name__}: {e}"}


def processes():
    """Agent / model / game processes by image name (tasklist). Identifies presence, not activity."""
    out = _run(["tasklist", "/fo", "csv", "/nh"], timeout=10) or ""
    found = {}
    for row in csv.reader(io.StringIO(out)):
        if len(row) < 5:
            continue
        name = row[0].lower()
        key = next((w for w in WATCHED if name.startswith(w.replace(" ", ""))
                    or name.startswith(w)), None)
        if key:
            mem_kib = int(row[4].replace(",", "").replace(".", "").split()[0] or 0)
            f = found.setdefault(row[0], {"count": 0, "working_set_mib": 0})
            f["count"] += 1
            f["working_set_mib"] += mem_kib // 1024
    return {"source": "measured (tasklist image names)", "processes": found}


def snapshot(overrides=None):
    """One sample of everything. overrides (testing only): {"vram_pct": 97, "ram_pct": 50, ...} replace measured
    percentages and are flagged as simulated."""
    s = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "gpu": gpu(), "ram": ram(), "cpu": cpu(),
         "lmstudio": lmstudio(), "agents": processes()}
    if overrides:
        s["simulated"] = dict(overrides)
        if "vram_pct" in overrides and s["gpu"].get("available"):
            s["gpu"]["vram_pct"] = overrides["vram_pct"]
        if "ram_pct" in overrides:
            s["ram"]["used_pct"] = overrides["ram_pct"]
    return s
