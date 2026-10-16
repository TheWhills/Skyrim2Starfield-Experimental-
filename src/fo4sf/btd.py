"""Starfield terrain (.btd) reader and writer.

Layout (Starfield variant), after fo76utils src/btdfile.cpp (MIT, (c) 2021-2025 fo76utils) and checked against vanilla
files (docs/terrain/architecture.md, section 1.4):

    "BTDB", u32 version, f32 height min, f32 height max      metres; raw u16 0..65535 maps linearly onto [min, max]
    u32 samples x, u32 samples y                              cells x 128 (100 m cells -> 0.78125 m spacing)
    4 x i32 cell rectangle                                    always 0 in Starfield
    u32 n, n x u32 LTEX FormIDs
    per cell        f32 min, f32 max                          of the decoded LOD0 heights
    per quadrant    8 bytes LTEX table indices                (index + 1 in Starfield, landtex.INDEX_RULE)
    LOD4            8 x 8 u16 heights per cell, then 8 x 8 u16 land-texture weights (every 16th sample)
    zlib tables     (u32 offset, u32 size) for LOD3 (8x8-cell groups), LOD2 (4x4), LOD1 (2x2), LOD0 (1 cell)
    zlib blocks     65,536 bytes each: 128 x 128 u16 heights then 128 x 128 u16 weights; LOD l = full grid sampled
                    every 2^l from the group's SW corner; partial groups padded with 0

Arrays here are indexed [row, column] with row 0 = south edge, column 0 = west edge. Only the numbers above are
verified offline; what the engine does with a new file is not (see the experiment in docs/terrain/architecture.md).
"""
import struct
import zlib
from dataclasses import dataclass, field
from typing import List

import numpy as np

MAGIC = b"BTDB"
CELL_SAMPLES = 128


class BtdError(ValueError):
    pass


@dataclass
class Btd:
    version: int
    hmin: float
    hmax: float
    ltex: List[int]
    heights_raw: np.ndarray            # uint16 [ny*128, nx*128]
    weights: np.ndarray                # uint16 same shape (3-bit alphas, 5 layers)
    quad_map: np.ndarray               # uint8 [ny*2, nx*2, 8]
    cell_minmax: np.ndarray = field(default=None)   # float32 [ny, nx, 2] as stored

    @property
    def ncx(self):
        return self.heights_raw.shape[1] // CELL_SAMPLES

    @property
    def ncy(self):
        return self.heights_raw.shape[0] // CELL_SAMPLES

    def heights_m(self) -> np.ndarray:
        return self.hmin + self.heights_raw.astype(np.float64) / 65535.0 * (self.hmax - self.hmin)


def _group_count(n, l):
    return (n + (1 << l) - 1) >> l


def read(b: bytes) -> Btd:
    if b[:4] != MAGIC:
        raise BtdError("not a BTD file")
    ver, hmin, hmax, rx, ry, x0, y0, x1, y1, nlt = struct.unpack_from("<IffIIiiiiI", b, 4)
    if x0 | y0 | x1 | y1:
        raise BtdError("cell rectangle set: Fallout 76 style BTD, not handled")
    if rx % CELL_SAMPLES or ry % CELL_SAMPLES:
        raise BtdError(f"resolution {rx}x{ry} is not a multiple of 128")
    ncx, ncy = rx // CELL_SAMPLES, ry // CELL_SAMPLES
    n = ncx * ncy
    p = 44
    ltex = list(struct.unpack_from(f"<{nlt}I", b, p)); p += 4 * nlt
    mm = np.frombuffer(b, "<f4", 2 * n, p).reshape(ncy, ncx, 2).copy(); p += 8 * n
    quad = np.frombuffer(b, np.uint8, 32 * n, p).reshape(ncy * 2, ncx * 2, 8).copy(); p += 32 * n
    p += 256 * n                                   # LOD4 heights + weights (derivable from LOD0)
    tables = {}
    for l in (3, 2, 1, 0):
        cnt = _group_count(ncy, l) * _group_count(ncx, l)
        tables[l] = (p, cnt); p += 8 * cnt
    data_off = p
    off0, cnt0 = tables[0]
    h = np.zeros((ry, rx), np.uint16)
    w = np.zeros((ry, rx), np.uint16)
    for i in range(cnt0):
        o, sz = struct.unpack_from("<II", b, off0 + 8 * i)
        raw = zlib.decompress(b[data_off + o:data_off + o + sz])
        if len(raw) != 65536:
            raise BtdError(f"LOD0 block {i}: {len(raw)} bytes")
        cy, cx = divmod(i, ncx)
        h[cy * 128:(cy + 1) * 128, cx * 128:(cx + 1) * 128] = np.frombuffer(raw, "<u2", 16384, 0).reshape(128, 128)
        w[cy * 128:(cy + 1) * 128, cx * 128:(cx + 1) * 128] = np.frombuffer(raw, "<u2", 16384, 32768).reshape(128, 128)
    return Btd(ver, hmin, hmax, ltex, h, w, quad, mm)


