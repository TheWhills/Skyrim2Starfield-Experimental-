"""Skyrim NPCs' own hair and beards on their converted Starfield test NPCs (face_fit.py --hair): each NPC's Skyrim
hair / facial-hair head part (with its extra parts, e.g. the hairline) converted rigidly onto Starfield's head
(fo4sf.skyrimhair, no physics: vanilla Skyrim hair has none), its hair colour baked into the texture, written as a new
Starfield head part copied from the test NPC's own one of that kind and put in its place on the NPC.

Why now (owner 2026-10-27): for the first NPC conversions the Skyrim hairstyle is what tells NPCs apart and shows how
the appearance carries over; matching Starfield hairstyles comes later.
Unverified until the first run: that Starfield's head-part type numbers for hair / facial hair are Skyrim's (3 / 4;
OC Hairs' hair head parts carry 3), and how bright Skyrim's hair tint is (multiply, --hair-tint-gain).
"""
import os
import re
import struct
from typing import Dict, List, Optional, Tuple

import numpy as np

from fo4sf import nif as nifmod
from fo4sf import sfplugin, skyrimhair, skyrimnif, skyrimnpc

HAIR, FACIAL_HAIR = 3, 4
KINDS = {HAIR: "hair", FACIAL_HAIR: "facial hair"}
SF_SKELETON = "meshes/actors/human/characterassets/skeleton.nif"


def skeleton_world(nif_bytes: bytes) -> Dict[str, np.ndarray]:
    """Rest world transforms (metres) by bone name of a Starfield skeleton NIF."""
    nodes, _parent = skyrimhair.node_worlds(nifmod.parse(nif_bytes))
    return nodes


def head_parts(esm: str) -> Tuple[Dict[int, Dict], Dict[int, Dict]]:
    """({HDPT FormID: parsed}, {CLFM FormID: parsed}) of a Skyrim plugin."""
    recs = sfplugin.records(esm, [b"HDPT", b"CLFM"])
    hdpt = {fid: skyrimnpc.parse_head_part(s, fid) for t, _h, s, fid in recs if t == b"HDPT"}
    clfm = {fid: skyrimnpc.parse_color(s, fid) for t, _h, s, fid in recs if t == b"CLFM"}
    return hdpt, clfm


def part_models(fid: int, hdpt: Dict[int, Dict], seen=None) -> List[str]:
    """Models of a head part and its extra parts (HNAM, followed), Data-relative under meshes\\."""
    seen = set() if seen is None else seen
    if fid in seen or fid not in hdpt:
        return []
    seen.add(fid)
    p = hdpt[fid]
    out = [p["model"]] if p.get("model") else []
    for x in p["extra_parts"]:
        out += part_models(x, hdpt, seen)
    return out


def npc_parts(npc: Dict, hdpt: Dict[int, Dict]) -> Dict[int, Tuple[Dict, List[str]]]:
    """{kind: (Skyrim head part, models)} for the NPC's hair and facial hair."""
    out = {}
    for fid in npc["head_parts"]:
        p = hdpt.get(fid)
        if p and p["type"] in KINDS and p["type"] not in out:
            out[p["type"]] = (p, part_models(fid, hdpt))
    return out


def tint(npc: Dict, clfm: Dict[int, Dict], gain: float = 1.0) -> Optional[Tuple[float, float, float]]:
    c = clfm.get(npc.get("hair_color"))
    if not c or not c.get("rgba"):
        return None
    return tuple(min(1.0, v / 255.0 * gain) for v in c["rgba"][:3])


def convert_part(models: List[str], src, conv, sf_world, out_name: str, albedo_tint=None) -> Tuple[Dict, Dict]:
    """(files {Data-relative path: bytes}, report) of one head part's models merged into one rigid Starfield NIF."""
    hairs, mats, backs, report = [], [], [], {"models": models, "skipped": []}
    for m in models:
        rel = "meshes\\" + re.sub(r"^meshes[\\/]", "", m.replace("/", "\\"), flags=re.I)
        raw = src.mesh(rel)
        if raw is None:
            report["skipped"].append(f"{m}: not in the archives")
            continue
        n = nifmod.parse(raw)
        try:
            h = skyrimhair.convert(raw, None, sf_world)
        except skyrimhair.HairError as e:
            report["skipped"].append(f"{m}: {e}")
            continue
        hairs.append(h)
        for sh in h.shapes:
            mats.append(conv._shape_material(n, sh, albedo_tint=albedo_tint))
            backs.append(bool(sh.shader_ref >= 0 and skyrimnif.double_sided(n, sh.shader_ref)))
    if not hairs:
        raise skyrimhair.HairError("no model converted: " + "; ".join(report["skipped"]))
    hair = skyrimhair.merge(hairs)
    files = skyrimhair.nif_files(hair, mats, None, sf_world, out_name, backs)
    report.update(shapes=sum(len(h.shapes) for h in hairs), materials=mats,
                  bones=sorted({b for sh in hair.shapes for vw in sh.weights for b, _w in vw}))
    return files, report


