"""Which vanilla Starfield loose items have a body we can borrow to make converted items move (docs/interior/items.md
step 1; owner 2026-11-10: items you can pick up, drop, with physics / gravity). Read-only.

    python -I scripts\\interior\\item_physics_probe.py --sf-data "<Starfield>\\Data" --out C:\\Modding\\work\\items

Our converted props get a box body copied from a vanilla STATIC (historicaloilportraits_shackleton.nif: 6,168-byte
tagfile, hknpBoxShape); sfcollision.keyframed already turns that box into a door's keyframed body by copying the
words that differ (KEYFRAMED_FIELDS: filter / flags 232 / 264, motion type 240, body ids 448 / 456 / 472, mass
properties 1064-1095). The same with a DYNAMIC donor should give a box that falls and can be pushed.

For every MISC / ALCH / BOOK / AMMO / KEYM world model (MODL) in Starfield.esm this reads the NIF's physics
(bhkNPCollisionObject -> bhkPhysicsSystem tagfile): its size, the Havok shape classes named in it, and for the
6,168-byte box layout the KEYFRAMED_FIELDS words and the box size. The static template and the door donor are read
the same way, so each item's words can be compared with "static" and "keyframed". Writes item_physics_probe.json
and item_physics_probe.md (counts, the box-layout items grouped by those words, candidate donors).
"""
import argparse
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, nif as nifmod, sfcollision, sfplugin  # noqa: E402

ITEM_TYPES = (b"MISC", b"ALCH", b"BOOK", b"AMMO", b"KEYM")
STATIC_TEMPLATE = "meshes/setdressing/historicaloilportraits/historicaloilportraits_shackleton.nif"
DOOR_DONOR = "meshes/architecture/city/akila/animated/doors/ak_ext_bld_walla_doora_01/ak_ext_bld_walla_doora_01.nif"
SHAPES = (b"hknpBoxShape", b"hknpConvexPolytopeShape", b"hknpConvexShape", b"hknpSphereShape", b"hknpCapsuleShape",
          b"hknpCylinderShape", b"hknpCompressedMeshShape", b"hknpDynamicCompoundShape", b"hknpStaticCompoundShape",
          b"hknpCompoundShape", b"hknpScaledConvexShape")


class Archives:
    """Name -> archive index over the game's .ba2 files (lower-case, backslashes)."""

    def __init__(self, data):
        self.arcs, self.where = [], {}
        for fn in sorted(os.listdir(data)):
            if not fn.lower().endswith(".ba2") or "texture" in fn.lower():
                continue
            try:
                a = ba2.Ba2(os.path.join(data, fn))
            except Exception:                                  # noqa: BLE001 (sound / other archive kinds)
                continue
            self.arcs.append(a)
            for n in a.names:
                self.where.setdefault(n.replace("/", "\\").lower().lstrip("\\"), a)

    def read(self, path):
        key = path.replace("/", "\\").lower().lstrip("\\")
        a = self.where.get(key)
        if a is None:
            raise FileNotFoundError(path)
        return a.read(key)


def bodies(nif_bytes):
    """[(node name, blob)] of every bhkNPCollisionObject's physics system in a Starfield NIF."""
    n = nifmod.parse(nif_bytes)
    out = []
    for i in range(len(n.blocks)):
        if n.type_of(i) != "bhkNPCollisionObject":
            continue
        target, _flags, data = struct.unpack_from("<iHi", n.blocks[i], 0)
        name = b""
        if 0 <= target < len(n.blocks):
            k, = struct.unpack_from("<i", n.blocks[target], 0)
            name = n.strings[k] if 0 <= k < len(n.strings) else b""
        if 0 <= data < len(n.blocks):
            size, = struct.unpack_from("<I", n.blocks[data], 0)
            out.append((name.decode("latin-1"), bytes(n.blocks[data][4:4 + size])))
    return out


def words(blob):
    """The KEYFRAMED_FIELDS of a box-layout blob as hex, plus the mass words as floats."""
    w = {f"{off}": blob[off:off + n].hex() for off, n in sfcollision.KEYFRAMED_FIELDS}
    w["mass_floats"] = [round(x, 5) for x in struct.unpack_from("<4f", blob, 1064)]
    return w


def describe(blob):
    d = {"bytes": len(blob), "shapes": [s.decode() for s in SHAPES if s in blob]}
    if len(blob) == sfcollision.BLOB_SIZE and b"hknpBoxShape" in blob:
        c, h = sfcollision.read_box(blob)
        d["box"] = {"centre": [round(v, 4) for v in c], "half": [round(v, 4) for v in h]}
        d["words"] = words(blob)
    return d


