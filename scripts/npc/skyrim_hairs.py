"""Every Skyrim hairstyle as a Starfield looks-menu hairstyle (owner 2026-11-03: "export all of Skyrim's hairs").

On the owner's PC, in one run:
  1. reads the hair head parts (HDPT type 3; with --facial-hair also beards, type 4) of Skyrim.esm and the official
     masters after it (Update, Dawnguard, HearthFires, Dragonborn: later ones override), leaving out the beast races'
     (Khajiit / Argonian) and extra parts (each part's extra parts, e.g. its hairline, are merged into it);
  2. converts each with the KS wig pipeline (scripts/armor/hair_pack.py, fo4sf.skyrimhair): placed on Starfield's head
     of the part's sex by the measured head fit, shaped (follow the skull difference, cards outward, hairline / volume
     to the vanilla hair's, temple hollow bridged, pushed out of the head, stacked cards apart, tangents along +U),
     Starfield's hair shader (crisp strands, per-strand ID, KS-style painted bands evened) with no colour baked in:
     the character's hair colour applies, as verified on the KS hairstyles 2026-11-03; no physics (vanilla Skyrim hair
     has none); the <model>_facebones.nif twin with the head's share on the face bones;
  3. writes one head part per hairstyle into S2SSkyrimHairs.esm, copied from a vanilla hairstyle of that sex's looks
     menu list, and overrides the vanilla lists HeadPartsChargenOptionsFemale / Male with them appended (another mod
     that edits those lists wins or loses by load order);
  4. packs "S2SSkyrimHairs - Main.ba2" / "- Textures.ba2" (Archive2) or leaves the files loose.

    python -I scripts\\npc\\skyrim_hairs.py --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield folder>"
        --texconv "<texconv.exe>" --out "<MO2 mods>\\S2S Skyrim Hairs" [--only Nord01,Serana] [--facial-hair]

The shaping / material options are hair_pack's (--drape, --layer-gap, --no-strands, --classic-material, ...).
Read-only on both games' files.
"""
import argparse
import copy
import json
import os
import re
import shutil
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, HERE)

from fo4sf import bsa, fo4land, hairstrands, sfplugin, skyrimconvert  # noqa: E402
from fo4sf import skyrimhair, skyrimnif, skyrimnpc, smpcloth  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
import hair_pack  # noqa: E402

PLUGIN = "S2SSkyrimHairs.esm"
MAIN_BA2 = "S2SSkyrimHairs - Main.ba2"
TEX_BA2 = "S2SSkyrimHairs - Textures.ba2"
OUT_DIR = "s2s/skyrimhair"
SKYRIM_PLUGINS = ("Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm")
HAIR, FACIAL_HAIR = 3, 4
# KS-tuned steps that hurt a vanilla Skyrim hair (one thin shell over its own hairline layer): the hairline lift
# (KS starts low; vanilla's matches its own scalp layer), the volume and the temple bridge (they lift the shell off the
# scalp layer: a gap), a wide conform blend (a deep spot lifts the whole neighbourhood) and wide card spacing
# (2026-11-03: owner saw the Skyrim hairstyles float off the skull with a gap, "flat")
# geometric_normals: the stored Skyrim normals do not follow the shaping (2026-11-03, dark / light patches)
# hairline_drop / skyrim_cutout (2026-11-03): the hair started 12-23 mm above Starfield's hairline (a bare band) and
# the hair Skyrim alpha-tested solid was half see-through. tessellate / blend_coverage (2026-11-03, owner's
# diagnose rounds + report): the vanilla hairs are low-poly shells
# (a faceted helmet with broad flat light patches) and their hairline layers were alpha-blended (cut into strands
# they read as a pale band of thin hair between the forehead and the hair)
VANILLA_DEFAULTS = dict(hairline_lift=0.0, volume=0.0, drape=0.0, push_blend=15.0, layer_gap=0.3,
                        geometric_normals=True, tessellate=3, blend_coverage=3.0, hairline_drop=20.0,
                        skyrim_cutout=True, vanilla_maps=True)
