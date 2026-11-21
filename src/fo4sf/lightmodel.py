"""How much light Skyrim and Starfield put on a surface: the models the lighting audit (scripts/interior/light_audit.py)
compares, and later the converter's light fit. docs/interior/lighting-model.md has the evidence for each part.

Skyrim (verified for the point lights, Community Shaders' package/Shaders/Lighting.hlsl, the vanilla path without its
light-limit fix): a point light adds colour x (1 - (d / radius)^2) x max(0, N.L), nothing past the radius, no inverse
square; the colour is the LIGH colour (0..1) x its fade (supported: the engine fills PointLightColor with the fade
applied; the fix's own path multiplies light.fade explicitly). Lighting happens on gamma-space values (no
linearisation in the vanilla path). Ambient: the shader's DirectionalAmbient is a 3 x 4 matrix applied to (N, 1)
(verified), built from the cell's six directional ambient colours (how: supported hypothesis, AMBIENT_FIT below).
The cell's directional light: colour x directional fade x max(0, N.L) (direction from the XCLL rotations: hypothesis).

Starfield: physically based (lumens, metres). Its falloff is NOT known yet; STARFIELD_FALLOFF names the hypothesis in use
until the calibration cell measures it (docs/interior/lighting-model.md)."""
import math

UNITS_PER_M = 70.0
AXES = ("x+", "x-", "y+", "y-", "z+", "z-")


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n) if n > 0 else (0.0, 0.0, 0.0)


def skyrim_point(light: dict, light_pos, p, n=(0.0, 0.0, 1.0)) -> tuple:
    """RGB (0..1+, gamma space) one Skyrim light adds at point p (game units) on a surface facing n: colour x fade x
    (1 - (d / r)^2) x max(0, N.L). fade = the base's fade + the reference's XLIG fade offset (ref_fade_delta;
    supported hypothesis that it adds). Off-by-default lights add nothing."""
    if light.get("off_by_default"):
        return (0.0, 0.0, 0.0)
    r = float(light.get("radius") or 0.0)
    v = _sub(light_pos, p)
    d = math.sqrt(_dot(v, v))
    if r <= 0 or d >= r:
        return (0.0, 0.0, 0.0)
    att = 1.0 - (d / r) ** 2
    ndl = max(0.0, _dot(n, _norm(v))) if d > 0 else 1.0
    fade = max(0.0, float(light.get("fade", 1.0)) + float(light.get("ref_fade_delta", 0.0)))
    k = fade * att * ndl / 255.0
    c = light.get("color") or (255, 255, 255)
    return (c[0] * k, c[1] * k, c[2] * k)


def ambient_fit(amb6: dict) -> tuple:
    """AMBIENT_FIT (supported hypothesis): the linear (constant + N-weighted) function a 3 x 4 matrix can hold that
    agrees with the six colours on average: constant = their mean, the N.x weight = (X+ - X-) / 2, and so on. Returns
    (constant RGB, [x, y, z] weight RGBs), 0..1."""
    c = [[v / 255.0 for v in amb6[a][:3]] for a in AXES]
    const = tuple(sum(c[i][ch] for i in range(6)) / 6.0 for ch in range(3))
    w = [tuple((c[2 * k][ch] - c[2 * k + 1][ch]) / 2.0 for ch in range(3)) for k in range(3)]
    return const, w


def skyrim_ambient(lighting: dict, n=(0.0, 0.0, 1.0)) -> tuple:
    """RGB ambient on a surface facing n: the directional ambient through ambient_fit; a cell without the six colours
    takes its single ambient colour."""
    amb6 = lighting.get("directional_ambient")
    if amb6 and any(any(v) for v in amb6.values()):
        const, w = ambient_fit(amb6)
        return tuple(max(0.0, const[ch] + n[0] * w[0][ch] + n[1] * w[1][ch] + n[2] * w[2][ch]) for ch in range(3))
    a = lighting.get("ambient") or (0, 0, 0)
    return (a[0] / 255.0, a[1] / 255.0, a[2] / 255.0)


def directional_vector(rotation) -> tuple:
    """Unit vector toward the cell's directional light from XCLL Directional Rotation XY / Z (degrees). Hypothesis:
    XY = heading about the vertical, Z = elevation above the horizon."""
    rxy, rz = (math.radians(float(v)) for v in (rotation or (0, 0)))
    return (math.cos(rz) * math.sin(rxy), math.cos(rz) * math.cos(rxy), math.sin(rz))


def skyrim_directional(lighting: dict, n=(0.0, 0.0, 1.0)) -> tuple:
    c = lighting.get("directional") or (0, 0, 0)
    k = max(0.0, _dot(n, directional_vector(lighting.get("directional_rotation")))) * \
        float(lighting.get("directional_fade", 1.0)) / 255.0
    return (c[0] * k, c[1] * k, c[2] * k)


def skyrim_light_at(lighting: dict, lights, p, n=(0.0, 0.0, 1.0)) -> dict:
    """{"ambient", "directional", "points", "total"}: RGB at p from each part (lights: [(light dict, pos)])."""
    amb = skyrim_ambient(lighting or {}, n)
    dl = skyrim_directional(lighting or {}, n)
    pts = [0.0, 0.0, 0.0]
    for light, pos in lights:
        c = skyrim_point(light, pos, p, n)
        for ch in range(3):
            pts[ch] += c[ch]
    tot = tuple(amb[ch] + dl[ch] + pts[ch] for ch in range(3))
    return {"ambient": amb, "directional": dl, "points": tuple(pts), "total": tot}


def luma(rgb) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def srgb_to_linear(v: float) -> float:
    """Skyrim lights in gamma space: what reaches the screen as v (0..1) is linear v^2.2-ish (sRGB curve)."""
    v = max(0.0, min(1.0, v))
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


