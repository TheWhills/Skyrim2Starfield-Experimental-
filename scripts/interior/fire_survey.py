"""Fires, candles and their light: how Skyrim builds them and what Starfield can draw (read-only; owner 2026-11-09:
"candles, hearths ... I'm wondering if getting the effects from skyrim actually converted will be better").

    python -I scripts\\interior\\fire_survey.py --skyrim "$sky\\Skyrim.esm" --skyrim-data "$sky" --starfield $sf ^
        --work C:\\Modding\\work\\s2s\\riverwood_doors --out C:\\Modding\\work\\fire

Skyrim side, over every model placed in the batch's interiors (<work>\\cells.txt, plus --cell): the models that carry
effects, i.e. effect-shader shapes (flame cards, glows: texture, greyscale palette, emissive colour / strength, and
the controllers that animate them), particle systems (block types), refraction planes (heat haze) and add-on nodes
(BSValueNode "AddOnNode<n>" -> the ADDN record with DATA index n, whose model is the effect: how candle flames are
attached), with each add-on's model surveyed too. Per effect model: how often it is placed in the batch and, unless
--no-global, in all of Skyrim.esm (how much one converted asset covers); the nearest Skyrim light to its placements
(LIGH DATA as the interior export reads it: radius, colour, flicker, fade) and the distance.
Starfield side: vanilla models whose path names fire / flame / candle / torch / brazier / lantern / ember / spark
(up to --sf-limit): their NIF block types (do Starfield models still carry particle systems?), their material and
particle strings; Starfield.esm ADDN records and lights with a model; and every BSMaterial:: component type named in
the material database (materialsbeta.cdb), with the strings near the flipbook / emissive / effect ones (their field
names): can a Starfield material play Skyrim's animated fire atlases and glow.
Writes fire_survey.json and fire_survey.md.
"""
import argparse
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import nif as nifmod, packages  # noqa: E402

U = 70.0
FIRE_WORDS = re.compile(r"fire|flame|candle|torch|brazier|lantern|ember|spark|hearth|sconce|chandelier|campfire|smoke",
                        re.I)
ADDON = re.compile(rb"^AddOnNode(\d+)$", re.I)
PARTICLE = re.compile(r"particle|psys", re.I)
LIGHT_FLICKER, LIGHT_PULSE = 0x8, 0x80          # skyriminterior's flags (xEdit: Flicker bit 3, Pulse bit 7)
CDB_INTEREST = (b"Flipbook", b"Emissive", b"Effect", b"UVStream", b"Translucency", b"Glow")


# ----------------------------------------------------------------------------------------------- Skyrim NIFs
def _controllers(n, ref):
    """Types of a controller chain (NiTimeController: next controller ref first)."""
    out, seen = [], set()
    while 0 <= ref < len(n.blocks) and ref not in seen:
        seen.add(ref)
        out.append(n.type_of(ref))
        b = n.blocks[ref]
        ref = struct.unpack_from("<i", b, 0)[0] if len(b) >= 4 else -1
    return out


def _net_controller(b):
    """(controller ref, offset after NiObjectNET) of a block laid out NiObjectNET first (name, extra data, controller)."""
    if len(b) < 12:
        return -1, len(b)
    n_extra = struct.unpack_from("<I", b, 4)[0]
    at = 8 + 4 * n_extra
    if n_extra > 64 or at + 4 > len(b):
        return -1, len(b)
    return struct.unpack_from("<i", b, at)[0], at + 4


def effect_shader(n, i):
    """Fields of a BSEffectShaderProperty (Skyrim SE; xEdit / nif.xml): textures (every .dds named in it, source first),
    emissive colour and multiple, its controllers."""
    b = n.blocks[i]
    ctrl, p = _net_controller(b)
    out = {"textures": [t.decode("latin-1") for t in re.findall(rb"[\w\\/ .-]+\.dds", b)],
           "controllers": _controllers(n, ctrl)}
    try:
        p += 8 + 16                                    # shader flags 1 / 2, UV offset, UV scale
        ln = struct.unpack_from("<I", b, p)[0]
        p += 4 + ln + 4 + 16                           # source texture, clamp / lighting / LOD / pad, falloff (4 f)
        out["emissive_color"] = [round(x, 3) for x in struct.unpack_from("<4f", b, p)]
        out["emissive_multiple"] = round(struct.unpack_from("<f", b, p + 16)[0], 3)
    except struct.error:
        pass
    return out