# The hair shader's depth offset off (IDG's 0.01 m with our flat mid-grey depth map moves every hair pixel's depth
# by about 5 mm; the vanilla Skyrim shells lie 2.5-4 mm over Starfield's skin at the front and sides, 0-2 mm at a
# parting: the skin then wins the depth test. 2026-11-03, owner: "every time strands meet in the middle they go into
# the skull", the bare band at the front). --hair-setting MaxDepthOffset=0.01 puts it back.
VANILLA_HAIR_SETTINGS = {"MaxDepthOffset": "0"}
# --diagnose: extra looks-menu copies of each hairstyle, each with one suspect of the dark / light patches removed
# (round 1, owner 2026-11-03: flat colour / no see-through / shell normals all kept the same patches: neither the
# texture, the gaps nor the normals. Round 2: the strand direction and the light through the hair)
# Round 3 (owner 2026-11-03: the parts of the hair differ in colour, brightest where they overlap / face up; the
# hair sits on the scalp instead of growing from it): Skyrim's blended layers (hairlines) with their soft alpha kept
# (a soft fade at the roots, dithered by the shader, instead of cut strands) and a rougher hair shader (a softer,
# wider highlight: the near-white sheen on the top piece)
# Round 4 (owner 2026-11-03: round 3's soft / rough copies looked exactly like the normal one; strands dip into the
# skull where they meet in the middle): the depth offset back at IDG's value next to the new default of none, which
# also shows whether the material's shader settings take effect in game at all (no settings-only copy has differed
# so far: transmission, roughness, and earlier MaxDepthOffset on the KS wigs)
DIAGNOSE = (("depth", "old depth offset"),)
# --strand-cards (owner 2026-11-03: "do we need it to have all the strands like Starfield's" - yes): a looks-menu
# copy of each hairstyle made of Starfield-style strand cards on a vanilla hair material (fo4sf.hairstrands)
STRANDS = (("strands", "Starfield strands"), ("strandsthin", "Starfield strands, thin"),
           ("strandsline", "Starfield strands, thin, Skyrim hairline"))
# round 3 (owner 2026-11-04: with the Skyrim hair kept under the cards "it just looks like the originals again"):
# the cards alone, denser (5 layers, 5 mm apart, 18 mm wide, up to 3500), next to the same over the Skyrim hair
DENSE_CARDS = dict(layers=5, spacing=0.005, width=0.018, gap=0.0015, max_cards=3500, step=0.010)
# round 7 (owner 2026-11-05: the cards are choppy, blocky light / dark patches the size of a card, worst on light
# hair; neither copy has a good hairline): 18 mm cards 5 mm apart overlap about 3.6 times within a layer at nearly the
# same depth, so neighbouring cards cross each other and show their different strips in card-sized blocks
# (hypothesis). [strandsthin]: 7 mm cards (1.4 overlap) at three fixed depths per layer. [strandsline]: the same over
# Skyrim's own hairline layers (the alpha-blended shapes: Skyrim draws its hairline with them, a soft fade into the
# scalp) instead of card roots ending on the forehead. [strands] stays as it was, to compare.
THIN_CARDS = dict(DENSE_CARDS, width=0.007, slots=3)
# the material most of IDG's hairs use (22 of 50, read from its NIFs 2026-11-03): straight strands (the bob's
# Medium_Hair_Shared made every card wavy, owner's first strand-card shots)
STRAND_MATERIAL = "Materials\\Actors\\Human\\Hair\\Long_Straight_Hair_Shared.mat"


def strand_material(starfield: str, texconv: str, cr_zip: str, mat_path: str, report: dict):
    """(the material path for the NIFs, its texture's strand strips) of a vanilla hair material, or None: the .mat
    from ContentResources.zip, its opacity map from the game's archives (decoded with texconv), its strips
    (hairstrands.strip_layout)."""
    import hair_probe
    rep = report.setdefault("strand_material", {"path": mat_path})
    mat = hair_probe.read_material(cr_zip, mat_path)
    if mat is None:
        rep["error"] = "not in ContentResources.zip"
        return None
    info = hair_probe.material_info(mat)
    op = info["textures"].get("Opacity")
    rep["opacity"] = op
    dds = hair_pack.read_game_file(starfield, re.sub(r"^data[\\/]", "", op or "", flags=re.I).replace("\\", "/")) \
        if op else None
    if dds is None:
        rep["error"] = "its opacity map is not in the game's archives"
        return None
    px = hair_probe.decode_rgba(dds, texconv)
    strips = hairstrands.strip_layout(px[:, :, 0])
    rep["strips"] = len(strips)
    return mat_path, strips, hairstrands.strip_coverage(px[:, :, 0], strips)
NO_TRANSMISSION = {"DiffuseTransmissionScale": "0", "IndirectSpecularTransmissionScale": "0"}
SETTING_VARIANTS = {"notrans": NO_TRANSMISSION, "rough": {"Roughness": "0.85"}, "depth": {"MaxDepthOffset": "0.01"}}
FLAG_PLAYABLE, FLAG_MALE, FLAG_FEMALE, FLAG_EXTRA = 0x01, 0x02, 0x04, 0x08     # Skyrim HDPT DATA (xEdit TES5)
BEAST = re.compile(r"khajiit|argonian", re.I)
CHARGEN = {True: "HeadPartsChargenOptionsFemale", False: "HeadPartsChargenOptionsMale"}


def plugin_masters(path: str):
    """The plugin's master file names (TES4 MAST), lower case."""
    with fo4land.Plugin(path) as p:
        return [fo4land.zstring(bytes(d)).lower() for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0))
                if s == b"MAST"]


