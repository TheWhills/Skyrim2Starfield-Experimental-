"""Write a retargeted clip (retarget.retarget) as a Starfield .af animation (+ .rig, + .afx descriptor) through the
CALUMI.Animation library, and read it back through the same library to compare every key.

CALUMI (github.com/Calaverah/CALUMI.Animation, LGPL-3.0) is loaded at run time with ctypes and never vendored; give the
path of the owner's Windows DLL, or of a Linux build (shared library) made outside the repository. Call conventions as
in native_door.py (verified by the door export): AddBoneToSkeletonRigC(rig, qx, qy, qz, qw, tx, ty, tz, name, parent,
animated, error); Create{Rotation,Translation,Scalar}EntryC(frame u16, values: rotation x y z w f32, translation
f64 x 3, scale f32); one anim block per rig bone, index = the bone's index in the rig.

The rig written here is built from a skeleton NIF (BodySlide's or the game's); the in-game test saves against the
game's own human skeleton.rig instead (SaveAnimationToSFBGSFormatWithExistingRigDirectC, `rig_path=`), with the bones
listed in that rig's order and hierarchy (load_rig + retarget.rehome; verified 2026-10-19 on the vanilla rig from the
owner's survey: 97 bones, Root first, Weapon under C_Chest, C_Waist absent from the NIF; read-back error 6e-4 rotation,
0.24 mm translation), so the clip indexes bones exactly as vanilla clips do. Supported hypothesis until a clip plays in game: the .afx descriptor schema
for actor clips (taken from the door descriptors: is_state, tag, filename).
"""
import ctypes as c
import copy
import json
import math
import os
import pathlib
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

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
             "footleft": "FootLeft", "footright": "FootRight", "attackstop": "AttackEnd",
             # equip / unequip (Starfield names from the vanilla one-handed Equip / Unequip descriptors, 2026-10-19)
             "weapondraw": "WeaponDraw", "weaponsheathe": "WeaponSheathe"}


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
    return ET.tostring(root, encoding="utf-8", short_empty_elements=False)


def retime_descriptor(vanilla: bytes, new_last: int, filename: str, old_last: Optional[int] = None,
                      own_events=(), hit_frame: Optional[int] = None) -> Tuple[bytes, Dict]:
    """A vanilla .afx fitted to a replacement clip: every <frame>, <start> and <end> (events, variables, audio...)
    scaled from the vanilla clip's last frame to ours (old_last, or when unknown the descriptor's largest frame, which
    is exact for the usual whole-clip variables); <filename> set; <rampout> (the blend-out, in frames) scaled down with
    a shorter clip and never past its last frame (vanilla SlideFromSprint: 29 of 51 frames; kept at 29 on a 27-frame
    dodge, the whole clip would blend out); everything else (tag, is_state, flags, payloads, prefixes) kept. Events our clip carries itself (own_events: (frame, name, payload), e.g. HitFrame from
    the Skyrim annotations) replace the vanilla ones of the same name, in order, when the counts match.
    hit_frame (our clip's hit, e.g. retarget.blade_peak; a HitFrame in own_events wins): when the vanilla descriptor
    has a HitFrame, the scaling is piecewise linear through (vanilla HitFrame -> hit_frame), so PreHitFrame,
    WeaponSwing, CameraShake, the swing sounds and the windows around them keep their distance to the hit instead of
    landing mid wind-up. Returns (bytes, report)."""
    text = vanilla.decode("utf-8-sig", "replace")
    root = ET.fromstring(text)
    marks = [e for e in root.iter() if e.tag in ("frame", "start", "end") and (e.text or "").strip().lstrip("-").isdigit()]
    est = old_last is None
    if est:
        old_last = max([int(e.text) for e in marks] or [new_last])
    scale = (new_last / old_last) if old_last else 1.0
    own_hits = sorted(f for f, n, _p in own_events if n == "HitFrame")
    if own_hits:
        hit_frame = int(own_hits[0])
    v_hits = [int(ev.findtext("frame")) for ev in root.iter("event")
              if ev.findtext("name") == "HitFrame" and (ev.findtext("frame") or "").strip().isdigit()]
    anchor = None
    if hit_frame is not None and v_hits and 0 < min(v_hits) < old_last and 0 < hit_frame < new_last:
        anchor = (min(v_hits), int(hit_frame))

    def warp(v):
        if anchor is None:
            return v * scale
        (a, b) = anchor
        return v * b / a if v <= a else b + (v - a) * (new_last - b) / (old_last - a)
    for e in marks:
        v = int(e.text)
        e.text = str(new_last if v >= old_last else max(0, min(new_last, int(round(warp(v))))))
    ramp = root.find("rampout")
    if ramp is not None and (ramp.text or "").strip().isdigit():
        r = int(ramp.text)
        ramp.text = str(max(0, min(new_last, int(round(r * min(1.0, scale))))))
    fn = root.find("filename")
    if fn is None:
        fn = ET.SubElement(root, "filename")
    fn.text = filename
    replaced = []
    own = {}
    for f, n, _p in own_events:
        own.setdefault(n, []).append(f)
    by_name = {}
    for ev in root.iter("event"):
        by_name.setdefault(ev.findtext("name"), []).append(ev)
    for n, frames in own.items():
        evs = by_name.get(n, [])
        if evs and len(evs) == len(frames):
            for ev, f in zip(evs, sorted(frames)):
                ev.find("frame").text = str(int(f))
            replaced.append(n)
    out = ET.tostring(root, encoding="utf-8", short_empty_elements=False)
    if b"\r\n" in vanilla:                         # the shipped descriptors use CRLF (the parser drops the CR)
        out = out.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return out, {"old_last": old_last, "old_last_estimated": est, "scale": round(scale, 4),
                                                 "retimed": len(marks), "events_from_clip": replaced,
                                                 "hit_anchor": anchor}


