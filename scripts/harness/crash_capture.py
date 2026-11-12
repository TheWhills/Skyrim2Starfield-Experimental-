"""Capture a native Starfield crash with a full minidump, or snapshot a hung game.

    python -I scripts\\harness\\crash_capture.py --selftest                 # prove the capture works, no game
    python -I scripts\\harness\\crash_capture.py                            # attach to the running Starfield.exe
    python -I scripts\\harness\\crash_capture.py --watch "D:\\S2S Test"      # attach to every test instance started there
    python -I scripts\\harness\\crash_capture.py --snapshot                 # stacks + dump of a HUNG game, then let go
    python -I scripts\\harness\\crash_capture.py --analyze out\\crash\\crash.dmp [--rva Starfield+0x1234]

Attaches cdb (Windows SDK "Debugging Tools for Windows") to the live process, waits for the fault, then writes
the exception record, registers, stacks, loaded modules and a full-memory dump. `--analyze` re-opens a dump
offline and disassembles the frames the stack names, so the faulting call site can be read without the game.

The mechanism matters (from tes4skyrim, where it was found on Skyrim SE): cdb's `-c` exception-handler commands
do NOT run for a `__fastfail` abort (`int 29h`, c0000409), because it is non-continuable and goes straight to
second chance, where cdb stops at its prompt and, with stdin closed, hangs capturing nothing. Feeding cdb its
commands over STDIN works, since the second-chance break has already frozen the faulting thread.

`.detach` is always the exit. cdb attaches invasively, so killing the debugger kills the game with it.

Ported from tes4skyrim's tools/live/crash_capture.py (MIT, bryantmh). See: scripts/harness/README.md
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

#: Where the x64 cdb.exe (matching the game) is looked for, after $env:S2S_CDB and before PATH.
CDB_PLACES = (r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe",
              r"C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe")


def find_cdb(env=os.environ, places=CDB_PLACES, which=shutil.which):
    """The cdb.exe to use: $env:S2S_CDB, the Windows SDK's usual folders, then PATH; None when there is none."""
    for path in ([env["S2S_CDB"]] if env.get("S2S_CDB") else []) + list(places):
        if os.path.exists(path):
            return path
    return which("cdb.exe") or which("cdb")


CDB = find_cdb()
PROCESS = "Starfield.exe"
OUT = os.path.join("out", "crash")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

#: Fed to cdb over stdin: arm, run, then describe the fault it stops on.
CAPTURE = """sxn eh
sxe c0000409
sxe -c ".echo MARKER_FASTFAIL; ~*kb 40" sbo
.echo MARKER_ARMED
g
.echo MARKER_CRASH
.exr -1
.lastevent
.echo MARKER_REGS
r
.echo MARKER_STACK
kb 100
.echo MARKER_CODE
u @rip-40 L30
.echo MARKER_MODULES
lm
.echo MARKER_THREADS
~*kb 15
.dump /ma "{dump}"
.echo MARKER_DUMPED
.detach
qd
"""

#: --watch: on a plain process exit, log who exited and let go (no dump).
ON_EXIT = 'sxe -c ".echo MARKER_EXIT; kb 60; ~*kb 20; .detach; qd" epr\n'

#: --snapshot: every thread's stack and a full dump of a process that is already hung, then let go
#: (non-invasive attach, -pv: never use it on a game that is merely running).
SNAPSHOT = """.echo MARKER_THREADS
~*kb 40
.dump /ma "{dump}"
.echo MARKER_DUMPED
qd
"""

WATCH_POLL = 2.0

#: Raises FAST_FAIL, so --selftest exercises the real non-continuable path.
VICTIM = """import ctypes
ctypes.windll.kernel32.RaiseFailFastException(None, None, 0)
"""

#: Sections of a capture log, in the order the debugger writes them.
SECTIONS = ("MARKER_CRASH", "MARKER_REGS", "MARKER_STACK", "MARKER_CODE",
            "MARKER_MODULES", "MARKER_THREADS", "MARKER_DUMPED")


