"""One plugin that merges every S2S plugin's override of the same Starfield form list (S2SLooksMenu.esm).

2026-11-15, owner: the converted Skyrim hairs were gone from the looks menu. Cause (the owner's loadorder.txt):
S2SRaceTest.esm loads after S2SSkyrimHairs.esm and, since 2026-11-11, overrides HeadPartsChargenOptionsFemale / Male
too (the vanilla entries plus its race copies of face parts); the last loaded override of a record wins, so the hairs'
list (vanilla + KS + Skyrim hairs) was replaced. Each S2S plugin still writes its own override; this plugin, loaded
after all of them, holds the union: Starfield's entries, then each plugin's added entries in load order.

Merged: every Starfield.esm form list that two or more of the S2S plugins override (a list only one plugin overrides
needs nothing). Entries a plugin left out of its override are kept (the union; none of ours removes entries). Other
mods' overrides of the same lists are not read (only the S2S*.esm plugins of the mod folders).

Run by race_heads.py and skyrim_hairs.py after they write their plugin (the mods folder is --out's parent), or alone:
  python -I scripts/npc/looks_menu_lists.py --mods <MO2 mods folder> --starfield <Starfield folder>
"""
import argparse
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
from fo4sf import fo4land, sfplugin  # noqa: E402

PLUGIN = "S2SLooksMenu.esm"
FOLDER = "S2S Looks Menu"
BASE = "starfield.esm"


def masters_of(path: str) -> list:
    """The plugin's master file names (TES4 MAST), as written."""
    with fo4land.Plugin(path) as p:
        return [fo4land.zstring(bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0))
                if s == b"MAST"]


def list_overrides(path: str) -> dict:
    """{Starfield.esm object id: (EditorID, [(plugin lower case, object id)])} of the plugin's form lists that override
    a Starfield.esm list, entries resolved through its masters (the high byte past them is the plugin itself)."""
    mx = [m.lower() for m in masters_of(path)]
    own = os.path.basename(path).lower()

    def owner(fid):
        i = fid >> 24
        return mx[i] if i < len(mx) else own
    out = {}
    for _t, _h, subs, fid in sfplugin.records(path, [b"FLST"]):
        if owner(fid) != BASE:
            continue
        entries = [(owner(e), e & 0xFFFFFF) for e in
                   (struct.unpack_from("<I", bytes(d), 0)[0] for s, d in subs if s == b"LNAM" and len(d) >= 4)]
        out[fid & 0xFFFFFF] = (sfplugin.edid(subs), entries)
    return out


def find_plugins(mods_dir: str) -> list:
    """The S2S*.esm plugins in the mods folder's mod folders (not this one's own); of two with the same name (a copy
    in another mod folder) the newer file."""
    newest = {}
    for p in sorted(glob.glob(os.path.join(mods_dir, "*", "S2S*.esm"))):
        n = os.path.basename(p).lower()
        if n != PLUGIN.lower() and (n not in newest or os.path.getmtime(p) > os.path.getmtime(newest[n])):
            newest[n] = p
    return sorted(newest.values())


def load_order(paths: list, order_file=None) -> list:
    """paths in the game's load order: the order of a loadorder.txt / plugins.txt when given (names not in it last),
    else each plugin after its own masters, then by name."""
    by_name = {os.path.basename(p).lower(): p for p in paths}
    if order_file and os.path.isfile(order_file):
        with open(order_file, encoding="utf-8", errors="replace") as fh:
            names = [ln.strip().lstrip("*").lower() for ln in fh if ln.strip() and not ln.startswith("#")]
        listed = [by_name[n] for n in names if n in by_name]
        return listed + [p for p in paths if p not in listed]
    out, seen = [], set()

    def visit(p):
        n = os.path.basename(p).lower()
        if n in seen:
            return
        seen.add(n)
        for m in masters_of(p):
            if m.lower() in by_name:
                visit(by_name[m.lower()])
        out.append(p)
    for p in sorted(paths, key=lambda q: os.path.basename(q).lower()):
        visit(p)
    return out


