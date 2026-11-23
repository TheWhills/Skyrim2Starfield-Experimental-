"""Write quadrant byte 6 of the staged Skyrim terrain like vanilla terrain does, and put it back (test, 2026-11-22).

Why: native grass (ground cover through Nirn's biome) grew nothing on our terrain, not even Starfield's own cover after
a ship landing. The vanilla survey (vanilla_btd_survey.py, owner's runs) found the one structural difference between
vanilla BTDs and ours: quadrant byte 6. Vanilla fills it in 96.6 % of hand-made world quadrants and 77.5 % of the
planet-trait overlays (bytes 5 and 7 always 0); ours writes 0. Its value names an LTEX table entry (head rule, b - 1)
that the quadrant's own bytes 0..4 never hold, usually one of Starfield's per-mask placeholder textures at the head of
the table (LDefault006Base, LDefault005Flow, LDefault004FlatOut, ...). Ground cover is chosen per biome mask
(Creation Kit wiki: not on Solid, Base or Path). Supported hypothesis: byte 6 tells the engine which mask (or mask
material) a painted quadrant belongs to, and with 0 nothing gets ground cover.

set     : appends the chosen LDefault* LTEX (from Starfield.esm, by --mask, e.g. FlatOut) to each staged BTD's table if
          missing and writes its entry into byte 6 of every quadrant with a texture; bytes 0..4, alphas and heights are
          untouched. The first time the BTDs are copied to <staging>\\btd_before_byte6.
restore : copies those originals back.
list    : prints Starfield.esm's LDefault* textures.
Reinstall the staging after set / restore (tools\\owner\\terrain_byte6.ps1 does both).

    python -I scripts\\terrain\\btd_byte6.py set --staging C:\\Modding\\staging\\skyrim_all --sf-esm "<Starfield>\\Data\\Starfield.esm" --mask FlatOut
"""
import argparse
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import btd, sfplugin  # noqa: E402

BACKUP = "btd_before_byte6"


def defaults(sf_esm):
    """{EditorID: FormID} of Starfield.esm's LDefault* landscape textures."""
    return {sfplugin.edid(s): fid for _t, _h, s, fid in sfplugin.records(sf_esm, [b"LTEX"])
            if sfplugin.edid(s).lower().startswith("ldefault")}


def pick(found, mask):
    """The LDefault texture whose EditorID contains mask (case-insensitive); SystemExit if none or several."""
    hits = {e: f for e, f in found.items() if mask.lower() in e.lower()}
    if len(hits) != 1:
        sys.exit(f"--mask {mask}: {'no' if not hits else 'several'} LDefault textures match "
                 f"({', '.join(sorted(hits or found))})")
    return next(iter(hits.items()))


def with_byte6(t: btd.Btd, fid: int) -> btd.Btd:
    """t with fid in its LTEX table (appended if missing: the existing indices stay) and byte 6 of every quadrant that
    holds a texture set to its entry (head rule: index + 1)."""
    table = list(t.ltex)
    if fid not in table:
        table.append(fid)
    if len(table) > 255:
        raise ValueError("LTEX table would pass 255 entries")
    q = t.quad_map.copy()
    has = (q[:, :, :5] > 0).any(axis=2)
    q[:, :, 6] = np.where(has, table.index(fid) + 1, 0).astype(np.uint8)
    return btd.Btd(t.version, t.hmin, t.hmax, table, t.heights_raw, t.weights, q)


def without_byte6(t: btd.Btd) -> btd.Btd:
    """t with byte 6 of every quadrant 0 and the LTEX table's trailing entries that no quadrant byte names any more
    removed (what with_byte6 appended), so set / restore work on the current terrain files (2026-11-23: a terrain
    refresh rewrites them; rebuilding from the first backup would put the old terrain back)."""
    q = t.quad_map.copy()
    q[:, :, 6] = 0
    used = int(q.max()) if q.size else 0
    table = list(t.ltex)[:max(used, 0)] if used < len(t.ltex) else list(t.ltex)
    return btd.Btd(t.version, t.hmin, t.hmax, table, t.heights_raw, t.weights, q)


def staged_btds(staging):
    import json
    with open(os.path.join(staging, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    out = []
    for o in prm["overlays"]:
        for rel in [o["btd_file"]] + list(o.get("btd_copies") or []):
            p = os.path.join(staging, *rel.split("/"))
            if os.path.exists(p):
                out.append(p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("set", "restore", "list"))
    ap.add_argument("--staging", default="")
    ap.add_argument("--sf-esm", default="")
    ap.add_argument("--mask", default="FlatOut", help="part of the LDefault texture's EditorID (default FlatOut)")
    a = ap.parse_args(argv)
    if a.cmd in ("set", "list") and not a.sf_esm:
        sys.exit("--sf-esm is needed")
    if a.cmd == "list":
        for e, f in sorted(defaults(a.sf_esm).items()):
            print(f"  {f:08X}  {e}")
        return 0
    if not a.staging:
        sys.exit("--staging is needed")
    backup = os.path.join(a.staging, BACKUP)
    if a.cmd == "restore":
        n = 0
        for p in staged_btds(a.staging):
            with open(p, "rb") as fh:
                t = btd.read(fh.read())
            with open(p, "wb") as fh:
                fh.write(btd.write(without_byte6(t)))
            n += 1
        if os.path.isdir(backup):
            shutil.rmtree(backup)
        print(f"{n} terrain file(s): byte 6 is 0 again")
        return 0
    edid, fid = pick(defaults(a.sf_esm), a.mask)
    paths = staged_btds(a.staging)
    if not paths:
        sys.exit("no staged BTD found (overlays_params.json btd_file)")
    for p in paths:
        keep = os.path.join(backup, os.path.relpath(p, a.staging))
        if not os.path.exists(keep):
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            shutil.copy2(p, keep)
        with open(p, "rb") as fh:                       # the current file: a terrain refresh may have rewritten it
            t = without_byte6(btd.read(fh.read()))      # an earlier set undone first: set twice = set once
        new = with_byte6(t, fid)
        data = btd.write(new)
        check = btd.read(data)
        assert np.array_equal(check.heights_raw, t.heights_raw) and np.array_equal(check.weights, t.weights)
        with open(p, "wb") as fh:
            fh.write(data)
        n = int((new.quad_map[:, :, 6] > 0).sum())
        print(f"{os.path.relpath(p, a.staging)}: byte 6 = {new.ltex.index(fid) + 1} ({edid}, {fid:08X}) in {n:,} "
              f"quadrants; table {len(t.ltex)} -> {len(new.ltex)} entries; heights and alphas unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