def section(text: str, name: str = "MARKER_CRASH") -> str:
    """The body of marked section `name` of a capture log, up to the next later marker; "" when absent."""
    start = text.find(name)
    if start < 0:
        return ""
    body = text[start:]
    for later in (SECTIONS[SECTIONS.index(name) + 1:] if name in SECTIONS else ()):
        end = body.find(later)
        if end > 0:
            return body[:end]
    return body


def find_pid(image: str = PROCESS):
    """The pid of the first running process named `image`, or None."""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.lower().startswith('"%s"' % image.lower()):
            return line.split(",")[1].strip('"')
    return None


def pids_under(image: str, folder: str) -> list:
    """Pids of running `image` processes whose executable lies under `folder`."""
    script = ("Get-Process -Name %s -ErrorAction SilentlyContinue | ForEach-Object { '{0}|{1}' -f $_.Id, $_.Path }"
              % os.path.splitext(image)[0])
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    root = os.path.normcase(os.path.abspath(folder)) + os.sep
    rows = (line.partition("|") for line in out.splitlines())
    return [pid for pid, _bar, path in rows if path and os.path.normcase(path).startswith(root)]


def _prepare(out_dir: str, tag: str):
    """Makes the capture folder; its (log, dump) paths, stale copies removed."""
    os.makedirs(out_dir, exist_ok=True)
    log, dump = os.path.join(out_dir, tag + ".txt"), os.path.join(out_dir, tag + ".dmp")
    for stale in (log, dump):
        if os.path.exists(stale):
            os.remove(stale)
    return log, dump


MISSING_CDB = ("cdb.exe not found (looked at $env:S2S_CDB, %s and PATH): install the Windows SDK with only "
               "'Debugging Tools for Windows' ticked, or set $env:S2S_CDB" % ", ".join(CDB_PLACES))


def _need_cdb() -> None:
    if not CDB:
        raise SystemExit(MISSING_CDB)


def attach(pid, out_dir: str = OUT, tag: str = "crash", first: str = "") -> str:
    """Attaches cdb to `pid` and leaves it waiting for the fault (running `first` before arming); the log path."""
    _need_cdb()
    log, dump = _prepare(out_dir, tag)
    with open(log, "w", encoding="utf-8") as handle:
        proc = subprocess.Popen([CDB, "-p", str(pid)], stdin=subprocess.PIPE, stdout=handle,
                                stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW)
        proc.stdin.write(first + CAPTURE.format(dump=dump))
        proc.stdin.flush()
    print("cdb %s attached to pid %s; log %s; dump %s" % (proc.pid, pid, log, dump), flush=True)
    print("waiting for the fault: do not kill cdb (it would kill the game)", flush=True)
    return log


def armed(log: str, seconds: float = 30) -> bool:
    """Whether cdb got far enough to resume the target within `seconds`."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if os.path.exists(log):
            with open(log, encoding="utf-8", errors="replace") as handle:
                if "MARKER_ARMED" in handle.read():
                    return True
        time.sleep(0.5)
    return False


def snapshot(pid, out_dir: str = OUT, tag: str = "hang") -> str:
    """One non-invasive stack walk and full dump of a HUNG `pid`; the log path."""
    _need_cdb()
    log, dump = _prepare(out_dir, tag)
    with open(log, "w", encoding="utf-8") as handle:
        subprocess.run([CDB, "-pv", "-p", str(pid)], input=SNAPSHOT.format(dump=dump), stdout=handle,
                       stderr=subprocess.STDOUT, text=True, timeout=900, creationflags=NO_WINDOW)
    print("hang snapshot %s / %s" % (log, dump), flush=True)
    return log


def watch(image: str, folder: str, out_dir: str) -> int:
    """Attaches to every `image` started from `folder` until interrupted; a plain exit logs the exiting
    thread's stack (pid<N>.txt) and detaches, a fault writes the full capture."""
    seen = set()
    print("watching for %s under %s (Ctrl+C to stop)" % (image, folder), flush=True)
    while True:
        for pid in pids_under(image, folder):
            if pid not in seen:
                seen.add(pid)
                attach(pid, out_dir, "pid%s" % pid, ON_EXIT)
        time.sleep(WATCH_POLL)