def text_of(d):
    runs = re.findall(rb"[ -~]{3,}", bytes(d))
    return max(runs, key=len).decode("latin-1") if runs else ""


def probe(sf_data, limit=0, arcs=None):
    arcs = arcs or Archives(sf_data)
    rep = {"references": {}, "items": [], "counts": {}}
    for label, path in (("static_template", STATIC_TEMPLATE), ("keyframed_door", DOOR_DONOR)):
        try:
            rep["references"][label] = [dict(describe(b), node=nm) for nm, b in bodies(arcs.read(path))][:3]
        except FileNotFoundError:
            rep["references"][label] = "not found"
    recs = sfplugin.records(os.path.join(sf_data, "Starfield.esm"), ITEM_TYPES)
    by_type, shapes, sizes, seen = Counter(), Counter(), Counter(), {}
    for t, _h, subs, fid in recs:
        modl = next((text_of(d) for s, d in subs if s == b"MODL"), "")
        if not modl:
            continue
        by_type[t.decode()] += 1
        if limit and len(rep["items"]) >= limit:
            continue
        key = modl.lower()
        if key not in seen:
            try:
                seen[key] = [dict(describe(b), node=nm) for nm, b in bodies(arcs.read("meshes\\" + modl))]
            except (FileNotFoundError, nifmod.NifError, struct.error, ValueError) as e:
                seen[key] = {"error": str(e)[:120]}
        phys = seen[key]
        row = {"type": t.decode(), "edid": sfplugin.edid(subs), "form_id": f"{fid:08X}", "model": modl,
               "bodies": phys}
        rep["items"].append(row)
        if isinstance(phys, list):
            for b in phys:
                for s in b["shapes"]:
                    shapes[s] += 1
                sizes[b["bytes"]] += 1
            if not phys:
                shapes["(no collision)"] += 1
    rep["counts"] = {"items_by_type": dict(by_type), "shape_classes": dict(shapes.most_common()),
                     "blob_sizes_top": dict(sizes.most_common(15)), "models_read": len(seen)}
    groups = defaultdict(list)
    for r in rep["items"]:
        if not isinstance(r["bodies"], list):
            continue
        for b in r["bodies"]:
            if "words" in b:
                groups[(b["words"]["240"], b["words"]["232"], b["words"]["264"])].append(
                    {"edid": r["edid"], "type": r["type"], "model": r["model"], "box": b["box"],
                     "mass": b["words"]["mass_floats"]})
    ref = rep["references"]
    st = ref.get("static_template")
    kf = ref.get("keyframed_door")
    st_w = st[0]["words"]["240"] if isinstance(st, list) and st and "words" in st[0] else None
    kf_w = kf[0]["words"]["240"] if isinstance(kf, list) and kf and "words" in kf[0] else None
    rep["box_layout_groups"] = [
        {"motion_240": k[0], "filter_232": k[1], "flags_264": k[2], "count": len(v),
         "like": "static template" if k[0] == st_w else "keyframed door" if k[0] == kf_w else "other (dynamic?)",
         "examples": v[:8]} for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
    return rep


def markdown(rep):
    L = ["# Item physics probe", "", f"Counts: {json.dumps(rep['counts'])}", "", "## References", ""]
    for k, v in rep["references"].items():
        L.append(f"- {k}: {json.dumps(v)[:600]}")
    L += ["", "## Box-layout item bodies by motion word (offset 240)", ""]
    for g in rep["box_layout_groups"]:
        L.append(f"- motion {g['motion_240']} filter {g['filter_232']} flags {g['flags_264']}: {g['count']} "
                 f"bodies, {g['like']}")
        for e in g["examples"]:
            L.append(f"  - {e['type']} {e['edid']}: {e['model']} box half {e['box']['half']} mass {e['mass']}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="at most this many items read (0: all)")
    a = ap.parse_args(argv)
    rep = probe(a.sf_data, a.limit)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "item_physics_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    with open(os.path.join(a.out, "item_physics_probe.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(rep))
    print(f"{sum(rep['counts']['items_by_type'].values())} items, {rep['counts']['models_read']} models; shapes "
          f"{rep['counts']['shape_classes']}; box-layout groups {[(g['motion_240'], g['count'], g['like']) for g in rep['box_layout_groups']]}")
    print(f"-> {os.path.join(a.out, 'item_physics_probe.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
