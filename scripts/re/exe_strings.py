"""Grass-related names inside Starfield.exe (read-only): INI settings, console commands, class names (RTTI).

2026-11-22: three record-level routes to Starfield's ground cover (a cover's own texture list, the world's biome, the
planet's biome under the overlay) and a vanilla control grew no grass on the Skyrim world. Until now only records and
BTD files were surveyed, never the engine. The executable's strings name what it reads and checks: INI settings
(`fGrassStartFadeDistance:Grass` style), console commands, and RTTI class names (`.?AVBGSGroundCover@@`), which point
at how grass is placed (procedural terrain only? a per-world switch? a setting to turn it on?).

    python -I scripts\\re\\exe_strings.py --exe "D:\\SteamLibrary\\steamapps\\common\\Starfield\\Starfield.exe" ^
        --out C:\\Modding\\work\\grass_strings.txt

Default pattern: grass|groundcover|gcvr|biome|procgen|landscape cover. Prints a summary by kind and writes every match
(offset, kind, text) to --out.
"""
import argparse
import re
import sys

DEFAULT = r"grass|groundcover|ground cover|gcvr|procgen|proc_gen|biome"
ASCII = re.compile(rb"[\x20-\x7e]{5,}")
UTF16 = re.compile(rb"(?<![\x20-\x7e])(?:[\x20-\x7e]\x00){5,}")   # not starting inside an ASCII string


def kind(text):
    """How a string looks: rtti (.?AV class@@), setting (name:Section with a type prefix), path, or text."""
    if text.startswith((".?AV", ".?AU")):
        return "rtti"
    if re.fullmatch(r"[bfiuS][A-Z][A-Za-z0-9_]*:[A-Za-z][A-Za-z0-9_]*", text):
        return "setting"
    if "\\" in text or "/" in text or re.search(r"\.(nif|dds|mat|btd|biom|esm)$", text, re.I):
        return "path"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]+", text):
        return "identifier"
    return "text"


def scan(data: bytes, pattern: str):
    """[(offset, kind, text)] of the ASCII and UTF-16 strings in data matching pattern (case-insensitive), unique by
    text (first offset kept)."""
    rx = re.compile(pattern, re.I)
    seen, out = set(), []
    for m in ASCII.finditer(data):
        t = m.group().decode("ascii")
        if rx.search(t) and t not in seen:
            seen.add(t)
            out.append((m.start(), kind(t), t))
    for m in UTF16.finditer(data):
        t = m.group().decode("utf-16-le")
        if rx.search(t) and t not in seen:
            seen.add(t)
            out.append((m.start(), kind(t), t))
    return sorted(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True, help="Starfield.exe (read only)")
    ap.add_argument("--pattern", default=DEFAULT, help=f"regular expression, case-insensitive (default {DEFAULT})")
    ap.add_argument("--out", default="", help="also write every match here (outside the repository)")
    a = ap.parse_args(argv)
    with open(a.exe, "rb") as fh:
        data = fh.read()
    hits = scan(data, a.pattern)
    by = {}
    for off, k, t in hits:
        by.setdefault(k, []).append((off, t))
    print(f"{len(hits)} strings matching /{a.pattern}/ in {a.exe} ({len(data) / 1e6:.0f} MB)")
    for k in ("setting", "rtti", "identifier", "path", "text"):
        rows = by.get(k, [])
        if not rows:
            continue
        print(f"\n{k} ({len(rows)}):")
        for off, t in rows[:150]:
            print(f"  {off:#010x}  {t[:160]}")
        if len(rows) > 150:
            print(f"  ... {len(rows) - 150} more in --out")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            for off, k, t in hits:
                fh.write(f"{off:#010x}\t{k}\t{t}\n")
        print(f"\nall matches -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