def resolve(fid: int, plugin: str, masters) -> tuple:
    """(plugin, object id) of a FormID as written in `plugin` (its high byte indexes the masters, then itself)."""
    i = fid >> 24
    return (masters[i] if i < len(masters) else plugin.lower(), fid & 0xFFFFFF)


def load_parts(skyrim_data: str, plugins=SKYRIM_PLUGINS):
    """({key: head part}, {key: form list EditorID}) of the given plugins present in the Data folder, later plugins
    overriding earlier ones; FormIDs (the part's own, its extra parts', its race list) resolved to keys
    (plugin, object id) so parts of different plugins can refer to each other."""
    parts, lists = {}, {}
    for name in plugins:
        path = os.path.join(skyrim_data, name)
        if not os.path.isfile(path):
            continue
        masters = plugin_masters(path)
        for t, _h, subs, fid in sfplugin.records(path, [b"HDPT", b"FLST"]):
            key = resolve(fid, name, masters)
            if t == b"FLST":
                lists[key] = sfplugin.edid(subs)
                continue
            p = skyrimnpc.parse_head_part(subs, fid)
            p["key"] = key
            p["plugin"] = name
            p["extra_parts"] = [resolve(x, name, masters) for x in p["extra_parts"]]
            p["races"] = resolve(p["races"], name, masters) if p["races"] is not None else None
            parts[key] = p
    return parts, lists


def part_models(key, parts, seen=None):
    """The part's model and its extra parts' (followed), in order."""
    seen = set() if seen is None else seen
    if key in seen or key not in parts:
        return []
    seen.add(key)
    p = parts[key]
    out = [p["model"]] if p.get("model") else []
    for x in p["extra_parts"]:
        out += part_models(x, parts, seen)
    return out


def wanted(p, lists, kinds=(HAIR,), playable_only=False) -> bool:
    """A part to export: of the wanted kinds, not an extra part, with a model, not for the beast races."""
    if p["type"] not in kinds or p["flags"] & FLAG_EXTRA or not p.get("model"):
        return False
    if playable_only and not p["flags"] & FLAG_PLAYABLE:
        return False
    race_list = lists.get(p["races"], "") if p["races"] is not None else ""
    return not (BEAST.search(race_list) or BEAST.search(p["model"]) or BEAST.search(p["edid"]))


def is_female(p) -> bool:
    """Female when flagged female, or flagged neither and not male-sounding; beards are male."""
    if p["type"] == FACIAL_HAIR:
        return False
    if p["flags"] & FLAG_FEMALE:
        return True
    if p["flags"] & FLAG_MALE:
        return False
    return not re.search(r"(^|[^e])male", p["edid"], re.I)


def list_entries_from(plugin_path: str, edid: str, masters_out) -> list:
    """The entries (LNAM) of `plugin_path`'s record of the form list `edid` (an override of a vanilla list), as
    FormIDs in a plugin whose masters are `masters_out` (file names; entries of a plugin not among them dropped)."""
    names = [m.lower() for m in masters_out]
    own = os.path.basename(plugin_path).lower()
    mx = plugin_masters(plugin_path)
    out = []
    for _t, _h, subs, _f in sfplugin.records(plugin_path, [b"FLST"]):
        if sfplugin.edid(subs) != edid:
            continue
        for s, d in subs:
            if s != b"LNAM" or len(d) < 4:
                continue
            fid = struct.unpack_from("<I", bytes(d), 0)[0]
            i = fid >> 24
            name = mx[i] if i < len(mx) else own
            if name in names:
                out.append((names.index(name) << 24) | (fid & 0xFFFFFF))
    return out


def chargen_template(sf_hdpt, flst, female: bool, kind: int, prefer: str = ""):
    """A vanilla head part of `kind` from that sex's looks-menu list to copy (the one whose model names `prefer`
    first), or None."""
    lst = next((r for r in flst if sfplugin.edid(r[2]) == CHARGEN[female]), None)
    ids = [struct.unpack_from("<I", bytes(d), 0)[0] for s, d in (lst[2] if lst else []) if s == b"LNAM" and len(d) >= 4]
    cands = [sf_hdpt[i] for i in ids if i in sf_hdpt and part_type(sf_hdpt[i]) == kind]
    model = lambda r: next((bytes(x).rstrip(b"\0").decode("latin-1") for s, x in r[2] if s == b"MODL"), "")  # noqa
    want = prefer.lower()
    return next((r for r in cands if want and want in model(r).lower()), cands[0] if cands else None)


