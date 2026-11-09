"""Can Skyrim race proportions (per-race skeletons, e.g. Racial Body Morphs) carry over onto Starfield's skeleton?

    python -I scripts\\npc\\skeleton_probe.py --starfield-data "$sf\\Data" --race-mod "<the mod's folder>" ^
        --out C:\\Modding\\work\\skeleton_probe [--calumi <CALUMI.Animation.dll>] [--test-pack Orc --pack-out "$mods\\S2S Skeleton Test"]

Reads (fo4sf.racebones):
  * Starfield's human skeleton.nif (male, female) and, with --calumi, its .rig: which nodes the clips animate (rig
    bones of type Default), which the engine drives (Twist), and which no clip touches; a non-rig node between Root
    and an animated bone would be a ready-made helper (Skyrim's CME trick); leaves are the chargen bone modifiers.
  * the race mod: its plugin's RACE records (ANAM: the skeleton per sex) and those skeletons' CME values (scale /
    offset between a bone and its child), mapped onto Starfield bones (skeletonmap) with the offsets turned into the
    Starfield parent bone's frame, in metres.
Writes skeleton_probe.json and skeleton_probe.md (per race and sex: Starfield bone, scale, offset in cm). --test-pack
RACE: a loose-file mod overriding the human skeleton.nif (male and female) with that race's helper nodes inserted
above the bones they change (S2S_RB_<bone>), so EVERY human (player too) gets those proportions: if they show while
walking and fighting, Starfield keeps a non-rig parent's scale and per-race skeletons will work; if everyone looks
normal, it needs the SFSE route; if it breaks, disable the mod.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

from fo4sf import fo4land, racebones  # noqa: E402

SF_SKELETON = {"male": "meshes/actors/human/characterassets/skeleton.nif",
               "female": "meshes/actors/human/characterassets/female/skeleton.nif"}
SF_RIG = "meshes/actors/human/characterassets/skeleton.rig"
RACE_LABELS = {"HighElfRace": "Altmer", "WoodElfRace": "Bosmer", "DarkElfRace": "Dunmer", "OrcRace": "Orc",
               "NordRace": "Nord", "ImperialRace": "Imperial", "BretonRace": "Breton", "RedguardRace": "Redguard",
               "KhajiitRace": "Khajiit", "ArgonianRace": "Argonian"}


def read_starfield(path_or_rel: str, starfield_data: str) -> bytes:
    import hkx_to_af
    return hkx_to_af.vanilla_file(path_or_rel, starfield_data)[0]


def classify(nif_bytes: bytes, rig_names=None, rig_types=None) -> dict:
    """{"nodes", "rig_bones", "animated", "twist", "not_in_rig": {"between": [...], "leaves": [...]}} of a skeleton
    NIF: a non-rig node is 'between' when an animated rig bone lies below it (a ready-made helper), else a leaf."""
    parents = racebones.nif_parents(nif_bytes)
    names = sorted(set(parents) | set(parents.values()))
    out = {"nodes": len(names)}
    if rig_names is None:
        out["note"] = "no rig read (--calumi): animated bones unknown"
        return out
    kind = {n.lower(): t for n, t in zip(rig_names, rig_types)}
    animated = {n for n in names if kind.get(n.lower()) == "Default"}
    below = {}
    for child, par in parents.items():
        below.setdefault(par, []).append(child)

    def has_animated_below(n):
        stack = list(below.get(n, []))
        while stack:
            c = stack.pop()
            if c in animated:
                return True
            stack += below.get(c, [])
        return False
    not_rig = [n for n in names if n.lower() not in kind and n]
    between = [n for n in not_rig if has_animated_below(n)]
    out.update(rig_bones=len(rig_names), animated=len(animated), twist=sum(t == "Twist" for t in rig_types),
               not_in_rig={"between": between, "leaves": sorted(set(not_rig) - set(between))})
    return out


def race_skeletons(mod: str) -> dict:
    """{race EditorID: {"male": path, "female": path}} from the mod's plugins (RACE ANAM, male then female), the paths
    found in the mod folder (case-insensitive)."""
    files = {}
    for root, _d, fs in os.walk(mod):
        for fn in fs:
            full = os.path.join(root, fn)
            files[os.path.relpath(full, mod).replace("\\", "/").lower()] = full
    out = {}
    for rel, full in files.items():
        if not rel.endswith((".esp", ".esm", ".esl")):
            continue
        with fo4land.Plugin(full) as p:
            for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
                if item[0] != "GRUP" or item[3] != b"RACE":
                    continue
                for typ, off, _f, _fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                    if typ != b"RACE":
                        continue
                    subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
                    edid = next((fo4land.zstring(d) for s, d in subs if s == b"EDID"), "")
                    anam = [fo4land.zstring(d) for s, d in subs if s == b"ANAM"]
                    row = {}
                    for sex, a in zip(("male", "female"), anam):
                        key = "meshes/" + a.replace("\\", "/").lower()
                        if key in files:
                            row[sex] = files[key]
                    if row:
                        out[edid] = row
    return out


def race_table(skeletons: dict, sf: dict) -> dict:
    """{race: {sex: {"helpers", "notes", "file"}}} with sf = {sex: Starfield skeleton bytes}."""
    sf_rot = {s: racebones.world_rotations(b) for s, b in sf.items()}
    sf_par = {s: racebones.nif_parents(b) for s, b in sf.items()}
    out = {}
    for race, by_sex in sorted(skeletons.items()):
        for sex, path in by_sex.items():
            if sex not in sf:
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            rows = racebones.cme_values(data)
            helpers, notes = racebones.to_starfield(rows, racebones.world_rotations(data), sf_rot[sex], sf_par[sex])
            out.setdefault(race, {})[sex] = {"file": os.path.basename(path), "helpers": helpers, "notes": notes,
                                             "skyrim_rows": len(rows)}
    return out


def report_md(sf_info: dict, table: dict) -> str:
    lines = ["# Skeleton probe", ""]
    for sex, info in sf_info.items():
        lines.append(f"Starfield {sex} skeleton: {info['nodes']} nodes" + (
            f", rig {info['rig_bones']} bones ({info['animated']} animated, {info['twist']} twist); not in the rig: "
            f"{len(info['not_in_rig']['between'])} between animated bones "
            f"({', '.join(info['not_in_rig']['between']) or 'none'}), {len(info['not_in_rig']['leaves'])} leaves"
            if "rig_bones" in info else f" ({info.get('note')})"))
    lines += ["", "Per race (helpers above these Starfield bones: scale, offset cm in the parent bone's frame):", ""]
    seen = set()
    order = sorted(table, key=lambda r: (r not in RACE_LABELS, r))     # the playable races first, then variants
    for race in order:
        by_sex = table[race]
        label = RACE_LABELS.get(race, race)
        for sex, r in by_sex.items():
            key = (r["file"], sex)
            dup = key in seen
            seen.add(key)
            if dup:
                lines.append(f"- {label} {sex}: same skeleton as above ({r['file']})")
                continue
            cells = ", ".join(f"{h['bone']} x{h['scale']}" + (
                f" +({', '.join(f'{v * 100:.1f}' for v in h['offset_m'])})" if any(abs(v) > 1e-4 for v in h["offset_m"])
                else "") for h in r["helpers"])
            lines.append(f"- {label} {sex} ({r['file']}): {cells or 'no changes'}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield-data", default="")
    ap.add_argument("--skeleton", action="append", default=[], metavar="SEX=FILE",
                    help="Starfield skeleton.nif on disk instead of the archives (male=..., female=...)")
    ap.add_argument("--rig", default="", help="Starfield skeleton.rig on disk (default: from the archives)")
    ap.add_argument("--calumi", default="", help="CALUMI.Animation.dll: reads the rig (animated / twist bones)")
    ap.add_argument("--race-mod", required=True, help="the race-skeleton mod's folder (its plugin + meshes)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--test-pack", metavar="RACE", help="also write the skeleton override test for this race "
                                                        "(Orc, Altmer, ... or a RACE EditorID)")
    ap.add_argument("--pack-out", default="", help="the test mod's folder (default: <out>\\S2S Skeleton Test)")
    a = ap.parse_args(argv)
    for p in (a.out, a.pack_out):
        if p and os.path.abspath(p).lower().startswith(os.path.abspath(REPO).lower()):
            sys.exit("outputs must be outside the repository")
    given = dict(s.split("=", 1) for s in a.skeleton)
    sf = {}
    for sex, rel in SF_SKELETON.items():
        try:
            sf[sex] = read_starfield(given.get(sex, rel), a.starfield_data)
        except SystemExit as e:
            print(f"Starfield {sex} skeleton not read: {e}")
    if not sf:
        sys.exit("no Starfield skeleton (--starfield-data or --skeleton male=...)")
    rig_names = rig_types = None
    if a.calumi:
        from fo4sf import af_writer
        rig_path = a.rig
        if not rig_path:
            rig_path = os.path.join(a.out, "skeleton.rig")
            os.makedirs(a.out, exist_ok=True)
            with open(rig_path, "wb") as fh:
                fh.write(read_starfield(SF_RIG, a.starfield_data))
        rig = af_writer.load_rig(a.calumi, rig_path)
        rig_names, rig_types = rig["names"], rig["types"]
    sf_info = {sex: classify(b, rig_names, rig_types) for sex, b in sf.items()}
    skeletons = race_skeletons(a.race_mod)
    if not skeletons:
        sys.exit(f"no RACE with a skeleton found in {a.race_mod}")
    table = race_table(skeletons, sf)
    os.makedirs(a.out, exist_ok=True)
    rep = {"starfield": sf_info, "races": table}
    if a.test_pack:
        want = a.test_pack.lower()
        race = next((r for r in table if r.lower() == want or RACE_LABELS.get(r, "").lower() == want
                     or r.lower() == want + "race"), None)
        if race is None:
            sys.exit(f"--test-pack: no race {a.test_pack} in the mod ({', '.join(sorted(table))})")
        pack = a.pack_out or os.path.join(a.out, "S2S Skeleton Test")
        written = []
        for sex, r in table[race].items():
            dst = os.path.join(pack, *SF_SKELETON[sex].split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(racebones.insert_helpers(sf[sex], r["helpers"]))
            written.append(os.path.relpath(dst, pack))
        rep["test_pack"] = {"race": race, "folder": pack, "files": written}
    with open(os.path.join(a.out, "skeleton_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    md = report_md(sf_info, table)
    with open(os.path.join(a.out, "skeleton_probe.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(md)
    if a.test_pack:
        print(f"test pack ({rep['test_pack']['race']}): {rep['test_pack']['folder']}: "
              + ", ".join(rep["test_pack"]["files"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
