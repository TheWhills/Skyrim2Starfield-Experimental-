"""Skyrim SE Havok animation files (.hkx, "hk_2010.2.0-r1" binary packfiles, 64-bit): what is inside, read-only.

This is the DESCRIBE stage of the Skyrim animation converter: skeletons (bone names, parents, reference pose),
animations (class, compression type, duration, track counts, spline frame / block counts), bindings (track ->
bone), and annotation tracks (Skyrim's timed animation events: hit frames, footsteps, sounds). It does not decode
the compressed tracks yet; that needs real files to check against.

Sources and status. Container (packfile header, 48-byte 2010 section headers, local / global / virtual fixup tables,
hkRootLevelContainer namedVariants of name / className / variant): hkxpack's notes on Skyrim files
(github.com/Dexesttp/hkxpack, doc/hkx findings, MIT), **supported**. Member ORDER of the classes below: the field order
of hk_2010.2.0-r1 XML dumps of Skyrim animations (hkxcmd output), from memory, not re-checked here. Member OFFSETS:
computed from that order with 64-bit C alignment (hkReferencedObject = 16 bytes), **unverified** until the owner's files
are read; describe() reports implausible values in "checks" so a wrong offset shows as nonsense, not silently:
* hkReferencedObject: vtable 8, memSizeAndFlags u16, referenceCount u16, pad 4 -> 16 bytes.
* hkArray: data pointer 8, size i32, capacityAndFlags i32 -> 16 bytes. char* strings: pointer to a 0-terminated run.
* hkRootLevelContainer: namedVariants hkArray at 0 of {name char*, className char*, variant pointer} (24 bytes).
* hkaAnimationContainer (hkReferencedObject): skeletons @16, animations @32, bindings @48, attachments @64,
  skins @80 (hkArray of pointers).
* hkaSkeleton: name @16, parentIndices hkArray<i16> @24, bones hkArray<hkaBone> @40 (hkaBone: name char* 8 +
  lockTranslation bool, padded to 16), referencePose hkArray<hkQsTransform> @56 (translation 4f, rotation 4f
  (x y z w), scale 4f = 48 bytes), referenceFloats @72, floatSlots @88.
* hkaAnimation: type i32 @16 (0 unknown, 1 interleaved, 2 delta, 3 wavelet, 4 mirrored, 5 spline compressed),
  duration f32 @20, numberOfTransformTracks i32 @24, numberOfFloatTracks i32 @28, extractedMotion pointer @32,
  annotationTracks hkArray<hkaAnnotationTrack> @40 (track: name char* 8 + annotations hkArray 16 = 24 bytes;
  annotation: time f32 + pad 4 + text char* = 16 bytes).
* hkaSplineCompressedAnimation (after the 56-byte hkaAnimation): numFrames i32 @56, numBlocks i32 @60,
  maxFramesPerBlock i32 @64, maskAndQuantizationSize i32 @68, blockDuration f32 @72, blockInverseDuration f32 @76,
  frameDuration f32 @80; then hkArrays blockOffsets @88, floatBlockOffsets @104, transformOffsets @120,
  floatOffsets @136, data (u8) @152.
* hkaAnimationBinding: originalSkeletonName char* @16, animation pointer @24, transformTrackToBoneIndices
  hkArray<i16> @32, floatTrackToFloatSlotIndices hkArray<i16> @48, blendHint i8 @64.
"""
import struct
from typing import Optional

from . import hkpackfile

ANIMATION_TYPES = {0: "unknown", 1: "interleaved", 2: "delta_compressed", 3: "wavelet_compressed", 4: "mirrored",
                   5: "spline_compressed"}
ANIMATION_CLASSES = ("hkaSplineCompressedAnimation", "hkaInterleavedUncompressedAnimation",
                     "hkaDeltaCompressedAnimation", "hkaWaveletCompressedAnimation", "hkaMirroredAnimation")


class HkxError(ValueError):
    pass


def _str(pf, at) -> Optional[str]:
    """The char* stored at data-section offset `at`, or None."""
    t = pf.pointer(at)
    if t is None:
        return None
    s = pf.data_section
    a = s.start + t
    end = pf.data.find(b"\0", a, s.start + s.end)            # section ends are stored relative to its start
    return pf.data[a:end].decode("latin-1") if end >= 0 else None


def _ptr_array(pf, at):
    off, n = pf.array(at)
    if off is None or n <= 0:
        return []
    return [pf.pointer(off + 8 * k) for k in range(n)]


def _class_of(pf):
    return {o: c for o, c in pf.objects()}


def skeleton(pf, o) -> dict:
    name = _str(pf, o + 16)
    poff, np_ = pf.array(o + 24)
    parents = list(pf.unpack(f"<{np_}h", poff)) if poff is not None and np_ > 0 else []
    boff, nb = pf.array(o + 40)
    bones = [_str(pf, boff + 16 * k) for k in range(nb)] if boff is not None else []
    roff, nr = pf.array(o + 56)
    pose = []
    if roff is not None:
        for k in range(nr):
            v = pf.unpack("<12f", roff + 48 * k)
            pose.append({"t": v[0:3], "q": v[4:8], "s": v[8:11]})
    return {"name": name, "bones": bones, "parents": parents, "reference_pose": pose}