def report(log: str, name: str = "MARKER_CRASH", limit: int = 80) -> None:
    """Prints one marked section of a capture log."""
    with open(log, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    body = section(text, name)
    if not body:
        print("%s not present; markers seen: %s" % (name, [m for m in SECTIONS if m in text]), flush=True)
        return
    for line in body.splitlines()[:limit]:
        print(line.rstrip(), flush=True)


def analyze(dump: str, out_dir: str, rvas=()) -> int:
    """Disassembles a saved dump offline; a process exit code."""
    _need_cdb()
    if not os.path.exists(dump):
        print("no dump at %s" % dump, flush=True)
        return 1
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "analyze.txt")
    parts = [".echo MARKER_CRASH", ".exr -1", ".lastevent", "r", "kb 100"]
    for rva in rvas:
        parts += [".echo ===RVA_%s===" % rva, "ub %s L14" % rva, ".echo ---AT---", "u %s L8" % rva]
    parts += [".echo MARKER_DUMPED", "q"]
    with open(out, "w", encoding="utf-8") as handle:
        subprocess.run([CDB, "-z", dump], input="\n".join(parts) + "\n", stdout=handle, stderr=subprocess.STDOUT,
                       text=True, timeout=900, creationflags=NO_WINDOW)
    print("wrote %s" % out, flush=True)
    report(out)
    return 0


def selftest(out_dir: str) -> int:
    """Proves the capture fires on a synthetic fast-fail; 0 when it passes."""
    _need_cdb()
    os.makedirs(out_dir, exist_ok=True)
    victim = os.path.join(out_dir, "victim.py")
    with open(victim, "w", encoding="utf-8") as handle:
        handle.write(VICTIM)
    log, dump = _prepare(out_dir, "selftest")
    with open(log, "w", encoding="utf-8") as handle:
        subprocess.run([CDB, sys.executable, "-I", victim], input=CAPTURE.format(dump=dump), stdout=handle,
                       stderr=subprocess.STDOUT, text=True, timeout=300)
    size = os.path.getsize(dump) if os.path.exists(dump) else 0
    with open(log, encoding="utf-8", errors="replace") as handle:
        seen = "MARKER_CRASH" in handle.read()
    ok = seen and size > 0
    print("selftest: crash_seen=%s dump_bytes=%d -> %s" % (seen, size, "PASS" if ok else "FAIL"), flush=True)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--process", default=PROCESS, help="image name to attach to")
    ap.add_argument("--pid", help="attach to this pid instead of searching")
    ap.add_argument("--out", default=OUT, help="capture folder")
    ap.add_argument("--tag", default="crash", help="base name of the log and dump")
    ap.add_argument("--analyze", metavar="DUMP", help="post-mortem a saved dump instead of attaching")
    ap.add_argument("--rva", action="append", default=[], help="extra address to disassemble with --analyze")
    ap.add_argument("--report", metavar="LOG", help="print a captured log's section without attaching")
    ap.add_argument("--section", default="MARKER_CRASH", help="which marked section --report prints")
    ap.add_argument("--selftest", action="store_true", help="prove the capture works, no game needed")
    ap.add_argument("--snapshot", action="store_true", help="stacks and a dump of a HUNG game, then let go")
    ap.add_argument("--watch", metavar="DIR", help="attach to every game started from DIR (test instances)")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.out)
    if args.analyze:
        return analyze(args.analyze, args.out, args.rva)
    if args.report:
        report(args.report, args.section)
        return 0
    if args.watch:
        return watch(args.process, args.watch, args.out)
    pid = args.pid or find_pid(args.process)
    if not pid:
        print("%s is not running" % args.process, flush=True)
        return 1
    if args.snapshot:
        snapshot(pid, args.out, args.tag if args.tag != "crash" else "hang")
        return 0
    return 0 if armed(attach(pid, args.out, args.tag)) else 1


if __name__ == "__main__":
    sys.exit(main())
