"""Skyrim fire and candle flames -> Starfield effect geometry and materials.

Read from the game files (flame_probe, owner's runs 2026-11-15; docs/interior/skyrim-interiors.md "Fires and candles"):
* Skyrim hearth flames are meshes with a BSEffectShaderProperty: a greyscale atlas coloured through a palette texture
  (Shader Flags 1 Greyscale_To_PaletteColor / _Alpha), animated by a BSEffectShaderPropertyFloatController on
  V Offset (0 -> 1 over a few seconds). Candles carry no flame: an "AddOnNode<n>" node names ADDN n, whose model is a
  particle system (MPSCandleFlame01: CandleFlame01.dds particles, radius 1.25 units, rising 7.5 units/s for 0.33 s).
* Starfield draws its own candle / lantern flames as plain static shapes (BSGeometry + BSLightingShaderProperty naming an
  effect .mat: FireCandleFlame.mat) and animates material values with BSBind controllers: a UV scroll is a
  Float2DCurveController on the binding "UVOffset", a flicker a FloatCurveController on "EmissiveIntensity".
So: flame meshes keep their geometry with an emissive effect material (palette baked into the texture, the V Offset
controller as a UVOffset curve); candle particles become crossed cards at each AddOnNode with a flickering material.
Supported hypotheses, to be checked in game: curve inputs are seconds (InputDistance = the loop length, as in vanilla
blink / scroll materials), Starfield adds UVOffset to UVs as Skyrim does, and the palette row (PALETTE_ROW).
"""
import json
import math
import re
import struct
from typing import Dict, List, Optional, Tuple

from . import nif as nifmod

# ---------------------------------------------------------------------------------------------------------- reading
CONTROLLED = {0: "Emissive Multiple", 1: "Falloff Start Angle", 2: "Falloff Stop Angle", 3: "Falloff Start Opacity",
              4: "Falloff Stop Opacity", 5: "Alpha Transparency", 6: "U Offset", 7: "U Scale", 8: "V Offset",
              9: "V Scale"}          # BSEffectShaderPropertyFloatController (nif.xml EffectShaderControlledVariable)

SLSF1_VERTEX_ALPHA = 1 << 3
SLSF1_PALETTE_COLOR = 1 << 4         # Greyscale_To_PaletteColor
SLSF1_PALETTE_ALPHA = 1 << 5         # Greyscale_To_PaletteAlpha
SLSF2_DOUBLE_SIDED = 1 << 4

FIRE_EFFECT = r"fire|flame|candle|woodfires"     # effect textures converted as flames (others stay skipped)
ADDON_MODELS = {49: "meshes\\mps\\mpscandleflame01.nif"}   # Skyrim ADDN DATA index -> model (000B9FC5 MPSCandleFlame01)
GLOW_RADIUS = 40.0                   # units: particle systems bigger than this are halos (CandleGlow01: 80), not cards
# Palette rows (owner's flame_textures run, 2026-11-15): GradFireExplosion is dark red -> orange -> white down to its
# middle and blue in its last rows; the fire shaders' "emissive colours" are greys (0.224, 0.275, 0.196) = the colour
# row, alpha 1 = the alpha row (the bottom row's alpha ramps 0 -> 237). Skyrim's lookup as read from that: colour =
# palette(u = grey, v = emissive red) x emissive multiple, alpha = palette alpha(u = texture alpha, v = emissive alpha).
PALETTE_ROW = 1.0
# Sub-texture grids (frames) of particle atlases, when the NIF's NiPSysData offsets cannot be read: from the owner's
# contact sheet (CandleFlame01 2 x 2 flames, FXFireAtlas02 4 x 2)
SUBTEXTURE_GRIDS = {"candleflame01": (2, 2), "fxfireatlas02": (4, 2)}
# 2026-11-15 (owner, flames v2 in game: "a slight low quality, the fires move slower than Starfield's"): Skyrim's atlases
# have 4 / 8 frames that its particles picked at random while rising and fading; cycled at 8 / 10 fps on fixed cards
# they read as slow steps. Faster frames, and two layers per flame spot (LAYER2: turned, smaller, higher, mirrored, its
# own frame rate, cross-fading with the first through OverallOpacity) so the overlap hides the few frames.
FLIPBOOK_FPS = {"candle": 12.0, "hearth": 20.0}
LAYER2 = {"fps": 0.73, "size": 0.8, "lift": 0.25, "turn_deg": 30.0}
CROSSFADE = (0.55, 1.0)              # OverallOpacity range of the two layers' cross-fade, a loop of 3 x a particle life


def time_controller(b: bytes) -> dict:
    """NiTimeController: next, flags, frequency, phase, start, stop, target (nif.xml, 20.2.0.7)."""
    nxt, flags, freq, phase, start, stop, target = struct.unpack_from("<iHffffi", b, 0)
    return {"next": nxt, "flags": flags, "frequency": round(freq, 3), "phase": round(phase, 3),
            "start": round(start, 3), "stop": round(stop, 3), "target": target}


def float_keys(n, data_ref, limit=64) -> dict:
    """NiFloatData keys: {count, type, keys [(time, value)]}."""
    if not (0 <= data_ref < len(n.blocks)) or n.type_of(data_ref) != "NiFloatData":
        return {}
    b = n.blocks[data_ref]
    count, = struct.unpack_from("<I", b, 0)
    if count == 0:
        return {"count": 0}
    ktype, = struct.unpack_from("<I", b, 4)
    size = {1: 8, 2: 16, 3: 20, 5: 8}.get(ktype, 8)          # linear, quadratic (+2 tangents), TBC (+3), const
    keys = []
    for k in range(min(count, limit)):
        t, v = struct.unpack_from("<ff", b, 8 + k * size)
        keys.append((round(t, 3), round(v, 4)))
    return {"count": count, "type": ktype, "keys": keys}


def controllers(n, ref) -> list:
    """A controller chain (next first): type, timing, interpolator, controlled variable, float keys."""
    out, seen = [], set()
    while 0 <= ref < len(n.blocks) and ref not in seen:
        seen.add(ref)
        t, b = n.type_of(ref), n.blocks[ref]
        c = {"type": t}
        try:
            c.update(time_controller(b))
            p = 26
            if (t.endswith("Controller") or t.endswith("Ctlr")) and len(b) >= p + 4:
                interp, = struct.unpack_from("<i", b, p)
                c["interpolator"] = n.type_of(interp) if 0 <= interp < len(n.blocks) else None
                if "EffectShaderProperty" in t and len(b) >= p + 8:
                    var, = struct.unpack_from("<I", b, p + 4)
                    c["variable"] = CONTROLLED.get(var, var) if "Float" in t else var
                if c["interpolator"] == "NiFloatInterpolator":
                    ib = n.blocks[interp]
                    c["value"], data = round(struct.unpack_from("<f", ib, 0)[0], 4), struct.unpack_from("<i", ib, 4)[0]
                    c["data"] = float_keys(n, data)
        except struct.error:
            c["error"] = "short block"
        out.append(c)
        ref = c.get("next", -1)
    return out


