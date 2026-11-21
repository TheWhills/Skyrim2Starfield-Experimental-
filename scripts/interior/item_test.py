"""One Skyrim item as a real Starfield item, end to end (docs/interior/items.md "wine bottle test", 2026-11-20).

Owner, 2026-11-20: "lets get the wine bottle test going". The steps of items.md, smallest form, before any builder
places items: a Skyrim ALCH (default: the first whose EditorID has "wine" and whose model is a bottle) becomes
  - its world model converted as the statics are (SkyrimConverter, Skyrim's textures), with NO collision of ours, and
    the physics body of a vanilla Starfield drink put on it instead (--donor: an ALCH whose EditorID / model reads as
    a bottle, wine first): the vanilla body is dynamic (owner's item_body_dump, verified: motionType 2, mass, mass
    distribution, motion properties), so the bottle falls, tips and can be picked up. The donor's shape is ITS
    bottle's hull, not ours (a writer of our own dynamic hull is the next step);
  - an ALCH copied from the donor (its effects, sounds, keywords, value / weight), with the Skyrim name and our model.
Writes S2SItemTest.esm (+ its archives) into --out. In game (enable "S2S Item Test" in MO2):
`player.placeatme <id>` drops one in front of you: does it fall and settle, can you knock it over, pick it up (its
name in the inventory), drop it, drink it?

    python -I scripts\\interior\\item_test.py --skyrim-data "<Skyrim>\\Data" --starfield "<Starfield>" ^
        --out "<MO2 mods>\\S2S Item Test" [--item <Skyrim ALCH EditorID>] [--donor <Starfield ALCH EditorID>]
"""
import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))
sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))

from fo4sf import nif as nifmod, sfplugin  # noqa: E402

PLUGIN = "S2SItemTest.esm"
ITEM_RX = r"wine"
DONOR_RX = (r"wine", r"whisk|liquor|spirit|bottle")       # tried in turn, on EditorID and model


def skyrim_items(recs, rx=ITEM_RX):
    """[(EditorID, FormID, model, name string id or text)] of Skyrim ALCH records whose EditorID matches rx and that
    have a model, bottles first."""
    out = []
    for t, _h, subs, fid in recs:
        if t != b"ALCH":
            continue
        e = sfplugin.edid(subs)
        d = dict(subs)
        model = d.get(b"MODL", b"").split(b"\0")[0].decode("latin-1")
        if not model or not re.search(rx, e, re.I):
            continue
        full = d.get(b"FULL", b"")
        name = struct.unpack("<I", full)[0] if len(full) == 4 else full.split(b"\0")[0].decode("latin-1")
        out.append((e, fid, model, name))
    return sorted(out, key=lambda r: ("bottle" not in r[2].lower(), r[0].lower()))


def donor_candidates(recs, patterns=DONOR_RX):
    """[(EditorID, FormID, model)] of Starfield ALCH records matching the patterns in turn (EditorID or model)."""
    out = []
    for rx in patterns:
        for t, _h, subs, fid in recs:
            if t != b"ALCH":
                continue
            e = sfplugin.edid(subs)
            model = next((bytes(d).split(b"\0")[0].decode("latin-1") for s, d in subs if s == b"MODL"), "")
            if model and (re.search(rx, e, re.I) or re.search(rx, model, re.I)) and \
                    all(e != o[0] for o in out):
                out.append((e, fid, model))
    return out


def donor_physics(nif_bytes):
    """(physics blob, collision object flags u16, collision object last u32, BSXFlags value) of a Starfield NIF's
    first bhkNPCollisionObject; None when it has none."""
    n = nifmod.parse(nif_bytes)
    bsx = next((struct.unpack_from("<I", n.blocks[i], 4)[0] for i in range(len(n.blocks))
                if n.type_of(i) == "BSXFlags"), None)
    for i in range(len(n.blocks)):
        if n.type_of(i) != "bhkNPCollisionObject":
            continue
        b = n.blocks[i]
        _target, flags, data = struct.unpack_from("<iHi", b, 0)
        tail = struct.unpack_from("<I", b, 10)[0] if len(b) >= 14 else 0
        size, = struct.unpack_from("<I", n.blocks[data], 0)
        return bytes(n.blocks[data][4:4 + size]), flags, tail, bsx
    return None


def with_physics(nif_bytes, blob, flags=0x80, tail=0, bsx=None) -> bytes:
    """Our model (build_static_nif layout, no collision) with a physics body on its root: a bhkNPCollisionObject
    (target the root, the donor's flags) and its bhkPhysicsSystem appended, the root's collision ref set, BSXFlags
    set to the donor's (Starfield draws and simulates the body by them). Any collision object already there is
    replaced (its blocks left unreferenced)."""
    n = nifmod.parse(nif_bytes)
    if n.type_of(0) != "NiNode":
        raise nifmod.NifError("root is not a NiNode")
    obj = n.add_block("bhkNPCollisionObject", struct.pack("<iHiI", 0, flags, len(n.blocks) + 1, tail))
    n.add_block("bhkPhysicsSystem", struct.pack("<I", len(blob)) + blob)
    root = n.blocks[0]
    _name, n_extra = struct.unpack_from("<iI", root, 0)
    p = 8 + 4 * n_extra + 8 + 52                      # controller, flags, transform (52), then the collision ref
    n.blocks[0] = root[:p] + struct.pack("<i", obj) + root[p + 4:]
    if bsx is not None:
        for i in range(len(n.blocks)):
            if n.type_of(i) == "BSXFlags":
                n.blocks[i] = n.blocks[i][:4] + struct.pack("<I", bsx) + n.blocks[i][8:]
    return nifmod.serialize(n)


