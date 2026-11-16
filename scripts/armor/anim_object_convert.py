"""A Skyrim model as a Starfield animation object (a hand-held prop), for our furniture sets.

2026-11-15, owner: Embry sweeps with our Skyrim sweeping clip but holds no broom; owner: convert Skyrim's broom.
Skyrim's sweep clips hold the prop bone AnimObjectR (under NPC R Hand) at a fixed offset; Skyrim's only broom mesh is
meshes\\clutter\\common\\broom.nif (anim_object_probe.py, owner's run). Starfield attaches an animation object's model to
the bone its root's "Prn" string extra data names (vanilla AnimObjectBroom: Prn AnimObjectA). So: the Skyrim mesh is
converted as usual (skyrimconvert, materials, textures, .mesh files), then its root is renamed, gets Prn = the hand bone
our clips key (hkx_to_af --prop AnimObjectR=R_AnimObject1) and loses any collision (a held prop must not push its
holder). The ANIO record naming this model is S2SStances.esm's (stance_plugin.PROP_OBJECTS).

    python -I scripts\\armor\\anim_object_convert.py --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield>"
        --texconv "<texconv.exe>" --out "<mods>\\S2S Furniture Anims"
"""
import argparse
import os
import shutil
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import nif as nifmod  # noqa: E402

NODE_TRANSFORM = 13 * 4          # NiNode (Starfield): translation 3f, rotation 9f, scale f

# Skyrim model per S2S animation object (stance_plugin.PROP_OBJECTS) and the Starfield bone it hangs on when the Skyrim
# model names none of its own. 2026-11-16, the Forge set: Skyrim's own animation-object models (ANIO
# BlackSmith...AnimObject / AnimObjectBlacksmithForge*: smithing_probe), whose root's Prn names the Skyrim prop bone
# (supported: Skyrim animation objects attach like Starfield's); the forge clips key AnimObjectR (hammer) and
# AnimObjectL (iron) (anim_object_probe, verified).
PROP_SOURCES = {"S2S_AnimObjectBroomSkyrim": ("meshes\\clutter\\common\\broom.nif", "R_AnimObject1"),
                "S2S_AnimObjectForgeHammerSkyrim": ("meshes\\animobjects\\animobjectblacksmithforgehammer.nif",
                                                    "R_AnimObject1"),
                "S2S_AnimObjectForgeIronSkyrim": ("meshes\\animobjects\\animobjectblacksmithforgeiron.nif",
                                                  "L_AnimObject1")}
SKY_PRN_TO_SF = {"animobjectr": "R_AnimObject1", "animobjectl": "L_AnimObject1", "animobjecta": "AnimObjectA",
                 "animobjectb": "AnimObjectB"}


def skyrim_prn(data: bytes):
    """The "Prn" string extra data on a Skyrim NIF's root node (the bone an animation object attaches to), or None."""
    n = nifmod.parse(data)
    if not n.blocks:
        return None
    _name, count = struct.unpack_from("<iI", n.blocks[0], 0)
    for r in struct.unpack_from(f"<{count}i", n.blocks[0], 8):
        if 0 <= r < len(n.blocks) and n.type_of(r) == "NiStringExtraData" and len(n.blocks[r]) >= 8:
            k, v = struct.unpack_from("<ii", n.blocks[r], 0)
            name = n.strings[k] if 0 <= k < len(n.strings) else b""
            if isinstance(name, bytes) and name.lower() == b"prn" and 0 <= v < len(n.strings):
                val = n.strings[v]
                return val.decode("latin-1") if isinstance(val, bytes) else str(val)
    return None


def bone_for(prn, default: str) -> str:
    """The Starfield bone for a Skyrim Prn (SKY_PRN_TO_SF), else `default`."""
    return SKY_PRN_TO_SF.get((prn or "").lower(), default)


