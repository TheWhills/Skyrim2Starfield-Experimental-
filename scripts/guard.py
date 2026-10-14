"""Fail if the repo contains game data or machine-specific paths.

Run before every commit (CI runs it too):  python scripts/guard.py
Walks the working tree, so it also catches untracked files you're about to `git add`.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", ".venv", "bin", "obj", ".vs", "node_modules"}
BANNED_EXT = {
    ".ba2", ".bsa", ".esm", ".esp", ".esl", ".nif", ".dds", ".mesh", ".hkx", ".fuz", ".wem", ".xwm",
    ".bgsm", ".bgem", ".btd", ".btr", ".bto", ".cdb", ".pex", ".swf", ".exe", ".dll", ".7z", ".zip",
    ".bnk", ".af", ".afx", ".agx", ".rig", ".ffxanim", ".dmp",
}
MAX_BYTES = 2_000_000
TEXT_EXT = {".md", ".py", ".json", ".toml", ".yml", ".yaml", ".txt", ".cs", ".csproj", ".sln", ".ps1", ".sh", ".xml"}
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"']+|/Users/[^/\s\"']+|/home/[^/\s\"']+")
ALLOWED_PATH_WORDS = {"<user>", "<you>", "%USERNAME%", "$HOME", "username"}


def main():
    problems = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            ext = os.path.splitext(fn)[1].lower()
            if ext in BANNED_EXT:
                problems.append(f"{rel}: banned file type {ext} (game data / binaries are never committed)")
                continue
            size = os.path.getsize(path)
            if size > MAX_BYTES:
                problems.append(f"{rel}: {size:,} bytes exceeds {MAX_BYTES:,}")
            if fn == "config.toml":
                problems.append(f"{rel}: local config must not be committed")
            if ext in TEXT_EXT and rel != "scripts/guard.py":
                with open(path, encoding="utf-8", errors="replace") as f:
                    for n, line in enumerate(f, 1):
                        m = LOCAL_PATH.search(line)
                        if m and not any(w in m.group(0) for w in ALLOWED_PATH_WORDS):
                            problems.append(f"{rel}:{n}: machine-specific path {m.group(0)!r}")
    if problems:
        print("guard: FAILED")
        for p in problems:
            print("  " + p)
        return 1
    print("guard: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
