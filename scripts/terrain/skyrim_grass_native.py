"""Test of Skyrim's grass grown by Starfield's own grass system instead of baked patches (docs/terrain/skyrim-objects.md
"Native grass"). Builds an MO2 mod with S2SGrass.esm:
  * one Starfield Grass (GRAS) per Skyrim grass used on the converted ground: a vanilla GRAS copied, its model the
    converted Skyrim grass model (single instance, as Skyrim's), Skyrim's density / slopes / height and colour range /
    flags written in (fo4sf.sfgrass);
  * one Ground Cover (GCVR) per spare Starfield LTEX the Skyrim terrain overrides (SKYG_..., overlays_params.json
    "ltex_overrides"), listing the grasses of the Skyrim textures painted with it (ltex_mapping.json) and that LTEX;
    textures that fell back to a vanilla Starfield LTEX get no cover (it would grow on vanilla planets);
  * an override of the Skyrim world's biome (--biome, default: the one the terrain build gave the world) adding a
    {mask, LTEX, GCVR} terrain entry per spare LTEX and terrain mask (--biome-masks). The grass survey (2026-10-28)
    found every vanilla ground cover reached through biomes, none through its own texture list, and the planet-trait
    overlay BTDs (overlaytrait*) painting exactly textures their biomes pair with ground cover: the supported route
    for an overlay. Side effect, test only: the planet generator may also paint those Skyrim textures on planets of
    that biome.
Use it with a terrain build staged with --no-grass (make_skyrim_objects.py stage), so only the engine's grass shows.

2026-11-22 (owner: grass as a Starfield grass type, with its fading): the October test added the cover to the
world's land biome (ForestDeciduousLifeJemison) and grew nothing. But Nirn's biome map is ocean everywhere (make_planet
--land-px 0), so the biome under Riverwood is Nirn's ocean biome (NirnOceanNoCoating, our copy of OceanLife04 in the
planet plugin): its slime coat once covered every Riverwood object, i.e. the engine applies the planet's biome at the
spot to the overlay. Supported hypothesis: ground cover comes from that biome too. --biome planet (now the default)
adds the {mask, LTEX, GCVR} entries to that biome (our own record: no vanilla planet changes); the plugin then has the
terrain and planet plugins as masters and must load after them. --control grows one vanilla Jemison ground cover on
every converted Skyrim texture instead (no Skyrim models): grass there and none with Skyrim's points at our models,
none either way at the route. Without ltex_mapping.json (the October staging kept none) the Skyrim -> Starfield
texture mapping is read off the installed terrain (refresh_btd.infer_mapping).

    python -I scripts\\terrain\\skyrim_grass_native.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm"
        --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield>" --terrain <overlay build folder>
        --texconv <texconv.exe> --out "<MO2 mods>\\S2S Grass Native" [--tints <work>\\grass\\grass.json] [--biome <EDID>]
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))
sys.path.insert(0, HERE)

from fo4sf import bsa, grasshook, sfgrass, sfplugin, skyrimconvert, skyrimgrass, skyrimnif  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402

PLUGIN = "S2SGrass.esm"
# --path-variants (2026-11-23): which model paths the grass system accepts. Each variant copies a different vanilla
# grass NIF (so the owner can tell them apart in game) to a different kind of path; grass i takes variant i % 3.
PATH_VARIANTS = (
    ("flowers (hellebore)", "Landscape\\Grass\\grasshelleborefield02.nif", "Landscape\\Grass\\S2S_{stem}.nif"),
    ("moss mounds", "Landscape\\Grass\\GrassMossMounds02.nif", "Landscape\\Grass\\S2S\\{stem}.nif"),
    ("dried primrose", "Landscape\\Grass\\GrassPrimRoseDried01.nif", "Landscape\\Grass\\S2S\\GrassPrimRoseDried01.nif"),
)
PREFIX = "s2s"
VANILLA_OCEAN = 0x07F88A      # OceanLife04: the biome under the overlay when make_planet kept its coating
VANILLA_LAND = 0x1CBD6A       # ForestDeciduousLifeJemison: where --control takes its vanilla ground cover from


def mapping_from_fids(fids, sky_edid, overrides):
    """ltex_mapping.json's "skyrim" form from {Skyrim LTEX: Starfield LTEX} (refresh_btd.infer_mapping): a converted
    slot is named SKYG_<Skyrim EditorID> as the overrides list it, any other (vanilla) LTEX by its hex FormID."""
    slot = {int(o["form_id"]): "SKYG_" + o["skyrim"] for o in overrides}
    return {str(f): {"edid": sky_edid.get(f, f"{f:08X}"), "starfield": slot.get(int(sf), f"{int(sf):08X}")}
            for f, sf in fids.items()}


def location_biome(planet_recs, n_masters=2):
    """The planet plugin's own biome that lies under the overlay: make_planet's <Name>OceanNoCoating (the biome map is
    ocean everywhere), else its only own biome, else None (the vanilla ocean then)."""
    own = [r for r in planet_recs if r[0] == b"BIOM" and r[3] >> 24 == n_masters]
    for r in own:
        if sfplugin.edid(r[2]).lower().endswith("oceannocoating"):
            return r
    return own[0] if len(own) == 1 else None


ALLOW_PROCGEN = 0x08         # WRLD FNAM bit 3 (xEdit wbDefinitionsSF1); no vanilla world sets it (grass survey)


def with_procgen(subs):
    """A WRLD's subrecords with FNAM bit 3 (Allow ProcGen) set; FNAM added after DATA if the world has none."""
    out, done = [], False
    for sig, d in subs:
        d = bytes(d)
        if sig == b"FNAM" and d:
            d = bytes([d[0] | ALLOW_PROCGEN]) + d[1:]
            done = True
        out.append((sig, d))
    if not done:
        at = next((i + 1 for i, (sig, _d) in enumerate(out) if sig == b"DATA"), len(out))
        out.insert(at, (b"FNAM", bytes([ALLOW_PROCGEN])))
    return out


def control_cover(biome_subs):
    """The ground cover a vanilla biome pairs with its textures most often (FormID, 0 if none)."""
    from collections import Counter
    c = Counter(e["gcvr"] for e in sfgrass.biome_terrain(biome_subs) if e["gcvr"])
    return c.most_common(1)[0][0] if c else 0


def pick(recs, sig, rx=None, need=None):
    for t, h, subs, fid in sorted(recs, key=lambda r: sfplugin.edid(r[2])):
        if t != sig:
            continue
        if rx and not re.search(rx, sfplugin.edid(subs), re.I):
            continue
        if need is None or need(subs):
            return (t, h, subs, fid)
    return None


def gras_ok(subs):
    d = dict((s, bytes(v)) for s, v in subs)
    return b"MODL" in d and len(d.get(b"DNAM", b"")) >= sfgrass.DNAM_SIZE


def with_material(nif_bytes: bytes, material_path: str) -> bytes:
    """The NIF with every BSLightingShaderProperty naming material_path and every MaterialID extra data set to its
    CRC (2026-11-23 test: a vanilla grass material, which is in the game's compiled material database, on our
    converted geometry)."""
    from fo4sf import sfnif
    n = nifmod.parse(nif_bytes)
    si = n.string_index(material_path.encode("latin-1"))
    mid = n.string_index(b"MaterialID")
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        if t == "BSLightingShaderProperty":
            n.blocks[i] = struct.pack("<i", si) + b[4:]
        elif t == "NiIntegerExtraData" and struct.unpack_from("<i", b, 0)[0] == mid:
            n.blocks[i] = b[:4] + struct.pack("<I", sfnif.material_id(material_path))
    return nifmod.serialize(n)


MODEL_TYPES = (b"GRAS", b"STAT", b"MSTT", b"FLOR", b"TREE", b"ACTI", b"MISC", b"SCOL", b"PKIN", b"MOVS", b"BNDS")


UNDERWATER_RULES = (2, 3)       # Skyrim GRAS DATA water rule: Below - At Least, Below - At Most (UESP)


def family(edid: str) -> str:
    """A grass's family: its EditorID without the trailing number / variant (TundraGrass04 -> tundragrass,
    SnowGrass01Forest -> snowgrass)."""
    return re.sub(r"\d+[a-z]*$", "", edid.lower())


# 2026-11-23: the grass system refuses our own .mat, so each Skyrim grass family wears the closest of the game's own
# grass materials (grass_model_compare.py --list-materials, owner's list): a working stand-in until Skyrim's textures
# can be used.
FAMILY_MATERIALS = {
    "forestgrass": "Bladed\\GrassFieldLive01", "fieldgrass": "Bladed\\GrassFieldLive01",
    "ferngrass": "Bladed\\GrassFieldLive01", "fallforestgrass": "Bladed\\GrassFieldDried01Yellow",
    "tundragrass": "Bladed\\GrassFieldDried01", "reachgrass": "Bladed\\GrassFieldDried01Red",
    "snowgrass": "Bladed\\GrassFieldDried01Snow", "frozenmarshgrass": "Bladed\\GrassFieldDried01Snow",
    "rockgrasssnow": "Bladed\\GrassFieldDried01Snow", "rockgrass": "Bladed\\GrassFieldDried03",
    "beachgrass": "Bladed\\GrassCostal01", "volcanicgrass": "Bladed\\GrassDesert01",
    "rockgrasswater": "Bladed\\GrassWetlands01", "watercoralgrass": "Aquatic\\GrassSeaweed01",
    "waterkelpgrass": "Aquatic\\GrassEelgrass01",
}
DEFAULT_MATERIAL = "Bladed\\GrassFieldLive01"


