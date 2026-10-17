"""Print records of one type whose EditorID matches (read-only): every subrecord with its size, a hex preview and, when
it looks like text, the text. For designing a custom planet from a vanilla one (PNDT planets, STDT star systems,
BIOM biomes, ...), and for comparing them with a mod's (--esm can be any plugin).

    python -I scripts\\tools\\dump_records.py --esm "<Starfield>\\Data\\Starfield.esm" --type PNDT ^
        --edid "^(JemisonPlanetData|VoliiAlphaPlanetData|LunaPlanetData)$" > C:\\Modding\\work\\planets.txt
    python -I scripts\\tools\\dump_records.py --esm ... --type PNDT --list        (every EditorID of that type)
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402


def text_of(d: bytes):
    s = d.rstrip(b"\0")
    if len(s) >= 3 and all(32 <= c < 127 or c in (9, 10, 13) for c in s):
        return s.decode("latin-1")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--type", required=True, help="record type, e.g. PNDT, STDT, BIOM")
    ap.add_argument("--edid", default=".", help="regex on the EditorID")
    ap.add_argument("--list", action="store_true", help="only list matching EditorIDs and FormIDs")
    ap.add_argument("--bytes", type=int, default=96, help="hex preview length per subrecord")
    a = ap.parse_args(argv)
    rx = re.compile(a.edid, re.I)
    with fo4land.Plugin(a.esm) as p:
        rng = p.top_group(a.type.encode())
        if rng is None:
            sys.exit(f"no {a.type} group in {a.esm}")
        n = 0
        for typ, off, flags, fid in fo4land.iter_items(p.buf, *rng):
            if typ == "GRUP":
                continue
            subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
            edid = next((fo4land.zstring(d) for s, d in subs if s == b"EDID"), "")
            if not rx.search(edid):
                continue
            n += 1
            if a.list:
                print(f"{fid:08X} {edid}")
                continue
            print(f"== {typ.decode()} {fid:08X} {edid} (record flags 0x{flags:08X}, {len(subs)} subrecords)")
            for s, d in subs:
                d = bytes(d)
                t = text_of(d)
                hx = d[:a.bytes].hex(" ") + (" ..." if len(d) > a.bytes else "")
                print(f"  {s.decode('latin-1')} [{len(d)}] {hx}" + (f"   '{t}'" if t else ""))
        print(f"{n} {a.type} records matched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