def make_anim_object(data: bytes, root_name: str, bone: str) -> bytes:
    """The NIF with its root NiNode renamed `root_name`, a NiStringExtraData "Prn" = `bone` added to the root, the
    root's collision dropped (reference -1) and BSXFlags set to 0 (no collision)."""
    n = nifmod.parse(data)
    if not n.blocks or n.type_of(0) not in ("NiNode", "BSFadeNode"):
        raise ValueError(f"block 0 is {n.type_of(0) if n.blocks else 'missing'}, not a node")
    root = n.blocks[0]
    _name, count = struct.unpack_from("<iI", root, 0)
    refs = list(struct.unpack_from(f"<{count}i", root, 8))
    rest = root[8 + 4 * count:]
    ctrl_flags, transform = rest[:8], rest[8:8 + NODE_TRANSFORM]
    after = rest[8 + NODE_TRANSFORM + 4:]                       # past the collision reference
    prn = n.add_block("NiStringExtraData", struct.pack("<II", n.string_index(b"Prn"), n.string_index(bone.encode())))
    refs = [r for r in refs if not (0 <= r < len(n.blocks) and n.type_of(r) == "NiStringExtraData"
                                    and struct.unpack_from("<I", n.blocks[r])[0] == n.string_index(b"Prn")
                                    and r != prn)] + [prn]
    n.blocks[0] = (struct.pack("<iI", n.string_index(root_name.encode()), len(refs))
                   + struct.pack(f"<{len(refs)}i", *refs) + ctrl_flags + transform + struct.pack("<i", -1) + after)
    for i in range(len(n.blocks)):
        if n.type_of(i) == "BSXFlags" and len(n.blocks[i]) >= 8:
            n.blocks[i] = n.blocks[i][:4] + struct.pack("<I", 0) + n.blocks[i][8:]
    return nifmod.serialize(n)


def main(argv=None):
    import stance_plugin
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="the Starfield folder (Tools\\ContentResources.zip)")
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True, help="a mod folder (the model, its .mesh files, materials, textures go in)")
    ap.add_argument("--nif", help="one Skyrim model (with --model / --name / --bone); default: every PROP_SOURCES entry")
    ap.add_argument("--model", help="the output model under meshes\\ (= the ANIO's MODL)")
    ap.add_argument("--name", help="the root node's name")
    ap.add_argument("--bone", help="the bone it attaches to (Prn)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    from fo4sf import bsa
    sky = bsa.SkyrimArchives(a.skyrim_data)
    cr = os.path.join(a.starfield, "Tools", "ContentResources.zip")
    if a.nif:
        edid, _v, model = stance_plugin.PROP_OBJECTS[0]
        jobs = [(a.nif, a.model or model, a.name or edid, a.bone)]
    else:
        jobs = [(PROP_SOURCES[e][0], m, e, None) for e, _v, m in stance_plugin.PROP_OBJECTS if e in PROP_SOURCES]
    for nif_path, model, name, bone in jobs:
        convert_one(sky, cr, a.texconv, out, nif_path, model, name, bone)
    return 0


def convert_one(sky, cr, texconv, out, nif_path, model, name, bone=None):
    """One Skyrim model as an animation object (make_anim_object) into `out`; bone None: the Skyrim model's Prn mapped
    (bone_for), else PROP_SOURCES' default."""
    from fo4sf import skyrimconvert
    raw = sky.mesh(nif_path)
    if raw is None:
        print(f"{nif_path}: not in the Skyrim archives; skipped")
        return False
    prn = skyrim_prn(raw)
    default = next((b for e, (p, b) in PROP_SOURCES.items() if p.lower() == nif_path.lower()), "R_AnimObject1")
    bone = bone or bone_for(prn, default)
    print(f"{nif_path}: Skyrim Prn {prn!r} -> {bone}")
    staging = tempfile.mkdtemp(prefix="anim_object_")
    try:
        conv = skyrimconvert.SkyrimConverter(sky, staging, texconv, cr, collision_template=None, prefix="s2s")
        res = conv.convert_nif(nif_path)
        if not res.get("ok"):
            print(f"{nif_path}: not converted ({res.get('reason')}); skipped")
            return False
        nifs = [os.path.join(d, f) for d, _ds, fs in os.walk(staging) for f in fs if f.lower().endswith(".nif")]
        if len(nifs) != 1:
            print(f"{nif_path}: expected one converted model, found {len(nifs)}; skipped")
            return False
        with open(nifs[0], "rb") as fh:
            data = make_anim_object(fh.read(), name, bone)
        dst = os.path.join(out, "meshes", *model.replace("/", "\\").split("\\"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        copied = 0
        for d, _ds, fs in os.walk(staging):
            for f in fs:
                src = os.path.join(d, f)
                if src == nifs[0]:
                    continue
                rel = os.path.relpath(src, staging)
                target = os.path.join(out, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(src, target)
                copied += 1
        print(f"{nif_path} -> meshes\\{model} (root {name}, Prn {bone}, no collision; {res.get('shapes')} shapes, "
              f"materials {res.get('materials')}); {copied} mesh / material / texture files into {out}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return True


if __name__ == "__main__":
    sys.exit(main())