def family_material(edid: str, overrides=None) -> str:
    """The game grass material standing in for a Skyrim grass family (--vanilla-material auto); overrides maps a
    family to a material under Materials\\Landscape\\Grass (--family-material forestgrass=Bladed\\GrassCityShort01)."""
    fam = family(edid)
    mat = (overrides or {}).get(fam) or FAMILY_MATERIALS.get(fam, DEFAULT_MATERIAL)
    return "Materials\\Landscape\\Grass\\" + mat + ".mat"


def parse_family_materials(items):
    """--family-material FAMILY=MATERIAL (repeatable; several families may share one item: forestgrass,fieldgrass=...)
    -> {family: material path under Materials\\Landscape\\Grass without .mat}."""
    out = {}
    for it in items or ():
        if "=" not in it:
            raise ValueError(f"--family-material wants FAMILY=MATERIAL, got {it!r}")
        fams, mat = it.split("=", 1)
        mat = mat.strip().replace("/", "\\")
        low = mat.lower()
        for pre in ("materials\\landscape\\grass\\",):
            if low.startswith(pre):
                mat = mat[len(pre):]
        if mat.lower().endswith(".mat"):
            mat = mat[:-4]
        for f in fams.split(","):
            if f.strip():
                out[f.strip().lower()] = mat
    return out


def shared_model(edid: str, placed):
    """For a grass left without a free path (only 12, 2026-11-23): the model of a converted grass of the same family,
    else of the commonest converted grass (placed is in coverage order); None if nothing was converted."""
    fam = family(edid)
    for e, m in placed:
        if family(e) == fam:
            return m
    return placed[0][1] if placed else None


def with_coverage(dnam: bytes, coverage):
    """GRAS DNAM with its coverage (offset 32, f32: the share of the ground the grass covers; the templates have 20)
    set; unchanged when coverage is None. Skyrim has no such field: its grass fills every spot its density allows."""
    if coverage is None:
        return dnam
    b = bytearray(dnam)
    struct.pack_into("<f", b, 32, float(coverage))
    return bytes(b)


def world_cells(skyrim_esm):
    """Skyrim's Tamriel LAND texture weights per cell (landtex.read_world_textures)."""
    from fo4sf import landtex, skyrimland
    cells, _t = landtex.read_world_textures(skyrim_esm, skyrimland.SkyrimLand(skyrim_esm, "Tamriel").land_source, {})
    return cells


def grass_coverage(cells, ltex_grass):
    """{Skyrim GRAS FormID: summed LAND texture weight of the Skyrim textures that grow it} over the given cells: which
    grasses cover the most ground (2026-11-23: only 12 unused vanilla grass paths, so the commonest grasses get them)."""
    per_ltex = {}
    for ws in cells.values():
        for fid, w in ws.items():
            per_ltex[fid] = per_ltex.get(fid, 0.0) + float(w.sum())
    out = {}
    for lt, gs in ltex_grass.items():
        for g in gs:
            out[g] = out.get(g, 0.0) + per_ltex.get(lt, 0.0)
    return out


def norm_model(p: str) -> str:
    """A model path as the archives list it: lower case, backslashes, under meshes\\."""
    p = p.replace("/", "\\").lower().lstrip("\\")
    return p if p.startswith("meshes\\") else "meshes\\" + p


GRASS_DIR = "meshes\\landscape\\grass\\"
CELL_GRASS_SUBDIRS = ("rocks",)       # sCellGrassSubdirectories:Grass default "Rocks," (Starfield.exe 0x1459046d0)


def grass_visible(path: str, subdirs=CELL_GRASS_SUBDIRS) -> bool:
    """Whether the grass system can find a model at this path (docs/re/ground-cover-density.md, 2026-11-24): the
    grass manager copies the file index entries of meshes\\landscape\\grass\\ (exactly that folder, not recursive) and
    of each sCellGrassSubdirectories folder to meshes\\landscape\\cellgrass\\ once at start-up (FUN_140621660 ->
    FUN_1427e19d0), and loads every grass model as meshes\\landscape\\cellgrass\\<path after landscape\\grass\\>
    (FUN_140625d40). So only direct children of landscape\\grass\\ (or of a listed subfolder) are ever found."""
    k = norm_model(path)
    if not k.startswith(GRASS_DIR):
        return False
    rest = k[len(GRASS_DIR):]
    parts = rest.split("\\")
    return len(parts) == 1 or (len(parts) == 2 and parts[0] in subdirs)


def unused_grass_paths(sf_data: str, plugins=None):
    """Grass NIF paths shipped in the game's mesh archives (meshes\\landscape\\grass\\) that no record of the
    game's own plugins names, sorted. 2026-11-23: the grass system loads a model only at a path the game already
    ships (our file over GrassMossMounds04.nif grew; the same file at any new path did not), so our grass models go
    over vanilla grass paths nothing uses: nothing vanilla changes."""
    import glob
    from fo4sf import ba2
    shipped = set()
    for p in sorted(glob.glob(os.path.join(sf_data, "Starfield - Meshes*.ba2"))):
        for n in ba2.Ba2(p).names:
            k = norm_model(n)
            if k.startswith("meshes\\landscape\\grass\\") and k.endswith(".nif"):
                shipped.add(k)
    if plugins is None:
        plugins = [os.path.join(sf_data, f) for f in sorted(os.listdir(sf_data))
                   if f.lower().endswith(".esm") and (f.lower().startswith(("starfield", "sfbgs", "shatteredspace",
                                                                             "constellation", "oldmars",
                                                                             "blueprintships")))]
    used = set()
    for esm in plugins:
        for _t, _h, subs, _fid in sfplugin.records(esm, MODEL_TYPES):
            for sig, d in subs:
                if sig == b"MODL":
                    used.add(norm_model(bytes(d).rstrip(b"\0").decode("latin-1", "replace")))
    # 2026-11-24: only paths the grass system can see (grass_visible); the 6 nested free paths
    # (grass\grasshellebore\...) were handed out first before, so the commonest Skyrim grasses never loaded
    return sorted(p for p in shipped - used if grass_visible(p)), len(shipped), len(used & shipped)


def template_nif(sf_data: str, model: str) -> bytes:
    """A vanilla model's NIF bytes from the game's archives."""
    import glob
    from fo4sf import ba2
    name = "meshes\\" + model.replace("/", "\\").lstrip("\\")
    for p in sorted(glob.glob(os.path.join(sf_data, "Starfield - *.ba2")), reverse=True):
        try:
            arc = ba2.Ba2(p)
        except Exception:                                # noqa: BLE001 (texture archives etc.)
            continue
        if arc.find(name) is not None:
            return arc.read(name)
    raise FileNotFoundError(f"{name} not in the game's archives")


def template_geometry(sf_data: str, model: str):
    """(MeshRef, sphere, box) of a vanilla model's first BSGeometry, read from the game's archives."""
    import glob
    from fo4sf import ba2, sfnif
    name = "meshes\\" + model.replace("/", "\\").lstrip("\\")
    for p in sorted(glob.glob(os.path.join(sf_data, "Starfield - *.ba2")), reverse=True):
        try:
            arc = ba2.Ba2(p)
        except Exception:                                # noqa: BLE001 (texture archives etc.)
            continue
        if arc.find(name) is None:
            continue
        n = nifmod.parse(arc.read(name))
        for i, b in enumerate(n.blocks):
            if n.type_of(i) == "BSGeometry":
                g = sfnif.parse_bsgeometry(b)
                return g.meshes[0], g.sphere, g.box
    raise FileNotFoundError(f"{name} not in the game's archives")


def with_geometry(nif_bytes: bytes, geometry) -> bytes:
    """The NIF with every BSGeometry drawing the given vanilla mesh (2026-11-23 test: our NIF, archive, path and
    records with a vanilla .mesh, to tell our mesh data apart from everything else)."""
    from fo4sf import sfnif
    ref, sphere, box = geometry
    n = nifmod.parse(nif_bytes)
    for i, b in enumerate(n.blocks):
        if n.type_of(i) == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            g.meshes, g.sphere, g.box = [ref, None, None, None], sphere, box
            n.blocks[i] = sfnif.build_bsgeometry(g)
    return nifmod.serialize(n)


