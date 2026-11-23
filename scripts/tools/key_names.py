"""Read-only: Starfield's keyboard key-name table (the "name<TAB>hex" rows BSWin32KeyboardDevice resolves names with,
as OSF Settings does for a hotkey's "default"), found in Starfield.exe as UTF-16 text.

    python -I scripts\\tools\\key_names.py --exe "$sf\\Starfield.exe" [--all]

Why (2026-11-23): S2SDodge's OSF Settings hotkey default "LAlt" was not a name in the table, so the action was not
created ("not available in the current native Controls list"). Prints the rows for Alt / Shift / Ctrl / Space (or all).
"""
import argparse
import re
import sys

ROW = re.compile(r"([^\t\n\x00]{1,32})\t([0-9A-Fa-f]{1,4})\n")


def tables(text: str):
    """[[(name, code)]]: runs of at least 20 consecutive name<TAB>hex rows."""
    out, i = [], 0
    while True:
        m = ROW.search(text, i)
        if not m:
            return out
        rows, pos = [], m.start()
        while True:
            r = ROW.match(text, pos)
            if not r:
                break
            rows.append((r.group(1), int(r.group(2), 16)))
            pos = r.end()
        if len(rows) >= 20:
            out.append(rows)
        i = max(pos, m.end())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--all", action="store_true", help="print every row")
    a = ap.parse_args(argv)
    with open(a.exe, "rb") as fh:
        data = fh.read()
    found = []
    for start in (0, 1):                                  # UTF-16 text at either byte alignment
        text = data[start:len(data) - ((len(data) - start) % 2)].decode("utf-16-le", errors="replace")
        found += tables(text)
    if not found:
        print("no key-name table found")
        return 1
    for n, rows in enumerate(found):
        pick = rows if a.all else [r for r in rows if re.search(r"alt|shift|ctrl|control|space|menu", r[0], re.I)]
        print(f"table {n}: {len(rows)} rows")
        for name, code in pick:
            print(f"  {name!r}\t0x{code:02X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