def extra_parts(rec, sf_hdpt) -> list:
    """The extra parts (HNAM) of a vanilla head part: [{form_id, edid, type, model}] (report; the vanilla Skyrim
    hairstyles keep them, 2026-11-03: Starfield's own hairline under the low-poly Skyrim hair)."""
    out = []
    for s, d in rec[2]:
        if s != b"HNAM" or len(d) < 4:
            continue
        fid = struct.unpack_from("<I", bytes(d), 0)[0]
        r = sf_hdpt.get(fid)
        out.append({"form_id": f"{fid:08X}", "edid": sfplugin.edid(r[2]) if r else None,
                    "type": part_type(r) if r else None, "model": record_model(r) if r else None})
    return out


def part_type(rec):
    d = next((bytes(x) for s, x in rec[2] if s == b"PNAM" and len(x) >= 4), None)
    return struct.unpack_from("<I", d, 0)[0] if d else None


def record_model(rec) -> str:
    return next((bytes(x).rstrip(b"\0").decode("latin-1") for s, x in rec[2] if s == b"MODL"), "")


def settings_variant(conv, material, suffix: str, settings: dict):
    """A copy of a hair material (written in conv's staging) with other hair shader settings and its own name, on
    the same texture files: '<material>_<suffix>.mat'. 2026-11-03: the 'rough' / 'no light through' copies had
    re-converted every texture under a new name (the owner's --diagnose run took over an hour)."""
    from fo4sf import convert_material as cm
    if not material or not material.lower().endswith(".mat"):
        return material
    out = material[:-4] + "_" + suffix + ".mat"
    cache = conv.__dict__.setdefault("_settings_variants", {})
    if out in cache:
        return cache[out]
    src = os.path.join(conv.staging, *material.split("\\"))
    try:
        with open(src, encoding="utf-8") as fh:
            mat = json.load(fh)
    except OSError:
        cache[out] = material
        return material
    slot = {i: k for k, i in cm.HAIR_SLOTS.items()}
    files, base = {}, {}
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::MRTextureFile" and c.get("Index") in slot:
                files[slot[c["Index"]]] = c["Data"]["FileName"]
            elif c.get("Type") == "BSMaterial::HairSettingsComponent":
                base = dict(c.get("Data", {}))
    if not files.get("Albedo") or not files.get("Opacity"):     # not one of our hair materials: kept as is
        cache[out] = material
        return material
    name = "S2SHair_" + re.sub(r"[^a-z0-9]+", "_", os.path.splitext(os.path.basename(out.replace("\\", "/")))[0]
                                                    .lower())
    new = cm.build_hair_mat(name, files, dict(base, **settings))
    dst = os.path.join(conv.staging, *out.split("\\"))
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(cm.dump_mat(new))
    cache[out] = out
    return out


BLEND_SOLID = 0.5          # a Skyrim-blended layer counts as hair where its alpha is at least this


def hairline_shapes(nifs, hair) -> list:
    """Indices of the shapes Skyrim alpha-blends (its hairline layers: the soft fade where the hair meets the scalp,
    drawn over the alpha-tested hair)."""
    out = []
    for i, (n, sh) in enumerate(zip(nifs, hair.shapes)):
        if sh.alpha_ref >= 0 and skyrimnif.alpha_test(n, sh.alpha_ref)[1]:
            out.append(i)
    return out


def skyrim_coverage(conv, n, sh):
    """Per vertex how much of the shape's Skyrim texture is hair there (0-1): its alpha at the vertex's UV, ramped
    around Skyrim's alpha-test threshold for shapes Skyrim alpha-tested (pipeline.cutout_alpha's ramp); None when
    the texture cannot be read. Cached per texture on the converter."""
    try:
        import hair_probe
        if sh.shader_ref < 0 or not sh.uvs:
            return None
        paths = skyrimnif.texture_set(n, sh.shader_ref)
        if not paths or not paths[0]:
            return None
        cache = conv.__dict__.setdefault("_alpha_cache", {})
        key = paths[0].lower()
        if key not in cache:
            dds = conv.src.texture(paths[0])
            cache[key] = None if dds is None else hair_probe.decode_rgba(dds, conv.texconv)[:, :, 3].copy()
        a = cache[key]
        if a is None:
            return None
        from fo4sf import pipeline
        alpha = pipeline.sample_texels(a, np.asarray(sh.uvs, float)).astype(float)
        test, blend, ref = skyrimnif.alpha_test(n, sh.alpha_ref) if sh.alpha_ref >= 0 else (False, False, 128)
        if test and not blend:
            return np.clip((alpha - (ref - 24.0)) / 48.0, 0.0, 1.0)
        # Skyrim's blended layers (the hairlines) fade out down the forehead: only their solid part counts, so the
        # guide's smoothed coverage does not carry cards onto the faded part (2026-11-05: a fringe down to the brows
        # on a style without one)
        a = alpha / 255.0
        return np.where(a >= BLEND_SOLID, a, 0.0)
    except Exception:                                      # noqa: BLE001 (no coverage: every vertex counts)
        return None