def model_info(all_shapes, kept) -> dict:
    """Shape / triangle counts and the height (game units) of a converted grass model: kept shapes against all."""
    zs = [p[2] * sh.scale + sh.translation[2] for sh in kept for p in sh.positions]
    return {"shapes": len(kept), "dropped": len(all_shapes) - len(kept),
            "tris": sum(len(sh.triangles) for sh in kept), "verts": sum(len(sh.positions) for sh in kept),
            "height": (max(zs) - min(zs)) if zs else 0.0}


def info_text(i: dict) -> str:
    return (f"{i['shapes']} shape(s)" + (f" (+{i['dropped']} dropped)" if i.get("dropped") else "")
            + f", {i['tris']} tris, {i['height']:.0f} units tall"
            + (f", {sum(b['cards'] for b in i['blades'])} card(s) cut into "
               f"{sum(b['strips'] for b in i['blades'])} blade strips" if i.get("blades") else ""))


def parse_model_from(items):
    """--model-from FAMILY[,FAMILY]=EditorID -> {family: EditorID whose converted model those families use}."""
    out = {}
    for it in items or ():
        if "=" not in it:
            raise ValueError(f"--model-from wants FAMILY=EditorID, got {it!r}")
        fams, edid = it.split("=", 1)
        for f in fams.split(","):
            if f.strip():
                out[f.strip().lower()] = edid.strip()
    return out


KIND_FIELDS = (b"MNAM", b"QNAM")

# --mask-test (2026-11-23): one easily told apart vanilla grass per biome mask, so one look in game shows which mask
# the engine gives which ground (grass grew on slopes and banks only, never on the flats, in every test so far)
MASK_TEST_GRASSES = ("Hellebore", "Wheat", "MossMounds", "PrimRose", "Sage", "Salt", "CityShort")


def mask_test_grasses(gras_recs, masks):
    """[(mask, GRAS fid, EditorID)]: per mask, the first vanilla GRAS (with a model) whose EditorID contains the next
    MASK_TEST_GRASSES keyword, each keyword used once; masks left over get none. gras_recs: [(fid, subs)]."""
    pool = sorted(((sfplugin.edid(subs), fid) for fid, subs in gras_recs
                   if any(x == b"MODL" for x, _d in subs)), key=lambda t: t[0].lower())
    out, kws = [], list(MASK_TEST_GRASSES)
    for m in masks:
        while kws:
            kw = kws.pop(0).lower()
            hit = next(((e, f) for e, f in pool if kw in e.lower()), None)
            if hit:
                out.append((m, hit[1], hit[0]))
                break
    return out


def ltex_kind_overrides(terrain_ltex, sf_ltex, slots, donor_edid):
    """Overrides of the covered slots' LTEX (as the terrain plugin writes them: its re-skin kept) with the donor
    vanilla LTEX's MNAM (material type) and QNAM. 2026-11-23 (grass_slots.py, owner): every slot whose grass never
    shows re-skins a vanilla rock record (MNAM the rock type, QNAM 1.0); the tundra slots that grow re-skin dirt /
    grass records (QNAM 0). terrain_ltex / sf_ltex: {fid: (header, subs)}; slots: covered slot fids.
    Returns ([(LTEX, header, subs, fid)], [changed fids])."""
    donor = next((subs for _h, subs in sf_ltex.values() if sfplugin.edid(subs).lower() == donor_edid.lower()), None)
    if donor is None:
        raise ValueError(f"--ltex-kind-from: no LTEX {donor_edid!r} in Starfield.esm")
    want = {s: d for s, d in donor if s in KIND_FIELDS}
    out, changed = [], []
    for fid in slots:
        src = terrain_ltex.get(fid)       # only the terrain's re-skin: the vanilla record would undo its look
        if src is None:
            continue
        h, subs = src
        cur = {s: d for s, d in subs if s in KIND_FIELDS}
        if cur == want:
            continue
        drop = [s for s in KIND_FIELDS if s in cur and s not in want]
        out.append((b"LTEX", h, sfplugin.edit(subs, want, drop=drop), fid))
        changed.append(fid)
    return out, changed


VEGETATION_TEMPLATE = "Materials/Landscape/Grass/Bladed/GrassFieldLive01.mat"   # VegetationTranslucent1Layer
BLADE_REF = 96                       # the template's AlphaTestThreshold 0.375 x 255
SLOT_NAMES = {0: "Albedo", 1: "Normal", 2: "Opacity", 3: "Roughness"}
ATLAS_ONLY = {5: "AmbientOcclusion", 8: "Transmissive"}   # the template's atlas maps: wrong layout for Skyrim's UVs


def vegetation_mat(ours: dict, template: dict, name: str, terrain_tint: bool = False) -> dict:
    """Our converted grass material rebuilt on the game's grass material (2026-11-24): the owner's tenth slot-test run
    drew Skyrim's field grass with our own material (PlasticPlainSmooth01 parent, alpha-tested opacity map), but some
    cards showed as solid pale / dark triangles; vanilla grass uses the VegetationTranslucent1Layer shader model
    (wind, translucency, terrain tint). Keeps our albedo / normal / opacity / roughness files, drops the template's
    atlas-only AO and transmissive maps (their constant replacements stay)."""
    from fo4sf import convert_material
    files = {}
    for o in ours.get("Objects", []):
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::MRTextureFile" and c.get("Index") in SLOT_NAMES:
                files[SLOT_NAMES[c["Index"]]] = c["Data"]["FileName"]
    if "Albedo" not in files:
        raise ValueError(f"{name}: our material names no albedo texture")
    mat = convert_material.build_from_template(template, name, files)
    for o in mat["Objects"]:
        o["Components"] = [c for c in o.get("Components", [])
                           if not (c.get("Type") == "BSMaterial::MRTextureFile" and c.get("Index") in ATLAS_ONLY)]
    for o in mat["Objects"]:            # 2026-11-24: dark spots along the blades (owner); the ground under the grass
        for c in o.get("Components", []):   # is mixed in at 0.7 by world position, its specks drawn on the blades
            if c.get("Type") == "BSMaterial::TerrainTintSettingsComponent":
                c.setdefault("Data", {})["Enabled"] = "true" if terrain_tint else "false"
    tex = mat.get("Summary", {}).get("Layer1", {}).get("Textures", {})
    for slot in ATLAS_ONLY.values():
        if slot in tex:
            tex[slot]["File"] = ""
            tex[slot]["UseReplacement"] = True
    return mat


def material_file(staging: str, game_path: str) -> str:
    """The staged file of a material game path (Materials\\..., Data\\Materials\\..., any case), or ''."""
    rel = game_path.replace("\\", "/")
    if rel.lower().startswith("data/"):
        rel = rel[5:]
    for cand in (rel, rel.lower()):
        p = os.path.join(staging, *cand.split("/"))
        if os.path.isfile(p):
            return p
    return ""


def opacity_of(staging: str, game_path: str):
    """The level-0 opacity plane (uint8) of a staged converted material, or None (no cut-out / not found)."""
    from fo4sf import grasscards
    p = material_file(staging, game_path)
    if not p:
        return None
    with open(p, encoding="utf-8-sig") as fh:
        mat = json.load(fh)
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::MRTextureFile" and c.get("Index") == 2:
                q = material_file(staging, c["Data"]["FileName"])
                if q:
                    with open(q, "rb") as fh:
                        return grasscards.opacity_plane(fh.read())
    return None


def with_clamp(mat: dict) -> dict:
    """The material with its UV stream(s) set to clamp texture addressing (BSMaterial::TextureAddressModeComponent
    'Clamp', as 12,997 vanilla material objects have it). 2026-11-24 (owner: pale, disconnected pieces of grass on
    top of clumps): Skyrim's grass cards draw with Texture Clamp Mode CLAMP_S_CLAMP_T (FieldGrass01's
    BSLightingShaderProperty) and their UVs run past the texture (u -0.08..1.17, v -0.17 at the tip); Starfield wraps by
    default, so a card's tip showed the dense base of the clump from the texture's other edge."""
    stream_ids = {c["Data"]["ID"] for o in mat.get("Objects", []) for c in o.get("Components", [])
                  if c.get("Type") == "BSMaterial::UVStreamID" and c.get("Data", {}).get("ID")}
    for o in mat.get("Objects", []):
        if o.get("ID") in stream_ids:
            comps = [c for c in o.get("Components", []) if c.get("Type") != "BSMaterial::TextureAddressModeComponent"]
            comps.append({"Data": {"Value": "Clamp"}, "Index": 0, "Type": "BSMaterial::TextureAddressModeComponent"})
            o["Components"] = comps
    return mat


def clamp_material(staging: str, game_path: str) -> bool:
    """Rewrite a staged converted material with clamp addressing (with_clamp); False if not found."""
    from fo4sf import convert_material
    p = material_file(staging, game_path)
    if not p:
        return False
    with open(p, encoding="utf-8-sig") as fh:
        mat = json.load(fh)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(convert_material.dump_mat(with_clamp(mat)))
    return True


