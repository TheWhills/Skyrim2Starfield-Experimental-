"""Check the installed exterior's converted ground materials, slot by slot (2026-11-22).

    python -I scripts\\terrain\\ground_material_check.py --sf-data "$sf\\Data" --staging C:\\Modding\\staging\\skyrim_all

Why: every overridden LTEX wins in the load order with our material (ltex_winner.py: 55 of 55), yet in the owner's
colour test only some painted textures showed (LRocks01NoRocks, LRocks01, LDirt02), others never (LReachGrass01,
LReachGrass01NoGrass, LReachDirt01, LDirt01, LReachMossyRocks01). For each override this reads the material from the
installed archive ("<plugin> - Main.ba2", else loose), lists the textures it names and whether each is in the archive,
and lists every resource ID ("res:...") that more than one of our ground materials defines: the game keeps one object
per ID, so a shared ID would make two materials draw the same (or a vanilla) layer. Also lists loose files in Data
with the same names (loose files win over archives: an old copy from an earlier test would hide ours). Read-only.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import ba2  # noqa: E402


def archive_name(path):
    """'Data\\textures\\x.dds' / 'materials\\x.mat' -> the archive's name for it (lower case, '\\')."""
    p = path.replace("/", "\\").lower()
    if p.startswith("data\\"):
        p = p[5:]
    return p


def mat_name(bnam):
    p = archive_name(bnam)
    return p if p.startswith("materials\\") else "materials\\" + p


def defined_ids(mat):
    """The resource IDs this material defines (objects' "ID")."""
    return [o["ID"] for o in mat.get("Objects", []) if o.get("ID")]


def texture_files(mat):
    out = []
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::MRTextureFile":
                out.append((c.get("Index"), c.get("Data", {}).get("FileName", "")))
    return out


def check(read, overrides, loose=None):
    """read(name) -> bytes or None; loose(name) -> True when a loose file of that name is in Data (loose files win over
    archives, so an old loose copy hides what the archive holds). Returns the report lines."""
    lines, owners = [], defaultdict(list)
    loose = loose or (lambda _n: False)
    hidden = []
    for o in overrides:
        name = mat_name(o.get("material") or "")
        data = read(name)
        tag = f"{o.get('skyrim', '?'):28} slot {o.get('form_id')} ({o.get('vanilla_edid', '?')})"
        if data is None:
            lines.append(f"MISSING  {tag}: {name} not in the archive or Data")
            continue
        try:
            mat = json.loads(data.decode("utf-8-sig"))
        except ValueError as e:
            lines.append(f"BAD JSON {tag}: {name}: {e}")
            continue
        for i in defined_ids(mat):
            owners[i].append(o.get("skyrim", name))
        if loose(name):
            hidden.append(name)
        hidden += [archive_name(f) for _i, f in texture_files(mat) if f and loose(archive_name(f))]
        miss = [f for _i, f in texture_files(mat) if f and read(archive_name(f)) is None]
        colour = next((f for i, f in texture_files(mat) if i == 0), "")
        lines.append(f"{'OK      ' if not miss else 'TEXTURE?'} {tag}: colour {archive_name(colour) or '(none)'}"
                     + (f"; not found: {miss}" if miss else ""))
    hidden = sorted(set(hidden))
    lines.append(f"LOOSE files in Data that win over the archive's copy: {len(hidden)}")
    for h in hidden:
        lines.append(f"  {h}")
    shared = {i: v for i, v in owners.items() if len(v) > 1}
    lines.append(f"resource IDs defined by more than one ground material: {len(shared)}")
    for i, v in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:20]:
        lines.append(f"  {i}: {', '.join(v[:8])}{' ...' if len(v) > 8 else ''}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--staging", required=True)
    a = ap.parse_args(argv)
    with open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    overrides = prm.get("ltex_overrides")
    if overrides is None and os.path.exists(os.path.join(a.staging, "skyrim_source.json")):
        with open(os.path.join(a.staging, "skyrim_source.json"), encoding="utf-8") as fh:
            overrides = (json.load(fh).get("land_textures") or {}).get("ltex_overrides")
    with open(os.path.join(a.staging, "formids.json"), encoding="utf-8") as fh:
        plugin = json.load(fh)["plugin"]
    arc_path = os.path.join(a.sf_data, os.path.splitext(plugin)[0] + " - Main.ba2")
    arc = ba2.Ba2(arc_path) if os.path.exists(arc_path) else None
    print(f"archive: {arc_path if arc else '(none: loose files only)'}")

    def loose(name):
        return os.path.exists(os.path.join(a.sf_data, *name.split("\\")))

    def read(name):
        if arc is not None and arc.find(name) is not None:
            return arc.read(name)
        p = os.path.join(a.sf_data, *name.split("\\"))
        if os.path.exists(p):
            with open(p, "rb") as fh:
                return fh.read()
        return None
    for ln in check(read, overrides or [], loose):
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