def item_record(donor, edid: str, name: str, model: str, fid: int):
    """The donor ALCH (type, header, subs, FormID) as ours: EditorID, name, model path (under meshes\\)."""
    edits = {b"EDID": sfplugin.zs(edid), b"FULL": sfplugin.zs(name), b"MODL": sfplugin.zs(model)}
    if any(s == b"DESC" for s, _d in donor[2]):
        # 2026-11-20 (owner, in game: the item card showed "Oõ▮" under the name): the donor's DESC is a string id
        # into Starfield.esm's string tables, read as text in our (not localized) plugin; ours has none
        edits[b"DESC"] = sfplugin.zs("")
    return (b"ALCH", donor[1], sfplugin.edit(list(donor[2]), edits), fid)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--item", default="", help="Skyrim ALCH EditorID (default: the first wine, bottles first)")
    ap.add_argument("--donor", default="", help="Starfield ALCH EditorID whose body / record is copied")
    ap.add_argument("--texconv", default="")
    ap.add_argument("--content-resources", default="")
    ap.add_argument("--archive2", default="")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    from fo4sf import bsa, skyrimconvert
    import gear_fit
    import hair_pack
    import item_physics_probe as P
    import npc_records
    sf_data = os.path.join(a.starfield, "Data")
    sf_esm = os.path.join(sf_data, "Starfield.esm")
    sky = bsa.SkyrimArchives(a.skyrim_data)
    rep = {}
    items = skyrim_items(sfplugin.records(os.path.join(a.skyrim_data, "Skyrim.esm"), [b"ALCH"]),
                         re.escape(a.item) if a.item else ITEM_RX)
    if a.item:
        items = [r for r in items if r[0].lower() == a.item.lower()]
    rep["skyrim_candidates"] = [{"edid": e, "model": m} for e, _f, m, _n in items[:20]]
    if not items:
        sys.exit(f"no Skyrim ALCH {a.item or 'with wine'} with a model")
    s_edid, s_fid, s_model, s_name = items[0]
    if isinstance(s_name, int):
        s_name = npc_records.skyrim_names(sky).get(s_name, s_edid)
    print(f"Skyrim item: {s_edid} {s_fid:08X} \"{s_name}\" - {s_model}")
    sf_recs = sfplugin.records(sf_esm, [b"ALCH"])
    arcs = P.Archives(sf_data)
    cands = donor_candidates(sf_recs, (re.escape(a.donor),) if a.donor else DONOR_RX)
    if a.donor:
        cands = [c for c in cands if c[0].lower() == a.donor.lower()]
    donor, phys, tried = None, None, []
    for e, fid, model in cands:
        try:
            got = donor_physics(arcs.read("meshes\\" + model))
        except Exception as ex:                          # noqa: BLE001
            tried.append(f"{e}: {type(ex).__name__}")
            continue
        if got is None:
            tried.append(f"{e}: no collision")
            continue
        donor = next(r for r in sf_recs if r[3] == fid)
        phys = got
        break
    rep["donor_candidates"] = [{"edid": e, "model": m} for e, _f, m in cands[:30]]
    rep["donors_skipped"] = tried
    if donor is None:
        sys.exit(f"no Starfield donor with a physics body (candidates {len(cands)}; --donor <ALCH EditorID>)")
    d_model = next(bytes(d).split(b"\0")[0].decode("latin-1") for s, d in donor[2] if s == b"MODL")
    blob, flags, tail, bsx = phys
    print(f"donor: {sfplugin.edid(donor[2])} {donor[3]:08X} - {d_model}: body {len(blob)} bytes, "
          f"collision flags {flags:#x}, BSXFlags {bsx}")
    staging = os.path.join(a.out, "_staging")
    texconv = gear_fit.find_texconv(a.texconv)
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    conv = skyrimconvert.SkyrimConverter(sky, staging, texconv, cr, collision_template=None, prefix="s2s")
    res = conv.convert_nif("meshes\\" + s_model if not s_model.lower().startswith("meshes") else s_model)
    if not res.get("ok"):
        sys.exit(f"model not converted: {res.get('reason')}")
    rel = f"meshes/{res['out_name']}.nif"
    path = os.path.join(staging, *rel.split("/"))
    with open(path, "rb") as fh:
        ours = fh.read()
    with open(path, "wb") as fh:
        fh.write(with_physics(ours, blob, flags, tail, bsx))
    model = res["out_name"].replace("/", "\\") + ".nif"
    print(f"model: {model} ({res['shapes']} shapes, materials {res['materials']})")
    fid = sfplugin.new_form_id(0, masters=1)
    rec = item_record(donor, f"S2S_{s_edid}", s_name, model, fid)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build([rec], sfplugin.header_info(sf_esm), author="Skyrim2Starfield item test"))
    base = os.path.splitext(PLUGIN)[0]
    packed = hair_pack.pack(staging, a.out, a.starfield, a.archive2 or None, f"{base} - Main.ba2",
                            f"{base} - Textures.ba2")
    rep.update(item={"edid": s_edid, "name": s_name, "model": s_model}, donor={"edid": sfplugin.edid(donor[2]),
               "model": d_model, "body_bytes": len(blob), "flags": flags, "bsx": bsx},
               model=model, record=f"{fid:08X}", packed=packed, convert=res)
    with open(os.path.join(a.out, "item_test.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, default=str)
    print(f"{PLUGIN}: ALCH S2S_{s_edid} -> enable 'S2S Item Test' in MO2, then in game: "
          f"player.placeatme xx{fid & 0xFFFFFF:06X}  (xx = {PLUGIN}'s load order index; help S2S_{s_edid} 4)")
    print("textures:", packed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
