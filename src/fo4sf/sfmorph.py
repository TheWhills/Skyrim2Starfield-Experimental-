"""Starfield morph.dat (body / face slider deltas per vertex of a mesh): reader and writer.

Layout (supported: decoded 2026-11-02 from a vanilla female body morph.dat and IDG hair morphs, see
docs/ai/decisions.md; checked by scripts/armor/morph_probe.py against the game's files):
  'MDAT', u32 version (3), u32 vertex count, u32 key count, key names (u32 length + bytes),
  u32 record count, u32 entry count (= vertex count),
  records, 16 bytes each: 3 x half-float delta (metres), u16 colour, u32 packed normal delta, u32 packed tangent delta,
  entries, 20 bytes per vertex: u32 index of its first record, 128-bit key mask (bit k: key k has a record; the
  vertex's records follow in key order).
"""
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


class MorphError(ValueError):
    pass


@dataclass
class Morph:
    version: int
    num_vertices: int
    keys: List[str]
    # per key: {vertex: (dx, dy, dz)} plus the raw colour / normal / tangent words
    deltas: Dict[str, Dict[int, Tuple[float, float, float]]] = field(default_factory=dict)
    extra: Dict[str, Dict[int, Tuple[int, int, int]]] = field(default_factory=dict)
    layout: Dict = field(default_factory=dict)


def parse(data: bytes) -> Morph:
    if data[:4] != b"MDAT":
        raise MorphError(f"not a morph.dat (magic {data[:4]!r})")
    ver, nv, nk = struct.unpack_from("<III", data, 4)
    p, keys = 16, []
    for _ in range(nk):
        ln, = struct.unpack_from("<I", data, p)
        keys.append(data[p + 4:p + 4 + ln].decode("latin-1"))
        p += 4 + ln
    nrec, nent = struct.unpack_from("<II", data, p)
    p += 8
    need = p + 16 * nrec + 20 * nent
    if need != len(data):
        raise MorphError(f"size {len(data)} != {need} for {nrec} records and {nent} entries")
    rec_at, ent_at = p, p + 16 * nrec
    m = Morph(ver, nv, keys, {k: {} for k in keys}, {k: {} for k in keys},
              {"records": nrec, "entries": nent, "records_at": rec_at, "entries_at": ent_at})
    order_ok = True
    nxt = 0
    empty_zero = empty_running = 0
    for v in range(nent):
        first, = struct.unpack_from("<I", data, ent_at + 20 * v)
        mask = int.from_bytes(data[ent_at + 20 * v + 4:ent_at + 20 * v + 20], "little")
        bits = [k for k in range(min(nk, 128)) if mask >> k & 1]
        if bits and first != nxt:
            order_ok = False
        for j, k in enumerate(bits):
            r = rec_at + 16 * (first + j)
            dx, dy, dz = np.frombuffer(data[r:r + 6], "<f2").astype(float)
            col, nrm, tan = struct.unpack_from("<HII", data, r + 6)
            m.deltas[keys[k]][v] = (float(dx), float(dy), float(dz))
            m.extra[keys[k]][v] = (col, nrm, tan)
        if bits:
            nxt = first + len(bits)
        elif first == 0:
            empty_zero += 1
        elif first == nxt:
            empty_running += 1
    m.layout["records_in_vertex_order"] = order_ok
    m.layout["records_used"] = nxt
    m.layout["empty_entries_first_0"] = empty_zero
    m.layout["empty_entries_first_running"] = empty_running
    return m


def build(num_vertices: int, keys: List[str], deltas: Dict[str, Dict[int, Tuple[float, float, float]]],
          extra: Optional[Dict[str, Dict[int, Tuple[int, int, int]]]] = None, version: int = 3) -> bytes:
    """A morph.dat: per vertex, a record for each key it moves under (normal / tangent words 0 unless given)."""
    if len(keys) > 128:
        raise MorphError("at most 128 keys")
    head = b"MDAT" + struct.pack("<III", version, num_vertices, len(keys))
    head += b"".join(struct.pack("<I", len(k)) + k.encode("latin-1") for k in keys)
    recs, ents, n = [], [], 0
    for v in range(num_vertices):
        mask, first = 0, n
        for k, key in enumerate(keys):
            d = deltas.get(key, {}).get(v)
            if d is None:
                continue
            mask |= 1 << k
            col, nrm, tan = (extra or {}).get(key, {}).get(v, (0, 0, 0))
            recs.append(np.asarray(d, "<f2").tobytes() + struct.pack("<HII", col, nrm, tan))
            n += 1
        # an entry without records still carries the running record index (2026-11-06: with 0 there, thin pillars
        # shot out of the coat in game; a reader taking a vertex's record count from the next entry's index would
        # read far past the vertex's own records)
        ents.append(struct.pack("<I", first) + mask.to_bytes(16, "little"))
    return head + struct.pack("<II", n, num_vertices) + b"".join(recs) + b"".join(ents)


def summary(m: Morph) -> Dict:
    out = {"version": m.version, "vertices": m.num_vertices, "keys": m.keys, "layout": m.layout, "per_key": {}}
    for k in m.keys:
        d = np.array(list(m.deltas[k].values()), float).reshape(-1, 3)
        out["per_key"][k] = {"vertices": int(len(d)),
                             "max_m": float(np.abs(d).max()) if len(d) else 0.0,
                             "median_m": float(np.median(np.linalg.norm(d, axis=1))) if len(d) else 0.0}
    return out
