"""Which Skyrim plugins change ground textures' grass lists, grasses, or a cell's landscape (read-only).

2026-11-23: at Riverwood the owner's Skyrim shows a dense grass carpet where Skyrim.esm's ground textures grow almost
no grass (grass_at.py: 13 % of the ground has a grassy texture even counting layers underneath), with no grass mod
installed. Our converters read Skyrim.esm only, so something loaded after it (Update.esm, the DLC, the Unofficial
Patch, a landscape or texture mod with a plugin) may give those textures grass or repaint the cell. Prints per plugin
in Skyrim's Data (and each --mods folder): its LTEX / GRAS counts, every LTEX it defines or overrides whose EditorID is
in --ltex (with its grass list, resolved to EditorIDs where any scanned plugin defines them), and whether it has LAND
for the Tamriel cells in --cell. plugins.txt (Skyrim SE's, if found) marks which plugins are active.

    python -I scripts\\terrain\\skyrim_ltex_scan.py --data "<Skyrim SE>\\Data" --cell 4 -12
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

VANILLA = ("skyrim.esm", "update.esm", "dawnguard.esm", "hearthfires.esm", "dragonborn.esm")
RIVERWOOD = ("LFieldGrass02NoGrass", "LDirt02", "LPineForest02NoGrass", "LFieldGrass02", "LPineForest01",
             "LFieldGrass01", "LFieldGrass01NoGrass", "LPineForest02")


def plugin_order(names):
    """Vanilla masters first (game order), then the rest: .esm before .esp / .esl, each by name."""
    low = {n.lower(): n for n in names}
    head = [low[v] for v in VANILLA if v in low]
    rest = sorted((n for n in names if n.lower() not in VANILLA),
                  key=lambda n: (not n.lower().endswith(".esm"), n.lower()))
    return head + rest


def origin(fid, masters, own):
    """(plugin that defines the FormID, lower-case; its local id)."""
    idx = fid >> 24
    name = masters[idx] if idx < len(masters) else own
    return name.lower(), fid & 0xFFFFFF


def scan_plugin(path, ltex_names, cells):
    """{"masters", "ltex": [(edid, fid, [grass fids])] for wanted EDIDs, "n_ltex", "n_gras",
    "gras": {fid: edid}, "land_cells": [(x, y)]} of one plugin."""
    want = {e.lower() for e in ltex_names}
    out = {"masters": [], "ltex": [], "n_ltex": 0, "n_gras": 0, "gras": {}, "land_cells": []}
    with fo4land.Plugin(path) as p:
        out["masters"] = [fo4land.zstring(bytes(d)) for s, d in
                          fo4land.iter_subrecords(fo4land.record_data(p.buf, 0)) if s == b"MAST"]
        for sig in (b"LTEX", b"GRAS"):
            rng = p.top_group(sig)
            if rng is None:
                continue
            for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
                if typ == "GRUP":
                    continue
                subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
                edid = next((fo4land.zstring(bytes(d)) for s, d in subs if s == b"EDID"), "")
                if sig == b"GRAS":
                    out["n_gras"] += 1
                    out["gras"][fid] = edid
                    continue
                out["n_ltex"] += 1
                if edid.lower() in want:
                    g = [struct.unpack_from("<I", bytes(d))[0] for s, d in subs if s == b"GNAM" and len(d) >= 4]
                    out["ltex"].append((edid, fid, g))
        if cells:
            try:
                _w, start, end, _f = p.find_world("Tamriel")
            except (KeyError, TypeError):
                return out
            wanted = {tuple(c) for c in cells}

            def walk(s, e, cell):
                for item in fo4land.iter_items(p.buf, s, e):
                    if item[0] == "GRUP":
                        _g, goff, gend, label, gtype = item
                        if gtype in (4, 5):
                            walk(goff + 24, gend, None)
                        elif gtype == 6 and cell is not None and struct.unpack("<I", label)[0] == cell[0]:
                            walk(goff + 24, gend, cell)
                        elif gtype in (8, 9) and cell is not None and cell[1] in wanted:
                            for it in fo4land.iter_items(p.buf, goff + 24, gend):
                                if it[0] == b"LAND" and cell[1] not in out["land_cells"]:
                                    out["land_cells"].append(cell[1])
                        continue
                    typ, off, _fl, fid = item
                    if typ == b"CELL":
                        xy = None
                        for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                            if sig == b"XCLC" and len(d) >= 8:
                                xy = struct.unpack_from("<ii", bytes(d))
                        cell = (fid, xy)
            walk(start, end, None)
    return out


def active_plugins(path):
    """Plugin names marked active (*) in a Skyrim SE plugins.txt, lower-case; None if unreadable."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return {ln.strip()[1:].lower() for ln in f if ln.strip().startswith("*")}
    except OSError:
        return None