def quantize(heights_m: np.ndarray, hmin: float, hmax: float) -> np.ndarray:
    """Metres -> raw u16 for the [hmin, hmax] range (clipped)."""
    r = np.round((np.asarray(heights_m, np.float64) - hmin) / (hmax - hmin) * 65535.0)
    return np.clip(r, 0, 65535).astype(np.uint16)


def write(t: Btd, level: int = 9) -> bytes:   # vanilla zlib header is 78 DA (best compression)
    h, w = t.heights_raw, t.weights
    if h.shape != w.shape or h.shape[0] % 128 or h.shape[1] % 128:
        raise BtdError("heights/weights must be equal shapes, multiples of 128")
    ncx, ncy = t.ncx, t.ncy
    n = ncx * ncy
    if t.quad_map.shape != (ncy * 2, ncx * 2, 8):
        raise BtdError("quad map must be [ny*2, nx*2, 8]")
    hm = t.hmin + h.astype(np.float64) / 65535.0 * (t.hmax - t.hmin)
    mm = np.zeros((ncy, ncx, 2), np.float32)
    for cy in range(ncy):
        for cx in range(ncx):
            blk = hm[cy * 128:(cy + 1) * 128, cx * 128:(cx + 1) * 128]
            mm[cy, cx] = (blk.min(), blk.max())
    out = [MAGIC, struct.pack("<IffII4iI", t.version, t.hmin, t.hmax, ncx * 128, ncy * 128, 0, 0, 0, 0, len(t.ltex)),
           struct.pack(f"<{len(t.ltex)}I", *t.ltex), mm.astype("<f4").tobytes(), t.quad_map.astype(np.uint8).tobytes(),
           h[::16, ::16].astype("<u2").tobytes(), w[::16, ::16].astype("<u2").tobytes()]
    blocks, table = [], {}
    pos = 0
    for l in (3, 2, 1, 0):
        g = 1 << l
        ents = []
        for gy in range(_group_count(ncy, l)):
            for gx in range(_group_count(ncx, l)):
                hb = np.zeros((128, 128), np.uint16)
                wb = np.zeros((128, 128), np.uint16)
                sh = h[gy * g * 128::g, gx * g * 128::g][:128, :128]
                sw = w[gy * g * 128::g, gx * g * 128::g][:128, :128]
                hb[:sh.shape[0], :sh.shape[1]] = sh
                wb[:sw.shape[0], :sw.shape[1]] = sw
                z = zlib.compress(hb.astype("<u2").tobytes() + wb.astype("<u2").tobytes(), level)
                ents.append((pos, len(z)))
                blocks.append(z)
                pos += len(z)
        table[l] = ents
    for l in (3, 2, 1, 0):
        out.append(b"".join(struct.pack("<II", o, s) for o, s in table[l]))
    out.extend(blocks)
    return b"".join(out)
