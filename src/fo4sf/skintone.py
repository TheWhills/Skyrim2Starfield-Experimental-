"""Race skin tones as Starfield skin-tone textures (2026-11-11, docs/npc/races.md "skin tones").

Skyrim tints one base skin with a race's tint presets (RACE tint mask type 6: 5 Orc greens, 5 Dunmer greys ...);
Starfield picks one of 9 full colour textures per skin-tone group (body, hands, face per phenotype; sk0..sk8). A race of
ours gets recoloured copies: each vanilla tone texture keeps its detail (its luminance relative to its own median) on
the race's colour (a 9-step ramp through Skyrim's presets, lightest first like sk0..sk8).

    ramp = tone_ramp([(89, 113, 92), (80, 92, 82), (83, 96, 77), (63, 72, 57), (41, 47, 36)])
    rgba = recolour(decode_dds(vanilla_bytes), ramp[k])
"""
import re
import struct
from typing import List, Sequence, Tuple

import numpy as np

from .textures import read_dds_header, srgb_to_linear, linear_to_srgb

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def _luma_lin(rgb):
    return srgb_to_linear(rgb) @ LUMA


def tone_ramp(colours: Sequence[Tuple[int, int, int]], n: int = 9) -> List[Tuple[int, int, int]]:
    """n sRGB colours from the lightest preset to the darkest, interpolated in linear light (presets sorted by
    luminance; one preset: n copies)."""
    c = sorted((tuple(int(x) for x in rgb) for rgb in colours), key=lambda rgb: -float(_luma_lin(np.array(rgb))))
    if not c:
        raise ValueError("no colours")
    if len(c) == 1:
        return [c[0]] * n
    lin = srgb_to_linear(np.array(c, np.float32))
    out = []
    for k in range(n):
        t = k * (len(c) - 1) / (n - 1)
        i = min(int(t), len(c) - 2)
        f = t - i
        v = lin[i] * (1 - f) + lin[i + 1] * f
        out.append(tuple(int(round(x)) for x in linear_to_srgb(v)))
    return out


