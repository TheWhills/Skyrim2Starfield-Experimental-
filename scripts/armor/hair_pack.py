"""Build a test mod of Skyrim HDT-SMP wigs (KS Hairdos SMP's wigs) for Starfield, with their hair physics as Starfield's
own cloth (docs/armor/animation-port.md "SMP hair -> Starfield cloth").

On the owner's PC, in one run:
  1. finds each wig NIF of the mod (default: its "01 Wigs" folder, female wigs) and the SMP config it names;
  2. re-rigs the hair onto Starfield's head / chest bones and the hair's own simulated bones (fo4sf.skyrimhair),
     builds the cloth that drives those bones from the config (fo4sf.smpcloth) on a cloth template (a Starfield
     physics hair: the vanilla game's when one fits, else --cloth-template), converts materials and textures with
     the Skyrim object converter;
  3. copies a vanilla head apparel record (keyword ArmorTypeApparelHead) once per wig into S2SHair.esm;
  4. packs "S2SHair - Main.ba2" / "S2SHair - Textures.ba2" with Archive2 (or leaves the files loose).

    python -I scripts\\armor\\hair_pack.py --ks "<KS Hairdos SMP folder>" --starfield "<Starfield folder>"
        --texconv "<texconv.exe>" --out "<MO2 mods>\\S2S Hair" --only Anna

--cloth-template takes a Starfield NIF with cloth (or "<archive.ba2>:<path in archive>", or a .hkx tagfile); it must be
a bone-driving hair with bone-space skinning and capsule colliders (e.g. Eris Hairstyles' long curls). Read-only on
both games' files.
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fo4sf import ba2 as ba2mod  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import sfcloth, sfnif, sfplugin, skyrimconvert, skyrimhair, skyrimnif, smpcloth  # noqa: E402
from fo4sf import smpconfig as smp  # noqa: E402
from fo4sf import convert_material as cm  # noqa: E402

PLUGIN = "S2SHair.esm"
MAIN_BA2 = "S2SHair - Main.ba2"
TEX_BA2 = "S2SHair - Textures.ba2"
PREFIX = "s2s"
HEAD_KEYWORD = "ArmorTypeApparelHead"
WIG_GLOB = re.compile(r"(^|/)meshes/armor/kswigshdt/f/[^/]+\.nif$", re.I)


class LooseRoots:
    """Loose files of one or more mod folders (installer folders such as "00 Core" / "01 Wigs" included), with the
    interface pipeline.Converter uses (mesh, texture, material, mesh_names). Later roots win; names case-blind."""

    def __init__(self, roots):
        self.index = {}
        for root in roots:
            for d, _ds, fs in os.walk(root):
                for f in fs:
                    p = os.path.join(d, f)
                    rel = os.path.relpath(p, root).replace("\\", "/").lower()
                    self.index[rel] = p
                    # an installer subfolder ("00 Core/Meshes/..."): also index from its data root
                    m = re.match(r"^[^/]+/((?:meshes|textures|skse|interface)/.*)$", rel)
                    if m:
                        self.index[m.group(1)] = p

    def _read(self, rel):
        p = self.index.get(rel.replace("\\", "/").lower().lstrip("/"))
        if p is None:
            return None
        with open(p, "rb") as fh:
            return fh.read()

    def mesh(self, name):
        n = name.replace("\\", "/").lower()
        return self._read(n if n.startswith("meshes/") else "meshes/" + n)

    def texture(self, name):
        n = name.replace("\\", "/").lower()
        return self._read(n if n.startswith("textures/") else "textures/" + n)

    def material(self, name):
        return None

    def data(self, rel):
        return self._read(smp.data_relative(rel).replace("\\", "/"))

    def mesh_names(self, pattern):
        rx = re.compile(pattern, re.I)
        return sorted(k for k in self.index if k.endswith(".nif") and rx.search(k))


def read_template(spec: str) -> bytes:
    """Cloth tagfile from a NIF / .hkx file, or "<archive.ba2>:<path>"."""
    m = re.match(r"^(.*\.ba2):(.+)$", spec, re.I)
    if m:
        a = ba2mod.Ba2(m.group(1))
        want = m.group(2).replace("\\", "/").lower()
        hit = next((i for i, n in enumerate(a.names) if n.replace("\\", "/").lower().endswith(want)), None)
        if hit is None:
            raise SystemExit(f"{m.group(2)} not in {m.group(1)}")
        data = a.read(hit)
    else:
        with open(spec, "rb") as fh:
            data = fh.read()
    if data[4:8] == b"TAG0":
        return data
    n = nifmod.parse(data)
    blobs = [sfcloth.payload(b) for i, b in enumerate(n.blocks) if n.type_of(i) == "BSClothExtraData"]
    if not blobs:
        raise SystemExit(f"{spec}: no BSClothExtraData")
    return blobs[0]


def find_template(starfield: str, report: dict) -> bytes:
    """The best vanilla hair cloth smpcloth can build on (scans the game's mesh archives): one with a local range and
    stretch links (SMP's swing limits) wins; the first such ends the scan."""
    data = os.path.join(starfield, "Data")
    tried, best = 0, None
    for f in sorted(os.listdir(data)):
        if not (f.lower().startswith("starfield - meshes") and f.lower().endswith(".ba2")):
            continue
        try:
            a = ba2mod.Ba2(os.path.join(data, f))
        except ba2mod.Ba2Error:
            continue
        for i, name in enumerate(a.names):
            nl = name.lower()
            if "hair" not in nl or not nl.endswith(".nif"):
                continue
            raw = a.read(i)
            if b"BSClothExtraData" not in raw:
                continue
            tried += 1
            try:
                n = nifmod.parse(raw)
                blob = next(sfcloth.payload(b) for k, b in enumerate(n.blocks) if n.type_of(k) == "BSClothExtraData")
                root = smpcloth.check_template(blob)
            except Exception:                                    # noqa: BLE001 (not a usable template: next)
                continue
            score = smpcloth.template_score(root)
            if best is None or score > best[0]:
                best = (score, blob, f"{f}:{name}", root["$kind"])
            if score >= 3:
                break
        if best is not None and best[0] >= 3:
            break
    report["cloth_templates_looked_at"] = tried
    if best is None:
        raise SystemExit(f"no vanilla hair cloth fits ({tried} cloth hairs looked at): pass --cloth-template, e.g. "
                         "\"<Eris Hairstyles>\\ErisHair - Main.ba2:meshes/actors/human/mesh/hairs/eh_longcurls/"
                         "longcurls_f.nif\"")
    report["cloth_template"], report["cloth_template_kind"] = best[2], best[3]
    return best[1]


HIDE_HAIR, MORPH_HAIR = 1 << 0, 1 << 1        # biped object bits (xEdit wbDefinitionsSF1: 0 Hide Hair, 1 Morph Hair)


def hide_hair(arma):
    """The ARMA (or ARMO) with Hide Hair instead of Morph Hair (a hat squashes the hair under it; a wig replaces it:
    2026-11-02 the owner's own hair showed through the KS wigs' scalp). Set on both records: with only the addon
    flagged, a bun of the actor's own hair still showed behind a short wig (supported reading: as in Fallout 4, the
    worn item's own slots decide what it hides)."""
    t, h, subs, fid = arma
    out = []
    for sig, d in subs:
        if sig == b"BO64" and len(d) >= 8:
            bits = (struct.unpack_from("<Q", d)[0] & ~MORPH_HAIR) | HIDE_HAIR
            d = struct.pack("<Q", bits) + bytes(d[8:])
        out.append((sig, d))
    return (t, h, out, fid)


def head_apparel(armo, arma, kw_names):
    """(ARMO, ARMA) of the first vanilla ARMO with the head-apparel keyword that names an ARMA."""
    head = {k for k, n in kw_names.items() if n == HEAD_KEYWORD}
    by_fid = {r[3]: r for r in arma}
    for r in sorted(armo, key=lambda r: sfplugin.edid(r[2])):
        if head & set(sfplugin.keywords(r[2])):
            for s, d in r[2]:
                if s == b"MODL" and len(d) == 4 and struct.unpack("<I", d)[0] in by_fid:
                    return r, by_fid[struct.unpack("<I", d)[0]]
    raise SystemExit(f"no vanilla ARMO with {HEAD_KEYWORD} and an addon")


def read_game_file(starfield: str, rel: str):
    """A file of the game's own archives (Starfield - Meshes*.ba2 ...) by its path in the archive, or None."""
    want = rel.replace("\\", "/").lower()
    data = os.path.join(starfield, "Data")
    for f in sorted(os.listdir(data)):
        if not (f.lower().startswith("starfield - ") and f.lower().endswith(".ba2")):
            continue
        try:
            a = ba2mod.Ba2(os.path.join(data, f))
        except ba2mod.Ba2Error:
            continue
        for i, name in enumerate(a.names):
            if name.replace("\\", "/").lower() == want:
                return a.read(i)
    return None


def game_files_named(starfield: str, stem: str, limit: int = 200):
    """Paths in the game's archives whose file or folder name contains `stem` (case-blind): what else the game keeps
    for a model (morphs, face bones ...), found by name only."""
    stem = stem.lower()
    data = os.path.join(starfield, "Data")
    out = []
    for f in sorted(os.listdir(data)):
        if not (f.lower().startswith("starfield - ") and f.lower().endswith(".ba2")):
            continue
        try:
            a = ba2mod.Ba2(os.path.join(data, f))
        except ba2mod.Ba2Error:
            continue
        out += [f"{f}:{n}" for n in a.names if stem in n.replace("\\", "/").lower()]
        if len(out) >= limit:
            break
    return out[:limit]


def subrecord_dump(rec):
    """[signature, size, first 48 bytes as hex] of a record's subrecords (for comparing a template with its copy)."""
    return [[s.decode("latin-1"), len(d), bytes(d[:48]).hex()] for s, d in rec[2]]


def nif_materials(raw: bytes):
    """The material names of a Starfield NIF's shapes (BSLightingShaderProperty names), in block order."""
    n = nifmod.parse(raw)
    out = []
    for i in range(len(n.blocks)):
        if n.type_of(i) == "BSLightingShaderProperty":
            si, = struct.unpack_from("<i", n.blocks[i], 0)
            if 0 <= si < len(n.strings) and n.strings[si]:
                out.append(n.strings[si].decode("latin-1"))
    return out


def arma_model(arma) -> str:
    """The worn model of an ARMA (female, else male), as written in the record."""
    d = dict((k, bytes(v)) for k, v in arma[2])
    for k in (b"MOD3", b"MOD2"):
        if d.get(k, b"\0")[:1] != b"\0":
            return d[k].split(b"\0")[0].decode("latin-1")
    return ""


def hair_shader_material(conv, n, sh, color=None, ramp=None):
    """Starfield's hair shader for a KS shape (Hair1Layer: dithered soft edges and light through the hair, as the
    game's own and IDG's hairs; the generic cutout material gave hard 'strandy' edges, 2026-11-02), or None."""
    if sh.shader_ref < 0:
        return None
    paths = skyrimnif.texture_set(n, sh.shader_ref)
    if not paths or not paths[0]:
        return None
    _test, _blend, ref = skyrimnif.alpha_test(n, sh.alpha_ref) if sh.alpha_ref >= 0 else (True, False, 128)
    if ramp is None:
        return conv.skyrim_hair_material(paths[0], paths[1] if len(paths) > 1 else "", ref, color)
    return conv.skyrim_hair_material(paths[0], paths[1] if len(paths) > 1 else "", ref, color, ramp)


def hair_color(text: str) -> tuple:
    """argparse type for --hair-color: 'R,G,B' (0-255) -> (R, G, B)."""
    parts = [p.strip() for p in str(text).replace(" ", ",").split(",") if p.strip()]
    try:
        rgb = tuple(int(p) for p in parts)
    except ValueError:
        rgb = ()
    if len(rgb) != 3 or not all(0 <= v <= 255 for v in rgb):
        raise argparse.ArgumentTypeError(f"expected R,G,B with each 0-255, got {text!r}")
    return rgb


def back_faces_for(n, sh, hair_shader: bool) -> bool:
    """Whether a shape gets a mirrored copy of its triangles (skyrimconvert.with_back_faces: how a double-sided Skyrim
    surface is drawn from behind with an ordinary one-sided Starfield material). Never under the hair shader: it draws
    both sides itself (IDG's hairs have no mirrored triangles, verified on six styles), so the copy lay in the same
    place with its normal reversed and the two flickered dark / light (2026-11-02, owner's in-game shots)."""
    if hair_shader:
        return False
    return bool(sh.shader_ref >= 0 and skyrimnif.double_sided(n, sh.shader_ref))


def hair_setting(text: str) -> tuple:
    """argparse type for --hair-setting: 'Name=Value' with Name one of the hair shader's settings."""
    name, sep, value = str(text).partition("=")
    name, value = name.strip(), value.strip()
    if not sep or name not in cm.HAIR_SETTINGS or not value:
        raise argparse.ArgumentTypeError(f"expected NAME=VALUE with NAME one of {', '.join(sorted(cm.HAIR_SETTINGS))}, "
                                         f"got {text!r}")
    return name, value


OPACITY_RAMP = (48, 112)


def opacity_ramp(text: str) -> tuple:
    """argparse type for --opacity-ramp: 'LO,HI' (0-255, LO < HI)."""
    parts = [p.strip() for p in str(text).split(",") if p.strip()]
    try:
        lo, hi = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected LO,HI (0-255), got {text!r}")
    if not 0 <= lo < hi <= 255:
        raise argparse.ArgumentTypeError(f"expected 0 <= LO < HI <= 255, got {text!r}")
    return lo, hi


def tint_material(conv, n, sh, cutoff: int, color=None):
    """The material of KS's scalp fade layer ('Hairline'): its texture fades out over the forehead and Skyrim blends
    it (alpha test 10 + blend); a converted cutout material keeps every pixel above alpha 10/255, so the whole fade
    drew as a hard band down the forehead (2026-11-02: owner saw the KS scalp too low). The cut-off is raised to
    `cutoff` (0-255) so only the solid part of the fade shows."""
    paths = skyrimnif.texture_set(n, sh.shader_ref) if sh.shader_ref >= 0 else []
    if not paths or not paths[0]:
        return conv._shape_material(n, sh)
    return conv.skyrim_material(paths[0], paths[1] if len(paths) > 1 else "", True, False, int(cutoff),
                                albedo_target=color) or \
        conv._shape_material(n, sh)


HAIR_PART = 3                    # HDPT PNAM: hair (IDG's 46 hairs and OC Hairs' carry 3)
PART_PLAYABLE = 0x01             # HDPT DATA flag (IDG's hairs: 0x01; extra parts 0x09)


def hair_part_template(hdpt, prefer: str = ""):
    """A vanilla playable hair head part to copy (its race list, cap mask and hair category kept): the one whose model
    names `prefer` (the cloth template's hair, e.g. 'bob_f'), else the first playable hair. None when there is none."""
    def ok(r):
        d = next((bytes(x) for s_, x in r[2] if s_ == b"PNAM" and len(x) >= 4), None)
        f = next((bytes(x) for s_, x in r[2] if s_ == b"DATA" and len(x) >= 1), b"\0")
        return d is not None and struct.unpack_from("<I", d, 0)[0] == HAIR_PART and f[0] & PART_PLAYABLE
    hairs = sorted((r for r in hdpt if ok(r)), key=lambda r: sfplugin.edid(r[2]))
    model = lambda r: next((bytes(x).rstrip(b"\0").decode("latin-1") for s_, x in r[2] if s_ == b"MODL"), "")
    want = prefer.lower()
    return next((r for r in hairs if want and want in model(r).lower()), hairs[0] if hairs else None)


def hair_part_record(template, index: int, edid: str, name: str, model: str):
    """A new playable hair head part copied from `template` with its own EditorID, name and model, without the
    template's extra parts (HNAM) and face-slider morphs (MNAM: they move the template mesh's vertices, not ours).
    Starfield lists playable hair head parts of the character's race in the looks menu, and a head part takes the
    actor's hair colour (an apparel item does not: the wigs drew the texture's own grey, 2026-11-02). IDG's hairs
    are added the same way, with no change to the race or the menu's lists."""
    t, h, subs, _f = template
    flags = next((bytes(x) for s_, x in subs if s_ == b"DATA" and len(x) >= 1), b"\0")
    subs = sfplugin.edit(subs, {b"EDID": sfplugin.zs(edid), b"FULL": sfplugin.zs(name), b"MODL": sfplugin.zs(model),
                                b"DATA": bytes([flags[0] | PART_PLAYABLE]) + flags[1:]}, drop=(b"HNAM", b"MNAM"))
    return (t, h, subs, sfplugin.new_form_id(index))


CHARGEN_FEMALE = "HeadPartsChargenOptionsFemale"   # vanilla FLST of the head parts the looks menu offers women


def chargen_list_override(flst, edid: str, new_ids):
    """An override of the vanilla form list `edid` with `new_ids` appended (each once), or None when the game has no
    such list. 2026-11-02: playable hair head parts alone did not appear in the owner's looks menu; vanilla lists its
    choices here."""
    rec = next((r for r in flst if sfplugin.edid(r[2]) == edid), None)
    if rec is None:
        return None
    t, h, subs, fid = rec
    have = {struct.unpack_from("<I", bytes(d), 0)[0] for s_, d in subs if s_ == b"LNAM" and len(d) >= 4}
    add = [(b"LNAM", struct.pack("<I", i)) for i in new_ids if i not in have]
    last = max((k for k, (s_, _d) in enumerate(subs) if s_ == b"LNAM"), default=len(subs) - 1)
    return (t, h, list(subs[:last + 1]) + add + list(subs[last + 1:]), fid)


def write_files(staging: str, files: dict):
    for rel, data in files.items():
        p = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)


def facebones_worlds_of(raw: bytes) -> dict:
    """({face bone: rest world}, the shape node transform as a 4x4) of a vanilla *_facebones.nif."""
    from fo4sf import sfweaponleft
    n = nifmod.parse(raw)
    shapes = sfweaponleft.shapes_in_model(n)
    node = skyrimhair.xf_matrix(shapes[0][1]) if shapes else None
    return skyrimhair.face_bone_worlds(sfnif.parse_skin(n), node), node


SKY_FEMALE_HEAD = r"meshes\actors\character\character assets\femalehead.nif"
SF_FEMALE_HEAD = "meshes/actors/human/characterassets/female/femalehead_facebones.nif"


def measure_female_fit(skyrim_data: str, starfield: str, sf_world: dict, report: dict, per_axis: bool = True):
    """(scale, offset) fitting the Skyrim female head onto the Starfield female head (skyrimhair.fit_head), or None.
    The KS wigs are made for Skyrim's female head; the constants were measured on the male heads (2026-11-02: the
    owner's female character showed the wigs clipping the forehead)."""
    info = report.setdefault("head_fit", {})
    try:
        sky_pts, anchor, sf_pts, _nrm = load_female_heads(skyrim_data, starfield)
        report["_sky_head"] = (sky_pts, anchor)                 # for follow_head (not written to the report)
        head = sf_world[skyrimhair.SF_HEAD]
        s1, t1, rms1 = skyrimhair.fit_head(sky_pts, anchor, sf_pts, head)
        s3, t3, rms3 = skyrimhair.fit_head_axes(sky_pts, anchor, sf_pts, head)
    except Exception as e:                                       # noqa: BLE001 (reported; male constants kept)
        info["error"] = f"{type(e).__name__}: {e}"
        return None
    info.update(uniform={"scale": round(s1, 4), "offset": [round(x, 4) for x in t1], "rms_mm": round(1000 * rms1, 2)},
                per_axis={"scale_xyz": [round(x, 4) for x in s3], "offset": [round(x, 4) for x in t3],
                          "rms_mm": round(1000 * rms3, 2)},
                male_constants={"scale": skyrimhair.HEAD_SCALE, "offset": list(skyrimhair.HEAD_OFFSET)})
    if per_axis:
        info["applied"] = "per_axis"
        return np.array(s3), t3
    info["applied"] = "uniform"
    return s1, t1


def game_mesh_of(starfield: str, raw: bytes, read=None):
    """(points (V, 3) model space, unit normals (V, 3), per-vertex [(bone name, weight)], triangles) of a vanilla
    skinned NIF's first shape (the shape node's transform applied: the female head stores its mesh in C_Head's
    rotated frame, the bob hair at C_Head), its mesh read from the game's archives; None when the mesh is not found."""
    from fo4sf import sfmesh, sfweaponleft
    n = nifmod.parse(raw)
    shapes = sfweaponleft.shapes_in_model(n)
    if not shapes:
        return None
    i, xf = shapes[0]
    g = sfnif.parse_bsgeometry(n.blocks[i])
    if not g.meshes or g.meshes[0] is None:
        return None
    rel = sfweaponleft.mesh_archive_path(g.meshes[0].path)
    data = (read(rel) if read is not None else None) or read_game_file(starfield, rel)
    if data is None:
        return None
    m = sfmesh.parse(data)
    node = skyrimhair.xf_matrix(xf)
    pts = np.array([sfmesh.decode_position(p, m.scale) for p in m.positions], float)
    pts = pts @ node[:3, :3].T + node[:3, 3]
    if m.normals:
        nrm = np.array([sfmesh.decode_packed(u)[:3] for u in m.normals], float) @ node[:3, :3].T
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    else:
        nrm = np.zeros_like(pts)
    names = [b.decode("latin-1") for b in sfnif.parse_skin(n)["bones"]]
    k = m.weights_per_vertex or 0
    ws = []
    for v in range(len(m.positions)):
        row = m.weights[v * k:(v + 1) * k] if k else []
        ws.append([(names[b], w / 65535.0) for b, w in row if w > 0 and b < len(names)])
    return pts, nrm, ws, [tuple(t) for t in m.triangles]


def reference_hair(spec: str, starfield: str):
    """game_mesh_of for a hair named "<archive.ba2>:<path of its _facebones.nif in it>" (e.g. an IDG Elegant Hair
    style), its mesh read from the same archive (else the game's): the target of the hairline lift and the volume
    in place of the cloth template's vanilla hair. None when not found."""
    m = re.match(r"^(.*\.ba2):(.+)$", spec, re.I)
    if not m:
        raise SystemExit(f"--reference-hair: expected '<archive.ba2>:<path in archive>', got {spec}")
    arc = ba2mod.Ba2(m.group(1))
    index = {n.replace("\\", "/").lower(): i for i, n in enumerate(arc.names)}

    def read(rel):
        i = index.get(rel.replace("\\", "/").lower())
        return arc.read(i) if i is not None else None
    raw = read(m.group(2))
    if raw is None:
        raise SystemExit(f"--reference-hair: {m.group(2)} not in {m.group(1)}")
    return game_mesh_of(starfield, raw, read)


def facebones_skin_of(starfield: str, raw: bytes):
    """(points (V, 3) model space, per-vertex [(bone name, weight)]) of a vanilla *_facebones.nif's first skinned
    shape (game_mesh_of), or None."""
    got = game_mesh_of(starfield, raw)
    return None if got is None else (got[0], got[2])


def load_female_heads(skyrim_data: str, starfield: str):
    """(Skyrim female head points in units, its head bone 4x4 in units, Starfield female head points m, normals)."""
    from fo4sf import bsa, skyrimnpc, skyrimskin
    sky = bsa.SkyrimArchives(skyrim_data)
    raw = sky._read(bsa.norm(SKY_FEMALE_HEAD))
    if raw is None:
        raise HairPackError(f"not in Skyrim's archives: {SKY_FEMALE_HEAD}")
    n = nifmod.parse(raw)
    shape = skyrimnpc.head_shape(skyrimskin.skinned_shapes(n))
    anchor = skyrimhair.head_anchor(n, skyrimhair.node_worlds(n)[0])
    sf_raw = read_game_file(starfield, SF_FEMALE_HEAD)
    if sf_raw is None:
        raise HairPackError(f"not in the game's archives: {SF_FEMALE_HEAD}")
    got = game_mesh_of(starfield, sf_raw)
    if got is None:
        raise HairPackError("the Starfield female head's mesh was not found")
    to_model, _rot = skyrimhair.skin_to_model(shape)          # skinned vertices are stored in skin space
    return np.array([to_model(v) for v in shape.positions], float), anchor, got[0], got[1]


class HairPackError(Exception):
    pass


def facebones_template(starfield: str, hat_model: str, report: dict, hair_template: str = None):
    """(face bone, its rest world, every face bone's world, the hat's facebones NIF bytes) or None. Head items are
    drawn from <model>_facebones.nif on actors with face bones (the player, named NPCs): vanilla hats and hairs ship
    both files (verified in game 2026-11-02: our wigs show once that file exists). The face bones' rest worlds come
    from a vanilla hair's facebones file (the cloth template's, e.g. bob_f_facebones.nif) when found, else the hat's;
    both are reported to compare."""
    if not hat_model:
        return None
    rel = "meshes/" + os.path.splitext(hat_model.replace("\\", "/"))[0] + "_facebones.nif"
    raw = read_game_file(starfield, rel)
    info = report.setdefault("facebones", {})
    info["hat_file"] = rel if raw is not None else f"not found: {rel}"
    if raw is None:
        return None
    sources = []
    if hair_template and ":" in hair_template:
        hrel = os.path.splitext(hair_template.split(":", 1)[1].replace("\\", "/"))[0] + "_facebones.nif"
        hraw = read_game_file(starfield, hrel)
        info["hair_file"] = hrel if hraw is not None else f"not found: {hrel}"
        if hraw is not None:
            sources.append(("hair", hraw))
            try:
                skin = facebones_skin_of(starfield, hraw)
            except Exception as e:                               # noqa: BLE001 (reported; one face bone instead)
                skin, info["hair_skin_error"] = None, f"{type(e).__name__}: {e}"
            if skin is not None:
                info["hair_skin_vertices"] = len(skin[0])
                report["_face_skin"] = skin
    sources.append(("hat", raw))
    picked = None
    for kind, data in sources:
        worlds, node = facebones_worlds_of(data)
        face = skyrimhair.pick_face_bone(worlds)
        info[kind] = {"node": None if node is None else np.round(node, 4).tolist(), "face_bones": len(worlds),
                      "face_bone": face, "face_bone_world": np.round(worlds[face], 4).tolist()}
        if picked is None:
            picked = (kind, face, worlds)
    kind, face, worlds = picked
    info["used"] = kind
    report["face_bone"] = face
    return face, worlds[face], worlds, raw, report.pop("_face_skin", None)


def facebones_files(row: dict, fb, sf_world: dict, rigid_copies: bool) -> dict:
    """<model>_facebones.nif for a wig and its no-physics / head-bone copies: C_Head's weights on the face bone."""
    hair, mats, blob, out_name, backs = row["_fb"]
    face, fw = fb[0], fb[1]
    world = dict(sf_world, **{face: fw})
    skin = fb[4] if len(fb) > 4 else None
    if skin is not None:                     # the scalp spread over the face bones as the vanilla hair's
        world.update(fb[2])
        on_face = skyrimhair.on_face_bones(hair, skin[0], skin[1])
        row["face_bones"] = "spread"
    else:
        on_face = skyrimhair.on_face_bone(hair, face)
        row["face_bones"] = face
    files = skyrimhair.nif_files(on_face, mats, blob, world, out_name + "_facebones", backs)
    if rigid_copies:
        rg = skyrimhair.rigid(hair)
        files.update(skyrimhair.nif_files(skyrimhair.on_face_bone(rg, face), mats, None, world,
                                          out_name + "_rigid_facebones", backs))
        hl, hw = skyrimhair.head_local(rg, world, bone=face)
        files.update(skyrimhair.nif_files(hl, mats, None, hw, out_name + "_head_facebones", backs))
    return files


def control_files(row: dict, conv, hat_raw, hat_model: str, fb=None, sf_world=None) -> dict:
    """In-game controls for one wig, to find why a wig is not drawn (each {relative path: bytes} plus its model):
    "opaque": the head-bone copy with its material made solid (no alpha test), "hatmat": the head-bone copy with the
    vanilla hat's own material, "hatcopy": the vanilla hat NIF itself put in this mod's archive."""
    hl, hw, n, out_name, backs = row["_control"]
    out = {}
    mats = []
    for sh in hl.shapes:
        paths = skyrimnif.texture_set(n, sh.shader_ref) if sh.shader_ref >= 0 else []
        if paths and paths[0]:
            mats.append(conv.skyrim_material(paths[0], paths[1] if len(paths) > 1 else "", False, False, 0) or
                        conv.neutral)
        else:
            mats.append(conv.neutral)
    fhl = fhw = None
    if fb is not None:                        # the same controls on the face bone (the file the game draws)
        fhl, fhw = skyrimhair.head_local(skyrimhair.rigid(row["_fb"][0]), dict(sf_world, **{fb[0]: fb[1]}),
                                         bone=fb[0])

    def both(materials, name):
        files = skyrimhair.nif_files(hl, materials, None, hw, name, backs)
        if fhl is not None:
            files.update(skyrimhair.nif_files(fhl, materials, None, fhw, name + "_facebones", backs))
        return files, name
    out["opaque"] = both(mats, out_name + "_opaque")
    hat_mats = nif_materials(hat_raw) if hat_raw else []
    if hat_mats:
        out["hatmat"] = both([hat_mats[0]] * len(hl.shapes), out_name + "_hatmat")
    if hat_raw:
        files = {f"meshes/{PREFIX}/hair/control_hat_copy.nif": hat_raw}
        if fb is not None:
            files[f"meshes/{PREFIX}/hair/control_hat_copy_facebones.nif"] = fb[3]
        out["hatcopy"] = (files, f"{PREFIX}/hair/control_hat_copy")
    if hat_model:            # the addon copied exactly as for a wig, but still naming the vanilla model path
        out["armacopy"] = ({}, os.path.splitext(hat_model.replace("\\", "/"))[0])
    return out


def pack(staging: str, out: str, starfield: str, archive2: str = None, main_ba2: str = MAIN_BA2,
         tex_ba2: str = TEX_BA2) -> dict:
    """BA2 archives named after the plugin (Starfield loads "<plugin> - *.ba2"), or the files loose."""
    tool = archive2 or os.path.join(starfield, "Tools", "Archive2", "Archive2.exe")
    main = [d for d in ("meshes", "geometries", "materials") if os.path.isdir(os.path.join(staging, d))]
    tex = [d for d in ("textures",) if os.path.isdir(os.path.join(staging, d))]
    if os.path.isfile(tool):
        import deploy_starfield
        a = types.SimpleNamespace(starfield=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(tool)))),
                                  staging=staging)
        if main:
            deploy_starfield.build_archive(a, os.path.join(out, main_ba2), main, "General")
        if tex:
            deploy_starfield.build_archive(a, os.path.join(out, tex_ba2), tex, "DDS")
        return {"archives": [main_ba2] * bool(main) + [tex_ba2] * bool(tex)}
    for d in main + tex:
        shutil.copytree(os.path.join(staging, d), os.path.join(out, d), dirs_exist_ok=True)
    return {"loose": main + tex, "note": "Archive2 not found: files left loose"}


