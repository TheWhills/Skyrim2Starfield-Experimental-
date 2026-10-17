"""The worldspace cell index (WRLD OFST + CLSZ) that the Creation Kit writes and Mutagen does not.

Every Starfield world whose composite LOD draws (NewAtlantis, ShatteredSpace's Dazra, LC030World) has OFST and CLSZ;
ours had neither (owner's compare_worlds.py runs). Supported hypothesis (Skyrim / Fallout 4 layout; UESP "WRLD"): one
uint32 per cell of the world's bounds (NAM0 .. NAM9, metres, 100 m cells), OFST = where that cell's CELL record
starts, relative to the WRLD record, 0 for no cell; CLSZ = that cell record's size. `verify` checks which reading
matches a vanilla world (base of the offsets, row order, size with or without the 24-byte header); `write` adds both
to our plugin with the reading verify found (it re-verifies on the vanilla world first and refuses if none matches).

    python -I scripts\\tools\\world_offsets.py verify --plugin "<Starfield>\\Data\\Starfield.esm" --world LC030World
    python -I scripts\\tools\\world_offsets.py write --plugin C:\\Modding\\staging\\skyrim_all\\SkyrimTerrainTamriel.esm ^
        --world SKY_Tamriel --sf-esm "<Starfield>\\Data\\Starfield.esm"
"""
import argparse
import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

CELL_M = 100.0
REC = struct.Struct("<4sIII")
GRP = struct.Struct("<4sI4si")


def find(buf, body, edid):
    """(top WRLD group offset, WRLD record offset, its fields, children group (start, end), {(x, y): (cell offset,
    cell record total size)})."""
    top = None
    for item in fo4land.iter_items(buf, body, len(buf)):
        if item[0] == "GRUP" and item[3] == b"WRLD":
            top = item
            break
    if top is None:
        raise KeyError("no WRLD group")
    wrec = None
    for item in fo4land.iter_items(buf, top[1] + 24, top[2]):
        if item[0] == "GRUP":
            if wrec and item[4] == 1 and struct.unpack("<I", item[3])[0] == wrec[1]:
                cells = {}

                def walk(s, e):
                    for it in fo4land.iter_items(buf, s, e):
                        if it[0] == "GRUP":
                            if it[4] in (4, 5):
                                walk(it[1] + 24, it[2])
                            continue
                        typ, off, _fl, _fid = it
                        if typ != b"CELL":
                            continue
                        for sig, d in fo4land.iter_subrecords(fo4land.record_data(buf, off)):
                            if sig == b"XCLC" and len(d) >= 8:
                                size = REC.unpack_from(buf, off)[1]
                                cells[struct.unpack_from("<ii", d)] = (off, size + 24)
                                break
                walk(item[1] + 24, item[2])
                return top[1], wrec[0], wrec[2], (item[1], item[2]), cells
            continue
        typ, off, _fl, fid = item
        if typ == b"WRLD":
            fields = list(fo4land.iter_subrecords(fo4land.record_data(buf, off)))
            if next((fo4land.zstring(d) for s, d in fields if s == b"EDID"), "") == edid:
                wrec = (off, fid, fields)
    raise KeyError(f"world {edid} not found")


def grid(fields):
    f = dict(fields)
    x0, y0 = struct.unpack("<2f", f[b"NAM0"])
    x1, y1 = struct.unpack("<2f", f[b"NAM9"])
    cx0, cy0, cx1, cy1 = (int(math.floor(v / CELL_M)) for v in (x0, y0, x1, y1))
    return cx0, cy0, cx1 - cx0 + 1, cy1 - cy0 + 1


def cell_order(gx0, gy0, nx, ny, x_fastest=True):
    if x_fastest:
        return [(gx0 + i, gy0 + j) for j in range(ny) for i in range(nx)]
    return [(gx0 + i, gy0 + j) for i in range(nx) for j in range(ny)]


BASES = {"WRLD record": lambda w, kids: w, "WRLD data": lambda w, kids: w + 24, "children group": lambda w, kids: kids,
         "file": lambda w, kids: 0}


def verify(buf, body, edid, log=print):
    """The reading (base, x_fastest, size_with_header) that explains the vanilla OFST / CLSZ, or None."""
    _top, woff, fields, kids, cells = find(buf, body, edid)
    f = dict(fields)
    if b"OFST" not in f:
        raise KeyError(f"{edid} has no OFST")
    ofst = struct.unpack(f"<{len(f[b'OFST']) // 4}I", f[b"OFST"])
    clsz = struct.unpack(f"<{len(f[b'CLSZ']) // 4}I", f[b"CLSZ"]) if b"CLSZ" in f else None
    gx0, gy0, nx, ny = grid(fields)
    log(f"{edid}: {len(cells)} cells, bounds grid {nx} x {ny} from ({gx0}, {gy0}), OFST {len(ofst)} values")
    best = None
    for name, base in BASES.items():
        for xf in (True, False):
            order = cell_order(gx0, gy0, nx, ny, xf)
            if len(order) != len(ofst):
                continue
            ok = sum(1 for xy, v in zip(order, ofst)
                     if (xy in cells and v == cells[xy][0] - base(woff, kids[0])) or (xy not in cells and v == 0))
            sz = None
            if clsz:
                for hdr in (True, False):
                    m = sum(1 for xy, v in zip(order, clsz) if (xy in cells and v == cells[xy][1] - (0 if hdr else 24))
                            or (xy not in cells and v == 0))
                    if m == len(clsz):
                        sz = hdr
            log(f"  offsets relative to {name}, {'x' if xf else 'y'} fastest: {ok}/{len(ofst)} match"
                + (f"; CLSZ = record size {'with' if sz else 'without'} header" if sz is not None else ""))
            if ok == len(ofst):
                best = (name, xf, sz if sz is not None else True)
    return best


