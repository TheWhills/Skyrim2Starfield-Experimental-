"""Non-metal materials at a distance (make_skyrim_objects.py lod; docs/terrain/skyrim-objects.md "Glossy LOD").

Every converted material is a clone of the vanilla cast-iron template (convert_material.TEMPLATE_MAT), made non-metal
by a constant metalness replacement of 0 (texture slot 4, convert_material.build_mat). Owner's views (2026-10-17):
up close the objects look right, but in object LOD the same rocks and mountains look glossy and mottled, like wet
metal. Supported hypothesis: the distant renderer ignores the replacement and falls back to the template's metal.
Fix: every material gets an explicit black metalness texture in slot 4 (no replacement), so it is non-metal however
it is read. Files that are hard links into the work folder are replaced (written anew), never edited through the link.
"""
import json
import os
from typing import Dict

import numpy as np

from fo4sf import convert_material as cm, textures

METAL_TEX_REL = "textures/skyrim/_nonmetal_metal.dds"
SLOT = cm.METALNESS_SLOT


def write_black(data_dir: str, texconv: str) -> str:
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        textures.write_r8(os.path.join(tmp, "m_in.dds"), np.zeros((16, 16), np.uint8))
        textures.texconv(texconv, os.path.join(tmp, "m_in.dds"), tmp, "BC4_UNORM")
        dst = os.path.join(data_dir, *METAL_TEX_REL.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(tmp, "m_in.dds"), dst)
    return cm.game_path(METAL_TEX_REL)


def patch(mat: dict, black: str) -> bool:
    """Give the material a black metalness texture in slot 4 instead of a replacement. True if anything changed."""
    changed = False
    for o in mat.get("Objects", []):
        comps = o.get("Components", [])
        if not any(c.get("Type") == "BSMaterial::MRTextureFile" for c in comps):
            continue                                     # only the texture-set object holds the slot files
        keep = [c for c in comps if not (c.get("Index") == SLOT and c.get("Type") in
                                         ("BSMaterial::MRTextureFile", "BSMaterial::TextureReplacement"))]
        have = [c for c in comps if c.get("Index") == SLOT and c.get("Type") == "BSMaterial::MRTextureFile"]
        if len(keep) == len(comps) - 1 and have and have[0]["Data"].get("FileName") == black:
            continue
        keep.append({"Data": {"FileName": black}, "Index": SLOT, "Type": "BSMaterial::MRTextureFile", "Version": 1})
        o["Components"] = keep
        changed = True
    tex = mat.get("Summary", {}).get("Layer1", {}).get("Textures", {})
    if "Metalness" in tex or changed:
        m = tex.setdefault("Metalness", {})
        if m.get("File") != black or m.get("UseReplacement"):
            m["File"] = black
            m["UseReplacement"] = False
            m.pop("Replacement", None)
            changed = True
    return changed


def apply(data_dir: str, texconv: str, prefix: str = "skyrim") -> Dict[str, int]:
    """Patch every .mat under <data_dir>/materials/<prefix>; returns counts."""
    black = write_black(data_dir, texconv)
    st = {"materials": 0, "patched": 0, "failed": 0}
    root = os.path.join(data_dir, "materials", prefix)
    for d, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(".mat"):
                continue
            p = os.path.join(d, fn)
            st["materials"] += 1
            try:
                with open(p, encoding="utf-8-sig") as fh:
                    mat = json.load(fh)
                if not patch(mat, black):
                    continue
                tmp = p + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(cm.dump_mat(mat))
                os.replace(tmp, p)                       # a new file: the hard-linked original stays untouched
                st["patched"] += 1
            except (OSError, ValueError, KeyError, TypeError):
                st["failed"] += 1
    return st


# ----------------------------------------------------------------------------------------------- standalone rebuild
# Owner's views (2026-10-17): at Jemison's ocean spot every converted object, near and far, wears an olive, glossy,
# "underwater / mossy" coating; at the land spot the same mountains were grey rock. Our materials inherit everything
# but their three textures from vanilla PlasticPlainSmooth01 (Import + Parent); supported hypothesis: an inherited
# setting lets the planet's biome (ocean there) coat them. Rebuilt standalone (convert_material.build_mat_standalone,
# parents only the generic Root classes), nothing vanilla is inherited.
OBJECT_PARENTS = ("\\common\\plastic\\", "\\common\\metal\\")


def standalone(mat: dict):
    """The standalone rebuild of a plain opaque converted material, or None (cutouts, decals, glass, ground: kept)."""
    layer = mat.get("Summary", {}).get("Layer1", {})
    parent = (layer.get("Parent") or "").lower()
    if not any(p in parent for p in OBJECT_PARENTS):
        return None
    tex = layer.get("Textures", {})
    files = {k: (v or {}).get("File") for k, v in tex.items()}
    if any(files.get(k) for k in ("Opacity",)) or not files.get("Albedo"):
        return None
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::AlphaSettingsComponent" or \
                    (c.get("Type") == "BSMaterial::MRTextureFile" and c.get("Index") == 2):
                return None
    name = next((c["Data"]["Name"] for c in mat["Objects"][0].get("Components", [])
                 if c.get("Type") == "BSComponentDB::CTName"), "SKY_Material")
    t = layer.get("Tint") or {}
    tint = (float(t.get("x", 1.0)), float(t.get("y", 1.0)), float(t.get("z", 1.0)), float(t.get("w", 0.0)))
    return cm.build_mat_standalone(name, files["Albedo"], files.get("Normal") or "", files.get("Roughness") or "", tint)


def apply_standalone(data_dir: str, prefix: str = "skyrim") -> Dict[str, int]:
    st = {"materials": 0, "rebuilt": 0, "kept": 0, "failed": 0}
    for d, _dirs, files in os.walk(os.path.join(data_dir, "materials", prefix)):
        for fn in files:
            if not fn.lower().endswith(".mat"):
                continue
            p = os.path.join(d, fn)
            st["materials"] += 1
            try:
                with open(p, encoding="utf-8-sig") as fh:
                    mat = json.load(fh)
                new = standalone(mat)
                if new is None:
                    st["kept"] += 1
                    continue
                tmp = p + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(cm.dump_mat(new))
                os.replace(tmp, p)                       # a new file: the hard-linked original stays untouched
                st["rebuilt"] += 1
            except (OSError, ValueError, KeyError, TypeError):
                st["failed"] += 1
    return st
