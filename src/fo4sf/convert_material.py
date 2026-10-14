"""Fallout 4 .bgsm material + textures -> Starfield .mat + converted DDS files (spike S3, fidelity tier T2).

The Starfield `.mat` is a component database in JSON. We clone a vanilla single-layer PBR material read from the user's own
Creation Kit install (`Tools/ContentResources.zip`, never committed), re-point its three texture slots, set a white tint and
give every object it defines a new ID so it cannot clash with the vanilla material it was cloned from.
"""
import json
import struct
import zipfile
import zlib
from dataclasses import dataclass
from typing import Dict, Optional

TEMPLATE_MAT = "Materials/Common/Metal/MetalIronCast01.mat"      # inside ContentResources.zip
TEMPLATE_TEXTURES = {   # the three texture slots of that template (as written in the file)
    "Albedo": "Data\\Textures\\Common\\stone\\StoneMarblePolished02_color.DDS",
    "Normal": "Data\\Textures\\Common\\Concrete\\ConcretePlain02_normal.DDS",
    "Roughness": "Data\\Textures\\Common\\Concrete\\ConcretePlain02_rough.DDS",
}


@dataclass
class Bgsm:
    version: int
    tile_u: bool
    tile_v: bool
    uv_offset: tuple
    uv_scale: tuple
    diffuse: str
    normal: str
    smooth_spec: str
    greyscale: str
    envmap: str
    glow: str
    alpha_blend: bool = False      # header byte 32: alpha blending (overlay shells, glass)
    alpha_test: bool = False       # header byte 42
    alpha_ref: int = 128           # header byte 41: alpha-test reference (0..255)
    decal: bool = False            # header byte 47
    two_sided: bool = False        # header byte 48
    smoothness: float = 1.0        # scales the spec map's gloss channel (v2: 32 bytes after the 9 texture strings)
    spec_mult: float = 1.0


def parse_bgsm(d: bytes) -> Bgsm:
    if d[:4] != b"BGSM":
        raise ValueError("not a BGSM file")
    version, tiles = struct.unpack_from("<II", d, 4)
    uo, vo, us, vs = struct.unpack_from("<4f", d, 12)
    # the texture block starts at the first length-prefixed string that ends in .dds/.tga (before it: flags/floats)
    start = None
    for off in range(8, len(d) - 8):
        ln, = struct.unpack_from("<I", d, off)
        if 4 < ln < 260 and off + 4 + ln <= len(d) and d[off + 3 + ln] == 0 \
                and d[off + 4:off + 3 + ln].lower().endswith((b".dds", b".tga")):
            start = off
            break
    if start is None:
        raise ValueError("no texture paths found")
    out, pos = [], start
    for _ in range(6):                      # missing trailing strings (short decal/label materials) read as ""
        if pos + 4 > len(d):
            out.append("")
            continue
        ln, = struct.unpack_from("<I", d, pos)
        if ln > 512 or pos + 4 + ln > len(d):
            out.append("")
            pos = len(d)
            continue
        out.append(d[pos + 4:pos + 4 + ln].rstrip(b"\0").decode("latin-1"))
        pos += 4 + ln
    # v2 stores 9 texture strings; the lighting block after them holds specular mult (+28) and smoothness (+32),
    # verified on PatioFurniture.BGSM (rim power 2.0, rolloff 0.3, spec colour 1,1,1, mult 0.8, smoothness 1.0, fresnel 5.0)
    smooth, mult = 1.0, 1.0
    if version == 2:
        q = start
        for _ in range(9):
            if q + 4 > len(d):
                break
            ln, = struct.unpack_from("<I", d, q)
            q += 4 + ln
        if q + 36 <= len(d):
            mult, smooth = struct.unpack_from("<ff", d, q + 28)
            if not (0.0 <= smooth <= 1.0):
                smooth = 1.0
            if not (0.0 <= mult <= 100.0):
                mult = 1.0
    flags = d[32], d[42], d[47], d[48]
    return Bgsm(version, bool(tiles & 2), bool(tiles & 1), (uo, vo), (us, vs), *out,
                alpha_blend=bool(flags[0]), alpha_test=bool(flags[1]), decal=bool(flags[2]), two_sided=bool(flags[3]),
                smoothness=smooth, spec_mult=mult, alpha_ref=d[41])


def read_template(content_resources_zip: str) -> dict:
    with zipfile.ZipFile(content_resources_zip) as z:
        name = next(n for n in z.namelist() if n.lower() == TEMPLATE_MAT.lower())
        return json.loads(z.read(name).decode("utf-8-sig"))


def _new_id(old: str, salt: str) -> str:
    a, b, c = old[4:].split(":")
    return f"res:{zlib.crc32((salt + old).encode()) & 0xFFFFFFFF:08X}:{b}:{c}"


METALNESS_SLOT = 4      # MRTextureFile / TextureReplacement index: 0 albedo, 1 normal, 2 opacity, 3 roughness, 4 metalness, 5 AO