def write(path, edid, reading, log=print):
    name, xf, with_hdr = reading
    raw = bytearray(open(path, "rb").read())
    body = 24 + REC.unpack_from(raw, 0)[1]
    top, woff, fields, kids, cells = find(raw, body, edid)
    gx0, gy0, nx, ny = grid(fields)
    order = cell_order(gx0, gy0, nx, ny, xf)
    _t, size, flags, _fid = REC.unpack_from(raw, woff)
    data = bytes(raw[woff + 24:woff + 24 + size])
    if flags & fo4land.COMPRESSED:
        data = zlib.decompress(data[4:])
        flags &= ~fo4land.COMPRESSED
    subs = [(s, bytes(d)) for s, d in fo4land.iter_subrecords(data) if s not in (b"OFST", b"CLSZ")]
    n = len(order) * 4
    if n > 0xFFFF:
        raise ValueError(f"{len(order)} cells: OFST needs an XXXX size prefix (not implemented)")

    def pack(subs_):
        return b"".join(s + struct.pack("<H", len(d)) + d for s, d in subs_)
    # placeholders first: the record grows, so the cells move; then fill in their final offsets
    at = next((i + 1 for i, (s, _d) in enumerate(subs) if s == b"HNAM"), len(subs))
    new_subs = subs[:at] + [(b"OFST", b"\0" * n), (b"CLSZ", b"\0" * n)] + subs[at:]
    new_data = pack(new_subs)
    delta = len(new_data) - size
    old_rec_end = woff + 24 + size
    raw[woff + 24:old_rec_end] = new_data
    struct.pack_into("<I", raw, woff + 4, len(new_data))
    struct.pack_into("<I", raw, woff + 8, flags)
    struct.pack_into("<I", raw, top + 4, GRP.unpack_from(raw, top)[1] + delta)
    kids0 = kids[0] + delta
    base = BASES[name](woff, kids0)
    ofst = [(cells[xy][0] + delta - base) if xy in cells else 0 for xy in order]
    clsz = [(cells[xy][1] - (0 if with_hdr else 24)) if xy in cells else 0 for xy in order]
    new_subs = subs[:at] + [(b"OFST", struct.pack(f"<{len(ofst)}I", *ofst)),
                            (b"CLSZ", struct.pack(f"<{len(clsz)}I", *clsz))] + subs[at:]
    raw[woff + 24:woff + 24 + len(new_data)] = pack(new_subs)
    with open(path, "wb") as fh:
        fh.write(raw)
    log(f"{edid}: OFST + CLSZ for {len(order)} cells ({nx} x {ny} from ({gx0}, {gy0}); {len(cells)} cells exist) "
        f"written to {path}")
    # read back: the offsets must land on the cells
    chk = bytearray(open(path, "rb").read())
    _top, woff2, fields2, kids2, cells2 = find(chk, body, edid)
    f2 = dict(fields2)
    vals = struct.unpack(f"<{len(order)}I", f2[b"OFST"])
    bad = sum(1 for xy, v in zip(order, vals) if xy in cells2 and v != cells2[xy][0] - BASES[name](woff2, kids2[0]))
    if bad:
        raise RuntimeError(f"read-back: {bad} offsets do not land on their cells")
    return len(order)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("verify", "write"))
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--world", required=True)
    ap.add_argument("--sf-esm", help="write: Starfield.esm, to verify the reading on --vanilla-world first")
    ap.add_argument("--vanilla-world", default="LC030World")
    a = ap.parse_args(argv)
    if a.cmd == "verify":
        with fo4land.Plugin(a.plugin) as p:
            r = verify(p.buf, p.body, a.world)
        print(f"reading: {r}" if r else "no reading matches every cell")
        return 0 if r else 1
    if not a.sf_esm:
        sys.exit("write needs --sf-esm (the reading is verified on a vanilla world first)")
    with fo4land.Plugin(a.sf_esm) as p:
        r = verify(p.buf, p.body, a.vanilla_world)
    if not r:
        sys.exit(f"no reading explains {a.vanilla_world}'s OFST; nothing written")
    print(f"reading verified on {a.vanilla_world}: {r}")
    write(a.plugin, a.world, r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
