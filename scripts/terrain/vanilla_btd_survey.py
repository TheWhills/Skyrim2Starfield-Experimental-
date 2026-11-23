"""How Starfield's OWN terrain (.btd) lays out its ground-texture bytes (2026-11-22). Read-only.

    python -I scripts\\terrain\\vanilla_btd_survey.py --sf-data "$sf\\Data"

Why: our converted ground showed wrong textures in strips along 50 m quadrant edges, which fits the engine blending
neighbouring quadrants' texture bytes there (supported hypothesis, docs/terrain/skyrim-tamriel.md). Bethesda's files
are made for the engine's real rule, so this reads a sample of vanilla BTDs from the terrain archives and reports:

  1. quad maps: how many of the eight bytes a quadrant uses, whether bytes 5..7 are ever used, whether the base is
     the last used byte; for neighbouring quadrants (inside one 100 m cell and across cells, sides and corners) how
     often a byte position holds the same texture, and for textures both hold, how often at the same position;
     whether each texture keeps one position across the file
  2. sample words (a few cells per file): the 3-bit alphas used (on / off only, or partial values)
  3. edges: by distance to a quadrant edge, how often a sample draws a byte position whose texture DIFFERS from the
     neighbour's there, against positions that are the SAME. If vanilla avoids differing positions near edges, the
     first column drops close to the edge: that is the edge rule and its width.

Only headers, quad maps and the sampled cells are decompressed (planet files are large).

2026-11-22 (native grass grew nothing on our world, even Starfield's own cover after a ship landing): ground cover is
chosen per biome MASK (Base, Solid, FlatOuter, FlatInner, Talus, Flow, Path), and our BTD carries no mask anywhere we
know of. Two unexplained places could: quadrant bytes 5..7 (filled in 96.6 % of vanilla quadrants, written 0 by us)
and bit 15 of each sample's 16-bit texture word (above the five 3-bit alphas). The survey now reports both: bytes
5..7 value histograms, whether they name a valid table entry or repeat one of bytes 0..4, and how often bit 15 is set.
--match REGEX reads only matching files (e.g. overlaytrait: planet overlays painted with biome-covered textures).
"""
import argparse
import json
import os
import random
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

import numpy as np  # noqa: E402

from fo4sf import ba2  # noqa: E402

TERRAIN_ARCHIVES = ("Starfield - Terrain01.ba2", "Starfield - Terrain02.ba2", "Starfield - Terrain03.ba2",
                    "Starfield - Terrain04.ba2", "Starfield - TerrainPatch.ba2")
MAX_D = 32


def ltex_count(ar, e):
    """The LTEX table length of an archived BTD, read from its header only (vanilla terrain BTDs are stored)."""
    if e.packed == 0:
        with open(ar.path, "rb") as fh:
            fh.seek(e.offset)
            head = fh.read(44)
        return struct.unpack_from("<I", head, 40)[0] if head[:4] == b"BTDB" else -1
    head = ar.read(ar.entries.index(e))[:44]
    return struct.unpack_from("<I", head, 40)[0] if head[:4] == b"BTDB" else -1


def parse(b: bytes):
    """(ltex table, quad map [2ny, 2nx, 8], (ncy, ncx), read_cell(cy, cx) -> weights [128, 128] uint16)."""
    if b[:4] != b"BTDB":
        raise ValueError("not a BTD")
    ver, hmin, hmax, rx, ry, x0, y0, x1, y1, nlt = struct.unpack_from("<IffIIiiiiI", b, 4)
    ncx, ncy = rx // 128, ry // 128
    n = ncx * ncy
    p = 44
    ltex = list(struct.unpack_from(f"<{nlt}I", b, p))
    p += 4 * nlt + 8 * n
    quad = np.frombuffer(b, np.uint8, 32 * n, p).reshape(ncy * 2, ncx * 2, 8)
    p += 32 * n + 256 * n
    offs = {}
    for lvl in (3, 2, 1, 0):
        cnt = (((ncy + (1 << lvl) - 1) >> lvl) * ((ncx + (1 << lvl) - 1) >> lvl))
        offs[lvl] = (p, cnt)
        p += 8 * cnt
    data_off = p
    off0, _cnt0 = offs[0]

    def read_cell(cy, cx):
        o, sz = struct.unpack_from("<II", b, off0 + 8 * (cy * ncx + cx))
        raw = zlib.decompress(b[data_off + o:data_off + o + sz])
        return np.frombuffer(raw, "<u2", 16384, 32768).reshape(128, 128)
    return ltex, quad, (ncy, ncx), read_cell


