"""Write a retargeted clip (retarget.retarget) as a Starfield .af animation (+ .rig, + .afx descriptor) through the
CALUMI.Animation library, and read it back through the same library to compare every key.

CALUMI (github.com/Calaverah/CALUMI.Animation, LGPL-3.0) is loaded at run time with ctypes and never vendored; give the
path of the owner's Windows DLL, or of a Linux build (shared library) made outside the repository. Call conventions as
in native_door.py (verified by the door export): AddBoneToSkeletonRigC(rig, qx, qy, qz, qw, tx, ty, tz, name, parent,
animated, error); Create{Rotation,Translation,Scalar}EntryC(frame u16, values: rotation x y z w f32, translation
f64 x 3, scale f32); one anim block per rig bone, index = the bone's index in the rig.

The rig written here is built from a skeleton NIF (BodySlide's or the game's); the in-game test should save against
the game's own human skeleton.rig instead (SaveAnimationToSFBGSFormatWithExistingRigDirectC, `rig_path=`), so the clip
indexes bones exactly as vanilla clips do. Supported hypothesis until a clip plays in game: the .afx descriptor schema
for actor clips (taken from the door descriptors: is_state, tag, filename).
"""
import ctypes as c
import json
import math
import os
import pathlib
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import numpy as np


class CalumiError(RuntimeError):
    pass


class Calumi:
    def __init__(self, lib_path: str):
        self.lib = c.CDLL(str(pathlib.Path(lib_path).resolve()))
        self.p, self.b = c.c_void_p, c.c_bool
        self.error = self.fn("CreateStringContainerC", [], self.p)()
        self._msg = self.fn("GetStringFromContainerC", [self.p], c.c_char_p)

    def fn(self, name, args, result):
        f = getattr(self.lib, name)
        f.argtypes, f.restype = args, result
        return f

    def require(self, ok, what=""):
        if not ok:
            m = self._msg(self.error) or b"CALUMI operation failed"
            raise CalumiError(f"{what}: {m.decode(errors='replace')}")
        return ok

    def close(self):
        if self.error:
            self.fn("DeleteStringContainerC", [self.p], None)(self.error)
            self.error = None


# Skyrim annotation event -> Starfield .afx event name, for the names both games use (Starfield names as in the melee
# descriptors of the SW SFBM mod, Nexus 16022: PreHitFrame, WeaponSwing, HitFrame, FootLeft, FootRight). Matching is
# case-insensitive on the Skyrim side; others stay in <clip>.events.json until their Starfield counterpart is known.
EVENT_MAP = {"hitframe": "HitFrame", "prehitframe": "PreHitFrame", "weaponswing": "WeaponSwing",
             "footleft": "FootLeft", "footright": "FootRight", "attackstop": "AttackEnd"}


def map_events(annotations, fps: float):
    """(mapped [(frame, name, payload)], unmapped [annotation]) from skyrimhkx annotations ({"time", "text"})."""
    mapped, unmapped = [], []
    for a in annotations or []:
        name = EVENT_MAP.get(a["text"].strip().lower())
        if name:
            mapped.append((int(round(a["time"] * fps)), name, ""))
        else:
            unmapped.append(a)
    return sorted(mapped), unmapped


def descriptor(tag: str, filename: str, is_state: bool = False, events=(), variables=(), rampout=None) -> bytes:
    """An .afx in the shipped layout: is_state, tag, filename, rampout, flags, events (frame, name, payload),
    variables (name, start frame, end frame)."""
    root = ET.Element("root")
    ET.SubElement(root, "is_state").text = "1" if is_state else "0"
    ET.SubElement(root, "tag").text = tag
    ET.SubElement(root, "filename").text = filename
    if rampout is not None:
        ET.SubElement(root, "rampout").text = str(int(rampout))
    ET.SubElement(root, "flags").text = ""
    if events:
        ev = ET.SubElement(root, "events")
        for frame, name, payload in events:
            e = ET.SubElement(ev, "event")
            ET.SubElement(e, "frame").text = str(int(frame))
            ET.SubElement(e, "name").text = name
            ET.SubElement(e, "payload").text = payload or ""
    if variables:
        vs = ET.SubElement(root, "variables")
        for name, start, end in variables:
            v = ET.SubElement(vs, "variable")
            ET.SubElement(v, "name").text = name
            ET.SubElement(v, "start").text = str(int(start))
            ET.SubElement(v, "end").text = str(int(end))
    return ET.tostring(root, encoding="utf-8")


