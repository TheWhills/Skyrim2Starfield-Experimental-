"""Skyrim's directional snow baked into converted objects (2026-11-25, docs/terrain/skyrim-objects.md "Snow on rocks").

Skyrim draws snow on up-facing surfaces of statics whose base names a directional material (STAT DNAM: max angle +
MATO; skyrimrefs.directional_materials). Starfield has no such object shader and ignores the per-cell global layer
outdoors (owner's test). Its own snow-on-rock material blends a snow layer over the object by the vertex colour
(convert_material.SNOW_TEMPLATE_MAT: Blender VertexAlpha, channel Red). So each snowy model gets a variant whose
vertex colours carry a snow mask computed from the vertex normals: turning about the vertical axis does not change
which faces point up, only tilt does (variants per tilt, see tilt_key).

Weight (2026-11-25, after the owner's side-by-sides showed whole cliffs white): Skyrim's own formula as Community
Shaders' re-implementation of SSE's lighting shader has it (Lighting.hlsl, PROJECTED_UV; a supported hypothesis, not
Bethesda's binary):
  w = smoothstep(0, 1, 5 * (0.1 + dot(normal, dir) * vertex alpha - bias - scale * noise))
with dir the material's projection axis (MATO DATA floats 4-6), the mesh's own painted vertex alpha (Skyrim's mountain
skirts carry 0 there), bias / scale = MATO falloff bias / scale and noise a world-space noise texture (0..1), here its
mean 0.5 (per vertex). dir = minus the projection vector (SnowMaterialObject1P projects along (0, 0, -1): snow
from above, as on Skyrim's boulders). A material whose dir points down (SnowMaterialMountain1P projects along
(0, 0, +1)) gets no baked snow: Skyrim's cliffs with it show rock and their texture-painted snow (owner's
side-by-sides, 2026-11-25; with the axis read as "upper end" they came out ~75 % white). A supported hypothesis.
The base's DNAM max angle still cuts off faces further than it from dir. The earlier clamp((d - bias) / scale) put Mountain*1P snow (bias 0.2, scale 0.3) on
every face up to 60 degrees from vertical, straight up.
"""
import dataclasses
import math
from typing import Optional, Tuple

DEFAULT_FALLOFF = (0.35, 0.4)        # (scale, bias): SnowMaterialObject1P, MATO DATA floats 0 and 1
NOISE_MEAN = 0.5


def snow_dir(projection) -> Optional[Tuple[float, float, float]]:
    """The direction snow comes from: minus the material's projection vector, normalised; None when that points
    down or the vector is zero (no baked snow)."""
    x, y, z = (-float(c) for c in projection)
    ln = math.sqrt(x * x + y * y + z * z)
    if ln < 1e-9 or z <= 1e-6:
        return None
    return x / ln, y / ln, z / ln


def mask(d: float, scale: float, bias: float, max_angle_deg: float = 90.0, alpha: float = 1.0,
         noise: float = NOISE_MEAN) -> float:
    """Snow weight 0..1 for a surface whose normal has dot d with the projection axis (Skyrim's smoothstep)."""
    if d < math.cos(math.radians(min(max(max_angle_deg, 0.0), 180.0))) - 1e-9:
        return 0.0
    x = min(1.0, max(0.0, 5.0 * (0.1 + d * alpha - bias - scale * noise)))
    return x * x * (3.0 - 2.0 * x)


def _mv(a, v):
    return tuple(a[3 * r] * v[0] + a[3 * r + 1] * v[1] + a[3 * r + 2] * v[2] for r in range(3))


def with_snow(shape, up_model: Tuple[float, float, float], scale: float, bias: float, max_angle_deg: float = 90.0):
    """The shape with its vertex colours' red and alpha set to the snow weight (green / blue kept, 255 when the shape
    had no colours). up_model: the projection axis in the model's frame (a tilted reference: R^T dir). Normals go
    through the shape's own rotation into the model frame; the shape's own vertex alpha (Skyrim's painted snow limit)
    multiplies the dot, as in Skyrim. A shape without normals is returned unchanged (no snow)."""
    if not shape.normals:
        return shape
    rot = shape.rotation
    cols = list(shape.colors) if shape.colors and len(shape.colors) == len(shape.positions) else None
    out = []
    for i, n in enumerate(shape.normals):
        m = _mv(rot, n)
        ln = math.sqrt(m[0] * m[0] + m[1] * m[1] + m[2] * m[2])
        d = (m[0] * up_model[0] + m[1] * up_model[1] + m[2] * up_model[2]) / ln if ln > 1e-9 else 0.0
        if not math.isfinite(d):                    # a degenerate (NaN) normal: no snow (SPatioWallEntrance.nif)
            d = 0.0
        alpha = cols[i][3] / 255.0 if cols else 1.0
        v = int(round(255 * mask(d, scale, bias, max_angle_deg, alpha)))
        g, b = (cols[i][1], cols[i][2]) if cols else (255, 255)
        out.append((v, g, b, v))
    return dataclasses.replace(shape, colors=out)


