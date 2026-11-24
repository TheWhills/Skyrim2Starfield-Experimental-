"""Texture conversion helpers: Fallout 4 DDS (spec/gloss) -> Starfield DDS (color / normal / rough).

Needs numpy. Final block compression is done by Microsoft's `texconv` (ships with xEdit in `Edit Scripts/`).

Formats (measured on vanilla files, see docs/spikes/S3-materials.md):
  Fallout 4  _d  DXT5 / BC1 colour, sRGB      _n  BC5 (fourCC "BC5U" / ATI2) RG tangent-space normal
             _s  BC5 (fourCC "BC5U"): R = specular strength, G = smoothness (gloss)
  Starfield  _color  BC1_SRGB (BC7_SRGB with alpha)   _normal  BC5_SNORM   _rough  BC4_UNORM (1.0 = fully rough)
"""
import struct
import subprocess

import numpy as np

DDS_MAGIC = b"DDS "
DXGI_R8_UNORM = 61
DXGI_R8G8_SNORM = 51
DXGI_R8G8B8A8_UNORM = 28


class DdsError(ValueError):
    pass


def read_dds_header(data: bytes):
    if data[:4] != DDS_MAGIC:
        raise DdsError("not a DDS file")
    height, width = struct.unpack_from("<II", data, 12)
    mips, = struct.unpack_from("<I", data, 28)
    four = data[84:88]
    dxgi, offset = None, 128
    if four == b"DX10":
        dxgi, = struct.unpack_from("<I", data, 128)
        offset = 148
    return {"width": width, "height": height, "mips": max(mips, 1), "fourcc": four, "dxgi": dxgi, "data_offset": offset}


# ---- block decoders (mip 0 only) ---------------------------------------------------------

def _bc4_block_values(blocks):
    """blocks: (N, 8) uint8 -> (N, 16) uint8 values (BC4 / BC5 single-channel unorm)."""
    a0 = blocks[:, 0].astype(np.float32)
    a1 = blocks[:, 1].astype(np.float32)
    pal = np.zeros((len(blocks), 8), dtype=np.float32)
    pal[:, 0], pal[:, 1] = a0, a1
    gt = a0 > a1
    for i in range(1, 7):
        pal[:, i + 1] = np.where(gt, ((7 - i) * a0 + i * a1) / 7.0, 0.0)
    for i in range(1, 5):
        pal[:, i + 1] = np.where(~gt, ((5 - i) * a0 + i * a1) / 5.0, pal[:, i + 1])
    pal[:, 6] = np.where(~gt, 0.0, pal[:, 6])
    pal[:, 7] = np.where(~gt, 255.0, pal[:, 7])
    bits = blocks[:, 2:8].astype(np.uint64)
    word = np.zeros(len(blocks), dtype=np.uint64)
    for i in range(6):
        word |= bits[:, i] << np.uint64(8 * i)
    out = np.zeros((len(blocks), 16), dtype=np.uint8)
    for px in range(16):
        idx = ((word >> np.uint64(3 * px)) & np.uint64(7)).astype(np.int64)
        out[:, px] = np.round(pal[np.arange(len(blocks)), idx]).astype(np.uint8)
    return out


def _blocks_to_plane(values, width, height):
    bw, bh = width // 4, height // 4
    v = values.reshape(bh, bw, 4, 4)                     # block row, block col, y in block, x in block
    return v.transpose(0, 2, 1, 3).reshape(height, width)