def _num(v: float) -> str:
    return f"{v:g}"


def build_mat(template: dict, name: str, albedo: str, normal: str, rough: str,
              tint=(1.0, 1.0, 1.0, 0.0), metalness: float = 0.0, opacity: str = None, alpha_threshold: float = 0.5) -> dict:
    """tint: x, y, z = colour, w = how strongly the tint replaces the albedo texture (1.0 = flat colour, texture
    ignored; measured in game). 0 keeps the converted texture as is."""
    """Return a new .mat dict. Texture arguments are game paths like 'Data\\Textures\\...\\x_color.dds'."""
    mat = json.loads(json.dumps(template))
    defined = {o["ID"] for o in mat["Objects"] if "ID" in o}
    remap = {i: _new_id(i, name) for i in defined}
    repl = {TEMPLATE_TEXTURES["Albedo"]: albedo, TEMPLATE_TEXTURES["Normal"]: normal, TEMPLATE_TEXTURES["Roughness"]: rough}

    def walk(x):
        if isinstance(x, dict):
            for k, v in list(x.items()):
                if k == "Parent":
                    continue                        # class ids / vanilla parents stay as they are
                x[k] = walk(v)
            if x.get("Type") == "BSComponentDB::CTName" and "Name" in x.get("Data", {}):
                x["Data"]["Name"] = x["Data"]["Name"].replace("MetalIronCast01", name)
            return x
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            return remap.get(x, repl.get(x, x))
        return x

    mat = walk(mat)
    for o in mat["Objects"]:                        # base colour tint of the material object
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::Color" and "Value" in c.get("Data", {}) and c.get("Index") == 0 \
                    and "Edges" in o and any(cc.get("Type") == "BSMaterial::TextureSetID" for cc in o["Components"]):
                d = c["Data"]["Value"]["Data"]
                d["x"], d["y"], d["z"], d["w"] = (str(tint[0]), str(tint[1]), str(tint[2]), str(tint[3]))
            # texture slot 4 = metalness; the iron template enables a constant 1.0 there (fully metal), which the engine uses
            # regardless of the Summary block below
            if c.get("Type") == "BSMaterial::TextureReplacement" and c.get("Index") == METALNESS_SLOT:
                d = c["Data"]["Color"]["Data"]["Value"]["Data"]
                d["x"] = d["y"] = d["z"] = _num(metalness)
    if opacity:                                    # alpha-tested cutout: opacity texture in slot 2 + alpha settings on the root
        for o in mat["Objects"]:
            comps = o.get("Components", [])
            if any(c.get("Type") == "BSMaterial::MRTextureFile" for c in comps):
                comps.append({"Data": {"FileName": opacity}, "Index": 2, "Type": "BSMaterial::MRTextureFile", "Version": 1})
            if "ID" not in o and any(c.get("Type") == "BSMaterial::LayerID" for c in comps):
                comps.append({"Data": {"AlphaTestThreshold": f"{alpha_threshold:.3f}", "HasOpacity": "true"}, "Index": 0,
                              "Type": "BSMaterial::AlphaSettingsComponent"})
    layer = mat["Summary"]["Layer1"]
    layer["Tint"] = {"w": tint[3], "x": tint[0], "y": tint[1], "z": tint[2]}
    m = layer["Textures"]["Metalness"]
    m["Replacement"] = {"w": 1, "x": metalness, "y": metalness, "z": metalness}
    m["UseReplacement"] = True
    return mat


GLASS_TEMPLATE_MAT = "Materials/SetDressing/Outpost/Mine/OPMineMaskBox01Glass.mat"   # 1LayerEffectGlassNoFrost, own textures
DECAL_TEMPLATE_MAT = "Materials/Architecture/City/Akila/Decal/AKDecalPrintedTechWall01.mat"   # 1LayerStandardDecal, albedo/normal/rough/opacity


def parse_bgem_textures(d: bytes):
    """FO4 effect material (.bgem): return (base, normal) texture paths. Strings follow the header in the order base, greyscale,
    envmap, normal, envmap mask, ... (length-prefixed). Found the same way as in parse_bgsm."""
    if d[:4] != b"BGEM":
        raise ValueError("not a BGEM file")
    start = None
    for off in range(8, len(d) - 8):
        ln, = struct.unpack_from("<I", d, off)
        if 4 < ln < 260 and off + 4 + ln <= len(d) and d[off + 3 + ln] == 0 \
                and d[off + 4:off + 3 + ln].lower().endswith((b".dds", b".tga")):
            start = off
            break
    if start is None:
        raise ValueError("no texture paths found")
    out, pos = [], start
    for _ in range(5):
        if pos + 4 > len(d):
            out.append("")
            continue
        ln, = struct.unpack_from("<I", d, pos)
        if ln > 512 or pos + 4 + ln > len(d):
            out.append("")
            pos = len(d)
            continue
        out.append(d[pos + 4:pos + 4 + ln].rstrip(b"\0").decode("latin-1"))
        pos += 4 + ln
    return out[0], out[3]