def animation(pf, o, cls) -> dict:
    typ, duration, ntr, nfl = pf.unpack("<ifii", o + 16)
    out = {"class": cls, "type": ANIMATION_TYPES.get(typ, typ), "duration": duration, "transform_tracks": ntr,
           "float_tracks": nfl, "has_extracted_motion": pf.pointer(o + 32) is not None, "annotations": []}
    aoff, na = pf.array(o + 40)
    for k in range(max(na, 0) if aoff is not None else 0):
        t = aoff + 24 * k
        track = _str(pf, t)
        eoff, ne = pf.array(t + 8)
        for j in range(max(ne, 0) if eoff is not None else 0):
            time, = pf.unpack("<f", eoff + 16 * j)
            text = _str(pf, eoff + 16 * j + 8)
            if text:
                out["annotations"].append({"track": track, "time": round(time, 4), "text": text})
    if cls == "hkaSplineCompressedAnimation":
        nfr, nbl, maxf, mq, bdur, binv, fdur = pf.unpack("<iiiifff", o + 56)
        _d, ndata = pf.array(o + 152)
        out.update(frames=nfr, blocks=nbl, max_frames_per_block=maxf, mask_and_quantization_size=mq,
                   block_duration=bdur, frame_duration=fdur, data_bytes=ndata)
    return out


def binding(pf, o) -> dict:
    toff, nt = pf.array(o + 32)
    tracks = list(pf.unpack(f"<{nt}h", toff)) if toff is not None and nt > 0 else []
    return {"skeleton": _str(pf, o + 16), "animation_object": pf.pointer(o + 24), "track_to_bone": tracks}


def describe(data: bytes) -> dict:
    """Everything describable in one .hkx: {"havok": version, "classes": {...}, "skeletons": [...],
    "animations": [...], "bindings": [...], "checks": [...]}; checks lists anything implausible (a hint that an
    offset above is wrong for real files)."""
    if data[:8] != hkpackfile.MAGIC:
        raise HkxError("not a Havok binary packfile (XML .hkx files need converting to binary first)")
    version, = struct.unpack_from("<i", data, 12)
    if version != 8:
        raise HkxError(f"packfile version {version}; Skyrim SE uses 8 (hk_2010.2.0-r1)")
    try:
        pf = hkpackfile.Packfile(data)
    except (hkpackfile.PackfileError, struct.error, IndexError, ValueError) as e:
        raise HkxError(f"{type(e).__name__}: {e}") from e
    cls = _class_of(pf)
    counts = {}
    for c in cls.values():
        counts[c] = counts.get(c, 0) + 1
    out = {"havok": pf.version, "classes": counts, "skeletons": [], "animations": [], "bindings": [], "checks": []}
    by_obj = {}
    for o, c in sorted(cls.items()):
        if c == "hkaSkeleton":
            out["skeletons"].append(skeleton(pf, o))
        elif c in ANIMATION_CLASSES:
            a = animation(pf, o, c)
            by_obj[o] = len(out["animations"])
            out["animations"].append(a)
        elif c == "hkaAnimationBinding":
            out["bindings"].append(binding(pf, o))
    for b in out["bindings"]:
        b["animation"] = by_obj.get(b.pop("animation_object"))
    for sk in out["skeletons"]:
        if len(sk["parents"]) != len(sk["bones"]) or any(p >= len(sk["bones"]) or p < -1 for p in sk["parents"]):
            out["checks"].append(f"skeleton {sk['name']}: {len(sk['bones'])} bones, parents {len(sk['parents'])}")
        if sk["reference_pose"] and any(abs(sum(c * c for c in r["q"]) - 1.0) > 1e-3 for r in sk["reference_pose"]):
            out["checks"].append(f"skeleton {sk['name']}: non-unit reference rotations")
    for a in out["animations"]:
        if not (0.0 < a["duration"] < 3600.0) or not (0 <= a["transform_tracks"] < 1000):
            out["checks"].append(f"animation {a['class']}: duration {a['duration']}, tracks {a['transform_tracks']}")
        if a.get("frames") is not None and a["frame_duration"] > 0:
            want = round(a["duration"] / a["frame_duration"]) + 1
            if abs(want - a["frames"]) > 1:
                out["checks"].append(f"animation: {a['frames']} frames vs duration / frame time + 1 = {want}")
    for b in out["bindings"]:
        a = out["animations"][b["animation"]] if b["animation"] is not None else None
        if a and b["track_to_bone"] and len(b["track_to_bone"]) != a["transform_tracks"]:
            out["checks"].append(f"binding: {len(b['track_to_bone'])} track indices for {a['transform_tracks']} tracks")
    return out
