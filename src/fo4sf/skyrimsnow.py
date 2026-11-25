"""Skyrim's directional snow baked into converted objects (2026-11-25, docs/terrain/skyrim-objects.md "Snow on rocks").

Skyrim draws snow on up-facing surfaces of statics whose base names a directional material (STAT DNAM: max angle +
MATO; skyrimrefs.directional_materials). Starfield has no such object shader and ignores the per-cell global layer
outdoors (owner's test). Its own snow-on-rock material blends a snow layer over the object by the vertex colour
(convert_material.SNOW_TEMPLATE_MAT: Blender VertexAlpha, channel Red). So each snowy model gets a variant whose
vertex colours carry a snow mask computed from the vertex normals: turning about the vertical axis does not change
which faces point up, only tilt does (variants per tilt, see tilt_key).

Mask (an approximation; Skyrim's exact falloff formula is not known): with d = dot(world normal, up),
  mask = clamp((d - bias) / scale, 0, 1), and 0 where the normal is more than the base's max angle from up.
bias / scale come from the MATO (SnowMaterialObject1P: falloff bias 0.4, scale 0.35 -> snow from d 0.4, full from
d 0.75, i.e. from about 66 degrees to 41 degrees off vertical).
"""
import dataclasses
import math
from typing import Optional, Tuple

DEFAULT_FALLOFF = (0.35, 0.4)        # (scale, bias): SnowMaterialObject1P, MATO DATA floats 0 and 1


def mask(d: float, scale: float, bias: float, max_angle_deg: float = 90.0) -> float:
    """Snow amount 0..1 for a surface whose normal has dot d with world up."""
    if d < math.cos(math.radians(min(max(max_angle_deg, 0.0), 180.0))) - 1e-9:
        return 0.0
    s = max(scale, 1e-6)
    return min(1.0, max(0.0, (d - bias) / s))


def _mv(a, v):
    return tuple(a[3 * r] * v[0] + a[3 * r + 1] * v[1] + a[3 * r + 2] * v[2] for r in range(3))


def with_snow(shape, up_model: Tuple[float, float, float], scale: float, bias: float, max_angle_deg: float = 90.0):
    """The shape with its vertex colours' red and alpha set to the snow mask (green / blue kept, 255 when the shape had
    no colours). up_model: world up expressed in the model's frame (a tilted reference: R^T z). Normals go through the
    shape's own rotation into the model frame. A shape without normals is returned unchanged (no snow)."""
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
        v = int(round(255 * mask(d, scale, bias, max_angle_deg)))
        g, b = (cols[i][1], cols[i][2]) if cols else (255, 255)
        out.append((v, g, b, v))
    return dataclasses.replace(shape, colors=out)


def tilt_key(m, step_deg: float = 15.0) -> Tuple[int, int]:
    """(tilt bucket, direction bucket) of a reference's rotation matrix (row-major, exterior.ref_matrix): world up in
    the model frame (R^T z = row 3), its angle from the model's up in step_deg buckets and, when tilted, its compass
    direction in buckets of about step_deg along the circle. (0, 0) = upright."""
    up = (m[6], m[7], m[8])
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