def _afx_out(root, like: bytes) -> bytes:
    out = ET.tostring(root, encoding="utf-8", short_empty_elements=False)
    if b"\r\n" in like:
        out = out.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return out


def copy_timing(src: bytes, dst: bytes) -> bytes:
    """dst's descriptor with src's timing: rampout, flags, events, audios and variables taken from src; tag, filename
    and is_state kept. For two vanilla slots that now play the same clip (e.g. combo A and C both Skyrim's right
    swing), so the second gets the first's hit and combo windows."""
    s_root, d_root = ET.fromstring(src.decode("utf-8-sig")), ET.fromstring(dst.decode("utf-8-sig"))
    for name in ("rampout", "flags", "events", "audios", "variables"):
        old, new = d_root.find(name), s_root.find(name)
        at = list(d_root).index(old) if old is not None else None
        if old is not None:
            d_root.remove(old)
        if new is not None:
            el = copy.deepcopy(new)
            if at is None:                         # keep the shipped element order: after the last kept sibling
                order = ["is_state", "tag", "filename", "rampout", "flags", "events", "audios", "variables"]
                prev = [c for c in d_root if c.tag in order[:order.index(name)]]
                at = list(d_root).index(prev[-1]) + 1 if prev else len(d_root)
            d_root.insert(at, el)
    return _afx_out(d_root, dst)


def drop_variables(afx: bytes, names) -> Tuple[bytes, List[str]]:
    """The descriptor without the named <variable> windows (e.g. bAllowFinisher); returns (bytes, dropped names)."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    dropped = []
    vs = root.find("variables")
    for v in list(vs) if vs is not None else []:
        if v.findtext("name") in names:
            vs.remove(v)
            dropped.append(v.findtext("name"))
    return _afx_out(root, afx), dropped


def add_event(afx: bytes, frame: int, name: str, payload: str = "") -> bytes:
    """The descriptor with one more <event> (kept in frame order; same layout as the shipped events)."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    evs = root.find("events")
    if evs is None:
        evs = ET.SubElement(root, "events")
    ev = ET.Element("event")
    for tag, val in (("frame", str(int(frame))), ("name", name), ("payload", payload)):
        ET.SubElement(ev, tag).text = val
    kids = evs.findall("event")
    at = next((i for i, e in enumerate(kids) if int(e.findtext("frame") or 0) > frame), len(kids))
    if kids:
        ev.tail = kids[0].tail if at < len(kids) else kids[-1].tail
        if at == len(kids):
            kids[-1].tail = kids[0].tail if len(kids) > 1 else evs.text
    evs.insert(at, ev)
    return _afx_out(root, afx)