def decode_bc4(data: bytes, width: int, height: int):
    n = (width // 4) * (height // 4)
    blocks = np.frombuffer(data[:n * 8], dtype=np.uint8).reshape(n, 8)
    return _blocks_to_plane(_bc4_block_values(blocks), width, height)


def decode_bc5(data: bytes, width: int, height: int):
    """Returns (R, G) planes, uint8."""
    n = (width // 4) * (height // 4)
    blocks = np.frombuffer(data[:n * 16], dtype=np.uint8).reshape(n, 16)
    return (_blocks_to_plane(_bc4_block_values(blocks[:, :8]), width, height),
            _blocks_to_plane(_bc4_block_values(blocks[:, 8:]), width, height))


def _bc1_colour_values(blocks, four_colour_always: bool):
    """blocks: (N, 8) uint8 BC1 colour blocks -> (N, 16, 4) uint8 RGBA (alpha 0 for BC1's transparent index)."""
    c0 = blocks[:, 0].astype(np.uint32) | (blocks[:, 1].astype(np.uint32) << 8)
    c1 = blocks[:, 2].astype(np.uint32) | (blocks[:, 3].astype(np.uint32) << 8)

    def rgb(c):
        r = ((c >> 11) & 31) * 255.0 / 31.0
        g = ((c >> 5) & 63) * 255.0 / 63.0
        b = (c & 31) * 255.0 / 31.0
        return np.stack([r, g, b], axis=1)
    a, b = rgb(c0), rgb(c1)
    four = np.ones(len(blocks), bool) if four_colour_always else (c0 > c1)
    pal = np.zeros((len(blocks), 4, 4), np.float32)
    pal[:, 0, :3], pal[:, 1, :3] = a, b
    pal[:, :, 3] = 255.0
    pal[:, 2, :3] = np.where(four[:, None], (2 * a + b) / 3.0, (a + b) / 2.0)
    pal[:, 3, :3] = np.where(four[:, None], (a + 2 * b) / 3.0, 0.0)
    pal[:, 3, 3] = np.where(four, 255.0, 0.0)
    idx = blocks[:, 4].astype(np.uint32) | (blocks[:, 5].astype(np.uint32) << 8) | \
        (blocks[:, 6].astype(np.uint32) << 16) | (blocks[:, 7].astype(np.uint32) << 24)
    out = np.zeros((len(blocks), 16, 4), np.uint8)
    rows = np.arange(len(blocks))
    for px in range(16):
        k = ((idx >> np.uint32(2 * px)) & np.uint32(3)).astype(np.int64)
        out[:, px] = np.round(pal[rows, k]).astype(np.uint8)
    return out


def _blocks_to_rgba(values, width, height):
    bw, bh = max(1, width // 4), max(1, height // 4)
    v = values.reshape(bh, bw, 4, 4, 4)
    return v.transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)


def decode_dxt(data: bytes):
    """Top mip of a DXT1 / DXT5 (BC1 / BC3) DDS, legacy or DX10 header -> (h, w, 4) uint8 RGBA. Skyrim's effect
    textures are DXT5; for looking at them (flame_textures.py) without texconv."""
    h = read_dds_header(data)
    w, ht, off = h["width"], h["height"], h["data_offset"]
    n = max(1, w // 4) * max(1, ht // 4)
    if h["fourcc"] == b"DXT1" or h["dxgi"] in (71, 72):
        blocks = np.frombuffer(data[off:off + n * 8], np.uint8).reshape(n, 8)
        return _blocks_to_rgba(_bc1_colour_values(blocks, False), w, ht)
    if h["fourcc"] in (b"DXT5", b"DXT4") or h["dxgi"] in (77, 78):
        blocks = np.frombuffer(data[off:off + n * 16], np.uint8).reshape(n, 16)
        out = _bc1_colour_values(np.ascontiguousarray(blocks[:, 8:]), True)
        out[:, :, 3] = _bc4_block_values(np.ascontiguousarray(blocks[:, :8]))
        return _blocks_to_rgba(out, w, ht)
    raise DdsError(f"decode_dxt: unsupported format {h['fourcc']!r} / dxgi {h['dxgi']}")


def load_fo4_bc5(path):
    d = open(path, "rb").read()
    h = read_dds_header(d)
    if h["fourcc"] not in (b"BC5U", b"ATI2") and h["dxgi"] not in (83, 84):
        raise DdsError(f"{path}: expected BC5, got {h['fourcc']!r}/{h['dxgi']}")
    return decode_bc5(d[h["data_offset"]:], h["width"], h["height"])


# ---- DDS writers (uncompressed intermediates that texconv then compresses) ----------------

def write_dds_dx10(path, width, height, dxgi, pixels: bytes, bytes_per_pixel: int):
    hdr = DDS_MAGIC + struct.pack("<7I", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x8, height, width, width * bytes_per_pixel, 0, 1)
    hdr += b"\0" * 44
    hdr += struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    hdr += struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    hdr += struct.pack("<5I", dxgi, 3, 0, 1, 0)
    with open(path, "wb") as f:
        f.write(hdr + pixels)


DXGI_R16G16B16A16_FLOAT = 10


def write_dds_cube_rgba16f(path, faces, size: int = 4):
    """A cube map DDS (DX10 header, TEXTURECUBE, R16G16B16A16_FLOAT, a full mip chain) whose six faces are each one
    flat linear RGB colour, in D3D face order +X, -X, +Y, -Y, +Z, -Z (2026-11-21, a cell's environment light)."""
    levels, s_ = 0, size
    while s_ >= 1:
        levels += 1
        s_ //= 2
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000                          # caps, height, width, pixel format, mip count
    hdr = DDS_MAGIC + struct.pack("<7I", 124, flags, size, size, size * 8, 0, levels) + b"\0" * 44
    hdr += struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    hdr += struct.pack("<5I", 0x1000 | 0x8 | 0x400000, 0x200 | 0xFC00, 0, 0, 0)   # complex + mipmap; cube, all faces
    hdr += struct.pack("<5I", DXGI_R16G16B16A16_FLOAT, 3, 0x4, 1, 0)             # 2D, TEXTURECUBE, one cube
    body = b""
    for rgb in faces:
        px = np.array([rgb[0], rgb[1], rgb[2], 1.0], dtype=np.float16).tobytes()
        s_ = size
        while s_ >= 1:
            body += px * (s_ * s_)
            s_ //= 2
    with open(path, "wb") as f:
        f.write(hdr + body)


def write_r8(path, plane):
    h, w = plane.shape
    write_dds_dx10(path, w, h, DXGI_R8_UNORM, np.ascontiguousarray(plane, dtype=np.uint8).tobytes(), 1)


def coverage(plane, ref: int) -> float:
    """Share of texels an alpha test at ref (0..255) keeps."""
    return float((np.asarray(plane) >= ref).mean()) if np.asarray(plane).size else 0.0


def coverage_mips(plane, ref: int):
    """A mip chain (level 0 = plane, down to 1 x 1) for an alpha-tested opacity map, each level box-filtered from
    the one above and then scaled so the share of texels passing the alpha test stays the base level's.
    2026-11-24 (owner, Skyrim grass in game): with ordinary box-filtered mips the gaps between thin blades average
    above the cut-out threshold and whole grass cards draw solid ("fins"); foliage keeps its coverage this way."""
    base = np.asarray(plane, np.float32)
    target = coverage(base, ref)
    levels = [np.asarray(plane, np.uint8)]
    cur = base
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        h, w = cur.shape
        nh, nw = max(1, h // 2), max(1, w // 2)
        c = cur[:nh * 2 if h > 1 else 1, :nw * 2 if w > 1 else 1]
        if h > 1:
            c = (c[0::2] + c[1::2]) / 2.0
        if w > 1:
            c = (c[:, 0::2] + c[:, 1::2]) / 2.0
        cur = c
        scale = 1.0
        if coverage(cur, ref) != target:
            lo, hi = 0.0, 16.0
            for _ in range(24):                 # the scale where coverage(cur * s) reaches the target
                s = (lo + hi) / 2.0
                if coverage(np.clip(cur * s, 0, 255), ref) < target:
                    lo = s
                else:
                    hi = s
            cov_lo = coverage(np.clip(cur * lo, 0, 255), ref)
            cov_hi = coverage(np.clip(cur * hi, 0, 255), ref)
            scale = lo if abs(cov_lo - target) < abs(cov_hi - target) else hi
        levels.append(np.clip(np.round(cur * scale), 0, 255).astype(np.uint8))
    return levels


DDSD_MIPMAPCOUNT = 0x20000
DDSCAPS_COMPLEX_MIPMAP = 0x400008
DX10_HEADER_BYTES = 4 + 124 + 20


def assemble_mips(level_files):
    """One DDS with a mip chain from single-level DDS files of the same format (bytes, level 0 first): level 0's
    header with the mip count set, then every level's data in order (the DDS layout of a 2D texture)."""
    if not level_files:
        raise DdsError("no levels")
    head = bytearray(level_files[0][:DX10_HEADER_BYTES])
    if head[:4] != DDS_MAGIC or head[84:88] != b"DX10":
        raise DdsError("level 0 is not a DX10 DDS")
    flags, = struct.unpack_from("<I", head, 8)
    struct.pack_into("<I", head, 8, flags | DDSD_MIPMAPCOUNT)
    struct.pack_into("<I", head, 28, len(level_files))
    caps, = struct.unpack_from("<I", head, 108)
    struct.pack_into("<I", head, 108, caps | DDSCAPS_COMPLEX_MIPMAP)
    return bytes(head) + b"".join(f[DX10_HEADER_BYTES:] for f in level_files)


def write_bc4_coverage_mips(texconv_exe, plane, ref: int, out_path, tmp_dir):
    """An alpha-tested opacity map as BC4 with coverage-preserving mips (coverage_mips): each level compressed on
    its own by texconv, then joined (assemble_mips)."""
    import os
    blobs = []
    for i, lv in enumerate(coverage_mips(plane, ref)):
        src = os.path.join(tmp_dir, f"cov_mip{i}.dds")
        write_r8(src, lv)
        texconv(texconv_exe, src, tmp_dir, "BC4_UNORM", extra=("-m", "1"))
        with open(src, "rb") as fh:
            blobs.append(fh.read())
    with open(out_path, "wb") as fh:
        fh.write(assemble_mips(blobs))


def write_rg8_snorm(path, r_unorm, g_unorm):
    """Map unorm 0..255 (0.5 = zero) to signed bytes and write an R8G8_SNORM DDS."""
    h, w = r_unorm.shape
    conv = lambda a: np.clip(np.round((a.astype(np.float32) / 255.0 * 2.0 - 1.0) * 127.0), -127, 127).astype(np.int8)  # noqa: E731
    px = np.stack([conv(r_unorm), conv(g_unorm)], axis=-1)
    write_dds_dx10(path, w, h, DXGI_R8G8_SNORM, px.tobytes(), 2)


# ---- size caps (drop the top mip levels of a block-compressed DDS) ------------------------------

# bytes per 4 x 4 block: DXGI BC1..BC7 (typeless / unorm / srgb / snorm variants) and the legacy FourCCs
BC_BLOCK_BYTES_DXGI = {**{f: 8 for f in (70, 71, 72, 79, 80, 81)},
                       **{f: 16 for f in (73, 74, 75, 76, 77, 78, 82, 83, 84, 94, 95, 96, 97, 98, 99)}}
BC_BLOCK_BYTES_FOURCC = {b"DXT1": 8, b"ATI1": 8, b"BC4U": 8, b"BC4S": 8,
                         b"DXT2": 16, b"DXT3": 16, b"DXT4": 16, b"DXT5": 16, b"ATI2": 16, b"BC5U": 16, b"BC5S": 16}
TEXTURE_KINDS = ("color", "normal", "rough", "opacity")


def _bc_level_bytes(width, height, level, block_bytes):
    w, h = max(1, width >> level), max(1, height >> level)
    return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block_bytes


def cap_dds(data: bytes, max_side: int):
    """Drop the top mip levels of a 2-D block-compressed DDS until neither side exceeds max_side. The remaining levels
    are the original bytes (no re-encoding), so the result is exactly what a full mip chain holds at that size.
    Returns (bytes, info); data comes back unchanged (info["capped"] False, with a reason) when max_side <= 0, the
    texture already fits, it is not block-compressed, it is a cube map / array / volume, it has no smaller mip level,
    or its size does not match its header."""
    info = {"capped": False, "bytes": len(data), "out_bytes": len(data)}
    try:
        h = read_dds_header(data)
    except DdsError:
        return data, dict(info, reason="not a DDS")
    w, ht, mips, off = h["width"], h["height"], h["mips"], h["data_offset"]
    info.update(width=w, height=ht, mips=mips, out_width=w, out_height=ht, out_mips=mips)
    if max_side <= 0 or max(w, ht) <= max_side:
        return data, dict(info, reason="fits")
    bb = BC_BLOCK_BYTES_DXGI.get(h["dxgi"]) if h["dxgi"] is not None else BC_BLOCK_BYTES_FOURCC.get(bytes(h["fourcc"]))
    if bb is None:
        return data, dict(info, reason="not block-compressed")
    caps2, = struct.unpack_from("<I", data, 112)
    depth, = struct.unpack_from("<I", data, 24)
    if h["dxgi"] is not None:
        _fmt, dim, misc, array, _m2 = struct.unpack_from("<5I", data, 128)
        if dim != 3 or misc & 0x4 or array > 1:
            return data, dict(info, reason="not a single 2-D texture")
    if caps2 & 0x200 or (caps2 & 0x200000 and depth > 1):
        return data, dict(info, reason="not a single 2-D texture")
    need = sum(_bc_level_bytes(w, ht, i, bb) for i in range(mips))
    if len(data) != off + need:
        return data, dict(info, reason=f"size {len(data)} does not match the header ({off + need})")
    drop = 0
    while max(max(1, w >> drop), max(1, ht >> drop)) > max_side and drop < mips - 1:
        drop += 1
    if drop == 0:
        return data, dict(info, reason="no smaller mip level")
    skip = sum(_bc_level_bytes(w, ht, i, bb) for i in range(drop))
    hdr = bytearray(data[:off])
    nw, nh, nm = max(1, w >> drop), max(1, ht >> drop), mips - drop
    struct.pack_into("<II", hdr, 12, nh, nw)
    struct.pack_into("<I", hdr, 20, _bc_level_bytes(nw, nh, 0, bb))       # pitchOrLinearSize of the new top level
    struct.pack_into("<I", hdr, 28, nm)
    if nm == 1:                                                             # no mip chain left: clear its flags
        flags, = struct.unpack_from("<I", hdr, 8)
        caps, = struct.unpack_from("<I", hdr, 108)
        struct.pack_into("<I", hdr, 8, flags & ~0x20000)
        struct.pack_into("<I", hdr, 108, caps & ~0x400008)
    out = bytes(hdr) + data[off + skip:]
    info.update(capped=True, dropped=drop, out_width=nw, out_height=nh, out_mips=nm, out_bytes=len(out))
    return out, info


def parse_texture_caps(spec) -> dict:
    """'' or 0 -> {} (no cap); '1024' -> the same cap for every kind; 'color=1024,normal=512,rough=256,opacity=512'
    -> per kind (kinds left out are not capped). Caps are positive integers."""
    if spec in (None, "", 0, "0"):
        return {}
    if isinstance(spec, int) or str(spec).strip().isdigit():
        n = int(spec)
        if n <= 0:
            raise ValueError(f"texture cap must be positive: {spec!r}")
        return {k: n for k in TEXTURE_KINDS}
    out = {}
    for part in str(spec).split(","):
        k, sep, v = part.strip().partition("=")
        if not sep or k not in TEXTURE_KINDS or not v.strip().isdigit() or int(v) <= 0:
            raise ValueError(f"bad texture cap {part!r}: want <kind>=<pixels>, kinds {', '.join(TEXTURE_KINDS)}")
        out[k] = int(v)
    return out


def texconv(texconv_exe, src, out_dir, fmt, extra=()):
    mips = () if "-m" in extra else ("-m", "0")          # full mip chain unless the caller sets -m
    r = subprocess.run([texconv_exe, "-nologo", "-y", *mips, "-dx10", "-f", fmt, *extra, "-o", out_dir, src],
                       capture_output=True, text=True)
    if r.returncode != 0 or "FAILED" in r.stdout:
        raise DdsError(f"texconv failed for {src}: {r.stdout.strip()[-300:]} {r.stderr.strip()[-200:]}")


# ---- Fallout 4 spec/gloss -> Starfield PBR -------------------------------------------------

def roughness_from_smoothness(g, smoothness: float = 1.0, spec_mult: float = 1.0):
    """FO4 gloss (0..255, 255 = mirror) -> Starfield roughness (255 = fully rough).
    The material's smoothness scalar multiplies the gloss map (FO4 cave rock: map all 255, smoothness 0.5). Starfield has no
    specular multiplier, so a weak FO4 specular (spec_mult < 1) is approximated by scaling gloss by sqrt(spec_mult)."""
    k = max(0.0, min(1.0, smoothness)) * max(0.0, min(1.0, spec_mult)) ** 0.5
    return (255 - np.round(g.astype(np.float32) * k)).clip(0, 255).astype(np.uint8)


def flip_green(g):
    return (255 - g.astype(np.int32)).astype(np.uint8)


def srgb_to_linear(v):
    import numpy as np
    v = np.asarray(v, np.float32) / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(v):
    import numpy as np
    v = np.clip(np.asarray(v, np.float32), 0.0, 1.0)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055) * 255.0


def scale_albedo(rgb, target_luminance: float, max_gain: float = 6.0):
    """Scale an sRGB colour image (uint8 [..., 3]) in linear light so its mean luminance becomes target_luminance
    (linear, 0..1), keeping hue and relative detail; the gain is capped. Opt-in for Skyrim ground
    (--skyrim-ground-brightness): the pale Riverwood patch it was added for turned out to be a wrong BTD texture index,
    and the owner's side-by-sides showed Skyrim's own dark colours are right (vanilla DirtFootprints01 averages sRGB
    (144, 109, 90), linear luminance about 0.17)."""
    import numpy as np
    lin = srgb_to_linear(rgb)
    lum = float((lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)).mean())
    gain = min(max_gain, target_luminance / lum) if lum > 1e-6 else 1.0
    return np.rint(linear_to_srgb(lin * gain)).astype(np.uint8)