def _bc1_colours(c0, c1):
    def rgb565(c):
        return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31], -1)
    a, b = rgb565(c0).astype(np.int32), rgb565(c1).astype(np.int32)
    four = c0 > c1
    p2 = np.where(four[:, None], (2 * a + b) // 3, (a + b) // 2)
    p3 = np.where(four[:, None], (a + 2 * b) // 3, 0)
    return np.stack([a, b, p2, p3], 1)                          # (blocks, 4, 3)


def decode_bc1(data: bytes, width: int, height: int) -> np.ndarray:
    """RGBA uint8 (h, w, 4) of BC1 blocks (mip 0; 3-colour blocks' index 3 drawn black, opaque)."""
    bw, bh = max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    blk = np.frombuffer(data, np.uint8, bw * bh * 8).reshape(-1, 8)
    c0 = blk[:, 0].astype(np.uint32) | (blk[:, 1].astype(np.uint32) << 8)
    c1 = blk[:, 2].astype(np.uint32) | (blk[:, 3].astype(np.uint32) << 8)
    pal = _bc1_colours(c0, c1)
    idx = (blk[:, 4:8].astype(np.uint32)[:, :, None] >> (2 * np.arange(4))) & 3     # (blocks, row, col)
    px = pal[np.arange(len(pal))[:, None, None], idx]                                # (blocks, row, col, 3)
    img = px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 3)[:height, :width]
    return np.concatenate([img.astype(np.uint8), np.full((height, width, 1), 255, np.uint8)], -1)


RAW_RGBA = (28, 29)          # R8G8B8A8_UNORM(_SRGB)
BC1 = (71, 72)               # BC1_UNORM(_SRGB)


def decode_dds(data: bytes) -> np.ndarray:
    """RGBA uint8 (h, w, 4) of a DX10 DDS's mip 0: uncompressed RGBA8 (Starfield's face tones) or BC1 (its body /
    hand tones). Other formats: ValueError."""
    h = read_dds_header(data)
    w, ht, off, dx = h["width"], h["height"], h["data_offset"], h["dxgi"]
    if dx in RAW_RGBA:
        return np.frombuffer(data, np.uint8, w * ht * 4, off).reshape(ht, w, 4).copy()
    if dx in BC1:
        return decode_bc1(data[off:], w, ht)
    raise ValueError(f"DDS format {dx} not decoded here")


def recolour(rgba: np.ndarray, target: Tuple[int, int, int], reference=None) -> np.ndarray:
    """rgba (h, w, 4 uint8) on the colour target: per pixel the target's linear colour times the pixel's luminance
    over the reference luminance (default: the median of pixels with alpha > 0 and some brightness), capped so the
    brightest stay in range; alpha kept."""
    rgb = rgba[..., :3]
    lum = _luma_lin(rgb)
    sel = (rgba[..., 3] > 0) & (lum > 0.002)
    ref = float(reference if reference is not None else (np.median(lum[sel]) if sel.any() else lum.mean() or 1.0))
    tgt = srgb_to_linear(np.array(target, np.float32))
    out = linear_to_srgb(tgt[None, None, :] * (lum / max(ref, 1e-6))[..., None])
    return np.concatenate([np.round(out).clip(0, 255).astype(np.uint8), rgba[..., 3:4]], -1)


def raw_dds(rgba: np.ndarray, srgb: bool = True) -> bytes:
    """A DX10 DDS (R8G8B8A8_UNORM_SRGB, one mip) of rgba (h, w, 4 uint8)."""
    h, w = rgba.shape[:2]
    hdr = b"DDS " + struct.pack("<7I", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x8, h, w, w * 4, 0, 1) + b"\0" * 44
    hdr += struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0) + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    hdr += struct.pack("<5I", RAW_RGBA[1] if srgb else RAW_RGBA[0], 3, 0, 1, 0)
    return hdr + np.ascontiguousarray(rgba, np.uint8).tobytes()


# ------------------------------------------------------------------------------------------- the race's AVMD groups
FACE_PREFIX = "simplegroup_faceskintones_"
FACE_COMPLEX = "complexgroup_faceskintones"
RACE_TONE_SIGS = (b"BSTT", b"HSTT", b"FSTT")


def _text(d):
    d = bytes(d)
    return d[:-1].decode("latin-1") if d.endswith(b"\0") and all(32 <= c < 127 for c in d[:-1]) else None


def _zs(t):
    return t.encode("latin-1") + b"\0"


def tone_group_kind(edid):
    """("body" / "hands" / "face", female) of a Starfield adult skin tone group, ("complex", None) of the face tones'
    complex group, None for the rest (children's, the mannequin's, everything else)."""
    e = (edid or "").lower()
    if "child" in e or "mannequin" in e:
        return None
    if e == FACE_COMPLEX:
        return "complex", None
    if e.startswith(FACE_PREFIX):
        return "face", e[len(FACE_PREFIX):].startswith("female")
    if e.startswith("simplegroup_") and "naked_body_skin_tones" in e:
        return "body", "female" in e
    if e.startswith("simplegroup_") and e.endswith("_hands"):
        return "hands", "female" in e
    return None


