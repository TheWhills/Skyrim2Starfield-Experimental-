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
GLOW_RADIUS = 10.0                   # units: particle systems bigger than this are halos (CandleGlow01: 80), not cards
PALETTE_ROW = 1.0                    # v of the palette row used (0 top .. 1 bottom); unresolved, see module doc


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
            systems[i] = {"block": i, "type": n.type_of(i), "name": name,
                          "shader_block": sh[0] if sh else None,
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
    return list(systems.values())


def particle_flame(system: dict) -> Optional[dict]:
    """What a flame particle system looks like as one card: {texture, half_w, half_h, lift, color} in Skyrim units
    (lift = the card centre above the emitter: half the rise over a particle's life). None for halos (radius over
    GLOW_RADIUS), systems without an emitter, and non-fire textures."""
    em = next((m["fields"] for m in system["modifiers"] if m.get("type") in EMITTERS and "fields" in m), None)
    tex = system["textures"][0] if system["textures"] else ""
    if em is None or not re.search(FIRE_EFFECT, tex, re.I) or em["radius"] > GLOW_RADIUS:
        return None
    scales = next((m.get("scales") for m in system["modifiers"] if m.get("type") == "BSPSysScaleModifier"), None)
    smax = max(scales) if scales else 1.0
    col = next((m["fields"] for m in system["modifiers"] if m.get("type") == "BSPSysSimpleColorModifier"), None)
    color = (col["c2r"], col["c2g"], col["c2b"]) if col else (1.0, 1.0, 1.0)
    rise = em["speed"] * em["life_span"]
    half_w = em["radius"] * smax
    return {"texture": tex, "half_w": half_w, "half_h": half_w + rise * 0.25, "lift": rise * 0.5,
            "color": tuple(min(1.0, max(0.0, c)) for c in color), "life": em["life_span"], "name": system["name"]}


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
def crossed_cards(center, half_w: float, half_h: float, planes: int = 3, name: bytes = b"Flame") -> nifmod.Fo4Shape:
    """`planes` vertical quads through `center` (Skyrim units), evenly turned about z, double-sided: a flame seen from
    any side (Starfield's own candle flames are static geometry too). UV v = 0 at the top (the flame's tip)."""
    cx, cy, cz = center
    pos, uvs, nor, tan, tris = [], [], [], [], []
    for k in range(planes):
        a = math.pi * k / planes
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        for side in (1, -1):                       # front, then the back face (mirrored so the texture reads right)
            base = len(pos)
            for s, top in ((-1, False), (1, False), (1, True), (-1, True)):
                pos.append((cx + s * half_w * dx, cy + s * half_w * dy, cz + (half_h if top else -half_h)))
                u = (s + 1) * 0.5 if side == 1 else (1 - s) * 0.5
                uvs.append((u, 0.0 if top else 1.0))
                nor.append((nx * side, ny * side, 0.0))
                tan.append((dx * side, dy * side, 0.0))
            if side == 1:                          # winding agrees with the normal by the right-hand rule
                tris += [(base, base + 2, base + 1), (base, base + 3, base + 2)]
            else:
                tris += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return nifmod.Fo4Shape(name, (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0, -1, -1, -1, pos, uvs, nor, tan,
                           [(255, 255, 255, 255)] * len(pos), tris, False)


# ---------------------------------------------------------------------------------------------------------- textures
def palette_bake(rgba, palette, palette_color: bool, palette_alpha: bool, row: float = PALETTE_ROW,
                 tint=(1.0, 1.0, 1.0)):
    """Skyrim's greyscale-to-palette lookup baked into the texture: colour = palette(u = texture green, v = row),
    alpha = palette alpha(u = texture alpha, v = row) (or the texture's own alpha); then times the effect's
    emissive colour. rgba, palette: (h, w, 4) uint8 arrays. Returns (h, w, 4) uint8."""
    import numpy as np
    out = rgba.astype(np.float32).copy()
    ph, pw = palette.shape[:2]
    pr = palette[min(ph - 1, max(0, int(round(row * (ph - 1)))))].astype(np.float32)      # (pw, 4)
    if palette_color:
        u = np.clip(np.round(rgba[:, :, 1].astype(np.float32) / 255.0 * (pw - 1)), 0, pw - 1).astype(np.int64)
        out[:, :, :3] = pr[u][:, :, :3]
    if palette_alpha:
        u = np.clip(np.round(rgba[:, :, 3].astype(np.float32) / 255.0 * (pw - 1)), 0, pw - 1).astype(np.int64)
        out[:, :, 3] = pr[u][:, :, 3]
    out[:, :, :3] *= np.array(tint[:3], np.float32)[None, None, :]
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------------- materials
EFFECT_TEMPLATE_MAT = "Materials/Effects/Fires/FiresGeneric_Sm_01_14x14.mat"   # 1LayerEffectEmissive, soft additive
EMITTANCE = {"hearth": {"LuminousEmittance": "5000", "AdaptiveEmittance": "true", "ExposureOffset": "8"},
             "candle": {"LuminousEmittance": "75000", "AdaptiveEmittance": "false"}}   # FiresGeneric / FireCandleFlame


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


def effect_material(template: dict, name: str, files: dict, kind: str = "hearth",
                    scroll: Optional[Tuple[str, float, float]] = None, flicker: Optional[float] = None,
                    vertex_color: bool = False) -> dict:
    """An emissive effect material cloned from the vanilla fire template (convert_material.build_from_template):
    files {"Albedo", "Emissive", "Opacity": game paths}; the template's flipbook removed (Skyrim's textures are single
    frames); EMITTANCE[kind]; controllers for a UV scroll (axis, delta, seconds) and / or a flicker (loop seconds)."""
    from . import convert_material as cm
    mat = cm.build_from_template(template, name, files)
    for o in mat["Objects"]:
        o["Components"] = [c for c in o.get("Components", []) if c.get("Type") != "BSMaterial::FlipbookComponent"]
    root = mat["Objects"][0]["Components"]
    em = EMITTANCE[kind]
    for c in root:
        if c.get("Type") == "BSMaterial::LayeredEmissivityComponent":
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
    if maps:
        root.insert(1, _directory(binds))
        root.insert(2, {"Data": {"upControllers": {"Data": {"Data": {
            "MappingsA": {"Data": maps, "ElementType": "BSBind::Controllers::Mapping", "Type": "<collection>"},
            "UseRandomOffset": "true"}, "Type": "BSBind::Controllers"}, "Type": "<ref>"}},
            "Index": 0, "Type": "BSBind::ControllerComponent"})
    return mat


def dumps(mat: dict) -> str:
    return json.dumps(mat, indent="\t", separators=(",", " : "), ensure_ascii=False)