def fit_report(placed, hair, ctx, sf_world) -> dict:
    """How the hair sits, by region (skyrimhair.fit_gaps): the Skyrim hair on Skyrim's head where the head fit puts
    both ('skyrim': what it should look like), the result on Starfield's head ('starfield'); and the result's
    hairline against the vanilla Starfield hair's (mm, + = ours higher: bare forehead between), when known. Owner
    2026-11-03: the vanilla hairstyles do not sit / flow from the scalp like in Skyrim."""
    head = sf_world[skyrimhair.SF_HEAD]
    out = {}
    if getattr(ctx, "sky_head", None) is not None:
        out["skyrim"] = skyrimhair.fit_gaps(skyrimhair.hair_points(placed), ctx.sky_head, head)
    if getattr(ctx, "head_surface", None) is not None:
        pts = skyrimhair.hair_points(hair)
        out["starfield"] = skyrimhair.fit_gaps(pts, ctx.head_surface[0], head)
        if getattr(ctx, "vanilla_profile", None):
            own = skyrimhair.hairline_profile(pts, *ctx.head_surface, head)
            out["hairline_vs_vanilla_mm"] = {
                k: None if own.get(k) is None or v is None else round(1000 * (own[k] - v), 1)
                for k, v in ctx.vanilla_profile.items()}
    return out


def shape_alpha(n, sh, conv, material) -> dict:
    """How a shape was drawn in Skyrim (alpha blend / test and threshold) and its opacity before / after the strand
    cut (the converter's record), for the report."""
    out = {}
    try:
        if sh.alpha_ref >= 0:
            test, blend, ref = skyrimnif.alpha_test(n, sh.alpha_ref)
            out["skyrim_alpha"] = {"blend": blend, "test": test, "threshold": ref}
    except Exception:                                      # noqa: BLE001 (report only)
        pass
    cov = conv.hair_coverage_of(material) if hasattr(conv, "hair_coverage_of") else None
    if cov:
        out["opacity"] = cov
    return out