def merge(vanilla_flst: list, plugins: list):
    """(records, masters, report) of the merged plugin. vanilla_flst: Starfield.esm's FLST records; plugins:
    [(file name, list_overrides(), its masters)] in load order."""
    vanilla = {fid & 0xFFFFFF: (h, subs) for _t, h, subs, fid in vanilla_flst}
    by_list = {}
    for name, ov, _m in plugins:
        for oid, (_edid, entries) in ov.items():
            by_list.setdefault(oid, []).append((name, entries))
    merged = {oid: rows for oid, rows in by_list.items() if len(rows) >= 2 and oid in vanilla}
    used = {p for rows in merged.values() for _n, entries in rows for p, _o in entries} - {BASE}
    masters = ["Starfield.esm"]
    for name, _ov, its in plugins:                    # each plugin after the masters its entries come from
        for m in list(its) + [name]:
            if m.lower() in used and m.lower() not in [x.lower() for x in masters]:
                masters.append(m)
    masters += sorted(used - {x.lower() for x in masters})
    index = {m.lower(): i for i, m in enumerate(masters)}
    recs, report = [], {"lists": {}, "masters": masters}
    for oid in sorted(merged):
        h, subs = vanilla[oid]
        have = [(BASE, struct.unpack_from("<I", bytes(d), 0)[0] & 0xFFFFFF)
                for s, d in subs if s == b"LNAM" and len(d) >= 4]
        seen, added = set(have), {}
        for name, entries in merged[oid]:
            for e in entries:
                if e not in seen:
                    seen.add(e)
                    have.append(e)
                    added[name] = added.get(name, 0) + 1
        lnam = [(b"LNAM", struct.pack("<I", (index[p] << 24) | o)) for p, o in have]
        at = next((i for i, (s, _d) in enumerate(subs) if s == b"LNAM"), len(subs))
        rest = [(s, d) for s, d in subs if s != b"LNAM"]
        recs.append((b"FLST", h, rest[:at] + lnam + rest[at:], oid))
        report["lists"][sfplugin.edid(subs)] = {"entries": len(have), "from": [n for n, _e in merged[oid]],
                                                "added_by": added}
    return recs, masters, report


def update(mods_dir: str, starfield_esm: str, order_file=None, quiet=False) -> dict:
    """Write <mods>/S2S Looks Menu/S2SLooksMenu.esm when two or more S2S plugins override the same Starfield list."""
    paths = load_order(find_plugins(mods_dir), order_file)
    plugins = []
    for p in paths:
        try:
            ov, its = list_overrides(p), masters_of(p)
        except Exception as e:                                   # noqa: BLE001 (one unreadable plugin: skip it)
            if not quiet:
                print(f"  looks menu lists: {os.path.basename(p)} not read ({type(e).__name__}: {e})")
            continue
        if ov:
            plugins.append((os.path.basename(p), ov, its))
    flst = sfplugin.records(starfield_esm, [b"FLST"])
    recs, masters, report = merge(flst, plugins)
    out = os.path.join(mods_dir, FOLDER, PLUGIN)
    report["plugin"] = out
    if not recs:
        report["written"] = False
        if not quiet:
            print("  looks menu lists: no list overridden by two S2S plugins" +
                  (f" ({PLUGIN} left as it was: disable it)" if os.path.isfile(out) else ""))
        return report
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(sfplugin.build(recs, sfplugin.header_info(starfield_esm), author="Skyrim2Starfield looks menu",
                                masters=masters))
    report["written"] = True
    if not quiet:
        for edid, r in report["lists"].items():
            print(f"  looks menu lists: {edid} {r['entries']} entries from {', '.join(r['from'])}")
        print(f"  {PLUGIN} in '{FOLDER}': enable it in MO2, loaded after {', '.join(masters[1:])}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mods", required=True, help="the MO2 mods folder (holds 'S2S Race Test', 'S2S Skyrim Hairs' ...)")
    ap.add_argument("--starfield", required=True, help="the Starfield folder (Data\\Starfield.esm)")
    ap.add_argument("--load-order", help="MO2's loadorder.txt (default: each plugin after its masters, then by name)")
    a = ap.parse_args(argv)
    update(a.mods, os.path.join(a.starfield, "Data", "Starfield.esm"), a.load_order)


if __name__ == "__main__":
    main()
