"""Hand props (animation objects) in both games, read-only: what converting Skyrim's broom for our Sweep set needs.

2026-11-15, owner, in game: Embry sweeps with our Skyrim sweeping clip, arms placed for a broom, but no broom in his
hands; owner: convert Skyrim's broom now. Skyrim's prop bone AnimObjectR maps to Starfield's R_AnimObject1 (skeletonmap),
which the converter leaves out of every clip (NOT_ANIMATED, verified on chair and sword clips only). This prints:
  * both games' ANIO records matching --match (EditorID, model, other fields),
  * each such model's root node name and string extra data (the attach bone, "Prn"),
  * the AnimObj* events (with payloads) of a Starfield template folder's descriptors,
  * which animation-object bones a Starfield clip keys (does vanilla sweeping animate the prop bone?).

    python -I scripts\\armor\\anim_object_probe.py --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield>"
        --match broom --folder standing_sweep --calumi "<CALUMI.Animation.dll>"
"""
import argparse
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import bsa, nif, sfplugin  # noqa: E402

ANIM = "meshes\\actors\\human\\animations\\furniture\\"


def anio_records(esm_path: str, match: str) -> list:
    """[(EditorID, {subrecord: text or hex})] of the plugin's ANIO records whose EditorID or model contains `match`."""
    out = []
    for _t, _h, subs, fid in sfplugin.records(esm_path, [b"ANIO"]):
        fields = {}
        for s, d in subs:
            d = bytes(d)
            txt = d.rstrip(b"\0")
            fields[s.decode("latin-1")] = (txt.decode("latin-1") if txt and all(32 <= c < 127 or c in (92, 47) for c in txt)
                                           else d.hex())
        e = fields.get("EDID", "")
        if match.lower() in (e + " " + fields.get("MODL", "")).lower():
            out.append((f"{fid:08X}", e, fields))
    return out


def nif_root_info(data: bytes) -> dict:
    """{"root": name of block 0 (if it has one), "extra": [(name, value)] of every NiStringExtraData}."""
    n = nif.parse(data)
    info = {"version_bs": n.bs_version, "blocks": len(n.blocks), "extra": []}
    if n.blocks and len(n.blocks[0]) >= 4:
        idx = struct.unpack_from("<I", n.blocks[0])[0]
        info["root"] = n.strings[idx].decode("latin-1") if idx < len(n.strings) else None
    for i, blk in enumerate(n.blocks):
        if n.type_of(i) == "NiStringExtraData" and len(blk) >= 8:
            a, b = struct.unpack_from("<2I", blk)
            name = n.strings[a].decode("latin-1") if a < len(n.strings) else None
            val = n.strings[b].decode("latin-1") if b < len(n.strings) else None
            info["extra"].append((name, val))
    info["types"] = sorted(set(n.block_types))
    return info


def anim_obj_events(afx_text: str) -> list:
    """[(event name, payload)] of the descriptor's AnimObj* events."""
    out = []
    for m in re.finditer(r"<event>(.*?)</event>", afx_text, re.S):
        nm = re.search(r"<name>\s*([^<]*?)\s*</name>", m.group(1))
        pl = re.search(r"<payload>\s*([^<]*?)\s*</payload>", m.group(1))
        if nm and nm.group(1).lower().startswith("animobj"):
            out.append((nm.group(1), pl.group(1) if pl else ""))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--match", default="broom")
    ap.add_argument("--folder", default="standing_sweep", help="a Starfield furniture template folder")
    ap.add_argument("--calumi", help="CALUMI.Animation.dll: also list the animation-object bones the folder's Idle keys")
    a = ap.parse_args(argv)
    import furniture_anim_survey as S
    sky = bsa.SkyrimArchives(a.skyrim_data, loose=False)
    sf_data = os.path.join(a.starfield, "Data")
    arcs = S.SfArchives(sf_data)
    for game, esm, read in (("Skyrim", os.path.join(a.skyrim_data, "Skyrim.esm"), lambda p: sky.mesh(p)),
                            ("Starfield", os.path.join(sf_data, "Starfield.esm"),
                             lambda p: arcs.read(S.norm(p if p.lower().startswith("meshes") else "meshes\\" + p)))):
        recs = anio_records(esm, a.match)
        print(f"== {game} ANIO matching '{a.match}': {len(recs)}")
        for fid, edid, fields in recs:
            print(f"  {fid} {edid}: " + ", ".join(f"{k}={v}" for k, v in fields.items() if k != "EDID"))
            model = fields.get("MODL")
            if model:
                data = read(model)
                if data is None:
                    print(f"    model {model}: not in the archives")
                    continue
                try:
                    print(f"    model {model}: {nif_root_info(data)}")
                except Exception as e:                              # noqa: BLE001
                    print(f"    model {model}: not read ({type(e).__name__}: {e})")
    folder = ANIM + a.folder.lower().replace("/", "\\").strip("\\") + "\\"
    print(f"== Starfield {folder} AnimObj events")
    for n in sorted(x for x in arcs.names if x.startswith(folder) and x.endswith(".afx")):
        ev = anim_obj_events((arcs.read(n) or b"").decode("utf-8", "replace"))
        if ev:
            print(f"  {n[len(folder):]}: {ev}")
    if a.calumi:
        import hkx_to_af
        from fo4sf import af_writer
        work = os.path.join(os.environ.get("TEMP", "/tmp"), "anim_object_probe")
        os.makedirs(work, exist_ok=True)
        name, data = hkx_to_af.starfield_find(sf_data, hkx_to_af.SF_RIG_RX, ("starfield - animations",))
        rig_path = os.path.join(work, "skeleton.rig")
        with open(rig_path, "wb") as fh:
            fh.write(data)
        for clip in ("idle.af", "enterfromstand.af"):
            raw = arcs.read(folder + clip)
            if raw is None:
                continue
            p = os.path.join(work, clip)
            with open(p, "wb") as fh:
                fh.write(raw)
            rb = af_writer.read_back(a.calumi, p, rig_path)
            keyed = [b for b in rb["bones"] if "animobject" in b.lower() or b.lower() in ("weapon", "root")]
            print(f"== Starfield {a.folder}\\{clip}: {len(rb['bones'])} bones keyed; prop bones keyed: {keyed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