def build_part(p, models, sky, conv, sf_world, ctx, fb, staging, spread=True, out_name=None, tint=None,
               variant=None, strands=None) -> dict:
    """Convert one head part (its models merged), shape it for ctx's head, write its NIF and _facebones twin into
    staging (as out_name, default s2s/skyrimhair/<edid>). tint: a Skyrim hair colour (0-1 RGB) multiplied into the
    albedo (an NPC's own; the looks-menu hairstyles have none). variant: a diagnostic copy ('flat' / 'solid':
    texture variants, 'shell': normals pointing away from the head, 'combed': strand directions smoothed across
    cards, 'notrans': no light through the hair, 'soft': Skyrim's blended layers keep their soft alpha, 'rough': a
    rougher hair shader). Returns its report row (ok, model, ...)."""
    row = {"skyrim": p["edid"], "plugin": p.get("plugin"), "models": models, "ok": False, "skipped": []}
    key = (p["edid"], tuple(models))
    last = ctx.__dict__.get("_shaped_last")
    if last is not None and last[0] == key:          # a diagnostic copy: the same shape as the hairstyle's own
        hair, nifs, done = last[1], last[2], last[3]
        row.update(copy.deepcopy(done))
    else:
        hairs, nifs = [], []
        for m in models:
            rel = "meshes\\" + re.sub(r"^meshes[\\/]", "", m.replace("/", "\\"), flags=re.I)
            raw = sky.mesh(rel) if hasattr(sky, "mesh") else sky._read(bsa.norm(rel))
            if raw is None:
                row["skipped"].append(f"{m}: not in the archives")
                continue
            try:
                n = nifmod.parse(raw)
                h = skyrimhair.convert(raw, None, sf_world, ctx.head_scale, tuple(ctx.head_offset))
            except (skyrimhair.HairError, nifmod.NifError, ValueError) as e:
                row["skipped"].append(f"{m}: {e}")
                continue
            if ctx.hair_shader:                          # one copy of a two-pass shape (before the materials)
                h, _dropped = skyrimhair.drop_duplicate_shapes(h)
            # 2026-11-03: the strand direction comes from each texture region (strand_orientation, after the
            # materials), not from the mesh: the whole-shape guess (strands_down) left cards cut across their strands
            hairs.append(h)
            nifs += [n] * len(h.shapes)
        if not hairs:
            row["reason"] = "no model converted"
            return row
        hair = skyrimhair.merge(hairs)
        if getattr(ctx, "tessellate", 1) > 1:            # low-poly shells rounded (before the shaping works on them)
            hair, row["tessellated"] = skyrimhair.tessellate(hair, ctx.tessellate)
        placed = hair
        hair = hair_pack.shape_hair(hair, ctx, sf_world, row, drop=False)
        row["fit"] = fit_report(placed, hair, ctx, sf_world)
        ctx.__dict__["_shaped_last"] = (key, hair, nifs, copy.deepcopy({k: v for k, v in row.items()
                                                                         if k not in ("skyrim", "plugin", "models",
                                                                                      "ok")}))
    if variant == "shell":
        hair, row["shell_normals"] = skyrimhair.shell_normals(hair, sf_world[skyrimhair.SF_HEAD])
        hair, row["tangents"] = skyrimhair.uv_tangents(hair)
    look = variant if variant in ("flat", "solid", "soft") else None
    mats, backs = hair_pack.hair_materials(conv, nifs, hair, ctx, tint=tint, orient=bool(ctx.hair_shader), look=look)
    across = [skyrimhair.strands_across(sh, conv.hair_orientation_of(m) if hasattr(conv, "hair_orientation_of")
                                        else None) for sh, m in zip(hair.shapes, mats)]
    if variant in SETTING_VARIANTS:                  # the same textures, only the shader settings differ
        mats = [settings_variant(conv, m, variant, SETTING_VARIANTS[variant]) for m in mats]
    if any(x.any() for x in across):                 # cards whose strands run along U: lit along them
        hair, row["tangents"] = skyrimhair.uv_tangents(hair, along_v=across)
    if variant == "combed":
        hair, row["combed"] = skyrimhair.comb_strands(hair)
    row["shape_detail"] = [dict({"name": (sh.name or b"").decode("latin-1"), "vertices": len(sh.positions),
                                 "across_share": round(float(x.mean()), 2) if len(x) else 0.0, "material": m},
                                **shape_alpha(n, sh, conv, m))
                           for sh, x, m, n in zip(hair.shapes, across, mats, nifs)]
    if any(m is None for m in mats):
        row["reason"] = "a shape has no material"
        return row
    if variant in ("strands", "strandsbase", "strandsthin", "strandsline"):   # Starfield-style cards over the
        #                                            shaped Skyrim hair
        if not strands:
            row["reason"] = "no strand material / strips (see the report's strand_material)"
            return row
        dirs = [hairstrands.uv_strand_dirs(sh, x) for sh, x in zip(hair.shapes, across)]
        cover = [skyrim_coverage(conv, n, sh) for n, sh in zip(nifs, hair.shapes)]
        cards, row["strand_cards"] = hairstrands.grow_cards(hair, sf_world[skyrimhair.SF_HEAD], strands[1],
                                                            dirs=dirs, coverage=cover,
                                                            densities=strands[2] if len(strands) > 2 else None,
                                                            head_pts=(ctx.head_surface[0]
                                                                      if getattr(ctx, "head_surface", None)
                                                                      is not None else None),
                                                            **(DENSE_CARDS if variant in ("strands", "strandsbase")
                                                               else THIN_CARDS))
        if not cards.shapes:
            row["reason"] = "no strand cards grown"
            return row
        cards, _t = skyrimhair.uv_tangents(cards)
        if variant == "strandsbase":                 # the converted Skyrim hair under the cards
            hair = skyrimhair.Hair(list(hair.shapes) + list(cards.shapes), hair.bones, hair.host_of_root,
                                   hair.report)
            mats = list(mats) + [strands[0]] * len(cards.shapes)
            backs = list(backs) + [False] * len(cards.shapes)
        elif variant == "strandsline":               # Skyrim's hairline layers under the cards
            keep = hairline_shapes(nifs, hair)
            row["skyrim_hairline_shapes"] = len(keep)
            hair = skyrimhair.Hair([hair.shapes[i] for i in keep] + list(cards.shapes), hair.bones,
                                   hair.host_of_root, hair.report)
            mats = [mats[i] for i in keep] + [strands[0]] * len(cards.shapes)
            backs = [backs[i] for i in keep] + [False] * len(cards.shapes)
        else:                                        # the cards alone
            hair = cards
            mats, backs = [strands[0]] * len(cards.shapes), [False] * len(cards.shapes)
    out_name = out_name or f"{OUT_DIR}/{p['edid'].lower()}"
    hair_pack.write_files(staging, skyrimhair.nif_files(hair, mats, None, sf_world, out_name, backs))
    row["_fb"] = (hair, mats, None, out_name, backs)
    if fb is not None:
        hair_pack.write_files(staging, hair_pack.facebones_files(row, fb, sf_world, False, spread))
        row["facebones"] = True
    row.pop("_fb", None)
    row.update(ok=True, model=out_name.replace("/", "\\") + ".nif", shapes=len(hair.shapes),
               vertices=int(sum(len(s.positions) for s in hair.shapes)), materials=mats)
    return row