def starfield_part_template(npc_subs, sf_hdpt: Dict[int, tuple], kind: int, female: bool):
    """A Starfield head part record of `kind` to copy: the test NPC's own, else any of that kind for the sex."""
    for s, d in npc_subs:
        if s == b"PNAM" and len(d) >= 4:
            r = sf_hdpt.get(struct.unpack_from("<I", bytes(d), 0)[0])
            if r is not None and part_type(r[2]) == kind:
                return r
    want = 0x4 if female else 0x2
    hits = [r for r in sf_hdpt.values() if part_type(r[2]) == kind]
    hits.sort(key=lambda r: (not (part_flags(r[2]) & want), sfplugin.edid(r[2])))
    return hits[0] if hits else None


def part_type(subs) -> Optional[int]:
    d = next((bytes(d) for s, d in subs if s == b"PNAM" and len(d) >= 4), None)
    return struct.unpack_from("<I", d, 0)[0] if d else None


def part_flags(subs) -> int:
    d = next((bytes(d) for s, d in subs if s == b"DATA" and len(d) >= 1), b"\0")
    return d[0]


def head_part_record(template, fid: int, edid: str, model: str):
    """A copy of a Starfield HDPT with its own EditorID and model, without extra parts (they are merged into the
    model)."""
    t, h, subs, _f = template
    return (t, h, sfplugin.edit(subs, {b"EDID": sfplugin.zs(edid), b"MODL": sfplugin.zs(model)},
                                drop=(b"HNAM",)), fid)


def with_head_parts(subs, sf_hdpt: Dict[int, tuple], new: Dict[int, int]):
    """NPC subrecords with its head parts of each kind in `new` ({kind: FormID}) replaced by the new one (added when it
    had none of that kind)."""
    out, placed, at = [], set(), None
    for s, d in subs:
        if s == b"PNAM" and len(d) >= 4:
            at = len(out) + 1
            r = sf_hdpt.get(struct.unpack_from("<I", bytes(d), 0)[0])
            k = part_type(r[2]) if r is not None else None
            if k in new:
                if k not in placed:
                    out.append((s, struct.pack("<I", new[k])))
                    placed.add(k)
                continue
        out.append((s, d))
    rest = [(b"PNAM", struct.pack("<I", new[k])) for k in new if k not in placed]
    if rest:
        at = at if at is not None else next((i + 1 for i, (s, _d) in enumerate(out) if s == b"RNAM"), len(out))
        out[at:at] = rest
    return out


def add_hair(rows, npcs, chosen, recs, test_subs, args, sky, conv, sf_world, sf_hdpt, hdpt, clfm, staging,
             esm_name="Skyrim.esm"):
    """For every test NPC row (face_fit.py): convert its Skyrim hair / facial hair, add the head part records and
    swap them into the test NPC (test_subs: {row edid: index into recs}). Fills row["hair"]."""
    faces = skyrimnpc.faces_by_template(npcs)
    done: Dict[Tuple, int] = {}
    by_edid = {n["edid"]: n for n in chosen}
    for row in rows:
        k = test_subs.get(row["edid"])
        if k is None:
            continue
        n = by_edid[row["edid"]]
        src_npc = npcs.get(faces.get(n["form_id"], n["form_id"]), n)        # who its face (and hair) comes from
        parts = npc_parts(src_npc, hdpt)
        rinfo, new = {}, {}
        col = tint(src_npc, clfm, args.hair_tint_gain)
        for kind, (part, models) in sorted(parts.items()):
            key = (tuple(models), col if kind == HAIR else None)
            name = KINDS[kind]
            try:
                if key not in done:
                    tpl = starfield_part_template(recs[k][2], sf_hdpt, kind, n["female"])
                    if tpl is None:
                        raise skyrimhair.HairError(f"no Starfield {name} head part to copy")
                    tag = f"_{''.join(f'{int(v * 255):02X}' for v in col)}" if key[1] else ""
                    out = f"s2s/npc/{name.replace(' ', '')}/{part['edid'].lower()}{tag.lower()}"
                    files, rep = convert_part(models, sky, conv, sf_world, out, key[1])
                    for rel, data in files.items():
                        p = os.path.join(staging, *rel.split("/"))
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        with open(p, "wb") as fh:
                            fh.write(data)
                    fid = sfplugin.new_form_id(len(recs))
                    recs.append(head_part_record(tpl, fid, f"S2S_{part['edid']}{tag}",
                                                 out.replace("/", "\\") + ".nif"))
                    done[key] = fid
                    rep["starfield_template"] = sfplugin.edid(tpl[2])
                    rinfo[name] = {"skyrim": part["edid"], **rep, "form_id": f"{fid:08X}"}
                else:
                    rinfo[name] = {"skyrim": part["edid"], "shared_with_an_earlier_npc": True}
                new[kind] = done[key]
            except (skyrimhair.HairError, nifmod.NifError, ValueError) as e:
                rinfo[name] = {"skyrim": part["edid"], "error": str(e)}
        if not parts:
            rinfo["note"] = "no hair head part on the NPC (the race default is not converted)"
        if new:
            t, h, subs, fid = recs[k]
            recs[k] = (t, h, with_head_parts(subs, sf_hdpt, new), fid)
        rinfo["hair_tint"] = col
        row["hair"] = rinfo