def nif_effects(data):
    """What carries effects in a Skyrim NIF: effect-shader shapes, particle blocks, refraction (heat haze) shapes,
    add-on node indices, controller types anywhere."""
    from fo4sf import skyrimnif
    n = nifmod.parse(data)
    out = {"effect_shapes": [], "particle_blocks": Counter(), "refraction_shapes": 0, "addon_indices": [],
           "controllers": Counter()}
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        if t == "BSEffectShaderProperty":
            out["effect_shapes"].append(effect_shader(n, i))
        elif PARTICLE.search(t) or t.startswith("NiPSys"):
            out["particle_blocks"][t] += 1
        elif t.endswith("Controller") or t.endswith("Interpolator"):
            out["controllers"][t] += 1
        if (t.endswith("Node") or t == "BSValueNode") and len(b) >= 4:
            k = struct.unpack_from("<i", b, 0)[0]
            if 0 <= k < len(n.strings):
                m = ADDON.match(n.strings[k])
                if m:
                    out["addon_indices"].append(int(m.group(1)))
        if t == "BSLightingShaderProperty":
            try:
                if skyrimnif.refraction(n, i):
                    out["refraction_shapes"] += 1
            except Exception:                          # noqa: BLE001  a layout the helper does not know
                pass
    out["particle_blocks"] = dict(out["particle_blocks"])
    out["controllers"] = dict(out["controllers"])
    return out


FIRE_TEXTURE = re.compile(r"fire|flame|smoke|ember|spark|glow|candle|torch|burn|heat", re.I)
MARKER_MODEL = re.compile(r"(^|\\)markers?\\|marker", re.I)


def fire_card(shape):
    """An effect shape that looks like fire / glow: a fire-ish texture, or one animated by a controller (flame
    cards scroll / flicker). 2026-11-09 (owner's run): editor markers, knives and forks carry one static
    effect-shader shape each (no fire)."""
    return bool(any(FIRE_TEXTURE.search(t) for t in shape.get("textures") or []) or shape.get("controllers"))


def has_effects(e):
    return bool(e and (any(fire_card(c) for c in e["effect_shapes"]) or e["particle_blocks"]
                       or e["refraction_shapes"] or e["addon_indices"]))


# ------------------------------------------------------------------------------------------- Skyrim records
def model_of(subs):
    return next((d.rstrip(b"\0").decode("latin-1") for s, d in subs if s == b"MODL"), None)


def light_of(subs):
    """A LIGH's DATA as skyriminterior.read_lights reads it."""
    light = {"radius_m": 0.0, "color": [255, 255, 255], "flicker": False, "fade": 1.0}
    for s, d in subs:
        if s == b"DATA" and len(d) >= 40:
            radius = struct.unpack_from("<I", d, 4)[0]
            fl = struct.unpack_from("<I", d, 12)[0]
            period, amp = struct.unpack_from("<2f", d, 28)
            light.update(radius_m=round(radius / U, 3), color=list(d[8:11]), flicker=bool(fl & (LIGHT_FLICKER | LIGHT_PULSE)),
                         flicker_period=round(period, 3), flicker_intensity=round(amp, 3))
        elif s == b"FNAM" and len(d) >= 4:
            light["fade"] = round(struct.unpack_from("<f", d)[0], 3)
    return light


def ref_pos(ix, r):
    d = next((d for s, d in ix.subs(r) if s == b"DATA" and len(d) >= 12), None)
    return struct.unpack_from("<3f", d) if d else None


def ref_base(ix, r):
    return next((struct.unpack_from("<I", d)[0] for s, d in ix.subs(r) if s == b"NAME" and len(d) == 4), None)