def set_event_frame(afx: bytes, name: str, frame: int) -> bytes:
    """The descriptor with the first <event> called `name` moved to `frame` (added when missing)."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    ev = next((e for e in root.iter("event") if e.findtext("name") == name), None)
    if ev is None:
        return add_event(afx, frame, name)
    ev.find("frame").text = str(int(frame))
    return _afx_out(root, afx)


def set_tag(afx: bytes, tag: str, filename: str, prefix: Optional[str] = "keep") -> bytes:
    """The descriptor with another <tag> and <filename>; prefix None removes <prefix>, a string sets it, "keep"
    leaves it. Verified 2026-10-19 on vanilla descriptors: a clip is found by (<prefix>, <tag>) - the sneak / zero-g
    variants say <tag>MeleeAttack_B</tag> <prefix>Sneak</prefix> - not by its file name."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    for name, val in (("tag", tag), ("filename", filename)):
        el = root.find(name)
        if el is None:
            el = ET.SubElement(root, name)
        el.text = val
    if prefix != "keep":
        el = root.find("prefix")
        if prefix is None and el is not None:
            kids = list(root)
            i = kids.index(el)
            if i > 0:
                kids[i - 1].tail = el.tail
            root.remove(el)
        elif prefix is not None:
            if el is None:
                el = ET.Element("prefix")
                fn = root.find("filename")
                i = list(root).index(fn) + 1
                el.tail = fn.tail
                root.insert(i, el)
            el.text = prefix
    return _afx_out(root, afx)


def event_frame(afx: bytes, name: str) -> Optional[int]:
    """Frame of the first <event> called `name`, or None."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    for e in root.iter("event"):
        if e.findtext("name") == name and (e.findtext("frame") or "").strip().isdigit():
            return int(e.findtext("frame"))
    return None


def set_variable_window(afx: bytes, name: str, start: int, end: int) -> bytes:
    """The descriptor with variable window `name` set to start..end (added when missing)."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    vs = root.find("variables")
    if vs is None:
        vs = ET.SubElement(root, "variables")
    v = next((x for x in vs.findall("variable") if x.findtext("name") == name), None)
    if v is None:
        prev = vs.findall("variable")
        v = ET.SubElement(vs, "variable")
        for tag in ("name", "start", "end"):
            ET.SubElement(v, tag)
        v.find("name").text = name
        if prev:
            v.tail, prev[-1].tail = prev[-1].tail, vs.text
    v.find("start").text, v.find("end").text = str(int(start)), str(int(end))
    return _afx_out(root, afx)


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


def _qmul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0)
    bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def rest_relative(rest_t, rest_q, clip_t, clip_q):
    """Local (t, q) per frame -> the values an .af stores: rotation key = rest_q^-1 * q, translation key = t - rest_t.
    The engine plays local = rest * key, rest + key (verified 2026-10-19: decoding the vanilla chair Idle and sword
    MeleeAttack_A that way gives a seated / standing human, hips 0.67 / 0.96 m, ankles 0.12 m above the floor, knees
    forward; read as absolute locals the same keys put the hips below the floor; key * rest bends the knees backwards).
    Returns (q_keys, t_keys)."""
    rest_t, rest_q = np.asarray(rest_t, float), np.asarray(rest_q, float)
    inv = rest_q * np.array([-1.0, -1.0, -1.0, 1.0])
    return _qmul(np.broadcast_to(inv, np.shape(clip_q)), np.asarray(clip_q, float)), np.asarray(clip_t, float) - rest_t


def from_rest_relative(rest_t, rest_q, key_t, key_q):
    """Inverse of rest_relative: stored keys -> local (t, q)."""
    return np.asarray(rest_t, float) + np.asarray(key_t, float), _qmul(np.asarray(rest_q, float), np.asarray(key_q, float))