def mo2_profile(instance, profile=""):
    """(profile folder, [enabled mod names, lowest priority first], active plugins lower-case or None) of a Mod
    Organizer instance (<instance>\\profiles\\<name>\\modlist.txt: '+Mod' enabled, top line = highest priority).
    Without a name: the only profile, else the one whose plugins.txt changed last."""
    root = os.path.join(instance, "profiles")
    names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    if profile:
        if profile not in names:
            raise SystemExit(f"profile {profile!r} not in {names}")
        pick = profile
    elif len(names) == 1:
        pick = names[0]
    else:
        def stamp(n):
            q = os.path.join(root, n, "plugins.txt")
            return os.path.getmtime(q) if os.path.isfile(q) else 0.0
        pick = max(names, key=stamp)
    folder = os.path.join(root, pick)
    mods = []
    try:
        with open(os.path.join(folder, "modlist.txt"), encoding="utf-8-sig", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith("+") and not ln.endswith("_separator"):
                    mods.append(ln[1:])
    except OSError:
        pass
    return folder, list(reversed(mods)), active_plugins(os.path.join(folder, "plugins.txt"))


def report(scans, active=None):
    """Lines: scans = [(plugin name, scan_plugin result)] in load order."""
    gras = {}
    for name, s in scans:
        for fid, e in s["gras"].items():
            gras[origin(fid, s["masters"], name)] = e
    out = []
    for name, s in scans:
        mark = "" if active is None else ("  [active]" if name.lower() in active or name.lower() in VANILLA
                                         else "  [not active]")
        if not (s["ltex"] or s["land_cells"] or s["n_ltex"] or s["n_gras"]):
            continue
        out.append(f"{name}{mark}: {s['n_ltex']} LTEX, {s['n_gras']} GRAS"
                   + (f", LAND for Tamriel cells {sorted(s['land_cells'])}" if s["land_cells"] else ""))
        for edid, fid, g in s["ltex"]:
            o = origin(fid, s["masters"], name)
            how = "defines" if o[0] == name.lower() else f"overrides {o[0]}'s"
            names = [gras.get(origin(x, s["masters"], name), f"{x:08X}") for x in g]
            out.append(f"    {how} {edid}: grass " + (", ".join(names) if names else "none"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="Skyrim SE's Data folder")
    ap.add_argument("--mods", action="append", default=[], help="a mod folder with plugins (repeatable)")
    ap.add_argument("--mo2", default="", help="a Mod Organizer instance folder (e.g. %%LOCALAPPDATA%%\\ModOrganizer\\"
                                              "Skyrim Special Edition): scans its profile's enabled mods")
    ap.add_argument("--profile", default="", help="with --mo2: the profile name (default: the only one, else the "
                                                  "last used)")
    ap.add_argument("--ltex", default=",".join(RIVERWOOD), help="LTEX EditorIDs to show (comma-separated)")
    ap.add_argument("--cell", type=int, nargs=2, action="append", default=[], metavar=("X", "Y"),
                    help="Tamriel cell whose LAND overrides to list (repeatable)")
    ap.add_argument("--plugins-txt", default=os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                                          "Skyrim Special Edition", "plugins.txt"))
    a = ap.parse_args(argv)
    active = active_plugins(a.plugins_txt)
    if a.mo2:
        folder, enabled, active = mo2_profile(a.mo2, a.profile)
        mods_root = os.path.join(a.mo2, "mods")
        found = [m for m in enabled if os.path.isdir(os.path.join(mods_root, m))]
        print(f"Mod Organizer profile {os.path.basename(folder)}: {len(enabled)} mods enabled, {len(found)} found")
        a.mods += [os.path.join(mods_root, m) for m in found]
    files = []
    for folder in [a.data] + a.mods:
        names = [n for n in os.listdir(folder) if n.lower().endswith((".esm", ".esp", ".esl"))
                 and os.path.isfile(os.path.join(folder, n))]
        files += [(n, os.path.join(folder, n)) for n in plugin_order(names)]
    scans = []
    for name, path in files:
        try:
            scans.append((name, scan_plugin(path, a.ltex.split(","), a.cell)))
        except Exception as e:                                     # noqa: BLE001 (reported, the scan goes on)
            print(f"{name}: unreadable ({type(e).__name__}: {e})")
    print(f"{len(files)} plugins scanned" + ("" if active is None else f"; plugins.txt: {len(active)} active"))
    for line in report(scans, active):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