def addons(ix):
    """{node index: (EditorID, model)} of the ADDN records."""
    out = {}
    for f in ix.by_type.get(b"ADDN", []):
        subs = ix.subs(f)
        idx = next((struct.unpack_from("<I", d)[0] for s, d in subs if s == b"DATA" and len(d) >= 4), None)
        if idx is not None:
            out[idx] = (ix.edid(f), model_of(subs))
    return out


def skyrim_side(ix, archives, cells, global_counts=True):
    cell_ids = {f: ix.edid(f) for f in ix.by_type.get(b"CELL", []) if ix.edid(f) in cells}
    add = addons(ix)
    nif_cache = {}

    def effects_of(model):
        if model not in nif_cache:
            data = archives.mesh(model) if model else None
            try:
                nif_cache[model] = nif_effects(data) if data else None
            except Exception as e:                     # noqa: BLE001
                nif_cache[model] = {"error": f"{type(e).__name__}: {e}"}
        return nif_cache[model]

    placed = defaultdict(list)                         # base -> [(cell, pos)]
    lights = defaultdict(list)                         # cell -> [(pos, LIGH base)]
    for r, c in ix.cell_of.items():
        if c not in cell_ids or ix.kind(r) != "REFR":
            continue
        b = ref_base(ix, r)
        pos = ref_pos(ix, r)
        if b is None or pos is None:
            continue
        if ix.kind(b) == "LIGH":
            lights[c].append((pos, b))
        placed[b].append((c, pos))
    rows = []
    for b, where in placed.items():
        subs = ix.subs(b)
        model = model_of(subs)
        e = effects_of(model) if model else None
        if e and "error" in e:
            rows.append({"edid": ix.edid(b), "type": ix.kind(b), "model": model, "error": e["error"]})
            continue
        named_fire = bool(FIRE_WORDS.search((ix.edid(b) or "") + " " + (model or "")))
        if model and MARKER_MODEL.search(model) and not named_fire:
            continue                                   # editor markers: not drawn in game
        if not (has_effects(e) or named_fire or ix.kind(b) == "LIGH"):
            continue
        row = {"edid": ix.edid(b), "form": f"{b:08X}", "type": ix.kind(b), "model": model, "placed": len(where),
               "fire_named": named_fire, "effects": e}
        if ix.kind(b) == "LIGH":
            row["light"] = light_of(subs)
        if e and e.get("addon_indices"):
            row["addons"] = []
            for k in e["addon_indices"]:
                ed, m = add.get(k, (None, None))
                row["addons"].append({"index": k, "addn": ed, "model": m, "effects": effects_of(m) if m else None})
        # nearest Skyrim light to each placement (same cell), and its data
        near = []
        for c, p in where:
            best = min(((sum((a - q) ** 2 for a, q in zip(p, lp)) ** 0.5, lb) for lp, lb in lights.get(c, [])
                        if lb != b), default=None)
            if best is not None:
                near.append(best)
        if near:
            near.sort()
            d, lb = near[len(near) // 2]
            row["nearest_light"] = {"median_m": round(d / U, 2), "edid": ix.edid(lb), **light_of(ix.subs(lb))}
        rows.append(row)
    rows.sort(key=lambda x: (-int(has_effects(x.get("effects"))), -x.get("placed", 0)))
    if global_counts:
        want = {int(r["form"], 16) for r in rows if "form" in r}
        cnt = Counter()
        for r in ix.by_type.get(b"REFR", []):
            b = ref_base(ix, r)
            if b in want:
                cnt[b] += 1
        for r in rows:
            if "form" in r:
                r["placed_in_skyrim"] = cnt[int(r["form"], 16)]
    textures = Counter()
    for r in rows:
        for e in [r.get("effects")] + [a.get("effects") for a in r.get("addons", [])]:
            for s in (e or {}).get("effect_shapes", []):
                if s["textures"]:
                    textures[s["textures"][0].lower()] += 1
    return {"cells": sorted(cell_ids.values()), "models": rows, "effect_textures": dict(textures.most_common(40)),
            "addon_records": len(add)}


# ---------------------------------------------------------------------------------------------- Starfield side
def cdb_components(data, window=600):
    """(every BSMaterial:: type name in the material database, {name of interest: printable strings near it})."""
    names = sorted({m.decode("latin-1") for m in re.findall(rb"BSMaterial::\w+", data)})
    near = {}
    for nm in names:
        if any(k.decode() in nm for k in CDB_INTEREST):
            at = data.find(nm.encode())
            chunk = data[max(0, at - 50):at + window]
            near[nm] = [s.decode("latin-1") for s in re.findall(rb"[A-Za-z_][A-Za-z0-9_:]{2,}", chunk)][:40]
    return names, near


def sf_nif_summary(data):
    n = nifmod.parse(data)
    types = Counter(n.type_of(i) for i in range(len(n.blocks)))
    strings = [s.decode("latin-1", "replace") for s in n.strings]
    return {"block_types": dict(types), "materials": sorted({s for s in strings if s.lower().endswith(".mat")}),
            "particle_strings": sorted({s for s in strings if PARTICLE.search(s) or "fx" in s.lower()})[:20],
            "particle_blocks": sorted(t for t in types if PARTICLE.search(t))}


def starfield_side(sf_data, limit=60):
    from fo4sf import ba2, sfplugin
    out = {"models": [], "block_types": Counter(), "particle_block_models": 0}
    arcs = [os.path.join(sf_data, f) for f in sorted(os.listdir(sf_data))
            if f.lower().endswith(".ba2") and f.lower().startswith("starfield - ")]
    seen = 0
    for path in arcs:
        low = os.path.basename(path).lower()
        if "mesh" not in low and "material" not in low:
            continue
        a = ba2.Ba2(path)
        for i, nm in enumerate(a.names):
            ln = nm.lower().replace("\\", "/")
            if ln.endswith("materialsbeta.cdb"):
                names, near = cdb_components(a.read(i))
                out["material_components"] = names
                out["material_components_near"] = near
            elif ln.endswith(".nif") and FIRE_WORDS.search(ln.rsplit("/", 1)[-1]) and seen < limit:
                seen += 1
                try:
                    s = sf_nif_summary(a.read(i))
                except Exception as e:                 # noqa: BLE001
                    s = {"error": f"{type(e).__name__}: {e}"}
                s["path"] = nm
                out["models"].append(s)
                out["block_types"].update(s.get("block_types", {}))
                out["particle_block_models"] += bool(s.get("particle_blocks"))
    out["block_types"] = dict(out["block_types"].most_common())
    esm = os.path.join(sf_data, "Starfield.esm")
    if os.path.exists(esm):
        recs = sfplugin.records(esm, [b"ADDN", b"LIGH"])
        add = [(sfplugin.edid(s), model_of(s)) for t, _h, s, _f in recs if t == b"ADDN"]
        out["addn_records"] = len(add)
        out["addn_fire"] = [x for x in add if FIRE_WORDS.search(f"{x[0]} {x[1]}")][:40]
        lm = [(sfplugin.edid(s), model_of(s)) for t, _h, s, _f in recs if t == b"LIGH" and model_of(s)]
        out["lights_with_model"] = len(lm)
        out["lights_with_model_fire"] = [x for x in lm if FIRE_WORDS.search(f"{x[0]} {x[1]}")][:40]
    return out


# ------------------------------------------------------------------------------------------------------ report
def report_md(r):
    sk, sf = r.get("skyrim", {}), r.get("starfield", {})
    L = ["# Fire survey", "", f"Skyrim cells: {len(sk.get('cells', []))}; ADDN records {sk.get('addon_records')}", "",
         "| Skyrim model | type | placed (batch / Skyrim) | flame cards | particles | haze | add-ons | nearest light |",
         "|---|---|---|---|---|---|---|---|"]
    for m in sk.get("models", [])[:80]:
        e = m.get("effects") or {}
        cards = ", ".join(sorted({(s["textures"] or ["?"])[0].rsplit("\\", 1)[-1] +
                                  (" (animated)" if s["controllers"] else "") for s in e.get("effect_shapes", [])}))
        nl = m.get("nearest_light")
        light = (f"{nl['edid']} {nl['median_m']} m, r {nl['radius_m']} m, {nl['color']}" +
                 (", flicker" if nl.get("flicker") else "")) if nl else ""
        ad = ", ".join(f"{a['addn']}" for a in m.get("addons", []))
        L.append(f"| {m.get('edid')} ({m.get('model')}) | {m.get('type')} | {m.get('placed')} / "
                 f"{m.get('placed_in_skyrim', '?')} | {cards} | {', '.join(e.get('particle_blocks', {}))} | "
                 f"{e.get('refraction_shapes', '')} | {ad} | {light} |")
    L += ["", f"Skyrim effect textures: {sk.get('effect_textures')}", "", "## Starfield", "",
          f"Fire-named models read: {len(sf.get('models', []))}; with particle blocks: {sf.get('particle_block_models')}",
          f"Block types: {sf.get('block_types')}", f"ADDN records: {sf.get('addn_records')} (fire: {sf.get('addn_fire')})",
          f"Lights with a model: {sf.get('lights_with_model')} (fire: {sf.get('lights_with_model_fire')})",
          f"Material components: {sf.get('material_components')}", "",
          f"Near flipbook / emissive / effect components: {json.dumps(sf.get('material_components_near'))[:3000]}"]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--skyrim-data", required=True, help="Skyrim Data folder (archives)")
    ap.add_argument("--starfield", default="", help="Starfield install folder (its side is skipped without it)")
    ap.add_argument("--work", default="", help="interior batch work folder (cells.txt)")
    ap.add_argument("--cell", action="append", default=[], help="an interior cell EditorID (repeatable)")
    ap.add_argument("--no-global", action="store_true", help="skip counting placements over all of Skyrim.esm")
    ap.add_argument("--sf-limit", type=int, default=60, help="Starfield fire-named models to read")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import furniture_survey
    cells = furniture_survey.batch_cells(a.work, a.cell) if a.work else list(a.cell)
    if not cells:
        ap.error("give --work (cells.txt) or --cell")
    report = {}
    archives = archives_for(a.skyrim_data)
    ix = packages.Index(a.skyrim)
    try:
        report["skyrim"] = skyrim_side(ix, archives, set(cells), not a.no_global)
    finally:
        ix.close()
    if a.starfield:
        report["starfield"] = starfield_side(os.path.join(a.starfield, "Data"), a.sf_limit)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "fire_survey.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    with open(os.path.join(a.out, "fire_survey.md"), "w", encoding="utf-8") as fh:
        fh.write(report_md(report))
    sk = report["skyrim"]
    fx = [m for m in sk["models"] if has_effects(m.get("effects"))]
    print(f"Skyrim: {len(sk['models'])} fire / light / effect models in {len(sk['cells'])} cells; {len(fx)} carry effects")
    for m in fx[:15]:
        print(f"  {m['edid']}: placed {m['placed']} here, {m.get('placed_in_skyrim', '?')} in Skyrim; "
              f"cards {sum(fire_card(c) for c in m['effects']['effect_shapes'])}, particles {m['effects']['particle_blocks']}, "
              f"add-ons {[x['addn'] for x in m.get('addons', [])]}")
    if "starfield" in report:
        sf = report["starfield"]
        print(f"Starfield: {len(sf['models'])} fire models read; particle blocks in {sf['particle_block_models']}; "
              f"material components with flipbook / emissive / effect: {sorted(sf.get('material_components_near', {}))}")
    print(f"-> {os.path.join(a.out, 'fire_survey.md')}")
    return 0


def archives_for(skyrim_data):
    from fo4sf import bsa
    return bsa.SkyrimArchives(skyrim_data)


if __name__ == "__main__":
    sys.exit(main())