def effect_shader(n, i) -> dict:
    """A Skyrim SE BSEffectShaderProperty: flags, UV offset / scale, textures (source, greyscale palette), emissive
    colour / multiple and its controllers."""
    b = n.blocks[i]
    n_extra, = struct.unpack_from("<I", b, 4)
    p = 8 + 4 * n_extra
    ctrl, = struct.unpack_from("<i", b, p)
    f1, f2 = struct.unpack_from("<II", b, p + 4)
    uv = struct.unpack_from("<4f", b, p + 12)
    out = {"flags1": f1, "flags2": f2, "uv_offset": uv[:2], "uv_scale": uv[2:], "controllers": controllers(n, ctrl),
           "textures": [x.decode("latin-1") for x in re.findall(rb"[\w\\/ .-]+\.dds", b)]}
    q = p + 28
    try:
        ln, = struct.unpack_from("<I", b, q)
        source = b[q + 4:q + 4 + ln].rstrip(b"\0").decode("latin-1")
        q += 4 + ln + 4 + 16                       # clamp / lighting / LOD / pad, falloff (4 f)
        out["emissive_color"] = list(struct.unpack_from("<4f", b, q))
        out["emissive_multiple"] = struct.unpack_from("<f", b, q + 16)[0]
        q += 24                                    # colour, multiple, soft falloff depth
        ln2, = struct.unpack_from("<I", b, q)
        grey = b[q + 4:q + 4 + ln2].rstrip(b"\0").decode("latin-1") if ln2 < 512 else ""
        if source and not source.lower().endswith(".dds") or grey and not grey.lower().endswith(".dds"):
            raise struct.error("layout")
        out["greyscale"] = grey
        out["source"] = source
    except struct.error:
        texs = out["textures"]
        out["source"] = texs[0] if texs else ""
        out["greyscale"] = next((t for t in texs[1:] if "grad" in t.lower()), "")
    out["palette_color"] = bool(f1 & SLSF1_PALETTE_COLOR) and bool(out["greyscale"])
    out["palette_alpha"] = bool(f1 & SLSF1_PALETTE_ALPHA) and bool(out["greyscale"])
    out["vertex_alpha"] = bool(f1 & SLSF1_VERTEX_ALPHA)
    out["double_sided"] = bool(f2 & SLSF2_DOUBLE_SIDED)
    return out


def uv_scroll(ctrls) -> Optional[Tuple[str, float, float]]:
    """(axis "U" / "V", offset change per loop, loop seconds) of a U / V Offset float controller, or None."""
    for c in ctrls:
        if c.get("variable") in ("U Offset", "V Offset"):
            keys = (c.get("data") or {}).get("keys") or []
            if len(keys) >= 2:
                (t0, v0), (t1, v1) = keys[0], keys[-1]
                period = (t1 - t0) / (c.get("frequency") or 1.0)
                if period > 0 and v1 != v0:
                    return c["variable"][0], v1 - v0, period
    return None


def bake_params(info: dict) -> dict:
    """How to bake one Skyrim effect shader (see PALETTE_ROW): palette flags, colour / alpha rows, the colour tint
    (the emissive colour when the colour is not palette-mapped, else none) and the emissive multiple, which goes into
    the material's emittance rather than the texture (baked, it clipped bright flames to white)."""
    col = list(info.get("emissive_color") or [1.0, 1.0, 1.0, 1.0])
    mult = float(info.get("emissive_multiple") or 1.0)
    pc, pa = bool(info.get("palette_color")), bool(info.get("palette_alpha"))
    tint = (1.0, 1.0, 1.0) if pc else tuple(min(1.0, max(0.0, c)) for c in col[:3])
    return {"greyscale": info.get("greyscale") or "", "palette_color": pc, "palette_alpha": pa,
            "color_row": min(1.0, max(0.0, col[0])), "alpha_row": min(1.0, max(0.0, col[3])), "tint": tint,
            "multiple": mult}


def is_fire_effect(info: dict, pattern: str = FIRE_EFFECT) -> bool:
    return bool(re.search(pattern, info.get("source") or "", re.I))


# ---- particles -------------------------------------------------------------------------------------------------
MODIFIER_FIELDS = {          # floats after NiPSysModifier (name, order, target, active = 13 bytes); nif.xml, SSE
    "NiPSysEmitter": ["speed", "speed_var", "declination", "declination_var", "planar_angle", "planar_angle_var",
                      "color_r", "color_g", "color_b", "color_a", "radius", "radius_var", "life_span", "life_span_var"],
    "BSPSysSimpleColorModifier": ["fade_in", "fade_out", "color1_end", "color1_start", "color2_end", "color2_start",
                                  "c1r", "c1g", "c1b", "c1a", "c2r", "c2g", "c2b", "c2a", "c3r", "c3g", "c3b", "c3a"],
    "BSPSysSubTexModifier": ["start_frame(u32)", "start_frame_fudge", "end_frame", "loop_start", "loop_start_fudge",
                             "frame_count", "frame_count_fudge"],
    "NiPSysAgeDeathModifier": [],
    "NiPSysGravityModifier": [],
}
EMITTERS = ("NiPSysCylinderEmitter", "NiPSysBoxEmitter", "NiPSysSphereEmitter", "NiPSysMeshEmitter")


def particle_modifier(n, i) -> dict:
    """A particle modifier / emitter block: its target system, named fields (raw floats kept beside them so a wrong
    layout shows), the volume emitter's extra floats, a scale modifier's curve."""
    t, b = n.type_of(i), n.blocks[i]
    out = {"block": i, "type": t}
    if len(b) < 13:
        return out
    out["target"] = struct.unpack_from("<i", b, 8)[0]
    body = b[13:]
    floats = [round(x, 4) for x in struct.unpack_from(f"<{len(body) // 4}f", body)]
    names = MODIFIER_FIELDS["NiPSysEmitter"] if t in EMITTERS else MODIFIER_FIELDS.get(t)
    if names:
        out["fields"] = dict(zip(names, floats))
        if t == "BSPSysSubTexModifier" and len(body) >= 4:
            out["fields"]["start_frame(u32)"] = struct.unpack_from("<I", body, 0)[0]
        if t in EMITTERS:
            out["volume"] = floats[len(names) + 1:]                 # after the emitter object ref
    elif t == "BSPSysScaleModifier" and len(body) >= 4:
        k = struct.unpack_from("<I", body, 0)[0]
        out["scales"] = [round(x, 4) for x in struct.unpack_from(f"<{min(k, 32)}f", body, 4)] if k < 1000 else []
    out["raw"] = floats[:24]
    return out