def write(lib_path: str, out_dir: str, name: str, bones: List[str], parents: List[int], rest_t, rest_q,
          clip_t, clip_q, tag: Optional[str] = None, rig_path: Optional[str] = None, rig_name: str = "SkyrimPort",
          tolerance: float = 1e-4, events: Optional[list] = None, fps: float = 30.0, is_state: bool = False,
          variables=(), like_afx: Optional[bytes] = None, like_last: Optional[int] = None, file_name: Optional[str] = None,
          omit=(), hit_frame: Optional[int] = None) -> Dict:
    """Write <out>/<name>.af (+ skeleton.rig unless rig_path, + <name>.afx, + <name>.events.json). Translations in
    metres, quaternions (x, y, z, w). Bones named in `omit` get no track (the game keeps driving them, e.g.
    skeletonmap.NOT_ANIMATED). hit_frame: see retime_descriptor. Returns {"af", "rig", "keys", "frames"}."""
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
    # .af keys are relative to the rig's rest pose (verified 2026-10-19 on vanilla clips: see rest_relative)
    clip_q, clip_t = rest_relative(rest_t, rest_q, clip_t, clip_q)
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
        skip = set(omit)
        for i, n in enumerate(bones):
            if n in skip:
                continue
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
        af = out / f"{file_name or name}.af"
        if rig_path is None:
            L.require(L.fn("SaveAnimationToSFBGSFormatDirectC", [p, c.c_wchar_p, p, p], b)(anim, str(af), rig, L.error),
                      "save animation")
        else:
            L.require(L.fn("SaveAnimationToSFBGSFormatWithExistingRigDirectC", [p, c.c_wchar_p, c.c_wchar_p, p], b)(
                anim, str(af), str(rig_path), L.error), "save animation")
        mapped, unmapped = map_events(events, fps)
        retime = None
        if like_afx is not None:                    # replacing a vanilla clip: its own descriptor, fitted to ours
            afx, retime = retime_descriptor(like_afx, F - 1, af.name, like_last, mapped, hit_frame)
        else:
            afx = descriptor(tag or name, af.name, is_state, mapped, variables)
        (out / f"{af.stem}.afx").write_bytes(afx)
        if like_afx is None:                        # a replacement goes into the game's folders: no side files there
            (out / f"{af.stem}.events.json").write_text(json.dumps({"in_afx": mapped, "not_mapped": unmapped},
                                                                   indent=1))
        return {"af": str(af), "rig": str(rig_path or rig_file), "keys": keys, "frames": F, "bones": B,
                "events_in_afx": len(mapped), "events_not_mapped": len(unmapped),
                "dropped_unnamed": dropped, "retime": retime, "omitted": sorted(skip & set(bones))}
    finally:
        if anim:
            L.fn("DeleteAnimationC", [p], b)(anim)
        if rig:
            L.fn("DeleteSkeletonRigC", [p], b)(rig)
        L.close()


def load_rig(lib_path: str, rig_path: str) -> Dict:
    """A Starfield .rig as {"names", "parents", "t" (B, 3), "q" (B, 4) local rest, "types", "animated"} via CALUMI
    (LoadSFBGSSkeletonRigFromFileC). The vanilla human rig (2026-10-19): 97 bones, Root first, order and parents
    unlike the skeleton NIF's; 82 of type Default (the animated ones, listed first) and 15 Twist bones last, which the
    engine drives itself: vanilla clips (chair Idle, sword MeleeAttack_A) declare 82 bones in their header."""
    L = Calumi(lib_path)
    p = L.p
    rig = None
    try:
        rig = L.require(L.fn("LoadSFBGSSkeletonRigFromFileC", [c.c_wchar_p, p], p)(str(rig_path), L.error), "load rig")
        n = L.fn("GetSkeletonRigBoneCountC", [p], c.c_size_t)(rig)
        animated = L.fn("GetSkeletonRigAnimatedBoneCountC", [p], c.c_size_t)(rig)
        get = L.fn("GetSkeletonBoneC", [p, c.c_int, p], p)
        name = L.fn("GetSkeletonBoneNameC", [p], c.c_char_p)
        parent = L.fn("GetSkeletonBoneParentIndexC", [p], c.c_int)
        rot = L.fn("GetSkeletonBoneRotationC", [p, c.c_bool], p)
        pos = L.fn("GetSkeletonBonePositionC", [p, c.c_bool], p)
        qget = [L.fn(f"GetQuaternion{a}", [p], c.c_float) for a in "XYZW"]
        vget = [L.fn(f"GetVector3{a}", [p], c.c_float) for a in "XYZ"]     # bone positions are float Vector3
        btype = L.fn("GetBoneTypeAsStringC", [p], c.c_char_p)
        out = {"names": [], "parents": [], "t": [], "q": [], "types": [], "animated": int(animated)}
        for i in range(n):
            bone = L.require(get(rig, i, L.error), f"bone {i}")
            out["names"].append((name(bone) or b"").decode("utf-8", "replace"))
            out["parents"].append(int(parent(bone)))
            out["types"].append((btype(bone) or b"").decode())
            qv, tv = rot(bone, False), pos(bone, False)
            out["q"].append([float(g(qv)) for g in qget])
            out["t"].append([float(g(tv)) for g in vget])
        out["t"], out["q"] = np.array(out["t"]), np.array(out["q"])
        return out
    finally:
        if rig:
            L.fn("DeleteSkeletonRigC", [p], c.c_bool)(rig)
        L.close()