class Survey:
    def __init__(self):
        self.c = Counter()
        self.pos_of = defaultdict(Counter)             # (file, byte value) -> Counter(position)
        self.alpha = np.zeros((5, 8), np.int64)
        self.edge = {k: np.zeros((MAX_D, 2), np.int64) for k in ("diff", "same")}   # [d] (active, total)

    def quads(self, name, quad, nlt=0):
        ny, nx, _ = quad.shape
        used = (quad > 0)
        for p in (5, 6, 7):                                  # 2026-11-22: what bytes 5..7 hold
            v = quad[:, :, p]
            vals, cnt = np.unique(v, return_counts=True)
            for x, k in zip(vals.tolist(), cnt.tolist()):
                self.c[f"b{p}_value_{x}"] += k
            nz = v > 0
            self.c[f"b{p}_nonzero"] += int(nz.sum())
            if nlt:
                self.c[f"b{p}_valid_entry"] += int((nz & (v <= nlt)).sum())
            self.c[f"b{p}_repeats_0_4"] += int((nz & np.any(quad[:, :, :5] == v[:, :, None], axis=2)).sum())
        self.c["quadrants"] += ny * nx
        self.c["uses_bytes_5_7"] += int(used[:, :, 5:].any(axis=2).sum())
        nused = used[:, :, :5].sum(axis=2)
        for k in range(6):
            self.c[f"quadrants_using_{k}"] += int((nused == k).sum())
        contiguous = np.all(used[:, :, :5] == (np.arange(5)[None, None, :] < nused[:, :, None]), axis=2)
        self.c["used_bytes_contiguous_from_0"] += int(contiguous.sum())
        for (dr, dc, kind) in ((0, 1, "side_ew"), (1, 0, "side_ns"), (1, 1, "corner"), (1, -1, "corner")):
            r0, r1 = max(0, -dr), ny - max(0, dr)
            c0, c1 = max(0, -dc), nx - max(0, dc)
            if r1 <= r0 or c1 <= c0:
                continue
            ra, ca = np.mgrid[r0:r1, c0:c1]
            a = quad[ra, ca, :5]
            b = quad[ra + dr, ca + dc, :5]
            same_cell = ((ra // 2) == ((ra + dr) // 2)) & ((ca // 2) == ((ca + dc) // 2))
            for scope, m in (("in_cell", same_cell), ("across_cells", ~same_cell)):
                if not m.any():
                    continue
                aa, bb = a[m], b[m]
                both = (aa > 0) & (bb > 0)
                key = f"{kind}_{scope}"
                self.c[f"{key}_pairs"] += len(aa)
                self.c[f"{key}_positions_both_used"] += int(both.sum())
                self.c[f"{key}_positions_equal"] += int((both & (aa == bb)).sum())
                self.c[f"{key}_identical_maps"] += int(np.all(aa == bb, axis=1).sum())
                # textures both quadrants hold: at the same position?
                for i in range(0, len(aa), max(1, len(aa) // 4000)):
                    sa, sb = aa[i], bb[i]
                    shared = set(int(x) for x in sa if x) & set(int(x) for x in sb if x)
                    for t in shared:
                        self.c[f"{key}_shared_textures"] += 1
                        self.c[f"{key}_shared_same_position"] += int(list(sa).index(t) == list(sb).index(t))
        for p in range(5):
            vals, cnt = np.unique(quad[:, :, p][quad[:, :, p] > 0], return_counts=True)
            for v, k in zip(vals.tolist(), cnt.tolist()):
                self.pos_of[(name, v)][p] += k

    def cell(self, quad, cy, cx, w):
        ny, nx, _ = quad.shape
        alphas = np.stack([(w.astype(np.int64) >> (3 * i)) & 7 for i in range(5)])    # [5, 128, 128]
        self.c["words"] += int(w.size)
        self.c["words_bit15"] += int(((w.astype(np.int64) >> 15) & 1).sum())
        for i in range(5):
            self.alpha[i] += np.bincount(alphas[i].ravel(), minlength=8)[:8]
        rr, cc = np.mgrid[0:64, 0:64]
        dist = {"w": cc, "e": 63 - cc, "s": rr, "n": 63 - rr}
        step = {"w": (0, -1), "e": (0, 1), "s": (-1, 0), "n": (1, 0)}   # quad map row 0 = south (as the samples)
        for sq in range(2):
            for sc in range(2):
                qr, qc = cy * 2 + sq, cx * 2 + sc
                q = quad[qr, qc, :5]
                used = [p for p in range(5) if q[p]]
                if not used:
                    continue
                base = used[-1]
                a = alphas[:, sq * 64:(sq + 1) * 64, sc * 64:(sc + 1) * 64]
                over = [p for p in used if p != base]
                top = np.full((64, 64), base)
                for p in reversed(over):                     # byte 0 on top: the first on (alpha >= 4) shows
                    top = np.where(a[p] >= 4, p, top)
                for s, (dr, dc) in step.items():
                    rr2, cc2 = qr + dr, qc + dc
                    if not (0 <= rr2 < ny and 0 <= cc2 < nx):
                        continue
                    nb = quad[rr2, cc2, :5]
                    d = dist[s].ravel()
                    tot = np.bincount(d, minlength=64)[:MAX_D]
                    for p in used:
                        kind = "same" if nb[p] == q[p] else "diff"
                        act = np.bincount(d, weights=(top == p).ravel().astype(np.float64), minlength=64)[:MAX_D]
                        self.edge[kind][:, 0] += act.astype(np.int64)
                        self.edge[kind][:, 1] += tot

    def report(self):
        c = self.c
        out = []
        q = max(c["quadrants"], 1)
        out.append(f"quadrants read: {c['quadrants']:,}")
        out.append("  bytes used per quadrant (of 0..4): " + ", ".join(
            f"{k}: {c[f'quadrants_using_{k}'] / q:.1%}" for k in range(6)))
        out.append(f"  quadrants using any of bytes 5..7: {c['uses_bytes_5_7'] / q:.2%}")
        out.append(f"  used bytes contiguous from byte 0: {c['used_bytes_contiguous_from_0'] / q:.1%}")
        for key in sorted({k.rsplit('_pairs', 1)[0] for k in c if k.endswith('_pairs')}):
            pr = max(c[f"{key}_pairs"], 1)
            out.append(f"  {key:22} pairs {c[f'{key}_pairs']:>9,}: identical maps {c[f'{key}_identical_maps'] / pr:6.1%}, "
                       f"positions equal where both used {c[f'{key}_positions_equal'] / max(c[f'{key}_positions_both_used'], 1):6.1%}, "
                       f"shared textures at the same position {c[f'{key}_shared_same_position'] / max(c[f'{key}_shared_textures'], 1):6.1%}")
        cons = [max(v.values()) / sum(v.values()) for v in self.pos_of.values() if sum(v.values()) >= 20]
        if cons:
            out.append(f"  each texture's most common position holds it in {np.mean(cons):.1%} of its quadrants "
                       f"(mean over {len(cons)} textures; 100 % = one position per texture)")
        for p in (5, 6, 7):
            nz = c[f"b{p}_nonzero"]
            top = sorted(((k, v) for k, v in c.items() if k.startswith(f"b{p}_value_")), key=lambda kv: -kv[1])[:12]
            out.append(f"  byte {p}: non-zero in {nz / q:.1%} of quadrants; of those a valid table entry "
                       f"{c[f'b{p}_valid_entry'] / max(nz, 1):.1%}, repeating one of bytes 0..4 "
                       f"{c[f'b{p}_repeats_0_4'] / max(nz, 1):.1%}; most common values "
                       + ", ".join(f"{k.rsplit('_', 1)[1]} ({v / q:.1%})" for k, v in top))
        if c["words"]:
            out.append(f"  sample words with bit 15 set: {c['words_bit15'] / c['words']:.2%} of {c['words']:,}")
        tot = self.alpha.sum(axis=1, keepdims=True)
        if tot.sum():
            out.append("alphas (share of samples per value 0..7), byte 0..4:")
            for i in range(5):
                out.append(f"  byte {i}: " + " ".join(f"{v / max(tot[i, 0], 1):5.1%}" for v in self.alpha[i]))
        d, s = self.edge["diff"], self.edge["same"]
        if s[:, 1].sum():
            out.append("edges: share of samples drawing a byte position, by distance (samples) to the quadrant edge:")
            out.append("  dist   position DIFFERS from neighbour   position SAME as neighbour")
            for dd in range(MAX_D):
                out.append(f"  {dd:4d}   {d[dd, 0] / max(d[dd, 1], 1):8.2%} of {d[dd, 1]:>10,}          "
                           f"{s[dd, 0] / max(s[dd, 1], 1):8.2%} of {s[dd, 1]:>10,}")
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True, help="Starfield's Data folder")
    ap.add_argument("--max-btds", type=int, default=12, help="vanilla BTDs to read (the largest with an LTEX table)")
    ap.add_argument("--cells", type=int, default=120, help="100 m cells per BTD whose samples are decompressed")
    ap.add_argument("--max-mb", type=float, default=400.0, help="skip BTDs larger than this (MB)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--all", action="store_true", help="also the procedural source tiles (no LTEX table)")
    ap.add_argument("--json", default="", help="also write the counts here")
    ap.add_argument("--match", default="", help="only BTDs whose path matches this regular expression (e.g. "
                                                 "overlaytrait)")
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    files, no_table = [], 0
    for arc in TERRAIN_ARCHIVES:
        p = os.path.join(a.sf_data, arc)
        if not os.path.exists(p):
            continue
        ar = ba2.Ba2(p)
        for i, e in enumerate(ar.entries):
            if not (e.name.lower().endswith(".btd") and e.kind == "GNRL" and e.unpacked <= a.max_mb * 1e6):
                continue
            if a.match and not re.search(a.match, e.name, re.I):
                continue
            nlt = ltex_count(ar, e)
            if nlt == 0 and not a.all:
                no_table += 1                                # procedural source tiles: no LTEX table, other rules
                continue
            files.append((ar, i, e.name, e.unpacked, nlt))
    if not files:
        sys.exit(f"no vanilla .btd with an LTEX table in the terrain archives of {a.sf_data}")
    files.sort(key=lambda f: -f[3])                          # the largest hand-made worlds first
    pick = files[:a.max_btds]
    print(f"{len(files)} vanilla BTDs with an LTEX table ({no_table} procedural tiles without one skipped); "
          f"reading the {len(pick)} largest")
    sv = Survey()
    for ar, i, name, size, _nlt in pick:
        before = {k: v.copy() for k, v in sv.edge.items()}
        try:
            ltex, quad, (ncy, ncx), read_cell = parse(ar.read(i))
        except Exception as e:                               # noqa: BLE001 - report and go on
            print(f"  {name}: not read ({e})")
            continue
        sv.quads(name, quad, len(ltex))
        cells = [(cy, cx) for cy in range(ncy) for cx in range(ncx)]
        rng.shuffle(cells)
        done = 0
        for cy, cx in cells:
            if done >= a.cells:
                break
            sub = quad[cy * 2:cy * 2 + 2, cx * 2:cx * 2 + 2, :5]
            if (sub > 0).sum(axis=2).max() < 2:              # one texture only: nothing to learn about edges
                continue
            sv.cell(quad, cy, cx, read_cell(cy, cx))
            done += 1
        dd = sv.edge["diff"] - before["diff"]
        ds = sv.edge["same"] - before["same"]
        near = lambda e: e[:4, 0].sum() / max(e[:4, 1].sum(), 1)                     # noqa: E731
        far = lambda e: e[16:, 0].sum() / max(e[16:, 1].sum(), 1)                    # noqa: E731
        print(f"  {name}: {ncx} x {ncy} cells, LTEX table {len(ltex)}, {done} cells sampled ({size / 1e6:.0f} MB); "
              f"differing positions drawn near / far from edges {near(dd):.1%} / {far(dd):.1%} "
              f"(same: {near(ds):.1%} / {far(ds):.1%})")
    for line in sv.report():
        print(line)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"counts": dict(sv.c), "alpha": sv.alpha.tolist(),
                       "edge": {k: v.tolist() for k, v in sv.edge.items()}}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