def build_one(src: LooseRoots, conv, nif_rel: str, template_blob: bytes, template_root: dict, sf_world: dict,
              settings: smpcloth.Settings, a, staging: str) -> dict:
    """Convert one wig: files written into staging; returns its report row (ok, model, ...)."""
    stem = os.path.splitext(os.path.basename(src.index.get(nif_rel, nif_rel)))[0]     # the file's own spelling
    row = {"wig": stem, "nif": nif_rel, "ok": False}
    raw = src._read(nif_rel)
    n = nifmod.parse(raw)
    paths = smp.nif_physics_paths(n)
    if not paths:
        row["reason"] = "no SMP config named in the NIF"
        return row
    xml = src.data(paths[0])
    if xml is None:
        row["reason"] = f"config not found: {paths[0]}"
        return row
    row["config"] = paths[0]
    hair = skyrimhair.convert(raw, xml, sf_world, a.head_scale, tuple(a.head_offset))
    if getattr(a, "sky_head", None) is not None and getattr(a, "head_surface", None) is not None:
        hair, row["follow_head"] = skyrimhair.follow_head(hair, a.sky_head, *a.head_surface,
                                                            sigma=a.follow_sigma / 1000.0)
    if a.hair_shader:                    # KS's second (alpha-tested) copy of every wig: the hair shader needs one
        hair, dropped = skyrimhair.drop_duplicate_shapes(hair)
        if dropped:
            row["dropped_duplicate_shapes"] = dropped
        # and draws a card's back with the front's lighting: every card faces away from the head
        hair, row["oriented"] = skyrimhair.orient_outward(hair, sf_world[skyrimhair.SF_HEAD])
    if getattr(a, "head_surface", None) is not None:
        head = sf_world[skyrimhair.SF_HEAD]
        pts = skyrimhair.hair_points(hair)                       # without KS's scalp tint layer
        lift = None
        if a.hairline_lift is not None:
            lift = a.hairline_lift / 1000.0
        elif getattr(a, "vanilla_profile", None) is not None:   # up to the vanilla hair's hairline, temple to temple
            own = skyrimhair.hairline_profile(pts, *a.head_surface, head)
            lift = skyrimhair.lift_profile(own, a.vanilla_profile)
            row["hairline_above_C_Head_mm_by_angle"] = {k: None if v is None else round(1000 * v, 1)
                                                         for k, v in own.items()}
        if lift:
            hair = skyrimhair.lift_hairline(hair, *a.head_surface, head, lift)
            row["hairline_lift_mm"] = ({k: round(1000 * v, 1) for k, v in lift.items()} if isinstance(lift, dict)
                                       else round(1000 * lift, 1))
        volume = None
        if a.volume is not None:
            volume = a.volume / 1000.0
        elif getattr(a, "vanilla_crown", None) is not None:      # stand off the scalp like the vanilla hair
            own_crown = skyrimhair.crown_height(pts, head)
            if own_crown is not None:
                cap = skyrimhair.VOLUME_MAX_LAYERED if a.layers > 0 else skyrimhair.VOLUME_MAX
                volume = float(np.clip(a.vanilla_crown - own_crown, 0.0, cap))
                row["crown_above_C_Head_mm"] = round(1000 * own_crown, 1)
        if volume:                       # fading to nothing at the (lifted) hairline: the edge stays on the skin
            edge = skyrimhair.hairline_profile(skyrimhair.hair_points(hair), *a.head_surface, head)
            hair = skyrimhair.add_volume(hair, *a.head_surface, head, volume, edge=edge, layers=a.layers)
            row["volume_mm"] = round(1000 * volume, 1)
            if a.layers > 0:
                row["layers"] = {"count": a.layers, "vertices_added": hair.report.get("layer_vertices", 0)}
        if a.drape > 0:                  # bridge the temple hollow: one convex curve from crown to brow
            hair, row["drape"] = skyrimhair.drape(hair, *a.head_surface, head, radius=a.drape / 1000.0)
        hair, row["conform"] = skyrimhair.push_out(hair, *a.head_surface,   # no scalp point inside the head
                                                   blend=a.push_blend / 1000.0)
    row.update({k: hair.report[k] for k in ("chain_bones", "hosts", "shapes", "vertices") if k in hair.report})
    if not hair.bones:
        row["reason"] = "the config simulates no bone of this mesh"
        return row
    cap = skyrimhair.head_capsule(sf_world, hair, margin=settings.radius + 0.004)
    body, body_report = ([], {}) if a.body_scale <= 0 else skyrimhair.body_capsules(
        sf_world, hair, a.body_scale, margin=settings.radius + 0.005)
    # the template's own colliders are left out: sized for its hair, the KS particles can start inside them (2026-11-02:
    # short wigs flailed at rest); S2S_head replaces its head collider
    face = skyrimhair.face_capsule(sf_world, hair, margin=settings.radius + 0.004)
    body_report["S2S_face"] = round(face.radius, 4) if face is not None else "left out: the hair starts inside it"
    root, rig = smpcloth.build_cloth(template_root, hair.bones, hair.host_of_root,
                                     [cap] + ([face] if face is not None else []) + body, settings,
                                     keep_template_colliders=False)
    blob = smpcloth.write(template_blob, root)
    row["cloth"] = {**rig.report, "check": smpcloth.verify(blob), "head_capsule_radius": round(cap.radius, 4),
                    "body_colliders": body_report}
    mats, backs = [], []
    for sh in hair.shapes:
        m = hair_shader_material(conv, n, sh, a.hair_color, a.opacity_ramp) if a.hair_shader else None
        hair_mat = m is not None
        if m is None:                          # the generic converted material (alpha cutout)
            m = (tint_material(conv, n, sh, a.tint_cutoff, a.hair_color) if skyrimhair.is_tint(sh)
                 else conv._shape_material(n, sh))
        mats.append(m)
        backs.append(back_faces_for(n, sh, hair_mat))
    row["materials"] = mats
    out_name = f"{PREFIX}/hair/{stem.lower()}"
    files = skyrimhair.nif_files(hair, mats, blob, sf_world, out_name, backs)
    for rel, data in files.items():
        p = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    row.update(ok=True, model=out_name.replace("/", "\\") + ".nif")
    row["_fb"] = (hair, mats, blob, out_name, backs)
    if getattr(a, "rigid_copies", False):          # the control: the same wig without physics
        files = skyrimhair.nif_files(skyrimhair.rigid(hair), mats, None, sf_world, out_name + "_rigid", backs)
        for rel, data in files.items():
            p = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(data)
        row["model_rigid"] = out_name.replace("/", "\\") + "_rigid.nif"
        hl, hw = skyrimhair.head_local(skyrimhair.rigid(hair), sf_world)   # second control: the left blade's skin
        files = skyrimhair.nif_files(hl, mats, None, hw, out_name + "_head", backs)
        for rel, data in files.items():
            p = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(data)
        row["model_head"] = out_name.replace("/", "\\") + "_head.nif"
        row["_control"] = (hl, hw, n, out_name, backs)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ks", required=True, nargs="+", help="the KS Hairdos SMP folder(s) (installer or installed)")
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True, help="the mod folder to create (outside the repository)")
    ap.add_argument("--only", help="comma list of wig names (file stems, e.g. Anna,Kikyo); default all")
    ap.add_argument("--cloth-template", help="Starfield NIF / .hkx / '<ba2>:<path>' with a physics hair's cloth")
    ap.add_argument("--content-resources", help="default: <Starfield>/Tools/ContentResources.zip")
    ap.add_argument("--archive2")
    ap.add_argument("--reference-hair",
                    help="'<archive.ba2>:<path of a _facebones.nif in it>': the hair whose hairline and crown height "
                         "the wigs are matched to (default: the cloth template's vanilla hair)")
    ap.add_argument("--hairline-lift", type=float,
                    help="mm to raise the front hairline everywhere (default: up to the vanilla hair's at each angle "
                         "from temple to temple, at most 30; 0 = off)")
    ap.add_argument("--volume", type=float,
                    help="mm to stand the hair off the scalp at the top (default: up to the reference hair's crown "
                         "height, at most 20 with fill layers, 8 without; 0 = off)")
    ap.add_argument("--layers", type=int, default=skyrimhair.LAYERS,
                    help="fill layers under raised hair: the wig stays on the scalp and this many turned copies of "
                         "its top stand between it and the volume (default %(default)s = off: the wig itself moves out; "
                         "3 at 20 mm looked like a choppy shelf)")
    ap.add_argument("--hair-color", type=hair_color, metavar="R,G,B",
                    help="the colour the hair averages to, sRGB 0-255 (e.g. 200,160,90 for blonde): Skyrim tints KS "
                         "wigs with the actor's hair colour, Starfield draws a wig's texture as it is (grey); "
                         "default the texture's own colour")
    ap.add_argument("--opacity-ramp", type=opacity_ramp, default=OPACITY_RAMP, metavar="LO,HI",
                    help="hair shader: alpha LO and below fully clear, HI and above fully solid (0-255): fewer "
                         "half-clear texels, which the shader draws as a flickering checker pattern (default "
                         "%s; 0,255 = KS's alpha as it is)" % ",".join(map(str, OPACITY_RAMP)))
    ap.add_argument("--hair-setting", action="append", default=[], type=hair_setting, metavar="NAME=VALUE",
                    help="override one of the hair shader's settings (BSMaterial::HairSettingsComponent: %s), e.g. "
                         "MaxDepthOffset=0; repeatable" % ", ".join(sorted(cm.HAIR_SETTINGS)))
    ap.add_argument("--head-parts", action="store_true",
                    help="also add every wig as a hairstyle in the looks menu (a hair head part, which takes the "
                         "character's hair colour; leave out --hair-color then)")
    ap.add_argument("--classic-material", dest="hair_shader", action="store_false",
                    help="the generic converted material (alpha cutout) instead of Starfield's hair shader")
    ap.add_argument("--tint-cutoff", type=int, default=128,
                    help="alpha (0-255) below which KS's scalp fade layer ('Hairline') is not drawn: Skyrim blends it, "
                         "a cutout at Skyrim's 10 draws the whole fade as a band down the forehead")
    ap.add_argument("--no-follow-head", dest="follow_head", action="store_false",
                    help="with --skyrim-data: do not move the wig by the difference between Skyrim's and Starfield's "
                         "head shapes (default: it follows Starfield's forehead / brow, then the conform step)")
    ap.add_argument("--follow-sigma", type=float, default=1000 * skyrimhair.FOLLOW_SIGMA,
                    help="mm over which the head-shape difference is averaged: larger = smoother hair, less of the "
                         "face's small shapes (default %(default)s)")
    ap.add_argument("--drape", type=float, default=1000 * skyrimhair.DRAPE_RADIUS,
                    help="mm: hollows in the hair narrower than about this over the temples / forehead are bridged, "
                         "so it runs in one curve from the crown past the brow (default %(default)s; 0 = off)")
    ap.add_argument("--push-blend", type=float, default=1000 * skyrimhair.PUSH_BLEND,
                    help="mm over which the conform step eases its push off around the points it moves, so the hair "
                         "curves over Starfield's forehead instead of bumping (default %(default)s; 0 = per point)")
    ap.add_argument("--no-conform", dest="conform", action="store_false",
                    help="leave the wig where the fit puts it (default: scalp points inside Starfield's female head "
                         "are pushed just outside it)")
    ap.add_argument("--skyrim-data", help="Skyrim SE's Data folder: measure the female head fit (Skyrim female head "
                                          "onto Starfield's) and use it instead of the male constants")
    ap.add_argument("--uniform-fit", action="store_true",
                    help="with --skyrim-data: one scale for the head instead of one per axis (width / depth / height)")
    ap.add_argument("--head-scale", type=float, default=skyrimhair.HEAD_SCALE,
                    help="Skyrim -> Starfield skull size ratio (measured on the male heads: 0.93)")
    ap.add_argument("--head-offset", type=float, nargs=3, default=skyrimhair.HEAD_OFFSET, metavar=("X", "Y", "Z"),
                    help="metres added after scaling, model axes (+Y forward, +Z up)")
    ap.add_argument("--damping", type=float, default=0.6,
                    help="share of the hair's speed lost per second (vanilla hairs: 0.97, a subtle jiggle; lower "
                         "flows more)")
    ap.add_argument("--friction", type=float, default=0.1, help="how much the hair sticks to the body colliders")
    ap.add_argument("--mass-scale", type=float, default=1.0,
                    help="x the SMP masses (heavier: less pushed by wind, more momentum)")
    ap.add_argument("--hair-radius", type=float, default=smpcloth.Settings.radius,
                    help="collision thickness around each hair chain, m (the mesh around the chain must not sink)")
    ap.add_argument("--twist", type=float, default=smpcloth.Settings.twist,
                    help="0-1: how strongly each lock resists turning about its own length (0 = free)")
    ap.add_argument("--no-sheet", dest="sheet", action="store_false",
                    help="leave neighbouring hair chains untied (each strand swings on its own)")
    ap.add_argument("--keep-own-hair", action="store_true",
                    help="keep the actor's own hair under the wig (squashed, as under a hat) instead of hiding it")
    ap.add_argument("--range-scale", type=float, default=1.0, help="how far the hair may swing (x the SMP limits)")
    ap.add_argument("--body-scale", type=float, default=1.0,
                    help="size of the body colliders (neck, chest, waist, hips, thighs, upper arms) the hair rests on; "
                         "0 = head collider only")
    ap.add_argument("--no-rigid-copies", dest="rigid_copies", action="store_false",
                    help="leave out the in-game controls: each wig's no-physics and head-bone copies and the vanilla control hat")
    ap.add_argument("--slot", type=int, help="biped slot bit for the wigs (default: the template hat's)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    staging = os.path.join(out, "_staging")
    shutil.rmtree(staging, ignore_errors=True)
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    for p, what in ((cr, "ContentResources.zip (Creation Kit)"), (esm, "Starfield.esm")):
        if not os.path.isfile(p):
            sys.exit(f"{what} not found: {p}")
    report = {"plugin": PLUGIN, "wigs": []}
    template_blob = read_template(a.cloth_template) if a.cloth_template else find_template(a.starfield, report)
    report.setdefault("cloth_template", a.cloth_template)
    template_root = smpcloth.check_template(template_blob)
    sk = smpcloth.human_skeleton(template_root)
    world = smpcloth.skeleton_world(sk)
    sf_world = {b["name"]: world[i] for i, b in enumerate(sk["bones"])}
    if a.skyrim_data:
        fit = measure_female_fit(a.skyrim_data, a.starfield, sf_world, report, per_axis=not a.uniform_fit)
        if fit is not None and a.head_scale == skyrimhair.HEAD_SCALE and \
                tuple(a.head_offset) == tuple(skyrimhair.HEAD_OFFSET):     # explicit --head-* values win
            a.head_scale, a.head_offset = fit[0], list(fit[1])
            report["head_fit"]["used"] = True
    a.head_surface = a.sky_head = None
    if a.conform:
        head_raw = read_game_file(a.starfield, SF_FEMALE_HEAD)
        got = game_mesh_of(a.starfield, head_raw) if head_raw is not None else None
        if got is not None:
            a.head_surface = (got[0], got[1])
        report["conform"] = "Starfield female head" if got is not None else "head mesh not found: not conformed"
        sky = report.pop("_sky_head", None)
        if got is not None and sky is not None and a.follow_head:   # Skyrim's head where the fit puts it
            head_t = sf_world[skyrimhair.SF_HEAD][:3, 3]
            a.sky_head = (head_t + np.asarray(a.head_offset, float)
                          + np.asarray(a.head_scale, float) * (sky[0] - sky[1][:3, 3]) * skyrimhair.UNIT)
    report.pop("_sky_head", None)
    settings = smpcloth.Settings(damping=a.damping, range_scale=a.range_scale, radius=a.hair_radius,
                                 friction=a.friction, lateral=smpcloth.Settings.lateral if a.sheet else 0.0,
                                 twist=a.twist, mass_scale=a.mass_scale)
    missing = [k for k in a.ks if not os.path.isdir(k)]
    if missing:
        sys.exit(f"--ks folder not found: {', '.join(missing)} (the KS Hairdos SMP folder with '00 Core' and "
                 f"'01 Wigs', or an installed copy with Meshes\\Armor\\KSWigsHDT)")
    src = LooseRoots(a.ks)
    wigs = sorted(k for k in src.index if k.startswith("meshes/") and WIG_GLOB.search(k))
    if a.only:
        keep = {w.strip().lower() for w in a.only.split(",")}
        wigs = [w for w in wigs if os.path.splitext(os.path.basename(w))[0].lower() in keep]
    if not wigs:
        sys.exit("no wig NIF found (meshes/armor/kswigshdt/f/*.nif under --ks)")
    conv = skyrimconvert.SkyrimConverter(src, staging, a.texconv, cr, collision_template=None, prefix=PREFIX)
    conv.hair_settings = dict(a.hair_setting) or None
    if a.hair_setting:
        report["hair_settings"] = dict(a.hair_setting)
    info = sfplugin.header_info(esm)
    sf = sfplugin.records(esm, [b"ARMO", b"ARMA", b"KYWD"])
    kw_names = {fid: sfplugin.edid(s) for t, _h, s, fid in sf if t == b"KYWD"}
    armo_t, arma_t = head_apparel([r for r in sf if r[0] == b"ARMO"], [r for r in sf if r[0] == b"ARMA"], kw_names)
    report["apparel_template"] = {"armo": sfplugin.edid(armo_t[2]), "arma": sfplugin.edid(arma_t[2])}
    fb = facebones_template(a.starfield, arma_model(arma_t), report, report.get("cloth_template"))
    a.vanilla_profile = a.vanilla_crown = None   # the reference hair's hairline / crown: targets of lift and volume
    ref_pts = None
    if a.reference_hair:
        got = reference_hair(a.reference_hair, a.starfield)
        ref_pts = got[0] if got is not None else None
        report["reference_hair"] = a.reference_hair if ref_pts is not None else f"mesh not found: {a.reference_hair}"
    elif fb is not None and len(fb) > 4 and fb[4] is not None:
        ref_pts = fb[4][0]
        report["reference_hair"] = report.get("cloth_template")
    if a.head_surface is not None and ref_pts is not None:
        head = sf_world[skyrimhair.SF_HEAD]
        a.vanilla_profile = skyrimhair.hairline_profile(ref_pts, *a.head_surface, head)
        a.vanilla_crown = skyrimhair.crown_height(ref_pts, head)
        report["vanilla_hair"] = {
            "hairline_above_C_Head_mm_by_angle": {k: None if v is None else round(1000 * v, 1)
                                                  for k, v in a.vanilla_profile.items()},
            "crown_above_C_Head_mm": None if a.vanilla_crown is None else round(1000 * a.vanilla_crown, 1)}
    for w in wigs:
        try:
            report["wigs"].append(build_one(src, conv, w, template_blob, template_root, sf_world, settings, a,
                                            staging))
        except Exception as e:                                   # noqa: BLE001 (one bad wig must not stop the rest)
            report["wigs"].append({"wig": w, "ok": False, "reason": f"{type(e).__name__}: {e}"})
    good = [r for r in report["wigs"] if r["ok"]]
    if not good:
        sys.exit("no wig converted: " + json.dumps(report["wigs"], indent=1))
    for r in good:
        if fb is not None:
            write_files(staging, facebones_files(r, fb, sf_world, a.rigid_copies))
            r["facebones"] = True
    import weapon_test_pack as wtp
    recs = []
    for r in good:
        edid = "S2S_KSWig_" + re.sub(r"[^A-Za-z0-9]+", "_", r["wig"])
        name = f"{r['wig']} wig (Skyrim)"
        aa, ao = wtp.left_blade_records(armo_t, arma_t, len(recs), edid, name, r["model"], slot=a.slot)
        if not a.keep_own_hair:
            aa, ao = hide_hair(aa), hide_hair(ao)
        recs += [aa, ao]
        r.update(editor_id=edid, name=name, form_id_in_plugin=f"{ao[3] & 0xFFFFFF:06X}")
        if r.get("model_rigid"):
            aa2, ao2 = wtp.left_blade_records(armo_t, arma_t, len(recs), edid + "_Rigid",
                                              f"{r['wig']} wig (Skyrim, no physics)", r["model_rigid"], slot=a.slot)
            aa2, ao2 = (aa2, ao2) if a.keep_own_hair else (hide_hair(aa2), hide_hair(ao2))
            recs += [aa2, ao2]
            r["form_id_rigid"] = f"{ao2[3] & 0xFFFFFF:06X}"
        if r.get("model_head"):
            aa3, ao3 = wtp.left_blade_records(armo_t, arma_t, len(recs), edid + "_Head",
                                              f"{r['wig']} wig (Skyrim, head bone)", r["model_head"], slot=a.slot)
            aa3, ao3 = (aa3, ao3) if a.keep_own_hair else (hide_hair(aa3), hide_hair(ao3))
            recs += [aa3, ao3]
            r["form_id_head"] = f"{ao3[3] & 0xFFFFFF:06X}"
    if a.head_parts:                         # the same wigs as looks-menu hairs (the actor's hair colour)
        hdpt_all = sfplugin.records(esm, [b"HDPT", b"FLST"])
        flst = [r for r in hdpt_all if r[0] == b"FLST"]
        tpl = hair_part_template([r for r in hdpt_all if r[0] == b"HDPT"],
                                 os.path.splitext(os.path.basename((report.get("cloth_template") or "")
                                                                   .replace("\\", "/")))[0])
        if tpl is None:
            report["head_parts"] = "no playable vanilla hair head part to copy"
        else:
            report["head_part_template"] = sfplugin.edid(tpl[2])
            for r in good:
                hp = hair_part_record(tpl, len(recs), "S2S_Hair_" + re.sub(r"[^A-Za-z0-9]+", "_", r["wig"]),
                                      f"{r['wig']} (Skyrim)", r["model"])
                recs.append(hp)
                r["head_part"] = {"editor_id": sfplugin.edid(hp[2]), "form_id_in_plugin": f"{hp[3] & 0xFFFFFF:06X}"}
            parts = [r["head_part"] for r in good if r.get("head_part")]
            ids = [rec[3] for rec in recs if rec[0] == b"HDPT"]
            lst = chargen_list_override(flst, CHARGEN_FEMALE, ids)
            if lst is None:
                report["chargen_list"] = f"{CHARGEN_FEMALE} not found in Starfield.esm: looks menu not changed"
            else:
                recs.append(lst)
                kinds = {r[3]: r[0] for r in hdpt_all}
                entries = [struct.unpack_from("<I", bytes(d), 0)[0] for s_, d in lst[2] if s_ == b"LNAM"]
                report["chargen_list"] = {"edid": CHARGEN_FEMALE, "entries": len(entries), "added": len(parts),
                                          "head_parts": sum(kinds.get(e) == b"HDPT" for e in entries),
                                          "lists": sum(kinds.get(e) == b"FLST" for e in entries),
                                          "template_listed": tpl[3] in entries}
    if a.rigid_copies:                       # the record control: the template hat itself under a new name
        ta, ha, sa, _f = armo_t
        ctl = (ta, ha, sfplugin.edit(sa, {b"EDID": sfplugin.zs("S2S_KSWig_ControlHat"),
                                          b"FULL": sfplugin.zs("S2S control hat (vanilla model)")}),
               sfplugin.new_form_id(len(recs)))
        recs.append(ctl)
        report["control_hat"] = f"{ctl[3] & 0xFFFFFF:06X}"
        first = next((r for r in good if r.get("_control")), None)
        if first is not None:                # material / archive controls, on the first wig only
            hat_model = arma_model(arma_t)
            hat_raw = read_game_file(a.starfield, "meshes/" + hat_model) if hat_model else None
            report["controls"] = {"wig": first["wig"], "hat_model": hat_model, "hat_found": hat_raw is not None,
                                  "hat_materials": nif_materials(hat_raw) if hat_raw else []}
            report["controls"]["arma_template"] = subrecord_dump(arma_t)
            report["controls"]["armo_template"] = subrecord_dump(armo_t)
            if hat_model:
                stem = os.path.splitext(os.path.basename(hat_model.replace("\\", "/")))[0]
                report["controls"]["hat_model_files"] = game_files_named(a.starfield, stem)
            names = {"opaque": "solid material", "hatmat": "hat material", "hatcopy": None, "armacopy": None}
            for kind, (files, model) in control_files(first, conv, hat_raw, hat_model, fb, sf_world).items():
                for rel, data in files.items():
                    pth = os.path.join(staging, *rel.split("/"))
                    os.makedirs(os.path.dirname(pth), exist_ok=True)
                    with open(pth, "wb") as fh:
                        fh.write(data)
                label = (f"{first['wig']} wig (Skyrim, {names[kind]})" if names[kind]
                         else "S2S control hat (copied addon, vanilla path)" if kind == "armacopy"
                         else "S2S control hat (from S2SHair archive)")
                aa4, ao4 = wtp.left_blade_records(armo_t, arma_t, len(recs), f"S2S_KSWig_Control_{kind}", label,
                                                  model.replace("/", "\\") + ".nif", slot=a.slot)
                recs += [aa4, ao4]
                report["controls"][kind] = {"name": label, "form_id": f"{ao4[3] & 0xFFFFFF:06X}"}
    for r in report["wigs"]:
        r.pop("_control", None)
        r.pop("_fb", None)
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, info))
    report["packing"] = pack(staging, out, a.starfield, a.archive2)
    report["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
    with open(os.path.join(out, "hair_pack.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    lines = ["S2S Hair: KS Hairdos SMP wigs with their hair physics as Starfield cloth.", "",
             "Enable this mod in MO2. In game, open the console (~) and run:",
             '  help "wig (Skyrim)" 4     - lists the wigs with their FormIDs', "  player.additem <FormID> 1",
             "then equip it like a hat (pick a short hairstyle or bald look under it).", "",
             "Wig               FormID ending   simulated bones"]
    for r in report["wigs"]:
        if r["ok"]:
            lines.append(f"  {r['wig']:<16} ..{r['form_id_in_plugin'][-3:]}          {len(r.get('chain_bones', []))}"
                         + (f"      (no-physics copy ..{r['form_id_rigid'][-3:]})" if r.get("form_id_rigid") else "")
                         + (f" (head-bone copy ..{r['form_id_head'][-3:]})" if r.get("form_id_head") else ""))
        else:
            lines.append(f"  {r['wig']}: not converted ({r.get('reason')})")
    if report.get("control_hat"):
        lines += ["", f"Control: 'S2S control hat (vanilla model)' ..{report['control_hat'][-3:]} is the vanilla hat "
                      "record under a new name (if it does not show either, the head slot itself is hidden)."]
    for kind, c in (report.get("controls") or {}).items():
        if isinstance(c, dict) and "form_id" in c:
            lines.append(f"Control: '{c['name']}' ..{c['form_id'][-3:]}")
    if report.get("head_part_template"):
        lines += ["", "Looks menu: the wigs are also hairstyles named '<wig> (Skyrim)' (copied from the vanilla "
                      f"{report['head_part_template']}); they take the character's hair colour.",
                  "They are added to the vanilla list " + CHARGEN_FEMALE + " (another mod that edits that list "
                  "wins or loses by load order)."]
    if isinstance(report.get("chargen_list"), dict):
        c = report["chargen_list"]
        lines.append(f"  ({c['edid']}: {c['entries']} entries, {c['head_parts']} head parts, {c['lists']} lists; "
                     f"template listed: {c['template_listed']})")
    elif report.get("head_parts"):
        lines += ["", f"Looks menu hairstyles: not added ({report['head_parts']})."]
    lines += ["", f"Record copied from the vanilla head apparel {report['apparel_template']['armo']}.",
              f"Cloth template: {report.get('cloth_template')}"]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    shutil.rmtree(staging, ignore_errors=True)
    print("\n".join(lines))
    print(f"\nreport: {os.path.join(out, 'hair_pack.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
