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
    edid, _vanilla, model = stance_plugin.PROP_OBJECTS[0]
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="the Starfield folder (Tools\\ContentResources.zip)")
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True, help="a mod folder (the model, its .mesh files, materials, textures go in)")
    ap.add_argument("--nif", default="meshes\\clutter\\common\\broom.nif", help="the Skyrim model")
    ap.add_argument("--model", default=model, help="the output model under meshes\\ (= the ANIO's MODL)")
    ap.add_argument("--name", default=edid, help="the root node's name")
    ap.add_argument("--bone", default="R_AnimObject1", help="the bone it attaches to (Prn)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    from fo4sf import bsa, skyrimconvert
    sky = bsa.SkyrimArchives(a.skyrim_data)
    cr = os.path.join(a.starfield, "Tools", "ContentResources.zip")
    staging = tempfile.mkdtemp(prefix="anim_object_")
    try:
        conv = skyrimconvert.SkyrimConverter(sky, staging, a.texconv, cr, collision_template=None, prefix="s2s")
        res = conv.convert_nif(a.nif)
        if not res.get("ok"):
            sys.exit(f"{a.nif}: not converted ({res.get('reason')})")
        nifs = [os.path.join(d, f) for d, _ds, fs in os.walk(staging) for f in fs if f.lower().endswith(".nif")]
        if len(nifs) != 1:
            sys.exit(f"expected one converted model, found {len(nifs)}")
        with open(nifs[0], "rb") as fh:
            data = make_anim_object(fh.read(), a.name, a.bone)
        dst = os.path.join(out, "meshes", *a.model.replace("/", "\\").split("\\"))
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
        print(f"{a.nif} -> meshes\\{a.model} (root {a.name}, Prn {a.bone}, no collision; {res.get('shapes')} shapes, "
              f"materials {res.get('materials')}); {copied} mesh / material / texture files into {out}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