def rebuild_as_vegetation(staging: str, game_path: str, template: dict, terrain_tint: bool = False) -> bool:
    """Rewrite a staged converted material in place as a vegetation (grass shader) material; False if not found."""
    from fo4sf import convert_material
    p = material_file(staging, game_path)
    if not p:
        return False
    with open(p, encoding="utf-8-sig") as fh:
        ours = json.load(fh)
    if any(o.get("Parent", "").lower().endswith("vegetationtranslucent1layer.mat") for o in ours.get("Objects", [])):
        return True                    # already rebuilt (materials are shared between models)
    mat = vegetation_mat(ours, template, os.path.splitext(os.path.basename(p))[0], terrain_tint)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(convert_material.dump_mat(mat))
    return True


def without_vertex_colours(sh):
    """The shape with no vertex colours. 2026-11-24: Skyrim grass keeps its wind sway in the vertex-colour alpha (0 on
    most vertices of FieldGrass01, 0x72..0x8C at the blade tips); vanilla Starfield grass meshes have no vertex colours,
    and our converted field grass stayed invisible on a field where our records grew the vanilla model densely
    (supported hypothesis: the grass shader reads that alpha as opacity)."""
    import dataclasses
    return dataclasses.replace(sh, colors=[])


def convert_model(conv, name: str, tint, staging: str, material: str = "", geometry=None, info=None,
                  keep_colours: bool = False, flat: bool = False, veg_template: dict = None,
                  blades: bool = False, back_faces: bool = True, terrain_tint: bool = False) -> str:
    """The Skyrim grass model as one Starfield static model (materials with Skyrim's tint, back faces when double
    sided, no vertex colours unless keep_colours); returns its path under meshes\\. info: a dict to fill with
    model_info."""
    raw = conv.src.mesh(name)
    if raw is None:
        raise FileNotFoundError("not in the Skyrim archives")
    src = nifmod.parse(raw)
    shapes, mats = [], []
    every = skyrimnif.trishapes(src)
    for sh in every:
        m = conv._shape_material(src, sh, flat_normal_ok=True, albedo_tint=tint)
        if m is None:
            continue
        if blades:                       # 2026-11-24: cards cut into blade strips along their cut-out
            alpha = opacity_of(staging, m)
            if alpha is not None:
                from fo4sf import grasscards
                # strips at the material's own cut (vegetation template 0.375 = 96), not Skyrim's (FieldGrass: 4)
                sh, st = grasscards.blade_shape(sh, alpha, max(int(sh.alpha_ref or 0), BLADE_REF))
                if info is not None:
                    info.setdefault("blades", []).append(st)
        if skyrimnif.double_sided(src, sh.shader_ref) and back_faces:
            sh = skyrimconvert.with_back_faces(sh) or sh
        if not keep_colours:
            sh = without_vertex_colours(sh)
        shapes.append(sh)
        mats.append(m)
    if info is not None:
        info.update(model_info(every, shapes))
    if not shapes:
        raise ValueError("no drawable shape")
    stem = re.sub(r"[^a-z0-9_]+", "_", os.path.splitext(name.lower().replace("\\", "/").split("meshes/", 1)[-1])[0])
    # 2026-11-23: under Landscape/Grass like every vanilla grass model (Starfield.exe names meshes/landscape/grass/)
    out_name = f"landscape/grass/{PREFIX}/{stem}"
    if flat:                         # 2026-11-24: directly in landscape\grass\, where the grass system looks
        out_name = f"landscape/grass/{PREFIX}_{stem.replace('/', '_')}"
    files = skyrimconvert.convert_static_sse(src, shapes, out_name, mats, None, {})
    if material:
        files = {rel: (with_material(d, material) if rel.lower().endswith(".nif") else d) for rel, d in files.items()
                 if not rel.lower().endswith(".mat")}
    else:                            # our own material
        for m in sorted({x for x in mats if x}):
            if veg_template is not None:     # rebuilt on the game's grass shader model
                rebuild_as_vegetation(staging, m, veg_template, terrain_tint)
            clamp_material(staging, m)       # Skyrim's grass textures clamp, Starfield wraps by default
    if geometry is not None:
        files = {rel: (with_geometry(d, geometry) if rel.lower().endswith(".nif") else d) for rel, d in files.items()
                 if not rel.lower().endswith(".mesh")}
    for rel, data in files.items():
        p = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    return out_name.replace("/", "\\") + ".nif"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--terrain", required=True, help="the overlay build folder (overlays_params.json, ltex_mapping.json)")
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--content-resources")
    ap.add_argument("--archive2")
    ap.add_argument("--tints", help="grass.json of a make_skyrim_objects.py grass run: its per-model vertex-colour tints")
    ap.add_argument("--density-scale", type=float, default=1.0, help="Skyrim density (percent) x this = Max Density")
    ap.add_argument("--threshold", type=float, help="GCVR painted-material threshold (default: the template's)")
    ap.add_argument("--biome", default="planet",
                    help="where the covers are listed: 'planet' (default) = the planet plugin's own biome under the "
                         "overlay (Nirn's ocean copy); 'world' = the terrain build's world biome (overlays_params.json "
                         "world_overrides; October's test); an EditorID or hex FormID of a Starfield.esm biome; "
                         "'none' = ground cover records only")
    ap.add_argument("--control", action="store_true",
                    help="control test: every converted Skyrim texture gets the vanilla ground cover the world's land "
                         "biome (Jemison's forest) uses most (vanilla grass models), no Skyrim grass converted")
    ap.add_argument("--biome-masks", default="2,3,4,5",
                    help="terrain masks of the added biome entries: a comma list (0-6: Base, Solid, FlatOuter, "
                         "FlatInner, Talus, Flow, Path) or 'all'; default 2,3,4,5: the Creation Kit wiki's Grass page "
                         "says not to add ground cover to the Solid, Base or Path masks")
    ap.add_argument("--allow-procgen", action="store_true",
                    help="test (2026-11-22, after the planet biome and the vanilla control grew nothing): also set the "
                         "Skyrim world's Allow ProcGen flag (WRLD FNAM bit 3), which no vanilla world sets; the engine "
                         "may then run planet generation (grass, maybe rocks / plants) in the world")
    ap.add_argument("--gras-template", help="EditorID regex of the vanilla GRAS to copy (default: the first grass of the "
                                            "control cover, which grew in game)")
    ap.add_argument("--gcvr-template", help="EditorID regex of the vanilla GCVR to copy (default: the control cover, "
                                            "the one the world's land biome uses most)")
    ap.add_argument("--cover-textures", action="store_true",
                    help="also list the texture in each ground cover's own texture list (LNAM). Off by default since "
                         "2026-11-22: the cover that grows (GC_MossMoundsGrass01) has none, like 95 of 96 vanilla "
                         "covers; the biome entry pairs texture and cover")
    ap.add_argument("--vanilla-material", default="",
                    help="our converted geometry with this game material instead of our own .mat (the grass "
                         "system refuses ours, 2026-11-23), e.g. Materials\\Landscape\\Grass\\Bladed\\GrassCityShort01.mat; 'auto' = the "
                         "closest game grass material per Skyrim grass family (FAMILY_MATERIALS)")
    ap.add_argument("--vanilla-geometry", action="store_true",
                    help="test (2026-11-23): our NIFs (path, archive, records) drawing the template grass's vanilla "
                         ".mesh instead of ours. Grass then = our .mesh data is what the grass system rejects")
    ap.add_argument("--copy-template-nif", action="store_true",
                    help="test (2026-11-23): the template grass's vanilla NIF copied byte for byte to our model paths "
                         "in our archive. Grass then = our NIF bytes differ (header); none = our path / archive")
    ap.add_argument("--loose", action="store_true",
                    help="test (2026-11-23): leave the models, meshes, materials and textures loose in the mod folder "
                         "instead of in S2SGrass - *.ba2")
    ap.add_argument("--drop-modt", action="store_true",
                    help="test (2026-11-23): leave out the template GRAS's MODT (model hashes of the vanilla model) "
                         "from our grass records")
    ap.add_argument("--path-variants", action="store_true",
                    help="test (2026-11-23): three kinds of model path at once, each with a different vanilla grass "
                         "NIF so they can be told apart in game (see PATH_VARIANTS)")
    ap.add_argument("--model-path", default="",
                    help="test (2026-11-23): every grass record names this model path (under meshes\\) and no model "
                         "files are written, e.g. Landscape\\Grass\\GrassMossMounds02.nif: a vanilla model other than "
                         "the template's, from the game's own archives")
    ap.add_argument("--replace-vanilla", default="",
                    help="test (2026-11-23): the template grass's NIF (hellebore flowers) written in our archive OVER "
                         "another vanilla grass model's path, e.g. Landscape\\Grass\\GrassMossMounds04.nif, and named "
                         "by every grass. Flowers = the grass loader reads mod files at known paths; moss mounds = it "
                         "reads only the game's archives")
    ap.add_argument("--vanilla-paths", action="store_true",
                    help="put each converted Skyrim grass model over a grass model path the game ships but none of "
                         "its records names (2026-11-23: the grass system only loads models at paths the game "
                         "already ships)")
    ap.add_argument("--coverage", type=float, default=None,
                    help="GRAS coverage (Creation Kit 'Distribution': share of the area covered, 0-100) for every "
                         "grass; default: the template's (GrassHelleboreField02: 20). 2026-11-23: Skyrim's grass "
                         "fills every spot its density allows, so 100 is the Skyrim-like value")
    ap.add_argument("--keep-template-model", action="store_true",
                    help="test: our GRAS records with the template grass's own (vanilla) model instead of the "
                         "converted Skyrim one, to tell a model problem from a record problem")
    ap.add_argument("--density-maps", type=int, default=None, metavar="VALUE",
                    help="test (2026-11-23): uniform biome-mask density maps (every pixel VALUE) for the terrain's "
                         "BTD in S2SGrass - Main.ba2 (density_maps.py naming; the terrain archive is at its 4 GiB "
                         "limit)")
    ap.add_argument("--mask-test", action="store_true",
                    help="test (2026-11-23): each biome mask (--biome-masks) grows its own vanilla grass on the "
                         "covered slots (MASK_TEST_GRASSES: flowers, wheat, moss, ...), the build prints which; "
                         "use with --only-ltex")
    ap.add_argument("--only-ltex", default="", metavar="EDIDS",
                    help="test (2026-11-23): ground cover only on the slots of these Skyrim textures "
                         "(comma-separated, e.g. LFieldGrass02)")
    ap.add_argument("--slot-first", action="store_true",
                    help="test (2026-11-24, docs/re/ground-cover-density.md route A): instead of appending entries, "
                         "rewrite the biome's own FIRST entry of each --biome-masks mask to {the one --only-ltex "
                         "slot, its cover}. An appended second mask-0 entry did not take the Base slot in game")
    ap.add_argument("--flat-paths", action="store_true",
                    help="put each converted grass model at a NEW path directly in landscape\\grass\\ "
                         "(s2s_<name>.nif) instead of over a free vanilla path: the grass system only sees direct "
                         "children of that folder (2026-11-24, Starfield.exe); whether it sees new files depends on "
                         "them being in the file index when the grass manager starts (test)")
    ap.add_argument("--grass-geometry", choices=("cards", "blades"), default="cards",
                    help="'cards' (default): Skyrim's grass cards as they are. 'blades' (test, 2026-11-24): every "
                         "card cut into strips along its cut-out (fo4sf.grasscards); owner: blades come out "
                         "disconnected and the shape off, so not the default")
    ap.add_argument("--terrain-tint", action="store_true",
                    help="keep the grass shader's terrain tint (the ground's colour mixed into the blades at 0.7 by "
                         "world position). Off by default since 2026-11-24: it drew the ground's specks as dark spots "
                         "on Skyrim's blades, and Skyrim's grass has no such tint")
    ap.add_argument("--no-back-faces", action="store_true",
                    help="test (2026-11-24): no mirrored copy of double-sided Skyrim grass triangles; the game's "
                         "grass material draws both sides already, so each card was two coplanar triangles")
    ap.add_argument("--grass-shader", choices=("vegetation", "plain"), default="vegetation",
                    help="our own grass materials: 'vegetation' (default, 2026-11-24) rebuilds them on the game's "
                         "grass material GrassFieldLive01 (VegetationTranslucent1Layer: wind, translucency, terrain "
                         "tint) with Skyrim's textures; 'plain' keeps the converter's standard material (some cards "
                         "drew as solid triangles in game)")
    ap.add_argument("--keep-vertex-colours", action="store_true",
                    help="keep Skyrim's grass vertex colours (before 2026-11-24 the default); now dropped like vanilla "
                         "grass meshes have none: their alpha (Skyrim's wind weight, 0 on most vertices) may hide the "
                         "blades")
    ap.add_argument("--no-water-clamp", action="store_true",
                    help="test (2026-11-24): our grasses get no water clamps (both FLT_MAX, as the vanilla moss mounds "
                         "that grew across the slot-test field); the hellebore template's above-water clamp 0.5 is "
                         "the one difference left between that control and our grass")
    ap.add_argument("--slot-map", default="", metavar="EDID=MASK,...",
                    help="route A for several textures (2026-11-24, fo4sf.grassslots): each listed Skyrim texture "
                         "gets its cover and is written into the biome's own first LNAM and ANAM of its mask (0..6); "
                         "'default' = DEFAULT_SLOT_MAP (7 land textures). Pair with btd_cover.py slots (same map)")
    ap.add_argument("--palette-hook", action="store_true",
                    help="route B (2026-11-24, needs the S2SGrass SFSE plugin): every grassy converted texture gets "
                         "its own cover, listed in SFSE/Plugins/S2SGrass.ini (fo4sf.grasshook); no biome override. "
                         "Use with the terrain as converted (btd_cover.py slots-restore)")
    ap.add_argument("--keep-underwater", action="store_true",
                    help="with --palette-hook: keep Skyrim's underwater grasses (kelp, coral); dropped by default since "
                         "the overlay has no water (they would grow on dry lake and river beds)")
    ap.add_argument("--slot-alt", action="store_true",
                    help="with --slot-first: also the biome's first ANAM of each mask names that slot's texture "
                         "(2026-11-24: rewriting the LNAM alone left the placeholder drawing pale sand)")
    ap.add_argument("--ltex-kind-from", default="", metavar="EDITORID",
                    help="test (2026-11-23): give every covered slot's LTEX the material type (MNAM) and QNAM of this "
                         "vanilla LTEX (e.g. LDirtCracked02), overriding the terrain's re-skin in S2SGrass.esm; the "
                         "slots whose grass never shows re-skin vanilla rock records")
    ap.add_argument("--ltex-kind-all", action="store_true",
                    help="test (2026-11-24, route B): --ltex-kind-from for EVERY converted texture the terrain plugin "
                         "re-skins, not only the covered ones (owner's Rift squares stay bare where their first layer, "
                         "LFallForestLeaves01, re-skins the lava rock LRockLavaSmooth02; it has no cover of its own)")
    ap.add_argument("--model-from", action="append", default=[], metavar="FAMILY=EDITORID",
                    help="test (2026-11-23): the grasses of these families use the converted model of that grass "
                         "(e.g. fieldgrass,forestgrass,ferngrass=SnowGrass01Forest), to tell a model that does not "
                         "show from ground cover that does not grow; repeatable")
    ap.add_argument("--family-material", action="append", default=[], metavar="FAMILY=MATERIAL",
                    help="with --vanilla-material auto: the game grass material for a Skyrim grass family, under "
                         "Materials\\Landscape\\Grass (e.g. forestgrass,fieldgrass=Bladed\\GrassCityShort01); "
                         "repeatable")
    a = ap.parse_args(argv)
    from fo4sf import grassslots
    slot_map = {}
    if a.slot_map:
        try:
            slot_map = grassslots.parse_slot_map(grassslots.DEFAULT_SLOT_MAP if a.slot_map == "default"
                                                 else a.slot_map)
        except ValueError as e:
            sys.exit(str(e))
        if not a.only_ltex:
            a.only_ltex = ",".join(slot_map)
    try:
        fam_mats = parse_family_materials(a.family_material)
        model_from = parse_model_from(a.model_from)
    except ValueError as e:
        sys.exit(str(e))
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    sf_esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    for p, what in ((sf_esm, "Starfield.esm"), (cr, "ContentResources.zip"), (a.skyrim, "Skyrim.esm"),
                    (os.path.join(a.terrain, "overlays_params.json"), "overlays_params.json")):
        if not os.path.isfile(p):
            sys.exit(f"{what} not found: {p}")
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    overrides = prm.get("ltex_overrides") or []
    if not overrides:
        sys.exit("the terrain build overrides no LTEX (build it with --skyrim-ground): nothing safe to grow grass on")
    mapping_path = os.path.join(a.terrain, "ltex_mapping.json")
    cells = None
    if os.path.isfile(mapping_path):
        with open(mapping_path, encoding="utf-8") as fh:
            mapping = json.load(fh)
    else:
        import refresh_btd
        from fo4sf import landtex, skyrimland
        print("no ltex_mapping.json in the staging: reading which texture the installed terrain draws for each "
              "Skyrim texture ...")
        land = skyrimland.SkyrimLand(a.skyrim, "Tamriel")
        cells, sky_tex = landtex.read_world_textures(a.skyrim, land.land_source, {})
        fids, _support, _outside = refresh_btd.infer_mapping(cells, prm["overlays"], a.terrain)
        mapping = {"skyrim": mapping_from_fids(fids, {f: v.get("edid", "") for f, v in sky_tex.items()}, overrides)}
        print(f"  {len(fids)} Skyrim textures mapped")
    tints = {}
    if a.tints:
        with open(a.tints, encoding="utf-8") as fh:
            tints = {k: tuple(v) for k, v in json.load(fh).get("tints", {}).items()}

    ltex_grass, gras_sky = skyrimgrass.read_grass(a.skyrim)
    from fo4sf import landtex as _lt
    sky_ltex = {fid: v.get("edid", "") for fid, v in _lt.read_ltex_loaded(a.skyrim).items()}   # Skyrim + Update + DLC
    plan = sfgrass.cover_plan(mapping.get("skyrim", {}), overrides, ltex_grass, sky_ltex)
    if a.only_ltex:                                  # test: ground cover on these Skyrim textures' slots only
        keep = {e.strip().lower() for e in a.only_ltex.split(",") if e.strip()}
        sky_of = {int(o["form_id"]): o["skyrim"].lower() for o in overrides}
        plan["slots"] = {k: v for k, v in plan["slots"].items() if sky_of.get(k) in keep}
        print(f"--only-ltex: ground cover on {len(plan['slots'])} slot(s): "
              + ", ".join(f"{k:08X} ({sky_of[k]})" for k in sorted(plan["slots"])))
    if a.palette_hook and slot_map:
        sys.exit("--palette-hook and --slot-map are two routes: pick one")
    if a.palette_hook and not a.keep_underwater:
        def underwater(g):
            r = gras_sky.get(g, {})
            return r.get("water_rule") in UNDERWATER_RULES or "water" in r.get("edid", "").lower()
        plan["slots"], wet = grasshook.drop_underwater(plan["slots"], underwater)
        print(f"--palette-hook: underwater grasses left out; {len(wet)} texture(s) with only those grow nothing")
    report = {"slots": {f"{k:08X}": [gras_sky[g]["edid"] for g in v if g in gras_sky] for k, v in plan["slots"].items()},
              "skipped_textures": plan["skipped"], "grasses": {}, "failed": {}}
    if not plan["slots"] and not a.control:
        sys.exit("no converted ground texture has Skyrim grass: " + json.dumps(plan["skipped"][:10], indent=1))

    sf = sfplugin.records(sf_esm, [b"GRAS", b"GCVR", b"BIOM"])
    masters = ["Starfield.esm"]
    biome = a.biome
    target = None                                     # (type, header, subs, FormID) of the biome to override
    if biome.lower() == "planet":
        mars = (prm.get("mars") or {}).get("plugin")
        planet = os.path.join(a.terrain, mars) if mars else ""
        if not planet or not os.path.isfile(planet):
            sys.exit("the terrain build has no planet plugin (overlays_params.json 'mars'): pass --biome world or a "
                     "biome EditorID")
        masters = ["Starfield.esm", prm["plugin"], mars]
        target = location_biome(sfplugin.records(planet, [b"BIOM"]))
        if target is None:
            target = next((r for r in sf if r[0] == b"BIOM" and r[3] == VANILLA_OCEAN), None)
        if target is None:
            sys.exit(f"no biome under the overlay found in {mars} or Starfield.esm")
    elif biome.lower() == "world":
        biome = (prm.get("world_overrides") or {}).get("biome")
        if not biome:
            sys.exit("the terrain build sets no world biome (overlays_params.json world_overrides): pass --biome "
                     "<EditorID or hex FormID> (Jemison / New Atlantis: 1CBD6A) or --biome none")
    if target is None and biome.lower() != "none":
        want = biome.lower()
        target = next((r for r in sf if r[0] == b"BIOM" and (sfplugin.edid(r[2]).lower() == want
                                                             or f"{r[3]:08x}" == want.zfill(8))), None)
        if target is None:
            sys.exit(f"biome {biome} not in Starfield.esm")
    nm = len(masters)

    os.makedirs(out, exist_ok=True)
    recs, covers, gras_fid = [], [], {}
    staging = os.path.join(out, "_staging")
    conv = None
    if a.control:
        wb = (prm.get("world_overrides") or {}).get("biome") or f"{VANILLA_LAND:08X}"
        src = next((r for r in sf if r[0] == b"BIOM" and (f"{r[3]:08x}" == wb.lower().zfill(8)
                                                          or sfplugin.edid(r[2]).lower() == wb.lower())), None)
        gc = control_cover(src[2]) if src else 0
        if not gc:
            sys.exit(f"control: the world's land biome ({wb}) lists no ground cover")
        covers = [(int(o["form_id"]), gc) for o in overrides]
        if a.only_ltex:                              # 2026-11-24: the slot test's control on the one texture
            covers = [c for c in covers if c[0] in plan["slots"]]
        names = {r[3]: sfplugin.edid(r[2]) for r in sf if r[0] == b"GCVR"}
        report["control"] = {"gcvr": f"{gc:08X}", "edid": names.get(gc, "?"), "textures": len(covers)}
    else:
        # 2026-11-22: the control (vanilla GC_MossMoundsGrass01) grew, ours (templates: the first GRAS by EditorID and
        # the one GCVR with a texture list) did not: the templates' Starfield-only fields (water clamps, coverage,
        # threshold) now come from the cover that is known to grow
        known = None
        if not a.gras_template or not a.gcvr_template:
            wb = (prm.get("world_overrides") or {}).get("biome") or f"{VANILLA_LAND:08X}"
            src = next((r for r in sf if r[0] == b"BIOM" and (f"{r[3]:08x}" == wb.lower().zfill(8)
                                                              or sfplugin.edid(r[2]).lower() == wb.lower())), None)
            kc = control_cover(src[2]) if src else 0
            known = next((r for r in sf if r[0] == b"GCVR" and r[3] == kc), None)
        if a.gcvr_template or known is None:
            ct = pick(sf, b"GCVR", a.gcvr_template, lambda s: any(x == b"LNAM" for x, _d in s))
        else:
            ct = known
        if a.gras_template or known is None:
            gt = pick(sf, b"GRAS", a.gras_template, gras_ok)
        else:
            first = next((g for g, _d in sfgrass.parse_gcvr(known[2])["grasses"]), None)
            gt = next((r for r in sf if r[0] == b"GRAS" and r[3] == first and gras_ok(r[2])), None) \
                or pick(sf, b"GRAS", None, gras_ok)
        if gt is None or ct is None:
            sys.exit("no vanilla GRAS / GCVR template found")
        report["templates"] = {"gras": sfplugin.edid(gt[2]), "gcvr": sfplugin.edid(ct[2]),
                               "gras_dnam": sfgrass.parse_gras_dnam(dict((s, bytes(d)) for s, d in gt[2])[b"DNAM"])}
        geometry = copied = free = None
        if a.vanilla_paths:
            free, n_shipped, n_used = unused_grass_paths(os.path.join(a.starfield, "Data"))
            report["vanilla_path_pool"] = {"shipped": n_shipped, "used_by_records": n_used, "free": len(free)}
            print(f"vanilla grass models: {n_shipped} shipped, {n_used} named by the game's records, {len(free)} free "
                  f"where the grass system looks (directly in landscape\\grass\\ or Rocks\\)")
        if a.copy_template_nif or a.replace_vanilla:
            tmodel = dict((x, bytes(d)) for x, d in gt[2])[b"MODL"].rstrip(b"\0").decode()
            copied = template_nif(os.path.join(a.starfield, "Data"), tmodel)
        if a.vanilla_geometry:
            tmodel = dict((x, bytes(d)) for x, d in gt[2])[b"MODL"].rstrip(b"\0").decode()
            geometry = template_geometry(os.path.join(a.starfield, "Data"), tmodel)
        shutil.rmtree(staging, ignore_errors=True)
        conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(a.skyrim_data), staging, a.texconv, cr, None,
                                             prefix=PREFIX)
        conv.coverage_mips = True            # 2026-11-24: grass cut-outs keep their coverage in every mip (no "fins")
        tdnam = dict((s, bytes(d)) for s, d in gt[2])[b"DNAM"]
        veg_template = None
        if a.grass_shader == "vegetation" and not a.vanilla_material:
            from fo4sf import convert_material
            try:
                veg_template = convert_material.read_template_path(cr, VEGETATION_TEMPLATE)
            except StopIteration:
                print(f"note: {VEGETATION_TEMPLATE} not in {os.path.basename(cr)}: plain grass materials")
            report["grass_shader"] = "vegetation" if veg_template else "plain"
        variants = [template_nif(os.path.join(a.starfield, "Data"), v[1]) for v in PATH_VARIANTS] \
            if a.path_variants else None
        order = lambda g: gras_sky.get(g, {}).get("edid", "")              # noqa: E731
        placed = []                                  # [(Skyrim EditorID, model)] converted at a free path
        if free is not None:                         # the commonest grasses first: they get the few free paths
            if cells is None:
                cells = world_cells(a.skyrim)
            cov = grass_coverage(cells, ltex_grass)
            for gg, rr in gras_sky.items():          # underwater grasses (Skyrim water rule "below", or named so)
                if rr.get("water_rule") in UNDERWATER_RULES or "water" in rr.get("edid", "").lower():
                    cov[gg] = -1.0                   # last: they waste the few free paths on lake beds
            order = lambda g: (-cov.get(g, 0.0), gras_sky.get(g, {}).get("edid", ""))   # noqa: E731
            report["grass_coverage"] = {gras_sky[g]["edid"]: round(cov.get(g, 0.0), 1) for g in gras_sky
                                        if cov.get(g, 0.0) > 0}
        base_order = order                           # --model-from: borrowers after every donor
        order = lambda g: (family(gras_sky.get(g, {}).get("edid", "")) in model_from, base_order(g))  # noqa: E731
        for gi, g in enumerate(sorted({g for v in plan["slots"].values() for g in v}, key=order)):
            r = gras_sky.get(g)
            if r is None:
                continue
            name = "meshes\\" + r["model"].replace("/", "\\").lstrip("\\")
            try:
                if a.model_path:                     # --model-path: every grass names this (game) model, no files
                    model = a.model_path
                elif a.replace_vanilla:              # --replace-vanilla: the template's NIF over a vanilla path
                    model = a.replace_vanilla
                    pth = os.path.join(staging, "meshes", *model.split("\\"))
                    os.makedirs(os.path.dirname(pth), exist_ok=True)
                    with open(pth, "wb") as fh:
                        fh.write(copied)
                elif variants is not None:
                    k = gi % len(PATH_VARIANTS)
                    stem = re.sub(r"[^A-Za-z0-9_]+", "_", os.path.splitext(os.path.basename(
                        r["model"].replace("\\", "/")))[0])
                    model = PATH_VARIANTS[k][2].format(stem=stem)
                    pth = os.path.join(staging, "meshes", *model.split("\\"))
                    os.makedirs(os.path.dirname(pth), exist_ok=True)
                    with open(pth, "wb") as fh:
                        fh.write(variants[k])
                    report.setdefault("path_variants", {}).setdefault(PATH_VARIANTS[k][0], []).append(model)
                elif copied is not None:               # --copy-template-nif: vanilla bytes at our path, in our archive
                    stem = re.sub(r"[^a-z0-9_]+", "_", os.path.splitext(r["model"].lower().replace("\\", "/"))[0])
                    rel = f"meshes/landscape/grass/{PREFIX}/{stem}.nif"
                    pth = os.path.join(staging, *rel.split("/"))
                    os.makedirs(os.path.dirname(pth), exist_ok=True)
                    with open(pth, "wb") as fh:
                        fh.write(copied)
                    model = rel.split("/", 1)[1].replace("/", "\\")
                elif a.keep_template_model:
                    model = dict((x, bytes(d)) for x, d in gt[2])[b"MODL"].rstrip(b"\0").decode()
                elif model_from.get(family(r["edid"])) in dict(placed):
                    donor = model_from[family(r["edid"])]
                    model = dict(placed)[donor]
                    report.setdefault("shared_models", {})[r["edid"]] = model
                    print(f"  {r['edid']} uses {donor}'s model {model} (--model-from)")
                elif free is not None and (not free or any(family(e) == family(r["edid"]) for e, _m in placed)):
                    # --vanilla-paths: one free path per grass family (the family's commonest grass); the rest of
                    # the family, and families without a path, share a converted model
                    model = shared_model(r["edid"], placed)
                    if model is None:
                        raise RuntimeError("no unused vanilla grass path left")
                    report.setdefault("shared_models", {})[r["edid"]] = model
                    print(f"  {r['edid']} shares {model}")
                else:
                    mat = (family_material(r["edid"], fam_mats) if a.vanilla_material == "auto"
                           else a.vanilla_material)
                    minfo = {}
                    model = convert_model(conv, name, tints.get(r["model"]), staging, mat, geometry, minfo,
                                          keep_colours=a.keep_vertex_colours, flat=a.flat_paths,
                                          veg_template=veg_template, blades=a.grass_geometry == "blades",
                                          back_faces=not a.no_back_faces, terrain_tint=a.terrain_tint)
                    report.setdefault("model_info", {})[r["edid"]] = minfo
                    if a.flat_paths:
                        print(f"  {r['edid']} -> meshes\\{model}  {info_text(minfo)}")
                    if mat:
                        report.setdefault("materials", {})[r["edid"]] = mat
                    if free is not None:             # --vanilla-paths: move it over an unused vanilla grass path
                        vpath = free.pop(0)
                        src_p = os.path.join(staging, "meshes", *model.split("\\"))
                        dst_p = os.path.join(staging, *vpath.split("\\"))
                        os.makedirs(os.path.dirname(dst_p), exist_ok=True)
                        shutil.move(src_p, dst_p)
                        report.setdefault("vanilla_paths", {})[r["edid"]] = vpath
                        print(f"  {r['edid']} -> {vpath}" + (f"  [{mat.rsplit(chr(92), 1)[-1]}]" if mat else "")
                              + f"  {info_text(minfo)}")
                        model = vpath.split("\\", 1)[1]
                        placed.append((r["edid"], model))
            except Exception as e:                                   # noqa: BLE001 (reported; that grass is left out)
                report["failed"][r["edid"]] = f"{type(e).__name__}: {e}"
                continue
            fid = sfplugin.new_form_id(len(recs), nm)
            # MODT: Mutagen's "TextureFileHashes"; the template's describes the template's model, not ours (2026-11-23:
            # the vanilla NIF at our path grew nothing, at its own path with the same MODT it grows)
            dnam = with_coverage(sfgrass.gras_dnam_from_skyrim(tdnam, r, a.density_scale), a.coverage)
            if a.no_water_clamp:
                dnam = sfgrass.without_water_clamps(dnam)
            subs = sfplugin.edit(gt[2], {b"EDID": sfplugin.zs("S2S_" + r["edid"]), b"MODL": sfplugin.zs(model),
                                         b"DNAM": dnam},
                                 drop=[b"MODT"] if (a.drop_modt and not a.keep_template_model) else [])
            recs.append((b"GRAS", gt[1], subs, fid))
            gras_fid[g] = fid
            report["grasses"][r["edid"]] = {"form_id": f"{fid:08X}", "model": model,
                                            "skyrim": {k: r[k] for k in ("density", "min_slope", "max_slope",
                                                                         "height_range", "colour_range", "flags")}}
        for slot, gs in sorted(plan["slots"].items()):
            lst = [(gras_fid[g], -1) for g in gs if g in gras_fid]
            if not lst:
                continue
            fid = sfplugin.new_form_id(len(recs), nm)
            subs = sfgrass.build_gcvr(ct[2], sfplugin.zs(f"S2S_Cover_{slot:08X}"), lst,
                                      [slot] if a.cover_textures else [], a.threshold)
            recs.append((b"GCVR", ct[1], subs, fid))
            covers.append((slot, fid))
    report["covers"] = [{"ltex": f"{s:08X}", "gcvr": f"{c:08X}"} for s, c in covers]
    masks = list(range(7)) if a.biome_masks == "all" else [int(x) for x in a.biome_masks.split(",") if x.strip()]
    if a.ltex_kind_from:
        terr_p = os.path.join(a.terrain, prm.get("plugin", "")) if prm.get("plugin") else ""
        terrain_ltex = {}
        if terr_p and os.path.isfile(terr_p):
            for _t, h, subs, fid in sfplugin.records(terr_p, [b"LTEX"]):
                if fid >> 24 == 0:                   # overrides of Starfield.esm records (its first master)
                    terrain_ltex[fid] = (h, subs)
        sf_ltex = {fid: (h, subs) for _t, h, subs, fid in sfplugin.records(sf_esm, [b"LTEX"])}
        try:
            targets = sorted(terrain_ltex) if a.ltex_kind_all else [sl for sl, _c in covers]
            kind_recs, changed = ltex_kind_overrides(terrain_ltex, sf_ltex, targets, a.ltex_kind_from)
        except ValueError as e:
            sys.exit(str(e))
        recs += kind_recs
        report["ltex_kind_from"] = {"donor": a.ltex_kind_from, "slots": [f"{f:08X}" for f in changed],
                                    "from_terrain_plugin": sum(1 for f in changed if f in terrain_ltex)}
        print(f"LTEX kind: {len(changed)} {'converted texture(s)' if a.ltex_kind_all else 'covered slot(s)'} take {a.ltex_kind_from}'s material type / QNAM, "
              f"their re-skin copied from {os.path.basename(terr_p)}")
        if not changed:
            print(f"  (no slot changed: terrain plugin {terr_p or '?'} not found or no re-skin there)")
    if a.palette_hook:                    # route B: the S2SGrass plugin gives each texture its cover; biome untouched
        target = None
    if slot_map and target is not None:   # route A, every slot (fo4sf.grassslots): the biome's own entries
        sky_name = {int(o["form_id"]): o["skyrim"].lower() for o in overrides}
        subs = target[2]
        placed_slots = {}
        for slot_fid, gc in covers:
            m = slot_map.get(sky_name.get(slot_fid, ""))
            if m is None:
                continue
            subs = sfgrass.biome_with_slot(subs, m, slot_fid, gc, alt=True)
            placed_slots[str(m)] = {"skyrim": sky_name[slot_fid], "ltex": f"{slot_fid:08X}", "gcvr": f"{gc:08X}"}
            print(f"  mask {m} ({grassslots.SLOT_NAMES[m]}): {sky_name[slot_fid]} {slot_fid:08X}, cover {gc:08X}")
        recs.append((b"BIOM", target[1], subs, target[3]))
        report["biome"] = {"edid": sfplugin.edid(target[2]), "form_id": f"{target[3]:08X}", "slots": placed_slots,
                           "entries_added": 0}
        missing = sorted(set(slot_map) - {v["skyrim"] for v in placed_slots.values()})
        if missing:
            print(f"  no cover for: {', '.join(missing)} (no grass, or a vanilla Starfield texture)")
    elif a.slot_first and target is not None:
        slots = sorted({s for s, _c in covers})
        if len(slots) != 1:
            sys.exit(f"--slot-first needs exactly one covered texture (--only-ltex), got {len(slots)}")
        subs = target[2]
        for m in masks:
            subs = sfgrass.biome_with_slot(subs, m, slots[0], covers[0][1], alt=a.slot_alt)
        recs.append((b"BIOM", target[1], subs, target[3]))
        report["biome"] = {"edid": sfplugin.edid(target[2]), "form_id": f"{target[3]:08X}", "masks": masks,
                           "entries_added": 0, "slot_first": {"ltex": f"{slots[0]:08X}", "gcvr": f"{covers[0][1]:08X}"}}
        print(f"--slot-first: the biome's own first entry of mask(s) {', '.join(map(str, masks))} = "
              f"{{{slots[0]:08X}, {covers[0][1]:08X}}}" + (" (and its first ANAM's texture)" if a.slot_alt else ""))
    elif a.mask_test and target is not None:
        picks = mask_test_grasses([(r[3], r[2]) for r in sf if r[0] == b"GRAS"], masks)
        entries = []
        print("mask test (biome mask -> vanilla grass grown there on the covered slots):")
        for m, gfid, gname in picks:
            fid = sfplugin.new_form_id(len(recs), nm)
            recs.append((b"GCVR", ct[1], sfgrass.build_gcvr(ct[2], sfplugin.zs(f"S2S_MaskTest{m}"), [(gfid, -1)],
                                                             [], a.threshold), fid))
            entries += [(m, slot, fid) for slot, _c in covers]
            print(f"  mask {m}: {gname} ({gfid:08X})")
        recs.append((b"BIOM", target[1], sfgrass.biome_with_entries(target[2], entries), target[3]))
        report["mask_test"] = {str(m): name for m, _g, name in picks}
        report["biome"] = {"edid": sfplugin.edid(target[2]), "form_id": f"{target[3]:08X}", "masks": masks,
                           "entries_added": len(entries)}
    elif target is not None:
        recs.append((b"BIOM", target[1], sfgrass.biome_with_cover(target[2], covers, masks=masks), target[3]))
        report["biome"] = {"edid": sfplugin.edid(target[2]), "form_id": f"{target[3]:08X}", "masks": masks,
                           "entries_added": len(covers) * len(masks)}
    if a.allow_procgen:
        world = prm["overlays"][0]["world"] if prm.get("overlays") else None
        terr = os.path.join(a.terrain, prm.get("plugin", ""))
        w = next((r for r in sfplugin.records(terr, [b"WRLD"]) if sfplugin.edid(r[2]) == world), None) \
            if world and os.path.isfile(terr) else None
        if w is None:
            sys.exit(f"--allow-procgen: world {world} not found in {terr}")
        if prm.get("plugin") not in masters:
            sys.exit("--allow-procgen needs --biome planet (the terrain plugin as a master)")
        recs.append((b"WRLD", w[1], with_procgen(w[2]), w[3]))
        report["allow_procgen"] = {"world": world, "form_id": f"{w[3]:08X}"}
    report["masters"] = masters
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, sfplugin.header_info(sf_esm), author="Skyrim2Starfield grass", masters=masters))
    ini_path = os.path.join(out, *grasshook.INI_DIR, grasshook.INI_NAME)
    if a.palette_hook:
        os.makedirs(os.path.dirname(ini_path), exist_ok=True)
        sky_of = {int(o["form_id"]): o["skyrim"] for o in overrides}
        with open(ini_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(grasshook.hook_ini(covers, masters, PLUGIN, sky_of))
        report["palette_hook"] = {"ini": os.path.relpath(ini_path, out), "covers": len(covers)}
        print(f"S2SGrass.ini: {len(covers)} ground textures with their own cover (needs S2SGrass.dll)")
    elif os.path.exists(ini_path):
        os.remove(ini_path)                       # a route A build: no stale hook list
    if a.density_maps is not None and conv is not None:
        import density_maps
        for stem, btd_path, rels in density_maps.targets(a.terrain):
            cx, cy = density_maps.btd_cells(btd_path)
            data = density_maps.uniform_bc4_dds(cx * density_maps.PX_PER_CELL, cy * density_maps.PX_PER_CELL,
                                                a.density_maps)
            for rel in rels:
                pth = os.path.join(staging, *rel.split("/")[1:])            # drop "Data/"
                os.makedirs(os.path.dirname(pth), exist_ok=True)
                with open(pth, "wb") as fh:
                    fh.write(data)
            report["density_maps"] = {"value": a.density_maps, "cells": [cx, cy], "files": [r[5:] for r in rels]}
            print(f"density maps: {len(rels)} uniform {a.density_maps} maps for {stem} ({cx} x {cy} cells) "
                  f"in {os.path.splitext(PLUGIN)[0]} - Main.ba2")
    if conv is not None:
        import hair_pack
        base = os.path.splitext(PLUGIN)[0]
        for old_dir in ("meshes", "geometries", "materials", "textures"):       # no stale loose files from a
            shutil.rmtree(os.path.join(out, old_dir), ignore_errors=True)       # --loose build win over archives
        if a.loose:                          # 2026-11-23 test: loose files, no archives (MO2 serves them)
            for old_ba2 in (f"{base} - Main.ba2", f"{base} - Textures.ba2"):
                if os.path.exists(os.path.join(out, old_ba2)):
                    os.remove(os.path.join(out, old_ba2))
            report["packing"] = hair_pack.pack(staging, out, a.starfield, "<none>", f"{base} - Main.ba2",
                                               f"{base} - Textures.ba2")
        else:
            report["packing"] = hair_pack.pack(staging, out, a.starfield, a.archive2, f"{base} - Main.ba2",
                                               f"{base} - Textures.ba2", general_textures=("terrain",))
        report["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
        shutil.rmtree(staging, ignore_errors=True)
    if not os.path.isfile(mapping_path):
        with open(os.path.join(out, "ltex_mapping_inferred.json"), "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, indent=1)
    with open(os.path.join(out, "grass_native.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    if "templates" in report:
        print(f"templates: grass {report['templates']['gras']}, cover {report['templates']['gcvr']}"
              + (" (vanilla model kept)" if a.keep_template_model else "")
              + (f" (our geometry, vanilla material {a.vanilla_material})" if a.vanilla_material else "")
              + (" (our NIFs, the template's vanilla .mesh)" if a.vanilla_geometry else "")
              + (" (the template's NIF copied to our paths)" if a.copy_template_nif else ""))
    print((f"control: vanilla ground cover {report['control']['edid']} on {len(covers)} converted textures"
           if a.control else f"{len(gras_fid)} grasses, {len(covers)} ground covers")
          + (f", biome {report['biome']['edid']} ({report['biome']['form_id']}) overridden "
             f"({report['biome']['entries_added']} entries)" if target is not None else ", no biome override")
          + f"; {len(plan['skipped'])} grassy Skyrim textures skipped (vanilla Starfield ground), "
            f"{len(report['failed'])} models failed")
    if a.allow_procgen:
        print(f"world {report['allow_procgen']['world']} ({report['allow_procgen']['form_id']}): Allow ProcGen set")
    if a.model_path:
        print(f"  every grass names {a.model_path}")
    if a.replace_vanilla:
        print(f"  every grass names {a.replace_vanilla}, which our archive replaces with the template's NIF")
    for label, paths in (report.get("path_variants") or {}).items():
        print(f"  {label}: {len(paths)} grasses at paths like {paths[0]}")
    if report.get("packing"):
        print("files: " + (f"loose ({', '.join(report['packing']['loose'])})" if "loose" in report["packing"]
                           else ", ".join(report["packing"].get("archives", []))))
    if len(masters) > 1:
        print(f"masters: {', '.join(masters)}: load {PLUGIN} after them")
    print(f"report: {os.path.join(out, 'grass_native.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