def particle_systems(n) -> list:
    """Every NiParticleSystem: the effect shader it draws with (block, textures), its modifiers / emitters and the
    controllers aimed at it."""
    shaders = {i for i in range(len(n.blocks)) if n.type_of(i) == "BSEffectShaderProperty"}
    systems = {}
    for i, b in enumerate(n.blocks):
        if n.type_of(i) in ("NiParticleSystem", "BSStripParticleSystem", "NiMeshParticleSystem"):
            refs = [struct.unpack_from("<i", b, k)[0] for k in range(0, len(b) - 3)]   # any offset: bools misalign
            sh = [r for r in refs if r in shaders]
            name = ""
            k = struct.unpack_from("<i", b, 0)[0] if len(b) >= 4 else -1
            if 0 <= k < len(n.strings):
                name = n.strings[k].decode("latin-1") if isinstance(n.strings[k], bytes) else str(n.strings[k])
            shader = None
            if sh:
                try:
                    shader = effect_shader(n, sh[0])
                except Exception:                                   # noqa: BLE001
                    shader = None
            data = [r for r in refs if 0 <= r < len(n.blocks) and n.type_of(r) == "NiPSysData"]
            systems[i] = {"block": i, "type": n.type_of(i), "name": name,
                          "shader_block": sh[0] if sh else None, "shader": shader,
                          "subtextures": subtexture_offsets(n.blocks[data[0]]) if data else [],
                          "emissive_color": list(shader["emissive_color"][:3]) if shader and "emissive_color" in shader
                          else None,
                          "textures": [x.decode("latin-1") for x in re.findall(rb"[\w\\/ .-]+\.dds", n.blocks[sh[0]])]
                          if sh else [], "modifiers": []}
    for i in range(len(n.blocks)):
        t = n.type_of(i)
        if (t.startswith("NiPSys") or t.startswith("BSPSys")) and not t.endswith(("Data", "Ctlr")) \
                and "Collider" not in t:
            m = particle_modifier(n, i)
            if m.get("target") in systems:
                systems[m["target"]]["modifiers"].append(m)
        elif t.endswith("Ctlr") and (t.startswith("NiPSys") or t.startswith("BSPSys")):
            c = controllers(n, i)[0]
            if c.get("target") in systems:
                systems[c["target"]]["modifiers"].append({"block": i, "controller": c})
    try:
        world = nifmod.world_transforms(n)
    except Exception:                                               # noqa: BLE001
        world = None
    for ps in systems.values():                    # where particles start: the emitter object (else the system)
        em = next((m for m in ps["modifiers"] if m.get("type") in EMITTERS), None)
        obj = -1
        if em is not None and len(n.blocks[em["block"]]) >= 73:
            obj = struct.unpack_from("<i", n.blocks[em["block"]], 13 + 56)[0]
        ps["emitter_object"] = obj
        pos = None
        for b in (obj, ps["block"]):
            if pos is None and world is not None and 0 <= b < len(n.blocks):
                try:
                    pos = tuple(float(x) for x in world(b)[0])
                except Exception:                                   # noqa: BLE001
                    pos = None
        ps["origin"] = pos or (0.0, 0.0, 0.0)
    return list(systems.values())


def subtexture_offsets(b: bytes) -> list:
    """The sub-texture rectangles of an NiPSysData block (the frames a particle picks from an atlas), found by their
    shape: a count byte 2..64 then that many Vector4 (u, v, u2 / width, v2 / height) inside 0..1 that tile a grid.
    [] when none is found (callers fall back to SUBTEXTURE_GRIDS)."""
    for p in range(0, len(b) - 1):
        k = b[p]
        if not 2 <= k <= 64 or p + 1 + 16 * k > len(b):
            continue
        rects = [struct.unpack_from("<4f", b, p + 1 + 16 * j) for j in range(k)]
        if not all(all(0.0 <= x <= 1.0001 for x in r) and r[2] > 0 and r[3] > 0 for r in rects):
            continue
        us, vs = {round(r[0], 3) for r in rects}, {round(r[1], 3) for r in rects}
        if len(us) * len(vs) == k and (len(us) > 1 or len(vs) > 1):
            return [tuple(round(x, 4) for x in r) for r in rects]
    return []


