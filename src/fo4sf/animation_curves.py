"""Decode FO4 NiTransformData curves; no target animation emission yet.

Layout follows niftools/nifxml NiKeyframeData, KeyGroup, Key and QuatKey.
Preserve tangents/TBC rather than replacing source interpolation with linear keys.
"""
import math
import struct
from .nif import NifError


def decode(data):
    offset = 0

    def take(fmt):
        nonlocal offset
        size = struct.calcsize(fmt)
        if offset + size > len(data):
            raise NifError("truncated transform curve")
        values = struct.unpack_from(fmt, data, offset)
        offset += size
        if any(isinstance(v, float) and not math.isfinite(v) for v in values):
            raise NifError("nonfinite transform curve")
        return values

    def group(dimensions):
        count, = take("<I")
        if count == 0:
            return {"interpolation": None, "keys": []}
        interpolation, = take("<I")
        if interpolation not in (1, 2, 3):
            raise NifError("unsupported transform key interpolation")
        keys = []
        for _ in range(count):
            time, = take("<f")
            key = {"time": time, "value": list(take(f"<{dimensions}f"))}
            if interpolation == 2:
                key["forward"] = list(take(f"<{dimensions}f"))
                key["backward"] = list(take(f"<{dimensions}f"))
            elif interpolation == 3:
                key["tension_bias_continuity"] = list(take("<3f"))
            keys.append(key)
        return {"interpolation": interpolation, "keys": keys}

    count, = take("<I")
    rotation = {"representation": "quaternion_wxyz", "interpolation": None, "keys": []}
    if count:
        interpolation, = take("<I")
        if interpolation == 4:
            if count != 1:
                raise NifError("XYZ rotation must have one outer key group")
            rotation = {"representation": "euler_xyz_radians", "axes": [group(1) for _ in range(3)]}
        elif interpolation in (1, 2, 3):
            rotation["interpolation"] = interpolation
            for _ in range(count):
                time, = take("<f")
                key = {"time": time, "value": list(take("<4f"))}
                if interpolation == 3:
                    key["tension_bias_continuity"] = list(take("<3f"))
                rotation["keys"].append(key)
        else:
            raise NifError("unsupported rotation interpolation")
    translation, scale = group(3), group(1)
    if offset != len(data):
        raise NifError("unparsed transform curve bytes")
    return {"rotation": rotation, "translation_source_units": translation, "scale": scale}

def evaluate_group(group, time, default):
    """Sample scalar/vector keys in source units, clamping outside key times.

    Quadratic tangents are segment-normalized: outgoing is the first key's
    backward field, incoming the next key's forward field. Do not multiply
    these by the interval duration. TBC requires separate verified semantics.
    """
    if not math.isfinite(time):
        raise NifError("nonfinite sample time")
    keys = group["keys"]
    if not keys:
        return list(default)
    mode = group["interpolation"]
    if mode not in (1, 2):
        raise NifError("unsupported sampled key interpolation")
    dimensions = len(default)
    previous = -math.inf
    for key in keys:
        t = key["time"]
        fields = [key["value"]]
        if mode == 2:
            fields += [key["forward"], key["backward"]]
        if not math.isfinite(t) or t <= previous:
            raise NifError("sampled key times must be strictly increasing")
        if any(len(v) != dimensions or not all(math.isfinite(x) for x in v) for v in fields):
            raise NifError("invalid sampled key values")
        previous = t
    if time <= keys[0]["time"]:
        return list(keys[0]["value"])
    if time >= keys[-1]["time"]:
        return list(keys[-1]["value"])
    for left, right in zip(keys, keys[1:]):
        if time > right["time"]:
            continue
        u = (time - left["time"]) / (right["time"] - left["time"])
        if mode == 1:
            return [a + (b - a) * u for a, b in zip(left["value"], right["value"])]
        u2, u3 = u * u, u * u * u
        weights = (2*u3-3*u2+1, -2*u3+3*u2, u3-2*u2+u, u3-u2)
        return [sum(w * v for w, v in zip(weights, values)) for values in
                zip(left["value"], right["value"], left["backward"], right["forward"])]
    raise NifError("sample interval not found")

def _unit_quaternion(value):
    if len(value) != 4 or not all(math.isfinite(v) for v in value):
        raise NifError("invalid rotation quaternion")
    length = math.hypot(*value)
    if length < 1e-12:
        raise NifError("zero rotation quaternion")
    return [v / length for v in value]


def evaluate_rotation(rotation, time, default_wxyz):
    """Evaluate source local rotation as a unit wxyz quaternion.

    XYZ curves compose Rz*Ry*Rx; absent axes are zero. Quaternion linear
    keys use shortest-path spherical interpolation. Quadratic/TBC quaternion
    semantics are deliberately unsupported rather than approximated linearly.
    No source/target basis or unit conversion occurs here.
    """
    if not math.isfinite(time):
        raise NifError("nonfinite sample time")
    representation = rotation['representation']
    if representation == 'euler_xyz_radians':
        axes = rotation['axes']
        if len(axes) != 3:
            raise NifError("XYZ rotation requires three axes")
        x, y, z = [evaluate_group(axis, time, [0])[0] / 2 for axis in axes]
        cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
        return _unit_quaternion([cx*cy*cz + sx*sy*sz, sx*cy*cz - cx*sy*sz,
                                 cx*sy*cz + sx*cy*sz, cx*cy*sz - sx*sy*cz])
    if representation != 'quaternion_wxyz':
        raise NifError("unsupported rotation representation")
    keys = rotation['keys']
    if not keys:
        return _unit_quaternion(default_wxyz)
    if rotation['interpolation'] != 1:
        raise NifError("unsupported sampled quaternion interpolation")
    previous = -math.inf
    normalized = []
    for key in keys:
        t = key['time']
        if not math.isfinite(t) or t <= previous:
            raise NifError("sampled key times must be strictly increasing")
        normalized.append((t, _unit_quaternion(key['value'])))
        previous = t
    if time <= normalized[0][0]:
        return normalized[0][1]
    if time >= normalized[-1][0]:
        return normalized[-1][1]
    for (start, a), (stop, b) in zip(normalized, normalized[1:]):
        if time > stop:
            continue
        u = (time - start) / (stop - start)
        dot = sum(x*y for x, y in zip(a, b))
        if dot < 0:
            b = [-v for v in b]
            dot = -dot
        dot = min(1.0, dot)
        if dot > .9995:
            return _unit_quaternion([x + u*(y-x) for x, y in zip(a, b)])
        theta = math.acos(dot)
        divisor = math.sin(theta)
        wa, wb = math.sin((1-u)*theta)/divisor, math.sin(u*theta)/divisor
        return _unit_quaternion([wa*x + wb*y for x, y in zip(a, b)])
    raise NifError("sample interval not found")