def read_template_path(content_resources_zip: str, path: str) -> dict:
    with zipfile.ZipFile(content_resources_zip) as z:
        name = next(n for n in z.namelist() if n.lower() == path.lower())
        return json.loads(z.read(name).decode("utf-8-sig"))


def build_from_template(template: dict, name: str, files: dict, opacity_value: float = None) -> dict:
    """Clone any single-layer vanilla material: every texture path the template's Summary names under Albedo / Normal /
    Roughness / ... is replaced by files[slot] (slots not given keep the template's file), object IDs are remapped (as in
    build_mat) and, for glass, the opacity replacement value is set."""
    old_layer = template["Summary"]["Layer1"]["Textures"]
    repl = {old_layer[k]["File"]: v for k, v in files.items() if k in old_layer and old_layer[k].get("File")}
    mat = json.loads(json.dumps(template))
    defined = {o["ID"] for o in mat["Objects"] if "ID" in o}
    remap = {i: _new_id(i, name) for i in defined}

    def walk(x):
        if isinstance(x, dict):
            for k, v in list(x.items()):
                if k != "Parent":
                    x[k] = walk(v)
            return x
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            return remap.get(x, repl.get(x, x))
        return x
    mat = walk(mat)
    for o in mat["Objects"]:
        for c in o.get("Components", []):
            if c.get("Type") == "BSComponentDB::CTName" and o is mat["Objects"][0]:
                c["Data"]["Name"] = name
    if opacity_value is not None:
        op = mat["Summary"]["Layer1"]["Textures"].get("Opacity")
        if op:
            op["Replacement"] = {"w": 1, "x": opacity_value, "y": opacity_value, "z": opacity_value}
        for o in mat["Objects"]:
            for c in o.get("Components", []):
                if c.get("Type") == "BSMaterial::TextureReplacement" and c.get("Index") == 2:
                    c["Data"]["Color"]["Data"]["Value"]["Data"].update(
                        {"x": str(opacity_value), "y": str(opacity_value), "z": str(opacity_value)})
    return mat


ROOT = "Data\\Materials\\Layered\\Root\\"


def _rid(name: str, role: str) -> str:
    return f"res:{zlib.crc32((name + '|' + role).encode()) & 0xFFFFFFFF:08X}:{zlib.crc32(name.encode()) & 0xFFFFFF:08X}:A487E721"


def build_mat_standalone(name: str, albedo: str, normal: str, rough: str, tint=(1.0, 1.0, 1.0, 0.0)) -> dict:
    """A single-layer material built from scratch like the Creation Kit's own test materials (TestQA1.mat): every object
    parents the generic Root classes, nothing inherits from a vanilla material, so no vanilla texture can leak through."""
    L, U, M, T = (_rid(name, r) for r in ("layer", "uv", "material", "textureset"))
    def obj(components, parent, outer=None, oid=None):
        o = {"Components": components,
             "Edges": [{"EdgeIndex": 0, "To": ROOT + parent, "Type": "BSMaterial::MaterialParent"}]}
        if outer:
            o["Edges"].append({"EdgeIndex": 0, "To": outer, "Type": "BSComponentDB2::OuterEdge"})
        if oid:
            o["ID"] = oid
        return o
    ctn = lambda n: {"Data": {"Name": n}, "Index": 0, "Type": "BSComponentDB::CTName"}  # noqa: E731
    tex = lambda i, f: {"Data": {"FileName": f}, "Index": i, "Type": "BSMaterial::MRTextureFile", "Version": 1}  # noqa: E731
    colour = {"Data": {"Value": {"Data": {"w": str(tint[3]), "x": str(tint[0]), "y": str(tint[1]), "z": str(tint[2])},
                                 "Type": "XMFLOAT4"}}, "Index": 0, "Type": "BSMaterial::Color"}
    return {"Objects": [
        obj([ctn(name), {"Data": {"ID": L}, "Index": 0, "Type": "BSMaterial::LayerID"}], "LayeredMaterials.mat"),
        obj([ctn(name + "_Layer1"), {"Data": {"ID": M}, "Index": 0, "Type": "BSMaterial::MaterialID"},
             {"Data": {"ID": U}, "Index": 0, "Type": "BSMaterial::UVStreamID"}], "Layers.mat", "<this>", L),
        obj([ctn(name + "_UVStream1")], "UVStreams.mat", L, U),
        obj([ctn(name + "_Material1"), {"Data": {"ID": T}, "Index": 0, "Type": "BSMaterial::TextureSetID", "Version": 1},
             colour], "Materials.mat", L, M),
        obj([ctn(name + "_TextureSet1"), tex(0, albedo), tex(1, normal), tex(3, rough)], "TextureSets.mat", M, T),
    ], "Version": 1}


def dump_mat(mat: dict) -> str:
    return json.dumps(mat, indent="\t", separators=(",", " : "), ensure_ascii=False)


def game_path(rel: str) -> str:
    return "Data\\" + rel.replace("/", "\\")