# Hypothesis H1 until measured: a windowed inverse square as in other physically based engines (UE4 / Frostbite):
# E = lm / (4 pi d^2) x clamp(1 - (d / R)^4, 0, 1)^2, d at least NEAR_M
STARFIELD_FALLOFF = "H1 windowed inverse square (unmeasured)"
NEAR_M = 0.1


def starfield_point(lumens: float, radius_m: float, light_pos_units, p_units, n=(0.0, 0.0, 1.0)) -> float:
    """Illuminance (lux) under H1 at p (game units) on a surface facing n."""
    v = _sub(light_pos_units, p_units)
    d = max(NEAR_M, math.sqrt(_dot(v, v)) / UNITS_PER_M)
    if radius_m <= 0 or d >= radius_m:
        return 0.0
    win = max(0.0, 1.0 - (d / radius_m) ** 4) ** 2
    ndl = max(0.0, _dot(n, _norm(v)))
    return lumens / (4 * math.pi * d * d) * win * ndl


# --- Skyrim's eye adaptation, baked into each room's lights (2026-11-21) ---------------------------------------------
# Starfield's image space for our interiors (LGT_NoLut 1C6C37) holds a FIXED exposure (EXPOSURE_MODE_FIXED, EV 5;
# verified, the owner's imgsdump decoded), so Starfield never brightens a dark room. Skyrim's HDR pass scales every frame
# by its adapted average (ISHDR.hlsl, verified) with eye adaptation on in every Riverwood room (FarmInteriorIS, strength
# 1.5): a dark room comes up, a bright one down (the owner's screens: Skyrim's inn as bright as the houses with half their
# light). So the converter scales each room's lights by ADAPT_REF / the room's mean Skyrim light (linear), to the
# ADAPT_STRENGTH power (1 = Skyrim fully evens rooms out: supported hypothesis, how strength 1.5 maps is unresolved).
# ADAPT_REF: the Riverwood houses' mean (0.51 - 0.62; the owner's houses sit within a stop of Skyrim's screens as they are)
ADAPT_REF = 0.55
ADAPT_STRENGTH = 1.0
ADAPT_LIMITS = (0.125, 8.0)
SAMPLE_LIFT = 10.0               # units above an object's origin, facing up
SKIP_SAMPLE_BASES = {"COCMarkerHeading"}


def sample_points(refs) -> list:
    """Where a room's light is measured: just above every enabled, modelled, non-light reference (facing up)."""
    return [(r["pos"][0], r["pos"][1], r["pos"][2] + SAMPLE_LIFT) for r in refs
            if r.get("type") != "Light" and r.get("model") and r.get("base_editor_id") not in SKIP_SAMPLE_BASES
            and not r.get("disabled")]


def room_mean_linear(lighting: dict, refs) -> float:
    """The room's mean Skyrim light (luma, linearised, clipped at 1) over sample_points; None without points."""
    lights = [(r["light"], r["pos"]) for r in refs if r.get("type") == "Light" and r.get("light") and not r.get("disabled")]
    pts = sample_points(refs)
    if not pts:
        return None
    vals = [srgb_to_linear(min(1.0, luma(skyrim_light_at(lighting or {}, lights, p)["total"]))) for p in pts]
    return sum(vals) / len(vals)


def adaptation_scale(mean_linear, ref=ADAPT_REF, strength=ADAPT_STRENGTH, limits=ADAPT_LIMITS) -> float:
    """What the room's lights are multiplied by so it lands where Skyrim's eye adaptation puts it: (ref / mean)^strength,
    within limits; 1 when the room has no measurable light."""
    if not mean_linear or mean_linear <= 0:
        return 1.0
    return max(limits[0], min(limits[1], (ref / mean_linear) ** strength))


# --- Skyrim's ambient as the cell's environment light (2026-11-21) ------------------------------------------------------
# The owner's screens after the adaptation bake: the bright parts of each room within 1 - 2 stops of Skyrim, the dark
# parts (stairs, corners) 5 - 6 stops under. Skyrim's ambient lights every surface (4 - 20 % of its light on objects,
# all of it where no light reaches). Our cells give Starfield a black environment cube (PluginSpike, blackcube.dds: a
# default sky washed the rooms out), so supported hypothesis: no ambient at all in Starfield. Here the cell's cube is
# Skyrim's ambient instead: its six directional colours averaged (one colour on every face until the face order is
# verified), linearised, x the room's adaptation, x ENV_AMBIENT_SCALE (Starfield radiance per linear unit: unresolved;
# 38 is 1.2 x 2^5, what EV100 5, our fixed exposure, maps to white)
# owner 2026-11-21 13:56 (auto exposure EV100 4 .. 8): bright ends of the inn views within 1.3 stops of Skyrim, dark
# ends 4.8 - 5.7 stops under, contrast (sd log2) 2.5 - 3.1 against Skyrim's 1.2 - 1.8: the fill is too weak against
# the lights. 38 -> 150 (2 stops)
ENV_AMBIENT_SCALE = 150.0


def ambient_env(lighting: dict, room_scale: float = 1.0, scale: float = ENV_AMBIENT_SCALE) -> tuple:
    """Linear RGB radiance for the cell's environment cube from Skyrim's ambient (lighting: skyrim_lighting)."""
    amb6 = (lighting or {}).get("directional_ambient")
    if amb6 and any(any(v) for v in amb6.values()):
        g = [sum(amb6[a][ch] for a in AXES) / 6.0 / 255.0 for ch in range(3)]
    else:
        a = (lighting or {}).get("ambient") or (0, 0, 0)
        g = [a[ch] / 255.0 for ch in range(3)]
    return tuple(round(srgb_to_linear(v) * room_scale * scale, 5) for v in g)