def subtexture_grid(system: dict) -> Tuple[int, int]:
    """(columns, rows) of a particle system's atlas: from its NiPSysData offsets, else SUBTEXTURE_GRIDS, else 1 x 1."""
    rects = system.get("subtextures") or []
    if rects:
        return len({round(r[0], 3) for r in rects}), len({round(r[1], 3) for r in rects})
    tex = (system.get("textures") or [""])[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    return SUBTEXTURE_GRIDS.get(tex.rsplit(".", 1)[0], (1, 1))


def particle_flame(system: dict) -> Optional[dict]:
    """What a flame particle system looks like as one card: {texture, half_w, half_h, lift, color} in Skyrim units
    (lift = the card centre above the emitter: half the rise over a particle's life). None for halos (radius over
    GLOW_RADIUS), systems without an emitter, and non-fire textures."""
    emitter = next((m for m in system["modifiers"] if m.get("type") in EMITTERS and "fields" in m), None)
    em = emitter["fields"] if emitter else None
    tex = system["textures"][0] if system["textures"] else ""
    if em is None or not re.search(FIRE_EFFECT, tex, re.I) or em["radius"] > GLOW_RADIUS \
            or re.search("glow", tex + " " + system.get("name", ""), re.I):
        return None
    scales = next((m.get("scales") for m in system["modifiers"] if m.get("type") == "BSPSysScaleModifier"), None)
    smax = max(scales) if scales else 1.0
    col = next((m["fields"] for m in system["modifiers"] if m.get("type") == "BSPSysSimpleColorModifier"), None)
    color = (col["c2r"], col["c2g"], col["c2b"]) if col else (1.0, 1.0, 1.0)
    shader = system.get("shader") or {}
    if not shader and system.get("emissive_color"):
        shader = {"emissive_color": list(system["emissive_color"]) + [1.0], "emissive_multiple": 1.0}
    bake = bake_params(shader)
    # Skyrim draws particle colour x the shader colour (bake tint: the emissive colour unless palette-mapped)
    color = tuple(min(1.0, max(0.0, c * t)) for c, t in zip(color, bake["tint"]))
    rise = em["speed"] * em["life_span"]
    half_w = em["radius"] * smax
    volume = (emitter or {}).get("volume") or []
    spread = float(volume[0]) if emitter.get("type") in ("NiPSysCylinderEmitter", "NiPSysSphereEmitter") and volume \
        else 0.0
    return {"texture": tex, "half_w": half_w, "half_h": half_w + rise * 0.25, "lift": rise * 0.5,
            "color": color, "life": em["life_span"], "name": system["name"], "grid": subtexture_grid(system),
            "origin": tuple(system.get("origin") or (0.0, 0.0, 0.0)), "spread": spread,
            "greyscale": bake["greyscale"], "palette_color": bake["palette_color"],
            "palette_alpha": bake["palette_alpha"], "color_row": bake["color_row"], "alpha_row": bake["alpha_row"],
            "multiple": bake["multiple"]}


def fire_spots(points, origin_z: Optional[float] = None, spacing: float = None, max_n: int = None) -> List[tuple]:
    """Where to put fires along a model's fire (Skyrim units, model space): `points` are the fire shapes' vertices;
    the fires go along the longer side of their XY box, `spacing` apart (at least one, at most max_n), centred on
    the box, at origin_z (the flame emitter's height) or the box's bottom."""
    spacing = spacing or FIRE_SPACING
    max_n = max_n or FIRE_MAX
    if not points:
        return []
    xs, ys, zs = [p[0] for p in points], [p[1] for p in points], [p[2] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    along_x = (x1 - x0) >= (y1 - y0)
    length = (x1 - x0) if along_x else (y1 - y0)
    n = max(1, min(max_n, int(round(length / spacing))))
    z = min(zs) if origin_z is None else origin_z
    out = []
    for i in range(n):
        d = (i - (n - 1) / 2) * (length / n)
        out.append((cx + d, cy, z) if along_x else (cx, cy + d, z))
    return out


def flame_card_centres(flame: dict) -> List[tuple]:
    """Where the cards of one particle flame go (model space): one at the emitter, plus four on a ring at RING x the
    emitter's radius when the emitter is wider than a card (FireplaceWood01Burning: a 20-unit cylinder)."""
    ox, oy, oz = flame["origin"]
    z = oz + flame["lift"]
    out = [(ox, oy, z)]
    r = flame.get("spread", 0.0) * RING
    if flame.get("spread", 0.0) > flame["half_w"] * 0.5:
        out += [(ox + r * math.cos(a), oy + r * math.sin(a), z) for a in (0.4, 0.4 + math.pi / 2, 0.4 + math.pi,
                                                                          0.4 + 3 * math.pi / 2)]
    return out


def addon_nodes(n) -> List[Tuple[int, tuple]]:
    """(ADDN index, model-space position) of every AddOnNode<n> in a Skyrim NIF."""
    try:
        world = nifmod.world_transforms(n)
    except Exception:                                               # noqa: BLE001
        world = None
    out = []
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        if not (t.endswith("Node") or t == "BSValueNode") or len(b) < 4:
            continue
        k, = struct.unpack_from("<i", b, 0)
        name = n.strings[k] if 0 <= k < len(n.strings) else b""
        name = name.decode("latin-1") if isinstance(name, bytes) else str(name)
        m = re.match(r"^AddOnNode(\d+)$", name, re.I)
        if m:
            pos = (0.0, 0.0, 0.0)
            if world is not None:
                try:
                    pos = tuple(float(x) for x in world(i)[0])
                except Exception:                                   # noqa: BLE001
                    pass
            out.append((int(m.group(1)), pos))
    return out


# ---------------------------------------------------------------------------------------------------------- geometry
def crossed_cards(center, half_w: float, half_h: float, planes: int = 3, name: bytes = b"Flame",
                  turn_deg: float = 0.0, mirror: bool = False) -> nifmod.Fo4Shape:
    """`planes` vertical quads through `center` (Skyrim units), evenly turned about z (plus turn_deg), double-sided: a
    flame seen from any side (Starfield's own candle flames are static geometry too). UV v = 0 at the top (the flame's
    tip); mirror flips u (a second layer that does not repeat the first)."""
    cx, cy, cz = center
    pos, uvs, nor, tan, tris = [], [], [], [], []
    for k in range(planes):
        a = math.pi * k / planes + math.radians(turn_deg)
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        for side in (1, -1):                       # front, then the back face (mirrored so the texture reads right)
            base = len(pos)
            for s, top in ((-1, False), (1, False), (1, True), (-1, True)):
                pos.append((cx + s * half_w * dx, cy + s * half_w * dy, cz + (half_h if top else -half_h)))
                u = (s + 1) * 0.5 if side == 1 else (1 - s) * 0.5
                uvs.append((1.0 - u if mirror else u, 0.0 if top else 1.0))
                nor.append((nx * side, ny * side, 0.0))
                tan.append((dx * side, dy * side, 0.0))
            if side == 1:                          # winding agrees with the normal by the right-hand rule
                tris += [(base, base + 2, base + 1), (base, base + 3, base + 2)]
            else:
                tris += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return nifmod.Fo4Shape(name, (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0, -1, -1, -1, pos, uvs, nor, tan,
                           [(255, 255, 255, 255)] * len(pos), tris, False)


def normalize_card_uvs(shape: nifmod.Fo4Shape) -> nifmod.Fo4Shape:
    """The shape with each connected piece's UVs stretched to 0..1 (its own UV box, orientation kept): a Skyrim flame
    card that shows one cell of an atlas, or a strip of a scrolling texture, shows a whole material made for one flame
    (LAYERED_FIRE_MAT)."""
    import dataclasses
    n = len(shape.positions)
    if not shape.uvs or not n:
        return shape
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b, c in shape.triangles:
        for x, y in ((a, b), (b, c)):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    uvs = list(shape.uvs)
    for idx in groups.values():
        us, vs = [shape.uvs[i][0] for i in idx], [shape.uvs[i][1] for i in idx]
        u0, du = min(us), (max(us) - min(us)) or 1.0
        v0, dv = min(vs), (max(vs) - min(vs)) or 1.0
        for i in idx:
            uvs[i] = ((shape.uvs[i][0] - u0) / du, (shape.uvs[i][1] - v0) / dv)
    return dataclasses.replace(shape, uvs=uvs)


def sf_flame_shape(sm, center, half_w: float, half_h: float, name: bytes = b"Flame") -> nifmod.Fo4Shape:
    """A Starfield flame mesh (sfmesh.SfMesh, e.g. its candle's "Flame:0") as a shape fitted to the box half_w across,
    half_h up, centred on `center` (Skyrim units): positions box to box, normals / tangents through the stretch,
    vertex colours (BGRA -> RGBA), UVs and triangles kept."""
    from . import sfmesh
    pts = [sfmesh.decode_position(p, sm.scale) for p in sm.positions]
    lo = [min(p[a] for p in pts) for a in range(3)]
    hi = [max(p[a] for p in pts) for a in range(3)]
    mid = [(lo[a] + hi[a]) / 2 for a in range(3)]
    ext = [((hi[a] - lo[a]) / 2) or 1.0 for a in range(3)]
    k = (half_w / ext[0], half_w / ext[1], half_h / ext[2])
    pos = [tuple(center[a] + (p[a] - mid[a]) * k[a] for a in range(3)) for p in pts]

    def unit(v):
        ln = math.sqrt(sum(c * c for c in v)) or 1.0
        return tuple(c / ln for c in v)
    nor = [unit(tuple(d / k[a] for a, d in enumerate(sfmesh.decode_packed(u)[:3]))) for u in sm.normals]
    tan = [unit(tuple(d * k[a] for a, d in enumerate(sfmesh.decode_packed(u)[:3]))) for u in sm.tangents]
    uvs = [(sfmesh.half_to_float(u), sfmesh.half_to_float(v)) for u, v in sm.uv1]
    cols = [((c >> 16) & 255, (c >> 8) & 255, c & 255, (c >> 24) & 255) for c in sm.colors]
    if len(tan) != len(pos) or len(nor) != len(pos):
        tan = []
    return nifmod.Fo4Shape(name, (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0, -1, -1, -1, pos, uvs, nor, tan,
                           cols, [tuple(t) for t in sm.triangles], False)


def sf_shape_mesh_path(nif_bytes: bytes, shape_name: bytes = b"Flame:0") -> Optional[str]:
    """"geometries/<dir>/<file>.mesh" of the LOD 0 mesh of the BSGeometry named shape_name in a Starfield NIF."""
    from . import sfnif
    n = nifmod.parse(nif_bytes)
    for i, b in enumerate(n.blocks):
        if n.type_of(i) != "BSGeometry" or len(b) < 4:
            continue
        k = struct.unpack_from("<i", b, 0)[0]
        nm = n.strings[k] if 0 <= k < len(n.strings) else b""
        if (nm if isinstance(nm, bytes) else str(nm).encode()) != shape_name:
            continue
        m = sfnif.parse_bsgeometry(b).meshes[0]
        if m is not None:
            return "geometries/" + m.path.decode("latin-1").replace("\\", "/") + ".mesh"
    return None


# 2026-11-16, owner on -FlameStyle layered in game: the fire runs across the hearth like Skyrim's but "awfully white" -
# as FireCandleFlame's own 75000 blew our candle cards out to white on 2026-11-15 (supported hypothesis: the same
# cause). The layered clone takes LAYERED_EMITTANCE wherever the material sets an emittance (set_emittance): about what
# our own hearth flames had when the owner called them orange (5000 x Skyrim's multiple 1.5 x EMITTANCE_SCALE 0.3)
# Owner at 2000 (2026-11-16 10:14): still white. The clone (verified, the owner's sf_layeredfirev2.mat): emissive
# texture FireColumnTile_color, coloured only by LayeredEmissivityComponent.FirstLayerTint = (1, 0.949, 0.922), near
# white - the material's colour is that tint, not its texture. LAYERED_TINT: Skyrim's fire orange (GradFireExplosion's
# upper rows, the colour our orange v2 hearth baked in); the bright cores clip red first and read yellow
LAYERED_TINT = (1.0, 0.45, 0.12)
LAYERED_EMITTANCE = {"LuminousEmittance": "2000", "AdaptiveEmittance": "true", "ExposureOffset": "8",
                     "FirstLayerTint": {"Data": {"Value": {"Data": {"w": "1", "x": f"{LAYERED_TINT[0]:g}",
                                                                    "y": f"{LAYERED_TINT[1]:g}",
                                                                    "z": f"{LAYERED_TINT[2]:g}"},
                                                           "Type": "XMFLOAT4"}},
                                        "Type": "BSMaterial::Color", "Version": 1}}


def set_emittance(mat: dict, em: dict) -> int:
    """Every component of the material that sets LuminousEmittance (LayeredEmissivityComponent) gets the fields of `em`
    (emittance, and with LAYERED_EMITTANCE its emissive tint) instead; returns how many did."""
    n = 0
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            d = c.get("Data")
            if isinstance(d, dict) and "LuminousEmittance" in d:
                d.update(em)
                n += 1
    return n


def material_summary(mat: dict) -> dict:
    """What a cloned vanilla material is: its shader model, layers and texture files (for the build report)."""
    out = {"shader_model": None, "layers": [], "textures": [], "emittance": []}
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::ShaderModelComponent":
                out["shader_model"] = (c.get("Data") or {}).get("FileName")
            d = c.get("Data")
            if isinstance(d, dict) and "LuminousEmittance" in d:
                out["emittance"].append({k: d[k] for k in ("LuminousEmittance", "AdaptiveEmittance", "ExposureOffset")
                                         if k in d})
    summ = mat.get("Summary", {}) or {}
    for layer, d in summ.items():
        if isinstance(d, dict) and "Textures" in d:
            out["layers"].append(layer)
            out["textures"] += sorted({t.get("File") for t in d["Textures"].values() if isinstance(t, dict)
                                       and t.get("File")})
    return out


# ---------------------------------------------------------------------------------------------------------- textures
def palette_bake(rgba, palette, palette_color: bool, palette_alpha: bool, row: float = PALETTE_ROW,
                 tint=(1.0, 1.0, 1.0), alpha_row: Optional[float] = None):
    """Skyrim's greyscale-to-palette lookup baked into the texture: colour = palette(u = texture green, v = row),
    alpha = palette alpha(u = texture alpha, v = alpha_row, default row) (or the texture's own alpha); then the
    colour times `tint`. rgba, palette: (h, w, 4) uint8 arrays. Returns (h, w, 4) uint8."""
    import numpy as np
    out = rgba.astype(np.float32).copy()
    ph, pw = palette.shape[:2]

    def pick(v):
        return palette[min(ph - 1, max(0, int(round(v * (ph - 1)))))].astype(np.float32)      # (pw, 4)
    if palette_color:
        u = np.clip(np.round(rgba[:, :, 1].astype(np.float32) / 255.0 * (pw - 1)), 0, pw - 1).astype(np.int64)
        out[:, :, :3] = pick(row)[u][:, :, :3]
    if palette_alpha:
        u = np.clip(np.round(rgba[:, :, 3].astype(np.float32) / 255.0 * (pw - 1)), 0, pw - 1).astype(np.int64)
        out[:, :, 3] = pick(row if alpha_row is None else alpha_row)[u][:, :, 3]
    out[:, :, :3] *= np.array(tint[:3], np.float32)[None, None, :]
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------------- materials
EFFECT_TEMPLATE_MAT = "Materials/Effects/Fires/FiresGeneric_Sm_01_14x14.mat"   # 1LayerEffectEmissive, soft additive
# brightness = base x Skyrim's emissive multiple x EMITTANCE_SCALE (the multiple was baked into the colour before and
# clipped hearth flames to white; owner 2026-11-15: hearth cores white-hot beside Skyrim's orange)
# 2026-11-15 v3 in game: hearth particle cards read as "intense straight clots": dimmer, and the ring wider
EMITTANCE_SCALE = {"hearth": 0.3, "candle": 1.0}
RING = 0.85                          # flame card ring radius / emitter radius (v2 / v3: 0.55)
# flame styles (owner 2026-11-15, after v3: "maybe it is better to use Starfield's flame"): "skyrim" = Skyrim's
# textures on the cards (flames v3); "starfield" = the same cards (Skyrim's places, sizes, timing) playing Starfield's
# own fire flipbooks, cloned from its materials with their textures (vanilla files; nothing copied)
# "particles" (2026-11-15, owner on v3: "still low quality, like moving pngs compared to flames"): a hearth's flame
# particles become Starfield's own particle fire, the vanilla MSTT FireMed01 (00C78D: ParticleSystem_Component ->
# particles\fires\firemed01.psfx; sf_fire_probe.py) placed with every reference of the model at the emitter
# (PluginSpike sf_effects); the hearth's scrolling flame meshes (PARTICLE_REPLACES) are left out, the log glow stays;
# candles keep the Skyrim cards (Starfield's own candles are cards too)
# "layered" (2026-11-16, owner on spread FireMed02: "a few fireballs thrown in there, compared to Skyrim's that looks like
# a hearth burning. Do we need to figure out how Starfield fire pits work"). sf_firepit_probe on the owner's game
# (verified): Starfield has no fire-pit flame geometry - 36 of 54,651 NIFs name a fire material, all candles / a paper
# lantern except Firepit_Portable01 (the pit only: metal, gravel, rocks, wood; its STAT carries no particles, so its fire
# is a separately placed particle fire, as ours were) and two debug models: LayeredFireV2.mat on a 1 m box
# (effects\debugfiles\testmaterialbox.nif) and xTests\LayeredFire.mat on a teapot - a fire material made for any
# geometry. So "layered" keeps Skyrim's whole hearth layout (its scrolling flame meshes, UVs stretched to 0..1 per card
# by normalize_card_uvs, and the flame-particle cards) and burns it with LAYERED_FIRE_MAT cloned as it is (unresolved:
# how it looks on cards)
FLAME_STYLES = ("skyrim", "starfield", "particles", "layered")
LAYERED_FIRE_MAT = "Materials/Effects/Fires/LayeredFireV2.mat"
# owner's comparisons (2026-11-15 / 16): FireMed01 00C78D "three flares"; FXP_MemorialFire 004630 far too big even at
# x0.35 / x0.5; the Armistice Archives fire pit 20D560 does not show when placed; FireMed02 1CEDAB at x0.8 "looks better"
PARTICLE_FIRE_BASE = "1CEDAB"
PARTICLE_FIRE_SCALE = 0.8            # x the hearth reference's scale
# 2026-11-16 (owner, FireMed02 default in game): "one fireball in a hearth, or 3 in a big one, not an actual fire across
# the hearth": one fire per Skyrim emitter is a point; Skyrim's fire runs along the logs through its flame meshes.
# Fires now sit along the long side of the model's fire shapes (flame meshes + log glow), FIRE_SPACING apart, at most
# FIRE_MAX, each x SPREAD_SCALE when there are several
FIRE_SPACING = 24.5                  # Skyrim units (0.35 m)
FIRE_MAX = 4
SPREAD_SCALE = 0.75
PARTICLE_REPLACES = r"fxfireatlas"
# candle_style "starfield" (owner 2026-11-16: "use Starfield's for candles as well but make them follow Skyrim's thicker
# teardrop shape"): Starfield's FireCandleFlame flipbook kept whole (its textures, flipbook, emittance: what its own
# candles show) on one card per Skyrim flame, the card widened so the flame - a narrow strip in each frame - takes
# Skyrim's fuller teardrop (the "starfield" flame style on 2026-11-15 used Skyrim's card size and our emittance: "very
# small, not bright, quite thin")
CANDLE_STYLES = ("skyrim", "starfield", "soft")
# candle_style "soft" (2026-11-21, owner on Skyrim's candle cards: "the candles just look very low quality", crops: a
# small hard-edged pixelated sliver, no glow): Skyrim's CandleFlame01 is 128 x 128 with 2 x 2 frames (64 px a flame)
# stepped at 12 fps; Starfield's candle flipbook draws a thin streak ("a line of fire", 2026-11-16). So our own flame,
# drawn at build time (procedural_flame_atlas, no game asset): SOFT_GRID frames of SOFT_FRAME px, a smooth teardrop
# (white-yellow core, orange rim, faint blue foot) swaying and stretching through one loop, a soft halo around it,
# played as a flipbook at SOFT_FPS on Skyrim's cards made SOFT_CARD x larger (the flame drawn in the middle 1 / SOFT_CARD
# of the frame, so it keeps Skyrim's size and place; SOFT_FLAME_SCALE grows it)
SOFT_GRID = (4, 4)
SOFT_FRAME = (128, 256)              # px (width, height)
SOFT_FPS = 16.0                      # one sway loop a second
SOFT_CARD = (2.2, 1.6)               # card half width / height x Skyrim's flame card
SOFT_FLAME_SCALE = 1.15              # the flame itself x Skyrim's
SOFT_HALO = 0.3                     # halo opacity at the flame


def _smooth(e0, e1, x):
    import numpy as np
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def procedural_flame_frame(phase: float, size=SOFT_FRAME, card=SOFT_CARD, flame_scale=SOFT_FLAME_SCALE,
                           halo=SOFT_HALO):
    """One candle flame (RGBA uint8, straight alpha, `size` = (w, h) px, v = 0 at the top) at `phase` (0 .. 1 of its
    loop): a teardrop whose half width along its height y (0 = foot, 1 = tip) is sqrt(y) (1 - y)^0.9 (widest about a
    third up), the tip swaying and the height breathing with the phase; colour by depth into the flame and height
    (white-yellow core, orange rim, a faint blue foot); a soft orange halo around it. The flame fills the middle
    flame_scale / card of the frame (Skyrim's card inside our larger one)."""
    import numpy as np
    w, h = size
    xs = (np.arange(w) + 0.5) / w * 2 - 1                    # -1 .. 1 across the card
    ys = 1 - (np.arange(h) + 0.5) / h * 2                    # 1 at the top .. -1 at the bottom
    X, Y = np.meshgrid(xs, ys)
    cw, ch = card[0] / flame_scale, card[1] / flame_scale    # card / flame size ratios
    two_pi = 2 * math.pi
    stretch = 1.0 + 0.07 * math.sin(two_pi * phase * 2 + 0.7) + 0.04 * math.sin(two_pi * phase * 3 + 2.1)
    fy = (Y * ch + 1.0) / 2.0 / stretch                      # flame height coordinate: 0 foot .. 1 tip
    fx = X * cw                                              # flame width coordinate: +-1 = Skyrim's half width
    sway = (0.10 * math.sin(two_pi * phase) + 0.05 * np.sin(7.0 * fy + two_pi * phase * 2)) * np.clip(fy, 0, 1) ** 2
    prof = np.sqrt(np.clip(fy, 0, 1)) * np.clip(1 - fy, 0, 1) ** 0.9
    prof = prof / 0.5 * 0.85                                 # widest ~0.85 of Skyrim's half width (a candle teardrop)
    d = np.abs(fx - sway) / np.maximum(prof, 1e-4)           # 0 on the axis, 1 at the rim
    inside = (fy > 0) & (fy < 1)
    body = np.where(inside, _smooth(1.0, 0.55, d), 0.0)
    body *= _smooth(0.0, 0.06, fy) * _smooth(1.0, 0.82, fy)
    core = np.where(inside, _smooth(0.5, 0.05, d), 0.0) * _smooth(0.08, 0.25, fy) * _smooth(0.6, 0.3, fy)
    foot = np.where(inside, _smooth(0.9, 0.3, d), 0.0) * _smooth(0.22, 0.02, fy) * _smooth(-0.02, 0.04, fy)
    rim = np.array([1.0, 0.47, 0.12])
    mid = np.array([1.0, 0.66, 0.22])
    white = np.array([1.0, 0.96, 0.82])
    blue = np.array([0.30, 0.42, 1.0])
    col = rim[None, None] * (1 - body[..., None]) + mid[None, None] * body[..., None]
    col = col * (1 - core[..., None]) + white[None, None] * core[..., None]
    col = col * (1 - 0.6 * foot[..., None]) + blue[None, None] * 0.6 * foot[..., None]
    # halo: a soft round glow around the flame's lower middle (Skyrim's CandleGlow01 particles, left out of the cards so
    # far), in card coordinates so it is gone well inside the card's edges (a visible box otherwise)
    hy = -1.0 / ch + 0.7 / ch                              # card y of the flame's widest part
    r2 = (X / 0.5) ** 2 + ((Y - hy) / 0.42) ** 2
    glow = halo * np.exp(-r2 * 1.6) * (0.92 + 0.08 * math.sin(two_pi * phase * 2))
    alpha = np.clip(body * 0.95 + glow * (1 - body), 0, 1)
    halo_col = np.array([1.0, 0.55, 0.2])
    a_body = body * 0.95
    col = (col * a_body[..., None] + halo_col[None, None] * (glow * (1 - body))[..., None]) / \
        np.maximum(alpha[..., None], 1e-6)
    edge = _smooth(1.0, 0.85, np.abs(X)) * _smooth(1.0, 0.85, np.abs(Y))   # nothing at the card's edges
    alpha = alpha * edge
    rgba = np.concatenate([np.clip(col, 0, 1), alpha[..., None]], 2)
    return (rgba * 255 + 0.5).astype(np.uint8)


def procedural_flame_atlas(grid=SOFT_GRID, size=SOFT_FRAME, **kw):
    """grid (columns, rows) frames of procedural_flame_frame through one loop, row by row (the flipbook order)."""
    import numpy as np
    cols, rows = grid
    n = cols * rows
    frames = [procedural_flame_frame(k / n, size, **kw) for k in range(n)]
    return np.concatenate([np.concatenate(frames[r * cols:(r + 1) * cols], 1) for r in range(rows)], 0)
# owner 2026-11-16 08:52 at x1.8 / x1.1: "the candles are quite thin still"
# owner 2026-11-16 10:14, Starfield's own flame mesh at x3.0 / x1.25: a small thin flicker at the wick (Skyrim's flame on
# the same horn candle stands about as tall as the horn's cup is wide): x2 taller, wider still
SF_CANDLE_WIDTH = 7.0                # x Skyrim's card half width
SF_CANDLE_HEIGHT = 2.5               # x Skyrim's card half height
# Starfield's candle flame is not a card (sf_firepit_probe, verified): "Flame:0" in setdressing\candles\*_lit.nif is a
# 228-vertex, 336-triangle mesh with vertex colours, radially symmetric (x, y +-7.0, z +-8.46 before the shape's 0.002 -
# 0.003 scale: 2.8 - 4.2 cm wide), FireCandleFlame.mat on it. With candle_style "starfield" and --starfield-data the
# converter reads that mesh from the game at build time (not stored) and fits it to SF_CANDLE_WIDTH / _HEIGHT x Skyrim's
# flame (sf_flame_shape); without it, crossed cards as before
SF_CANDLE_MESH_NIF = "meshes/setdressing/candles/candlegen_c01_lit.nif"
SF_CANDLE_MESH_SHAPE = b"Flame:0"
STARFIELD_FLAMES = {"hearth": ("Materials/Effects/Fires/FiresGeneric_Sm_01_14x14.mat", (14, 14, 30.0)),
                    "candle": ("Materials/Effects/Fires/FireCandleFlame.mat", (12, 12, 90.0))}
EMITTANCE = {"hearth": {"LuminousEmittance": "5000", "AdaptiveEmittance": "true", "ExposureOffset": "8"},
             # 2026-11-15 (owner, in game): FireCandleFlame's fixed 75000 blew the candle cards out to white; candles
             # now take the hearth's adaptive setting until tuned
             "candle": {"LuminousEmittance": "5000", "AdaptiveEmittance": "true", "ExposureOffset": "8"}}


def _curve(points, loop_seconds: float) -> dict:
    """A BSFloatCurve (vanilla layout) through (input seconds, value) points; None points = no controls."""
    vals = [v for _t, v in points] or [0.0]
    return {"Data": {
        "Controls": {"Data": [{"Data": {"Input": f"{t:g}", "Value": f"{v:g}"}, "Type": "BSFloatCurve::Control"}
                              for t, v in points] or None,
                     "ElementType": "BSFloatCurve::Control", "Type": "<collection>"},
        "DefaultValue": "0", "Edge": "Clamp", "InputDistance": f"{loop_seconds:g}", "IsSampleInterpolating": "true",
        "MaxInput": f"{loop_seconds:g}", "MaxValue": f"{max(vals):g}", "MinInput": "0", "MinValue": f"{min(min(vals), 0):g}",
        "Type": "Linear"}, "Type": "BSFloatCurve"}


def _mapping(binding: str, controller: dict) -> dict:
    return {"Data": {"Address": {"Data": {"Path": {"Data": [binding], "ElementType": "BSFixedString",
                                                   "Type": "<collection>"}}, "Type": "BSBind::Address"},
                     "Controller": {"Data": controller, "Type": "<ref>"}},
            "Type": "BSBind::Controllers::Mapping"}


def scroll_controller(axis: str, delta: float, period: float) -> dict:
    """Float2DCurveController on UVOffset: the axis goes 0 -> delta over `period` seconds, looping."""
    moving = _curve([(0.0, 0.0), (period, delta)], period)
    still = _curve([], period)
    return {"Data": {"Curve": {"Data": {"XCurve": moving if axis == "U" else still,
                                        "YCurve": moving if axis == "V" else still}, "Type": "BSFloat2DCurve"},
                     "Loop": "true", "Mask": "X;Y"}, "Type": "BSBind::Float2DCurveController"}


def flicker_controller(emittance: float, period: float, depth: float = 0.3) -> dict:
    """FloatCurveController on EmissiveIntensity: an uneven flicker between (1 - depth) and 1 times the emittance
    (vanilla FireCandleGlow flickers 29812 .. 45000)."""
    shape = (1.0, 0.82, 0.95, 0.7, 1.0, 0.88, 0.76, 0.97, 1.0)
    pts = [(period * k / (len(shape) - 1), emittance * (1.0 - depth * (1.0 - s) / 0.3)) for k, s in enumerate(shape)]
    return {"Data": {"Curve": _curve(pts, period), "Loop": "true"}, "Type": "BSBind::FloatCurveController"}


def _directory(bindings) -> dict:
    return {"Data": {"upDir": {"Data": {"Data": {"Children": {"Data": [
        {"Data": {"Key": b, "Value": {"Data": {"Data": {"Binding": b, "LayerIndex": "0", "Name": b},
                                               "Type": "BSMaterialBinding::MaterialPropertyNode"}, "Type": "<ref>"}},
         "Type": "StdMapType::Pair"} for b in bindings],
        "ElementType": "StdMapType::Pair", "Type": "<collection>"}, "Name": "", "SourceDirectoryHash": "0"},
        "Type": "BSBind::Directory"}, "Type": "<ref>"}}, "Index": 0, "Type": "BSBind::DirectoryComponent", "Version": 2}


def crossfade_controller(period: float, phase: int, lo_hi=CROSSFADE) -> dict:
    """FloatCurveController on OverallOpacity: up and down between lo and hi over `period`; phase 1 is the mirror image
    of phase 0, so two layers trade places (a stand-in for Skyrim's particles being born and fading)."""
    lo, hi = lo_hi
    a, b = (hi, lo) if phase == 0 else (lo, hi)
    return {"Data": {"Curve": _curve([(0.0, a), (period * 0.5, b), (period, a)], period), "Loop": "true"},
            "Type": "BSBind::FloatCurveController"}


def effect_material(template: dict, name: str, files: dict, kind: str = "hearth",
                    scroll: Optional[Tuple[str, float, float]] = None, flicker: Optional[float] = None,
                    vertex_color: bool = False, flipbook: Optional[Tuple[int, int, float]] = None,
                    multiple: float = 1.0, crossfade: Optional[Tuple[float, int]] = None,
                    keep_emittance: bool = False) -> dict:
    """An emissive effect material cloned from the vanilla fire template (convert_material.build_from_template):
    files {"Albedo", "Emissive", "Opacity": game paths}; EMITTANCE[kind]; controllers for a UV scroll (axis, delta,
    seconds) and / or a flicker (loop seconds). flipbook (columns, rows, fps): the atlas plays as a looping flipbook
    driven by a TimerController on FlipbookAuto, as vanilla FireCandleFlame.mat; without it the template's flipbook
    is removed (a single-frame texture). Emittance = EMITTANCE[kind] x multiple x EMITTANCE_SCALE[kind];
    crossfade (period, phase): an OverallOpacity curve (crossfade_controller); keep_emittance: the template's own
    emissivity stays (a vanilla material used as it is)."""
    from . import convert_material as cm
    mat = cm.build_from_template(template, name, files)
    for o in mat["Objects"]:
        comps = []
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::FlipbookComponent":
                if not flipbook:
                    continue
                cols, rows, fps = flipbook
                c["Data"] = {"Columns": str(int(cols)), "FPS": f"{fps:g}", "IsAFlipbook": "true", "Loops": "true",
                             "Rows": str(int(rows))}
            comps.append(c)
        o["Components"] = comps
    root = mat["Objects"][0]["Components"]
    em = dict(EMITTANCE[kind])
    em["LuminousEmittance"] = f"{float(em['LuminousEmittance']) * multiple * EMITTANCE_SCALE[kind]:g}"
    for c in root:
        if c.get("Type") == "BSMaterial::LayeredEmissivityComponent" and not keep_emittance:
            c["Data"] = {k: v for k, v in c["Data"].items() if k not in ("LuminousEmittance", "AdaptiveEmittance",
                                                                          "ExposureOffset")}
            c["Data"].update(em)
        if c.get("Type") == "BSMaterial::EffectSettingsComponent" and vertex_color:
            c["Data"]["VertexColorBlend"] = "true"
    root[:] = [c for c in root if c.get("Type") not in ("BSBind::DirectoryComponent", "BSBind::ControllerComponent")]
    maps, binds = [], []
    if scroll:
        maps.append(_mapping("UVOffset", scroll_controller(*scroll)))
        binds.append("UVOffset")
    if flicker:
        maps.append(_mapping("EmissiveIntensity", flicker_controller(float(em["LuminousEmittance"]), flicker)))
        binds.append("EmissiveIntensity")
    if flipbook:
        maps.append(_mapping("FlipbookAuto", {"Data": None, "Type": "BSBind::TimerController"}))
        binds.append("FlipbookAuto")
    if crossfade:
        maps.append(_mapping("OverallOpacity", crossfade_controller(*crossfade)))
        binds.append("OverallOpacity")
    if maps:
        root.insert(1, _directory(binds))
        root.insert(2, {"Data": {"upControllers": {"Data": {"Data": {
            "MappingsA": {"Data": maps, "ElementType": "BSBind::Controllers::Mapping", "Type": "<collection>"},
            "UseRandomOffset": "true"}, "Type": "BSBind::Controllers"}, "Type": "<ref>"}},
            "Index": 0, "Type": "BSBind::ControllerComponent"})
    return mat


def dumps(mat: dict) -> str:
    return json.dumps(mat, indent="\t", separators=(",", " : "), ensure_ascii=False)