def rig_prefix(lib_path: str, rig_path: str, count: int, out_path: str) -> str:
    """Write a copy of a game rig holding only its first `count` bones (same names, parents, rest pose, rig-package
    bone keys, mannequin flag and translation precision) and return its path. CALUMI sizes a clip's bone table from
    the rig it is saved against (all 97 bones of the vanilla human rig) while vanilla clips declare only the 82 animated
    ones; saving against this prefix gives the vanilla header (the indexes of the kept bones are unchanged)."""
    L = Calumi(lib_path)
    p, b = L.p, L.b
    src = dst = None
    try:
        src = L.require(L.fn("LoadSFBGSSkeletonRigFromFileC", [c.c_wchar_p, p], p)(str(rig_path), L.error), "load rig")
        n = L.fn("GetSkeletonRigBoneCountC", [p], c.c_size_t)(src)
        if not 0 < count <= n:
            raise ValueError(f"rig has {n} bones, asked for {count}")
        get = L.fn("GetSkeletonBoneC", [p, c.c_int, p], p)
        name = L.fn("GetSkeletonBoneNameC", [p], c.c_char_p)
        parent = L.fn("GetSkeletonBoneParentIndexC", [p], c.c_int)
        rot = L.fn("GetSkeletonBoneRotationC", [p, c.c_bool], p)
        pos = L.fn("GetSkeletonBonePositionC", [p, c.c_bool], p)
        qget = [L.fn(f"GetQuaternion{a}", [p], c.c_float) for a in "XYZW"]
        vget = [L.fn(f"GetVector3{a}", [p], c.c_float) for a in "XYZ"]
        key_of = L.fn("SFBGSRigPackage_GetBoneKeyC", [p, c.c_char_p], c.c_uint8)
        mapped = L.fn("SFBGSRigPackage_BoneIsMappedC", [p, c.c_char_p], b)
        rig_name = L.fn("GetSkeletonRigNameC", [p], c.c_char_p)(src) or b"rig"
        dst = L.require(L.fn("CreateSkeletonRigC", [c.c_char_p], p)(rig_name), "create rig")
        L.require(L.fn("SFBGSRigPackage_AddPackageToSkeletonRigC", [p, p, b], b)(dst, L.error, True), "rig package")
        add = L.fn("AddBoneToSkeletonRigC", [p] + [c.c_float] * 7 + [c.c_char_p, c.c_int, b, p], b)
        add_key = L.fn("SFBGSRigPackage_AddBoneNameToMapC", [p, c.c_uint8, c.c_char_p, p, b], b)
        for i in range(count):
            bone = L.require(get(src, i, L.error), f"bone {i}")
            nm = name(bone)
            q, t = rot(bone, False), pos(bone, False)
            L.require(add(dst, *(g(q) for g in qget), *(g(t) for g in vget), nm, int(parent(bone)), True, L.error),
                      f"bone {nm}")
            if mapped(src, nm):
                L.require(add_key(dst, key_of(src, nm), nm, L.error, True), f"key {nm}")
        L.fn("SFBGSRigPackage_SetMannequinC", [p, b], b)(dst, L.fn("SFBGSRigPackage_IsMannequinC", [p], b)(src))
        hi = L.fn("SFBGSRigPackage_GetHighPrecisionValueC", [p], c.c_float)(src)
        lo = L.fn("SFBGSRigPackage_GetLowPrecisionValueC", [p], c.c_float)(src)
        L.fn("SFBGSRigPackage_SetPrecisionToCustomC", [p, c.c_float, c.c_float], None)(dst, lo, hi)
        L.require(L.fn("SaveSkeletonRigToSFBGSFormatDirectC", [p, c.c_wchar_p, p], b)(dst, str(out_path), L.error),
                  "save rig")
        return str(out_path)
    finally:
        for r in (src, dst):
            if r:
                L.fn("DeleteSkeletonRigC", [p], b)(r)
        L.close()


def read_back(lib_path: str, af_path: str, rig_path: str, absolute: bool = True) -> Dict:
    """{"bones": [names], "frames", "rotations": {bone: [(frame, (x, y, z, w))]}, "translations": {...}} as CALUMI
    reads the written files back (LoadAnimationSceneFromSFBGSFormatC on the .rig + .af). absolute: local transforms
    (the stored rest-relative keys composed with the rig's rest pose); else the stored keys as they are."""
    out = _read_keys(lib_path, af_path, rig_path)
    if absolute:
        rig = load_rig(lib_path, rig_path)
        idx = {n: i for i, n in enumerate(rig["names"])}
        for n in out["bones"]:
            i = idx.get(n)
            if i is None:
                continue
            out["rotations"][n] = [(f, tuple(float(x) for x in _qmul(rig["q"][i], np.array(v))))
                                   for f, v in out["rotations"][n]]
            out["translations"][n] = [(f, tuple(float(x) for x in rig["t"][i] + np.array(v)))
                                      for f, v in out["translations"][n]]
    return out


def _read_keys(lib_path: str, af_path: str, rig_path: str) -> Dict:
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
