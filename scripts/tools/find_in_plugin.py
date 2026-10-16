"""Find a text anywhere inside a plugin's records (read-only), decompressing compressed records: which record type,
FormID, EditorID and field holds it, with the surrounding text. For "where does the game keep this name", e.g. the
composite LOD names (Gagarin_LOD_Grp012) that are no record's EditorID.

    python -I scripts\\tools\\find_in_plugin.py "<Starfield>\\Data\\Starfield.esm" Gagarin_LOD NA_LOD_Apollo --max 20
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402


def walk(p, start, end):
    for item in fo4land.iter_items(p.buf, start, end):
        if item[0] == "GRUP":
            yield from walk(p, item[1] + 24, item[2])
        else:
            yield item


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plugin")
    ap.add_argument("text", nargs="+")
    ap.add_argument("--max", type=int, default=20, help="hits to print per text")
    a = ap.parse_args(argv)
    pats = {t: re.compile(re.escape(t.encode("latin-1")), re.I) for t in a.text}
    hits = {t: 0 for t in a.text}
    with fo4land.Plugin(a.plugin) as p:
        raw = bytes(p.buf)
        for t, rx in pats.items():                    # uncompressed occurrences anywhere (headers, strings)
            n = len(rx.findall(raw))
            print(f"{t}: {n} raw (uncompressed) occurrences in the file")
        for typ, off, flags, fid in walk(p, p.body, len(p.buf)):
            if not any(h < a.max for h in hits.values()):
                break
            try:
                data = fo4land.record_data(p.buf, off)
            except Exception:                          # noqa: BLE001
                continue
            if not any(rx.search(data) for rx in pats.values()):
                continue
            edid = ""
            fields = list(fo4land.iter_subrecords(data))
            for sig, d in fields:
                if sig == b"EDID":
                    edid = fo4land.zstring(d)
            for t, rx in pats.items():
                if hits[t] >= a.max:
                    continue
                for sig, d in fields:
                    m = rx.search(d)
                    if m:
                        ctx = d[max(0, m.start() - 40):m.end() + 60].decode("latin-1", "replace")
                        ctx = re.sub(r"[^ -~]", ".", ctx)
                        print(f"  [{t}] {typ.decode()} {fid:08X} {edid!r} field {sig.decode('latin-1')} "
                              f"({len(d)} B): ...{ctx}...")
                        hits[t] += 1
                        break
    for t, n in hits.items():
        print(f"{t}: {n} records shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
