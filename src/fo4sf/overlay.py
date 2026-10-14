"""Records and files a Starfield worldspace needs to act as a unique terrain overlay (docs/terrain/overlay-records.md).

A worldspace's own BTD is applied only when the worldspace is an activated overlay on a planet. Vanilla unique
overlays differ from our first experiment plugins in a few verifiable places; this module holds the pure arithmetic for
them so it can be tested with synthetic data (tests/test_overlay.py):

* SFBK FNAM: DNAM.x * DNAM.y u16 values, one per BTD cell, cells row-major from the south row, west to east. Each value
  is the raw u16 BTD height of the cell's south-west corner sample (row 0, column 0 of the cell). Exact for every cell
  in 1,464 of the 1,711 vanilla SFBK whose BTD decodes (94.6 % of all cells); min, max, mean, median, midrange and
  cell centre match no record exactly (offline survey, 2026-10-11).
* Overlay mask: textures/terrain/overlaymasks/<edid lower case>.dds, BC4, 100 px per cell, 0 inside the authored area
  and 255 on a ring of border cells (vanilla). Only procedural generation reads it (supported, unverified in game).

Image rows here are written north-first (row 0 = north edge, like a DDS). Whether the engine reads mask rows
north-first or south-first is UNRESOLVED (QA's offline count of placed references inside the mask-0 area points both
ways: NewAtlantis 0.990 north-first vs 0.835 south-first, lc001world 0.818 vs 0.973; PR #67 review, not repeated
here). A full ring is the same either way; a mask with a ring on
only one of the north / south edges is not, so overlay_grid.mask_edges writes north / south rings only in pairs by
default.
"""
import struct

import numpy as np

CELL_SAMPLES = 128
MASK_PX_PER_CELL = 100
DDS_MAGIC = b"DDS "
DXGI_BC4_UNORM = 80


# ------------------------------------------------------------------------------------------------------------ FNAM
def fnam_values(heights_raw):
    """Per-cell SFBK FNAM values for a raw u16 BTD height grid [ny*128, nx*128] (row 0 = south):
    the raw height at each cell's south-west corner sample, cells row-major from the south row."""
    h = np.asarray(heights_raw)
    if h.ndim != 2 or h.shape[0] % CELL_SAMPLES or h.shape[1] % CELL_SAMPLES:
        raise ValueError("heights must be a 2-D grid of whole 128-sample cells")
    return [int(v) for v in h[::CELL_SAMPLES, ::CELL_SAMPLES].astype(np.uint16).ravel()]


def fnam_bytes(heights_raw):
    """FNAM payload: DNAM.x * DNAM.y little-endian u16 (vanilla size, e.g. 18 B for 3 x 3 cells, 50 B for 5 x 5)."""
    v = fnam_values(heights_raw)
    return struct.pack(f"<{len(v)}H", *v)


def fnam_match(fnam, heights_raw):
    """(exact cells, cells, max |difference|) between a stored FNAM (bytes or values) and the SW-corner rule."""
    want = np.array(fnam_values(heights_raw), np.int64)
    got = np.frombuffer(fnam, "<u2").astype(np.int64) if isinstance(fnam, (bytes, bytearray)) else np.asarray(fnam)
    if got.size != want.size:
        return 0, int(want.size), None
    d = np.abs(got - want)
    return int((d == 0).sum()), int(want.size), int(d.max())


# ------------------------------------------------------------------------------------------------------------ mask
EDGES = ("w", "e", "s", "n")


def mask_array(cells_x, cells_y=None, border_cells=1, px_per_cell=MASK_PX_PER_CELL, edges=EDGES):
    """Overlay mask image (uint8, rows written north-first): 0 inside, 255 on the outer `border_cells` ring of cells.
    `edges` limits the ring to some sides ('w', 'e', 's', 'n'): a tile of a grid of adjacent overlays keeps 0 on the
    seams it shares with its neighbours (docs/terrain/commonwealth-scale.md). A ring on 'n' without 's' (or the
    reverse) depends on the engine's unresolved row order."""
    cells_y = cells_x if cells_y is None else cells_y
    if cells_x <= 2 * border_cells or cells_y <= 2 * border_cells:
        raise ValueError("the border ring leaves no inside")
    if any(e not in EDGES for e in edges):
        raise ValueError(f"edges must be among {EDGES}")
    a = np.zeros((cells_y * px_per_cell, cells_x * px_per_cell), np.uint8)
    b = border_cells * px_per_cell
    if "w" in edges:
        a[:, :b] = 255
    if "e" in edges:
        a[:, a.shape[1] - b:] = 255
    if "n" in edges:                    # row 0 = north
        a[:b, :] = 255
    if "s" in edges:
        a[a.shape[0] - b:, :] = 255
    return a


