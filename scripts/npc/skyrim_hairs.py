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

from fo4sf import bsa, fo4land, sfplugin, skyrimconvert, skyrimhair, skyrimnif, skyrimnpc, smpcloth  # noqa: E402
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
VANILLA_DEFAULTS = dict(hairline_lift=0.0, volume=0.0, drape=0.0, push_blend=15.0, layer_gap=0.3,
                        geometric_normals=True)
# --diagnose: extra looks-menu copies of each hairstyle, each with one suspect of the dark / light patches removed
DIAGNOSE = (("flat", "flat colour"), ("solid", "no see-through"), ("shell", "shell normals"))
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


def part_type(rec):
    d = next((bytes(x) for s, x in rec[2] if s == b"PNAM" and len(x) >= 4), None)
    return struct.unpack_from("<I", d, 0)[0] if d else None


def record_model(rec) -> str:
    return next((bytes(x).rstrip(b"\0").decode("latin-1") for s, x in rec[2] if s == b"MODL"), "")


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
               variant=None) -> dict:
    """Convert one head part (its models merged), shape it for ctx's head, write its NIF and _facebones twin into
    staging (as out_name, default s2s/skyrimhair/<edid>). tint: a Skyrim hair colour (0-1 RGB) multiplied into the
    albedo (an NPC's own; the looks-menu hairstyles have none). variant: one of DIAGNOSE ('flat' / 'solid':
    texture variants, 'shell': normals pointing away from the head). Returns its report row (ok, model, ...)."""
    row = {"skyrim": p["edid"], "plugin": p.get("plugin"), "models": models, "ok": False, "skipped": []}
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
    placed = hair
    hair = hair_pack.shape_hair(hair, ctx, sf_world, row, drop=False)
    row["fit"] = fit_report(placed, hair, ctx, sf_world)
    if variant == "shell":
        hair, row["shell_normals"] = skyrimhair.shell_normals(hair, sf_world[skyrimhair.SF_HEAD])
        hair, row["tangents"] = skyrimhair.uv_tangents(hair)
    look = variant if variant in ("flat", "solid") else None
    mats, backs = hair_pack.hair_materials(conv, nifs, hair, ctx, tint=tint, orient=bool(ctx.hair_shader), look=look)
    across = [skyrimhair.strands_across(sh, conv.hair_orientation_of(m) if hasattr(conv, "hair_orientation_of")
                                        else None) for sh, m in zip(hair.shapes, mats)]
    if any(x.any() for x in across):                 # cards whose strands run along U: lit along them
        hair, row["tangents"] = skyrimhair.uv_tangents(hair, along_v=across)
    row["shape_detail"] = [dict({"name": (sh.name or b"").decode("latin-1"), "vertices": len(sh.positions),
                                 "across_share": round(float(x.mean()), 2) if len(x) else 0.0, "material": m},
                                **shape_alpha(n, sh, conv, m))
                           for sh, x, m, n in zip(hair.shapes, across, mats, nifs)]
    if any(m is None for m in mats):
        row["reason"] = "a shape has no material"
        return row
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
    conv.hair_settings = dict(a.hair_setting) or None
    merge = [os.path.abspath(m) for m in a.merge_plugin]
    sibling = os.path.join(os.path.dirname(out), "S2S Hair", "S2SHair.esm")
    if not merge and os.path.isfile(sibling):
        merge = [sibling]
    masters = ["Starfield.esm"] + [os.path.basename(m) for m in merge]
    report["masters"] = masters
    recs, added = [], {True: [], False: []}
    contexts = {}
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
        ctx, fb = contexts[(female, p["type"])]
        for variant, label in ((None, None),) + (DIAGNOSE if a.diagnose else ()):
            try:
                row = build_part(p, part_models(p["key"], parts), sky, conv, sf_world, ctx, fb, staging,
                                 a.spread_face_bones, variant=variant,
                                 out_name=f"{OUT_DIR}/{p['edid'].lower()}_{variant}" if variant else None)
            except Exception as e:                               # noqa: BLE001 (one bad part must not stop the rest)
                row = {"skyrim": p["edid"], "ok": False, "reason": f"{type(e).__name__}: {e}"}
            row["female"] = female
            if variant:
                row["variant"] = variant
            if row.get("ok"):
                edid = "S2S_" + p["edid"] + (f"_{variant}" if variant else "")
                rec = hair_pack.hair_part_record(tpl, len(recs), edid,
                                                 f"{p['edid']} (Skyrim{', ' + label if label else ''})",
                                                 row["model"], masters=len(masters))
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
