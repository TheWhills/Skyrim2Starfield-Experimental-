"""Which plugin wins each overridden ground texture (LTEX) record in the installed load order (2026-11-22).

    python -I scripts\\terrain\\ltex_winner.py --sf-data "$sf\\Data" --staging C:\\Modding\\staging\\skyrim_all

Why: the owner's colour test painted 8 converted Skyrim ground textures; magenta (LRocks01NoRocks, slot 00030138) and
cyan (LRocks01, 000557E2) showed in game, but red / green / orange / blue / yellow (LReachGrass01, LReachGrass01NoGrass,
LReachDirt01, LDirt01, LReachMossyRocks01) did not, and the pale band stayed pale. So for some slots the game does not
use our material. This lists, for every slot the exterior overrides (overlays_params.json ltex_overrides), every
plugin that has that Starfield.esm LTEX record and its BNAM (material path), in load order: official masters present
in Data first (Starfield.esm, then the others), then Plugins.txt's active entries. The last one wins in game. A slot
whose winner is not our plugin, or whose winning BNAM is not our material, is marked LOST. Read-only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import fo4land  # noqa: E402

OFFICIAL = ("Starfield.esm", "Constellation.esm", "OldMars.esm", "ShatteredSpace.esm")


def masters(p):
    """The plugin's master file names (TES4 MAST), in order."""
    out = []
    for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0)):
        if sig == b"MAST":
            out.append(fo4land.zstring(d))
    return out


def ltex_records(path):
    """{Starfield.esm LTEX form id (master index stripped): {"edid", "bnam"}} the plugin defines or overrides."""
    out = {}
    name = os.path.basename(path)
    with fo4land.Plugin(path) as p:
        ms = masters(p)
        rng = p.top_group(b"LTEX")
        if rng is None:
            return out
        for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
            if typ == "GRUP":
                continue
            idx = fid >> 24
            owner = ms[idx] if idx < len(ms) else name
            if owner.lower() != "starfield.esm":
                continue
            rec = {"edid": "", "bnam": ""}
            for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                if sig == b"EDID":
                    rec["edid"] = fo4land.zstring(d)
                elif sig == b"BNAM":
                    rec["bnam"] = fo4land.zstring(d)
            out[fid & 0xFFFFFF] = rec
    return out


def load_order(sf_data, plugins_txt):
    """Plugin paths in load order: the official masters present, other official-style SFBGS / BlueprintShips masters,
    then Plugins.txt's active ('*') entries."""
    order = [n for n in OFFICIAL if os.path.exists(os.path.join(sf_data, n))]
    extra = sorted(f for f in os.listdir(sf_data) if f.lower().endswith(".esm")
                   and (f.lower().startswith("sfbgs") or f.lower().startswith("blueprintships")))
    order += [f for f in extra if f not in order]
    if plugins_txt and os.path.exists(plugins_txt):
        with open(plugins_txt, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("*") and line[1:] not in order:
                    order.append(line[1:])
    return [os.path.join(sf_data, n) for n in order if os.path.exists(os.path.join(sf_data, n))]


def report(overrides, chains):
    """Lines for each override: its chain of (plugin, bnam) and OK / LOST."""
    lines, lost = [], 0
    for o in overrides:
        fid = int(o["form_id"], 16) if isinstance(o["form_id"], str) else int(o["form_id"])
        ours = (o.get("material") or "").replace("/", "\\").lower()
        chain = chains.get(fid & 0xFFFFFF, [])
        win = chain[-1] if chain else None
        ok = bool(win) and ours and ours.split("\\")[-1] in win[1].replace("/", "\\").lower()
        lost += 0 if ok else 1
        lines.append(f"{'OK  ' if ok else 'LOST'} {fid & 0xFFFFFF:08X} Skyrim {o.get('skyrim', '?'):26} "
                     f"(vanilla {o.get('vanilla_edid', '?')})")
        for plug, bnam in chain:
            lines.append(f"       {plug:40} {bnam}")
        if not chain:
            lines.append("       no plugin in the load order has this record")
    return lines, lost


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True, help="Starfield's Data folder")
    ap.add_argument("--staging", required=True, help="the installed exterior's staging (overlays_params.json)")
    ap.add_argument("--plugins", default=os.path.join(os.environ.get("LOCALAPPDATA", ""), "Starfield", "Plugins.txt"))
    a = ap.parse_args(argv)
    with open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    overrides = prm.get("ltex_overrides")
    if overrides is None and os.path.exists(os.path.join(a.staging, "skyrim_source.json")):
        with open(os.path.join(a.staging, "skyrim_source.json"), encoding="utf-8") as fh:
            overrides = (json.load(fh).get("land_textures") or {}).get("ltex_overrides")
    if not overrides:
        sys.exit("no ltex_overrides in the staging")
    chains = {}
    order = load_order(a.sf_data, a.plugins)
    print("load order read: " + ", ".join(os.path.basename(p) for p in order))
    for path in order:
        try:
            recs = ltex_records(path)
        except Exception as e:                                   # noqa: BLE001 - report and go on
            print(f"  {os.path.basename(path)}: not read ({e})")
            continue
        for fid, rec in recs.items():
            chains.setdefault(fid, []).append((os.path.basename(path), rec["bnam"]))
    lines, lost = report(overrides, chains)
    for ln in lines:
        print(ln)
    print(f"{len(overrides) - lost} of {len(overrides)} overridden ground textures win with our material; {lost} LOST")
    return 0


if __name__ == "__main__":
    sys.exit(main())