def _keys_needed(values: np.ndarray, tol: float) -> List[int]:
    """Frames to key so linear interpolation between kept keys stays within tol of every frame (greedy, keeps the
    first and last frame). values: (F, D)."""
    F = len(values)
    if F <= 2:
        return list(range(F))
    keep, a = [0], 0
    for b in range(2, F):
        seg = values[a:b + 1]
        t = np.linspace(0.0, 1.0, b - a + 1)[:, None]
        lin = seg[0] * (1 - t) + seg[-1] * t
        if np.max(np.abs(lin - seg)) > tol:
            keep.append(b - 1)
            a = b - 1
    keep.append(F - 1)
    return keep


def write(lib_path: str, out_dir: str, name: str, bones: List[str], parents: List[int], rest_t, rest_q,
          clip_t, clip_q, tag: Optional[str] = None, rig_path: Optional[str] = None, rig_name: str = "SkyrimPort",
          tolerance: float = 1e-4, events: Optional[list] = None, fps: float = 30.0, is_state: bool = False,
          variables=()) -> Dict:
    """Write <out>/<name>.af (+ skeleton.rig unless rig_path, + <name>.afx, + <name>.events.json). Translations in
    metres, quaternions (x, y, z, w). Returns {"af", "rig", "keys", "frames"}."""
    out = pathlib.Path(out_dir).resolve()
    repo = pathlib.Path(__file__).resolve().parents[2]
    if out == repo or repo in out.parents:
        raise ValueError("animation outputs must stay outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    clip_t, clip_q = np.asarray(clip_t, float), np.asarray(clip_q, float)
    if clip_q.shape[1] != len(bones):
        raise ValueError("bone count mismatch")
    # CALUMI rejects unnamed bones; Starfield's skeleton.nif has one unnamed leaf (under Camera): drop unnamed leaves
    used = set(parents)
    keep = [i for i, n in enumerate(bones) if n or i in used]
    if any(not bones[i] for i in keep):
        raise ValueError("an unnamed bone has children")
    remap = {old: new for new, old in enumerate(keep)}
    dropped = len(bones) - len(keep)
    bones = [bones[i] for i in keep]
    parents = [remap[parents[i]] if parents[i] >= 0 else -1 for i in keep]
    rest_t, rest_q = np.asarray(rest_t, float)[keep], np.asarray(rest_q, float)[keep]
    clip_t, clip_q = clip_t[:, keep, :], clip_q[:, keep, :]
    F, B = clip_q.shape[0], clip_q.shape[1]
    if F > 65535:
        raise ValueError("frame count over 65535")
    for i, p in enumerate(parents):
        if p >= i:
            raise ValueError("parents must precede children")
    L = Calumi(lib_path)
    p, b = L.p, L.b
    rig = anim = None
    keys = 0
    try:
        rig = L.require(L.fn("CreateSkeletonRigC", [c.c_char_p], p)(rig_name.encode()), "create rig")
        L.require(L.fn("SFBGSRigPackage_AddPackageToSkeletonRigC", [p, p, b], b)(rig, L.error, True), "rig package")
        add = L.fn("AddBoneToSkeletonRigC", [p] + [c.c_float] * 7 + [c.c_char_p, c.c_int, b, p], b)
        for i, n in enumerate(bones):
            x, y, z, w = (float(v) for v in rest_q[i])
            L.require(add(rig, x, y, z, w, *(float(v) for v in rest_t[i]), n.encode("utf-8"), int(parents[i]), True,
                          L.error), f"bone {n}")
        rig_file = out / "skeleton.rig"
        if rig_path is None:
            L.require(L.fn("SaveSkeletonRigToSFBGSFormatDirectC", [p, c.c_wchar_p, p], b)(rig, str(rig_file), L.error),
                      "save rig")
        anim = L.require(L.fn("CreateAnimationC", [c.c_char_p, c.c_uint], p)(name.encode(), B), "create animation")
        mk_block = L.fn("CreateAnimBlockC", [c.c_char_p, c.c_int, p], p)
        entries = {"Rotation": ([c.c_uint16] + [c.c_float] * 4), "Translation": ([c.c_uint16] + [c.c_double] * 3),
                   "Scalar": ([c.c_uint16, c.c_float])}
        mk = {k: L.fn(f"Create{k}EntryC", a, p) for k, a in entries.items()}
        add_sq = {k: L.fn(f"Add{k}SqToAnimBlockC", [p, p, c.c_uint, b], b) for k in entries}
        dele = {k: L.fn(f"Delete{k}EntryC", [p], b) for k in entries}
        add_block = L.fn("AddAnimBlockToAnimationC", [p, p, b, p], b)
        for i, n in enumerate(bones):
            blk = L.require(mk_block(n.encode("utf-8"), i, L.error), f"block {n}")
            try:
                q = clip_q[:, i, :].copy()
                for f in range(1, F):                       # keep quaternion signs continuous
                    if np.dot(q[f], q[f - 1]) < 0:
                        q[f] = -q[f]
                for kind, vals, frames in (("Rotation", q, _keys_needed(q, tolerance)),
                                           ("Translation", clip_t[:, i, :], _keys_needed(clip_t[:, i, :], tolerance))):
                    for f in frames:
                        v = [float(x) for x in vals[f]]
                        e = L.require(mk[kind](f, *v), kind)
                        try:
                            L.require(add_sq[kind](blk, e, 1, True), f"{kind} key")
                        finally:
                            dele[kind](e)
                        keys += 1
                for f in (0, F - 1):
                    e = L.require(mk["Scalar"](f, 1.0), "scale")
                    try:
                        L.require(add_sq["Scalar"](blk, e, 1, True), "scale key")
                    finally:
                        dele["Scalar"](e)
                L.require(add_block(anim, blk, True, L.error), f"add block {n}")
                blk = None
            finally:
                if blk:
                    L.fn("DeleteAnimationBlockC", [p], b)(blk)
        af = out / f"{name}.af"
        if rig_path is None:
            L.require(L.fn("SaveAnimationToSFBGSFormatDirectC", [p, c.c_wchar_p, p, p], b)(anim, str(af), rig, L.error),
                      "save animation")
        else:
            L.require(L.fn("SaveAnimationToSFBGSFormatWithExistingRigDirectC", [p, c.c_wchar_p, c.c_wchar_p, p], b)(
                anim, str(af), str(rig_path), L.error), "save animation")
        mapped, unmapped = map_events(events, fps)
        (out / f"{name}.afx").write_bytes(descriptor(tag or name, af.name, is_state, mapped, variables))
        (out / f"{name}.events.json").write_text(json.dumps({"in_afx": mapped, "not_mapped": unmapped}, indent=1))
        return {"af": str(af), "rig": str(rig_path or rig_file), "keys": keys, "frames": F, "bones": B,
                "events_in_afx": len(mapped), "events_not_mapped": len(unmapped),
                "dropped_unnamed": dropped}
    finally:
        if anim:
            L.fn("DeleteAnimationC", [p], b)(anim)
        if rig:
            L.fn("DeleteSkeletonRigC", [p], b)(rig)
        L.close()


def read_back(lib_path: str, af_path: str, rig_path: str) -> Dict:
    """{"bones": [names], "frames", "rotations": {bone: [(frame, (x, y, z, w))]}, "translations": {...}} as CALUMI
    reads the written files back (LoadAnimationSceneFromSFBGSFormatC on the .rig + .af)."""
    L = Calumi(lib_path)
    p, b = L.p, L.b
    try:
        arr = (c.c_wchar_p * 2)(str(rig_path), str(af_path))
        scene = L.require(L.fn("LoadAnimationSceneFromSFBGSFormatC", [c.POINTER(c.c_wchar_p), c.c_int, p], p)(
            arr, 2, L.error), "load")
        try:
            n = L.fn("GetAnimationCountC", [p], c.c_size_t)(scene)
            if n < 1:
                raise CalumiError("no animation read back")
            anim = L.require(L.fn("GetAnimationC", [p, c.c_int, p], p)(scene, 0, L.error), "animation 0")
            frames = L.fn("GetFrameCountC", [p], c.c_size_t)(anim)
            nb = L.fn("GetAnimationBlockCountC", [p], c.c_size_t)(anim)
            get_blk = L.fn("GetAnimationBlockC", [p, c.c_int, p], p)
            bname = L.fn("GetAnimBlockBoneNameC", [p], c.c_char_p)
            qget = [L.fn(f"GetQuaternion{a}", [p], c.c_float) for a in "XYZW"]
            vget = [L.fn(f"GetVector3D{a}", [p], c.c_double) for a in "XYZ"]
            out = {"frames": int(frames), "bones": [], "rotations": {}, "translations": {}}
            for i in range(nb):
                blk = L.require(get_blk(anim, i, L.error), f"block {i}")
                name = (bname(blk) or b"").decode("utf-8", "replace")
                out["bones"].append(name)
                for kind, getters, key in (("Rotation", qget, "rotations"), ("Translation", vget, "translations")):
                    cnt = L.fn(f"Get{kind}SqSizeC", [p], c.c_size_t)(blk)
                    get_e = L.fn(f"Get{kind}FromSqC", [p, c.c_int, p], p)
                    frame_of = L.fn(f"GetFrameFrom{kind}EntryC", [p], c.c_uint16)
                    value_of = L.fn(f"GetValueFrom{kind}EntryC", [p], p)
                    keys = []
                    for k in range(cnt):
                        e = L.require(get_e(blk, k, L.error), f"{kind} {k}")
                        v = value_of(e)
                        keys.append((int(frame_of(e)), tuple(float(g(v)) for g in getters)))
                    out[key][name] = keys
            return out
        finally:
            L.fn("DeleteAnimationSceneC", [p], None)(scene)
    finally:
        L.close()
