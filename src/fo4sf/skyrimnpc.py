"""Skyrim NPCs for conversion: what an NPC record says about its face, hair, outfit and AI, and where its baked face is.

Record layouts from xEdit's wbDefinitionsTES5 (read for the format only):
* NPC_: ACBS (flags u32: bit 0 female ...; then s16 magicka, s16 stamina, u16 level, u16 calc min, u16 calc max,
  u16 speed mult, s16 disposition, u16 template flags, s16 health, u16 bleedout), SNAM factions (formid u32, rank s8),
  VTCK voice, TPLT template, RNAM race, WNAM skin, PKID packages (repeated), CNAM class, PNAM head parts (repeated),
  HCLF hair colour, NAM6 height, NAM7 weight, DOFT / SOFT outfits, FTST head texture, QNAM texture lighting (3 floats),
  NAM9 face morph (19 floats), NAMA face parts (nose u32, unknown s32, eyes u32, mouth u32), tint layers
  (TINI u16 index, TINC rgba, TINV u32 value / 100, TIAS s16 preset).
* HDPT: MODL model, PNAM type (u32: 0 misc, 1 face, 2 eyes, 3 hair, 4 facial hair, 5 scar, 6 eyebrows), HNAM extra
  parts (repeated), DATA flags (u8: bit 0 playable, bit 1 male, bit 2 female, bit 3 is extra part ...), TNAM texture set.
* CLFM (colour form): CNAM rgba.

The face actually shown in game is baked per NPC by the Creation Kit (FaceGen): a head mesh with the race head, the
face morphs and the head parts already applied (meshes\\actors\\character\\facegendata\\facegeom\\<plugin>\\<id>.nif)
and a face tint texture (textures\\actors\\character\\facegendata\\facetint\\<plugin>\\<id>.dds), named by the
FormID's object id (the load-order byte zeroed). The face fitter (facefit.py) reads the shape from there.
"""
import struct
from typing import Dict, List, Optional

from . import fo4land, nif as nifmod

FEMALE = 0x1
# ACBS template flags (wbTemplateFlags): which data an NPC with a template (TPLT) takes from it
TEMPLATE_TRAITS = 0x0001          # race, sex, face, height / weight ... ("Use Traits")
TEMPLATE_AI_PACKAGES = 0x0010
TEMPLATE_INVENTORY = 0x0100
HEAD_PART_TYPES = {0: "misc", 1: "face", 2: "eyes", 3: "hair", 4: "facial hair", 5: "scar", 6: "eyebrows"}
FACE_MORPHS = ("nose long/short", "nose up/down", "jaw up/down", "jaw narrow/wide", "jaw forward/back",
               "cheeks up/down", "cheeks forward/back", "eyes up/down", "eyes in/out", "brows up/down",
               "brows in/out", "brows forward/back", "lips up/down", "lips in/out", "chin narrow/wide", "chin up/down",
               "chin underbite/overbite", "eyes forward/back", "vampire")


def _u32(d) -> int:
    return struct.unpack_from("<I", bytes(d), 0)[0]