def race_tone_groups(avmd, prefix, tex_root, new_fid):
    """Copies of the vanilla adult skin tone groups for a race of ours: avmd [(type, header, subs, FormID)] (AVMD
    records); prefix e.g. "S2S_Orc_" on each copy's EDID / YNAM / TNAM; its textures (VNAM) under tex_root, one set
    per kind and sex (sk0..sk8; every face phenotype shares its sex's set, made from <sex>_default's textures: the
    phenotypes' age detail is lost, 18 face textures instead of 180). The face tones' complex group is copied with
    every string naming a copied group (and every FormID of one) pointed at the copy.
    Returns (records, names {old: new}, jobs {new texture: (vanilla texture, kind, female, slot)}, report)."""
    groups = {}
    for t, h, subs, fid in avmd:
        k = tone_group_kind(_text(dict(subs).get(b"EDID", b"")))
        if k is not None:
            groups[fid] = (k, h, list(subs))
    names, fids, recs, jobs = {}, {}, [], {}
    default_face = {}
    for fid, ((kind, female), _h, subs) in groups.items():
        if kind == "face" and (_text(dict(subs).get(b"EDID", b"")) or "").lower().endswith("_default"):
            default_face[female] = [_text(d) for s, d in subs if s == b"VNAM"]
    for fid, ((kind, female), h, subs) in groups.items():
        for s, d in subs:
            if s in (b"EDID", b"YNAM", b"TNAM") and _text(d):
                names[_text(d)] = prefix + _text(d)
        fids[fid] = new_fid(prefix + _text(dict(subs)[b"EDID"]))
    rep = {"groups": 0, "complex": None}
    for fid, ((kind, female), h, subs) in groups.items():
        out, slot, pointed = [], 0, 0
        for s, d in subs:
            t = _text(d)
            if s in (b"EDID", b"YNAM", b"TNAM") and t:
                out.append((s, _zs(names[t])))
            elif kind == "complex":
                if t is not None and t in names:
                    out.append((s, _zs(names[t])))
                    pointed += 1
                elif len(d) == 4 and struct.unpack("<I", bytes(d))[0] in fids:
                    out.append((s, struct.pack("<I", fids[struct.unpack("<I", bytes(d))[0]])))
                    pointed += 1
                else:
                    out.append((s, d))
            elif s == b"VNAM" and t:
                sex = "female" if female else "male"
                new = f"{tex_root}/{kind}/{sex}_sk{slot}_color.dds"
                src = t
                if kind == "face" and slot < len(default_face.get(female, [])):
                    src = default_face[female][slot]
                jobs.setdefault(new, (src, kind, female, slot))
                out.append((s, _zs(new)))
                slot += 1
            else:
                out.append((s, d))
        if kind == "complex":
            rep["complex"] = {"edid": names.get(_text(dict(subs)[b"EDID"])), "subrecords": len(subs),
                              "pointed_at_copies": pointed,
                              "fields": [(s.decode("latin-1"), _text(d) if _text(d) is not None else bytes(d).hex())
                                         for s, d in subs[:40]]}
        recs.append((b"AVMD", h, out, fids[fid]))
        rep["groups"] += 1
    return recs, names, jobs, rep


def with_tone_names(subs, names, sigs=RACE_TONE_SIGS):
    """A RACE's subrecords with its body / hand / face skin tone strings (BSTT / HSTT / FSTT, every sex section)
    renamed by names ({old: new}; others kept)."""
    return [(s, _zs(names[_text(d)]) if s in sigs and _text(d) in names else d) for s, d in subs]


def slot_ranks(images):
    """{slot: rank}: the slots in order of their vanilla texture's median luminance (0 = lightest)."""
    lum = {k: float(np.median(_luma_lin(img[..., :3]))) for k, img in images.items()}
    return {k: i for i, k in enumerate(sorted(lum, key=lambda k: -lum[k]))}


def slot_colours(images, ramp):
    """{slot: colour}: the ramp's colours (lightest first) given to the slots in order of their vanilla texture's
    median luminance (lightest first), so the race's tones keep Starfield's slot order whichever way it runs."""
    return {k: tuple(ramp[min(i, len(ramp) - 1)]) for k, i in slot_ranks(images).items()}


