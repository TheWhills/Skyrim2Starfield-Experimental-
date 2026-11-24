"""Ask the analysed Starfield program in a Ghidra project questions without the GUI or ReVa (read-only).

Runs Ghidra's headless analyser on an existing project with -noanalysis -readOnly and the script
scripts/re/ghidra/QueryDump.java, which reads one command per line (info, decomp, xrefs, callers, qwords, string, sym,
vtable, find, insn; see the script's header) and writes the answers to a text file. Use it when ReVa is not running.
The Ghidra GUI must be closed (one process per project). Set GHIDRA_HEADLESS_MAXMEM (e.g. 12G) for Starfield.exe.

    python -I scripts\\re\\ghidra_query.py --ghidra <Ghidra 12.1 folder> ^
        --project "<folder>\\<project name>" --program Starfield.exe.1 ^
        --out C:\\Modding\\work\\q.txt "decomp 0x140bf45f0" "xrefs 0x144d60328"

Commands can also come from a file (--commands FILE). One run on the analysed Starfield project takes about a minute
(mostly opening the 3 GB project), so batch them.
"""
import argparse
import os
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ghidra")
COMMANDS = {"info", "decomp", "xrefs", "callers", "qwords", "string", "sym", "vtable", "find", "insn"}


def check_commands(lines):
    """Strip blank/comment lines and reject unknown commands before the slow headless start."""
    kept = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        word = line.split()[0]
        if word not in COMMANDS:
            raise ValueError(f"unknown command: {line}")
        kept.append(line)
    return kept


def headless_command(ghidra, project, program, cmd_file, out_file, script_dir=SCRIPT_DIR):
    """The analyzeHeadless argument list (project given as its folder + name, i.e. the .gpr path without .gpr)."""
    project = project[:-4] if project.lower().endswith(".gpr") else project
    location, name = os.path.split(project)
    launcher = os.path.join(ghidra, "support", "analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless")
    return [launcher, location, name, "-process", program, "-noanalysis", "-readOnly",
            "-scriptPath", script_dir, "-postScript", "QueryDump.java", cmd_file, out_file]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ghidra", required=True, help="Ghidra install folder")
    ap.add_argument("--project", required=True, help="project path without .gpr")
    ap.add_argument("--program", default="Starfield.exe", help="program name inside the project")
    ap.add_argument("--out", required=True)
    ap.add_argument("--commands", help="file with one command per line")
    ap.add_argument("command", nargs="*")
    a = ap.parse_args(argv)
    lines = list(a.command)
    if a.commands:
        with open(a.commands, encoding="utf-8") as f:
            lines += f.read().splitlines()
    lines = check_commands(lines)
    if not lines:
        ap.error("no commands")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
        cmd_file = f.name
    try:
        cmd = headless_command(a.ghidra, a.project, a.program, cmd_file, os.path.abspath(a.out))
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0 or not os.path.exists(a.out):
            sys.stderr.write(r.stdout[-4000:] + r.stderr[-4000:])
            return r.returncode or 1
    finally:
        os.unlink(cmd_file)
    print(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