def sex_context(a, sf_world, report, female: bool, template, starfield: str):
    """(settings namespace with that sex's head context, facebones template) for converting parts of one sex."""
    ctx = copy.copy(a)
    rep = report.setdefault("heads", {}).setdefault("female" if female else "male", {})
    hair_pack.setup_head(ctx, sf_world, rep, female=female)
    fb = None
    if template is not None:
        model = record_model(template)
        fb = hair_pack.facebones_template(starfield, model, rep, "x:meshes/" + model.replace("\\", "/"))
    hair_pack.setup_reference(ctx, sf_world, rep, fb[4][0] if fb is not None and fb[4] is not None else None)
    return ctx, fb


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True, help="the mod folder to create (outside the repository)")
    ap.add_argument("--only", help="comma list of text the head parts' EditorIDs must contain (e.g. Nord01,Serana)")
    ap.add_argument("--facial-hair", action="store_true", help="also the beards (the men's looks-menu list)")
    ap.add_argument("--playable-only", action="store_true",
                    help="only the parts Skyrim's own character creation offers (default: every human / elf hair, "
                         "NPC-only ones too)")
    ap.add_argument("--merge-plugin", action="append", default=[],
                    help="another plugin that adds to the looks-menu lists (e.g. ...\\S2S Hair\\S2SHair.esm): its "
                         "entries are kept in ours, so both show (it becomes a master: load it first). Default: "
                         "S2SHair.esm in the 'S2S Hair' mod folder next to --out, when there")
    ap.add_argument("--no-starfield-hairline", dest="starfield_hairline", action="store_false",
                    help="leave out the copied vanilla hairstyle's extra parts (HNAM: Starfield's own hairline / scalp "
                         "pieces, kept by default under the Skyrim hair; the report lists them)")
    ap.add_argument("--strand-cards", action="store_true",
                    help="also, per hairstyle, a looks-menu copy '(Skyrim, Starfield strands)': Starfield-style strand "
                         "cards grown over it on a vanilla hair material (--strand-material)")
    ap.add_argument("--strand-material", default=STRAND_MATERIAL,
                    help="the vanilla hair material the strand cards use (default: the bob's, %(default)s)")
    ap.add_argument("--diagnose", action="store_true",
                    help="also, per hairstyle, looks-menu copies each without one suspect of the dark / light patches: "
                         + ", ".join(f"'(Skyrim, {label})'" for _k, label in DIAGNOSE) + " (use with --only)")
    ap.add_argument("--cloth-template", help="as hair_pack: the vanilla hair whose skeleton / face bones are used")
    ap.add_argument("--content-resources", help="default: <Starfield>/Tools/ContentResources.zip")
    ap.add_argument("--archive2")
    hair_pack.add_shape_args(ap)
    ap.set_defaults(**VANILLA_DEFAULTS)
    a = ap.parse_args(argv)
    if not a.skyrim_data:
        sys.exit("--skyrim-data is required")
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
    report = {"plugin": PLUGIN, "parts": []}

    parts, lists = load_parts(a.skyrim_data)
    kinds = (HAIR, FACIAL_HAIR) if a.facial_hair else (HAIR,)
    chosen = sorted((p for p in parts.values() if wanted(p, lists, kinds, a.playable_only)), key=lambda p: p["edid"])
    if a.only:
        keys = [k.strip().lower() for k in a.only.split(",") if k.strip()]
        chosen = [p for p in chosen if any(k in p["edid"].lower() for k in keys)]
    report["skyrim_parts"] = {"read": len(parts), "chosen": len(chosen)}
    if not chosen:
        sys.exit("no Skyrim hair head part chosen")

    template_blob = (hair_pack.read_template(a.cloth_template) if a.cloth_template
                     else hair_pack.find_template(a.starfield, report))
    report.setdefault("cloth_template", a.cloth_template)
    sk = smpcloth.human_skeleton(smpcloth.check_template(template_blob))
    world = smpcloth.skeleton_world(sk)
    sf_world = {b["name"]: world[i] for i, b in enumerate(sk["bones"])}
    sf_recs = sfplugin.records(esm, [b"HDPT", b"FLST"])
    sf_hdpt = {r[3]: r for r in sf_recs if r[0] == b"HDPT"}
    flst = [r for r in sf_recs if r[0] == b"FLST"]
    stem = os.path.splitext(os.path.basename((report.get("cloth_template") or "").replace("\\", "/")))[0]

    sky = bsa.SkyrimArchives(a.skyrim_data)
    conv = skyrimconvert.SkyrimConverter(sky, staging, a.texconv, cr, collision_template=None,
                                         prefix=hair_pack.PREFIX)
    conv.hair_settings = dict(VANILLA_HAIR_SETTINGS, **dict(a.hair_setting)) or None
    merge = [os.path.abspath(m) for m in a.merge_plugin]
    sibling = os.path.join(os.path.dirname(out), "S2S Hair", "S2SHair.esm")
    if not merge and os.path.isfile(sibling):
        merge = [sibling]
    masters = ["Starfield.esm"] + [os.path.basename(m) for m in merge]
    report["masters"] = masters
    recs, added = [], {True: [], False: []}
    contexts = {}
    strands = (strand_material(a.starfield, a.texconv, cr, a.strand_material, report) if a.strand_cards else None)
    for p in chosen:
        female = is_female(p)
        tpl = chargen_template(sf_hdpt, flst, female, p["type"], stem if female else stem.replace("_f", "_m"))
        if tpl is None:
            report["parts"].append({"skyrim": p["edid"], "ok": False,
                                    "reason": f"no vanilla {'female' if female else 'male'} head part of type "
                                              f"{p['type']} in {CHARGEN[female]} to copy"})
            continue
        if (female, p["type"]) not in contexts:
            contexts[(female, p["type"])] = sex_context(a, sf_world, report, female, tpl, a.starfield)
            report.setdefault("templates", {})[f"{'female' if female else 'male'} type {p['type']}"] = \
                sfplugin.edid(tpl[2])
            report.setdefault("template_extra_parts", {})[sfplugin.edid(tpl[2])] = extra_parts(tpl, sf_hdpt)
        ctx, fb = contexts[(female, p["type"])]
        extra = (DIAGNOSE if a.diagnose else ()) + (STRANDS if a.strand_cards else ())
        for variant, label in ((None, None),) + extra:
            try:
                row = build_part(p, part_models(p["key"], parts), sky, conv, sf_world, ctx, fb, staging,
                                 a.spread_face_bones, variant=variant,
                                 out_name=f"{OUT_DIR}/{p['edid'].lower()}_{variant}" if variant else None,
                                 strands=strands)
            except Exception as e:                               # noqa: BLE001 (one bad part must not stop the rest)
                row = {"skyrim": p["edid"], "ok": False, "reason": f"{type(e).__name__}: {e}"}
            row["female"] = female
            if variant:
                row["variant"] = variant
            if row.get("ok"):
                edid = "S2S_" + p["edid"] + (f"_{variant}" if variant else "")
                rec = hair_pack.hair_part_record(tpl, len(recs), edid,
                                                 f"{p['edid']} (Skyrim{', ' + label if label else ''})",
                                                 row["model"], masters=len(masters),
                                                 keep_extra_parts=a.starfield_hairline)
                recs.append(rec)
                added[female].append(rec[3])
                row["form_id_in_plugin"] = f"{rec[3] & 0xFFFFFF:06X}"
            report["parts"].append(row)
    good = [r for r in report["parts"] if r.get("ok")]
    if not good:
        sys.exit("no hair converted: " + json.dumps(report["parts"][:5], indent=1, default=str))
    for female, ids in added.items():
        kept = [x for m in merge for x in list_entries_from(m, CHARGEN[female], masters)]
        if not ids and not kept:
            continue
        lst = hair_pack.chargen_list_override(flst, CHARGEN[female], kept + ids)
        if lst is None:
            report.setdefault("chargen_lists", {})[CHARGEN[female]] = "not found in Starfield.esm"
            continue
        recs.append(lst)
        report.setdefault("chargen_lists", {})[CHARGEN[female]] = {"added": len(ids), "kept_from_other_plugins":
                                                                  len([x for x in kept if x >> 24 > 0])}
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, sfplugin.header_info(esm), masters=tuple(masters)))
    report["packing"] = hair_pack.pack(staging, out, a.starfield, a.archive2, MAIN_BA2, TEX_BA2)
    report["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
    with open(os.path.join(out, "skyrim_hairs.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    bad = [r for r in report["parts"] if not r.get("ok")]
    lines = [f"S2S Skyrim Hairs: {len(good)} Skyrim hairstyles for Starfield's looks menu "
             f"({sum(1 for r in good if r['female'])} women's, {sum(1 for r in good if not r['female'])} men's).", "",
             "Enable the mod in MO2 (S2SSkyrimHairs.esm after any other mod that edits the looks-menu lists; with",
             "S2S Hair next to it, S2SHair.esm is its master and its hairstyles are kept: load S2SHair.esm first), then",
             "open the looks menu (console: slm 14) and pick '<Skyrim EditorID> (Skyrim)' from the hair list.",
             "The character's hair colour applies."]
    for female in (True, False):        # the looks menu shows no names: its order, after the vanilla / other mods'
        names = [r["skyrim"] + (f" [{r['variant']}]" if r.get("variant") else "") for r in good
                 if r["female"] == female]
        if names:
            lines += ["", f"{'Women' if female else 'Men'}'s hairstyles in looks-menu order (after the vanilla ones "
                          "and S2S Hair's):"] + [f"  {k + 1:3d}. {n}" for k, n in enumerate(names)]
    if bad:
        lines += ["", f"Not converted ({len(bad)}):"] + [f"  {r['skyrim']}: {r.get('reason')}" for r in bad[:40]]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    shutil.rmtree(staging, ignore_errors=True)
    print("\n".join(lines))
    print(f"\nreport: {os.path.join(out, 'skyrim_hairs.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