# ------------------------------------------------------------------------------------------------------------ DDS
def dds_info(b):
    """Header facts of a DDS: width, height, mip count and format ('BC4' for ATI1/BC4U or DXGI 80)."""
    if b[:4] != DDS_MAGIC:
        raise ValueError("not a DDS file")
    h, w = struct.unpack_from("<II", b, 12)
    mips = max(1, struct.unpack_from("<I", b, 28)[0])
    fourcc = bytes(b[84:88])
    off, fmt = 128, fourcc.decode("latin1")
    if fourcc == b"DX10":
        dxgi = struct.unpack_from("<I", b, 128)[0]
        off, fmt = 148, ("BC4" if dxgi in (79, 80, 81) else f"DXGI{dxgi}")
    elif fourcc in (b"ATI1", b"BC4U"):
        fmt = "BC4"
    return {"width": w, "height": h, "mips": mips, "format": fmt, "data_offset": off}


def bc4_decode_blocks(data, width, height):
    """Decode the top mip of BC4 (unsigned) block data to a uint8 image [height, width]."""
    bw, bh = (width + 3) // 4, (height + 3) // 4
    blk = np.frombuffer(bytes(data[:bw * bh * 8]), np.uint8).reshape(bh * bw, 8).astype(np.int32)
    r0, r1 = blk[:, 0], blk[:, 1]
    bits = np.zeros(len(blk), np.uint64)
    for i in range(6):
        bits |= blk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    pal = np.zeros((len(blk), 8), np.float64)
    pal[:, 0], pal[:, 1] = r0, r1
    gt = r0 > r1
    for i in range(1, 7):
        pal[:, 1 + i] = np.where(gt, ((7 - i) * r0 + i * r1) / 7.0, pal[:, 1 + i])
    for i in range(1, 5):
        pal[:, 1 + i] = np.where(~gt, ((5 - i) * r0 + i * r1) / 5.0, pal[:, 1 + i])
    pal[:, 6] = np.where(~gt, 0, pal[:, 6])
    pal[:, 7] = np.where(~gt, 255, pal[:, 7])
    idx = np.stack([(bits >> np.uint64(3 * k)) & np.uint64(7) for k in range(16)], 1).astype(np.int64)
    px = np.take_along_axis(pal, idx, 1).reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
    return np.clip(np.round(px), 0, 255).astype(np.uint8)[:height, :width]


def bc4_decode(dds):
    """Top mip of a BC4 DDS as a uint8 image (rows as stored: row 0 = top of the image)."""
    i = dds_info(dds)
    if i["format"] != "BC4":
        raise ValueError(f"not BC4: {i['format']}")
    return bc4_decode_blocks(dds[i["data_offset"]:], i["width"], i["height"])


def bc4_encode_blocks(img):
    """Lossless BC4 blocks for an image whose every 4 x 4 block holds at most the two values 0 and 255 (ring masks):
    endpoints r0 = 255, r1 = 0 (8-value mode), index 0 -> 255, index 1 -> 0. Used by the tests to build DDS input."""
    a = np.asarray(img, np.uint8)
    if a.shape[0] % 4 or a.shape[1] % 4 or not np.isin(a, (0, 255)).all():
        raise ValueError("only 0/255 images with sizes divisible by 4")
    out = bytearray()
    for by in range(0, a.shape[0], 4):
        for bx in range(0, a.shape[1], 4):
            blk = a[by:by + 4, bx:bx + 4].ravel()
            bits = 0
            for k, v in enumerate(blk):
                bits |= (0 if v == 255 else 1) << (3 * k)
            out += bytes((255, 0)) + bits.to_bytes(6, "little")
    return bytes(out)


def dds_bc4(img):
    """A minimal DX10 BC4_UNORM DDS (one mip) for a 0/255 image: test fixture and fallback writer."""
    a = np.asarray(img, np.uint8)
    h, w = a.shape
    hdr = bytearray(124)
    struct.pack_into("<IIIIIII", hdr, 0, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, h, w, ((w + 3) // 4) * 8 * ((h + 3) // 4), 0, 1)
    struct.pack_into("<II4s", hdr, 72, 32, 0x4, b"DX10")
    struct.pack_into("<I", hdr, 104, 0x1000)
    dx10 = struct.pack("<IIIII", DXGI_BC4_UNORM, 3, 0, 1, 0)
    return DDS_MAGIC + bytes(hdr) + dx10 + bc4_encode_blocks(a)


def mask_check(img, cells_x, cells_y=None, border_cells=1, px_per_cell=MASK_PX_PER_CELL, edges=EDGES):
    """Compare a decoded mask with mask_array(): (pixels that differ, max |difference|)."""
    want = mask_array(cells_x, cells_y, border_cells, px_per_cell, edges).astype(np.int32)
    got = np.asarray(img).astype(np.int32)
    if got.shape != want.shape:
        return int(want.size), 255
    d = np.abs(got - want)
    return int((d > 0).sum()), int(d.max())