def in_model(m, v) -> Tuple[float, float, float]:
    """A world vector in a reference's model frame: R^T v (m row-major, exterior.ref_matrix)."""
    return (m[0] * v[0] + m[3] * v[1] + m[6] * v[2], m[1] * v[0] + m[4] * v[1] + m[7] * v[2],
            m[2] * v[0] + m[5] * v[1] + m[8] * v[2])


def tilt_key(m, step_deg: float = 15.0, world_dir=(0.0, 0.0, 1.0)) -> Tuple[int, int]:
    """(tilt bucket, direction bucket) of the projection axis world_dir seen in a reference's model frame (m:
    row-major rotation, exterior.ref_matrix): its angle from the model's up in step_deg buckets and, when tilted, its
    compass direction in buckets of about step_deg along the circle. (0, 0) = straight up in the model."""
    up = in_model(m, world_dir)
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, up[2]))))
    tb = int(round(tilt / step_deg))
    if tb == 0:
        return 0, 0
    n = max(1, int(round(360.0 * math.sin(math.radians(tb * step_deg)) / step_deg)))
    az = math.degrees(math.atan2(up[1], up[0])) % 360.0
    return tb, int(round(az / (360.0 / n))) % n


def tilt_up(key: Tuple[int, int], step_deg: float = 15.0) -> Tuple[float, float, float]:
    """The up vector (model frame) at the centre of a tilt_key bucket."""
    tb, ab = key
    if tb == 0:
        return 0.0, 0.0, 1.0
    t = math.radians(tb * step_deg)
    n = max(1, int(round(360.0 * math.sin(t) / step_deg)))
    a = math.radians(ab * 360.0 / n)
    return math.sin(t) * math.cos(a), math.sin(t) * math.sin(a), math.cos(t)


SNOW_REPEAT_UNITS = 2048.0 / 12.0     # Skyrim's snow material UV scale (MATO DATA float 3: 170.667), = its ground


def snow_uv_scale(shape, repeat_units: float = SNOW_REPEAT_UNITS, step: float = 0.25) -> float:
    """The snow layer's UV scale on a shape so that Skyrim's snow repeats every repeat_units of model space, as on
    Skyrim's rocks and ground: the shape's own texture repeat (sqrt(area / UV area), Skyrim units) / repeat_units,
    rounded to step (fewer materials), at least step. 1.0 for a shape without UVs."""
    pos, uvs, tri = shape.positions, shape.uvs, shape.triangles
    if not uvs or not tri:
        return 1.0
    s = float(getattr(shape, "scale", 1.0) or 1.0)
    area = uv = 0.0
    for a, b, c in tri:
        p, q, r = pos[a], pos[b], pos[c]
        u = (q[0] - p[0], q[1] - p[1], q[2] - p[2])
        v = (r[0] - p[0], r[1] - p[1], r[2] - p[2])
        cx, cy, cz = u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]
        area += 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz) * s * s
        uv += 0.5 * abs((uvs[b][0] - uvs[a][0]) * (uvs[c][1] - uvs[a][1]) - (uvs[b][1] - uvs[a][1]) * (uvs[c][0] - uvs[a][0]))
    if not (math.isfinite(uv) and math.isfinite(area)) or uv <= 0 or area <= 0:
        return 1.0                                  # degenerate data (NaN in SPatioWallEntrance.nif)
    k = math.sqrt(area / uv) / repeat_units
    return max(step, round(k / step) * step)


def falloff(mato_data: Optional[bytes]) -> Tuple[float, float]:
    """(scale, bias) from a MATO DATA field (floats 0 and 1); DEFAULT_FALLOFF when missing."""
    import struct
    if not mato_data or len(mato_data) < 8:
        return DEFAULT_FALLOFF
    return struct.unpack_from("<2f", mato_data)