def relative(rgba, race, human):
    """rgba (h, w, 4 uint8) changed the way Skyrim tells this race from a human of the same rank: per channel, in
    linear light, times race / human (both Skyrim skin tone preset colours; Skyrim lays them over the same kind of
    base skin). The vanilla texture's own colour variation (lips, cheeks) and brightness stay; alpha kept."""
    f = srgb_to_linear(np.array(race, np.float32)) / np.maximum(srgb_to_linear(np.array(human, np.float32)), 1e-4)
    out = linear_to_srgb(np.clip(srgb_to_linear(rgba[..., :3]) * f[None, None, :], 0.0, 1.0))
    return np.concatenate([np.round(out).clip(0, 255).astype(np.uint8), rgba[..., 3:4]], -1)


TEST_COLOURS = ((0, 255, 0), (255, 255, 255), (128, 128, 128))     # slots sk0, sk1, sk2 in --skin-tone-test


def solid(rgba, colour):
    out = np.empty_like(rgba)
    out[..., :3] = colour
    out[..., 3] = rgba[..., 3]
    return out


def appended_tones(avmd, tex_root, count=9):
    """The alien mod's way (SW Aliens.esm, owner's look_probe 2026-11-11: it overrides HumanRace's own tone groups,
    18 entries instead of vanilla's 9, the new ones at the vanilla naming sk9..sk17; its green faces work, while our
    renamed copies of the groups drew no face at all): overrides of the vanilla adult tone groups (body, hands, every
    face phenotype; not the complex group, not children's) with `count` more entries each, after the vanilla ones.
    New entry n (index = vanilla count + k): LNAM the group's first LNAM with its sk number replaced (e.g.
    male_eu_md1_sk9_color), VNAM our texture of race slot k under tex_root (faces: one set per sex, made from
    <sex>_default's textures), NNAM as the first entry's; ITMC raised. The race keeps HumanRace's tone strings.
    Returns (override records, jobs {texture: (vanilla texture, kind, female, k)}, report {"groups", "first_index"})."""
    groups, default_face = [], {}
    for t, h, subs, fid in avmd:
        k = tone_group_kind(_text(dict(subs).get(b"EDID", b"")))
        if k is None or k[0] == "complex":
            continue
        groups.append((k, h, list(subs), fid))
        if k[0] == "face" and (_text(dict(subs).get(b"EDID", b"")) or "").lower().endswith("_default"):
            default_face[k[1]] = [_text(d) for s, d in subs if s == b"VNAM"]
    recs, jobs, firsts = [], {}, set()
    for (kind, female), h, subs, fid in groups:
        entries = [i for i, (s, _d) in enumerate(subs) if s == b"LNAM"]
        if not entries:
            continue
        lnam0 = _text(subs[entries[0]][1]) or ""
        nnam0 = next((d for s, d in subs[entries[0]:] if s == b"NNAM"), struct.pack("<I", 0))
        vanilla = [_text(d) for s, d in subs if s == b"VNAM"]
        n0 = len(entries)
        firsts.add(n0)
        sex = "female" if female else "male"
        new = []
        for k in range(count):
            path = f"{tex_root}/{kind}/{sex}_sk{k}_color.dds"
            srcs = default_face.get(female, vanilla) if kind == "face" else vanilla
            jobs.setdefault(path, (srcs[min(k, len(srcs) - 1)], kind, female, k))
            name = re.sub(r"sk\d+", f"sk{n0 + k}", lnam0, count=1) if re.search(r"sk\d+", lnam0) else f"{lnam0}_{n0 + k}"
            new += [(b"LNAM", _zs(name)), (b"VNAM", _zs(path)), (b"NNAM", nnam0)]
        end = max(i for i, (s, _d) in enumerate(subs) if s in (b"LNAM", b"VNAM", b"NNAM")) + 1
        out = subs[:end] + new + subs[end:]
        out = [(s, struct.pack("<I", n0 + count) if s == b"ITMC" else d) for s, d in out]
        recs.append((b"AVMD", h, out, fid))
    return recs, jobs, {"groups": len(recs), "first_index": sorted(firsts)}