def parse_npc(subs, form_id: int) -> Dict:
    """The fields of one NPC_ record that conversion uses."""
    out = {"form_id": form_id, "edid": "", "female": False, "race": None, "template": None, "template_flags": 0,
           "head_parts": [], "hair_color": None, "height": 1.0, "weight": 50.0, "packages": [], "factions": [],
           "outfit": None, "sleep_outfit": None, "class": None, "voice": None, "skin": None, "head_texture": None,
           "texture_lighting": None, "face_morph": None, "face_parts": None, "tints": [], "full_name_id": None}
    tint = None
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = fo4land.zstring(d)
        elif sig == b"FULL" and len(d) == 4:
            out["full_name_id"] = _u32(d)                    # localized plugin: a string-table id
        elif sig == b"FULL":
            out["full_name"] = fo4land.zstring(d)
        elif sig == b"ACBS" and len(d) >= 20:
            flags, = struct.unpack_from("<I", d, 0)
            out["female"] = bool(flags & FEMALE)
            out["flags"] = flags
            out["template_flags"], = struct.unpack_from("<H", d, 18)
        elif sig == b"SNAM" and len(d) >= 5:
            out["factions"].append((_u32(d), struct.unpack_from("<b", d, 4)[0]))
        elif sig in (b"VTCK", b"TPLT", b"RNAM", b"WNAM", b"CNAM", b"HCLF", b"DOFT", b"SOFT", b"FTST") and len(d) >= 4:
            key = {b"VTCK": "voice", b"TPLT": "template", b"RNAM": "race", b"WNAM": "skin", b"CNAM": "class",
                   b"HCLF": "hair_color", b"DOFT": "outfit", b"SOFT": "sleep_outfit", b"FTST": "head_texture"}[sig]
            out[key] = _u32(d)
        elif sig == b"PKID" and len(d) >= 4:
            out["packages"].append(_u32(d))
        elif sig == b"PNAM" and len(d) >= 4:
            out["head_parts"].append(_u32(d))
        elif sig == b"NAM6" and len(d) >= 4:
            out["height"], = struct.unpack_from("<f", d, 0)
        elif sig == b"NAM7" and len(d) >= 4:
            out["weight"], = struct.unpack_from("<f", d, 0)
        elif sig == b"QNAM" and len(d) >= 12:
            out["texture_lighting"] = struct.unpack_from("<3f", d, 0)
        elif sig == b"NAM9" and len(d) >= 4 * len(FACE_MORPHS):
            out["face_morph"] = dict(zip(FACE_MORPHS, struct.unpack_from(f"<{len(FACE_MORPHS)}f", d, 0)))
        elif sig == b"NAMA" and len(d) >= 16:
            nose, unk, eyes, mouth = struct.unpack_from("<IiII", d, 0)
            out["face_parts"] = {"nose": nose, "unknown": unk, "eyes": eyes, "mouth": mouth}
        elif sig == b"TINI" and len(d) >= 2:
            tint = {"index": struct.unpack_from("<H", d, 0)[0], "color": None, "value": None, "preset": None}
            out["tints"].append(tint)
        elif sig == b"TINC" and tint is not None and len(d) >= 4:
            tint["color"] = tuple(d[:4])
        elif sig == b"TINV" and tint is not None and len(d) >= 4:
            tint["value"] = _u32(d) / 100.0
        elif sig == b"TIAS" and tint is not None and len(d) >= 2:
            tint["preset"] = struct.unpack_from("<h", d, 0)[0]
    return out


def parse_head_part(subs, form_id: int) -> Dict:
    out = {"form_id": form_id, "edid": "", "model": None, "type": None, "type_name": None, "extra_parts": [],
           "flags": 0, "texture_set": None}
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = fo4land.zstring(d)
        elif sig == b"MODL":
            out["model"] = fo4land.zstring(d)
        elif sig == b"PNAM" and len(d) >= 4:
            out["type"] = _u32(d)
            out["type_name"] = HEAD_PART_TYPES.get(out["type"], "?")
        elif sig == b"HNAM" and len(d) >= 4:
            out["extra_parts"].append(_u32(d))
        elif sig == b"DATA" and len(d) >= 1:
            out["flags"] = d[0]
        elif sig == b"TNAM" and len(d) >= 4:
            out["texture_set"] = _u32(d)
    return out


def parse_color(subs, form_id: int) -> Dict:
    out = {"form_id": form_id, "edid": "", "rgba": None}
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = fo4land.zstring(d)
        elif sig == b"CNAM" and len(d) >= 4:
            out["rgba"] = tuple(d[:4])
    return out


def facegen_paths(plugin: str, form_id: int) -> Dict[str, str]:
    """Data-relative paths of the NPC's baked face mesh and tint texture."""
    oid = f"{form_id & 0xFFFFFF:08X}"
    return {"mesh": f"meshes\\actors\\character\\facegendata\\facegeom\\{plugin}\\{oid}.nif",
            "tint": f"textures\\actors\\character\\facegendata\\facetint\\{plugin}\\{oid}.dds"}


def head_shape(shapes, names_hint=("head",)):
    """The face shape among a FaceGen NIF's shapes: the first whose name contains a hint (case-insensitive) and
    has the most vertices among those, else the shape with the most vertices."""
    def name(s):
        n = getattr(s, "name", b"") or b""
        return (n.decode("latin-1") if isinstance(n, bytes) else str(n)).lower()
    hinted = [s for s in shapes if any(h in name(s) for h in names_hint)]
    pool = hinted or list(shapes)
    return max(pool, key=lambda s: len(s.positions)) if pool else None


def faces_by_template(npcs: Dict[int, Dict]) -> Dict[int, int]:
    """{npc: npc whose face it shows}: NPCs using a template's traits show the template's face (followed to the end of
    the chain; a missing or looping template keeps the NPC itself)."""
    out = {}
    for fid in npcs:
        cur, seen = fid, set()
        while True:
            n = npcs.get(cur)
            if not n or not (n["template_flags"] & TEMPLATE_TRAITS) or n["template"] not in npcs or cur in seen:
                break
            seen.add(cur)
            cur = n["template"]
        out[fid] = cur
    return out
