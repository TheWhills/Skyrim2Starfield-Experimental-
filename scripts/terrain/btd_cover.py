"""Re-encode the staged terrain so ground cover sees the textures the renderer draws (test, 2026-11-23).

Owner's ground_at runs at Riverwood with ground cover on one slot (LFieldGrass02) only: grass grew where the reading
"index tail (table[n - b]), alpha bits 3(4-i)" gives LFieldGrass02 and the renderer's reading (table[b - 1], alpha
bits 3i, verified 2026-10) gives LRiverBottom01NoGrass; the flat where the renderer draws LFieldGrass02 at alpha 7/7
stays bare, and there the tail reading gives LRocks01NoRocks (supported hypothesis, 2 of 2 spots). Paired the other
way round, ground cover takes the texture of byte 4 - i with the alpha of slot i, indexing the LTEX table from its end;
byte 6 (the biome mask) is read head-first (switching its entry switched the mask).

set     : rewrites bytes 0..4 and the LTEX table of each staged BTD so that, per quadrant, byte j's head entry is the
          texture drawn now (rendering unchanged) and its tail entry is the texture drawn at slot 4 - j (what ground
          cover pairs with that alpha). Every used (head, tail) pair gets one byte value c (1..k); the table becomes
          2k entries: heads at 0..k-1, tails at 2k-c. Byte 6 keeps its LDefault texture and becomes 2k, the table's
          length (2026-11-23: with a small byte 6 no grass grew at all; supported hypothesis: ground cover reads
          table[byte6 - b], which equalled table[n - b] when byte 6 was the last entry). Heights and alphas
          untouched; the result is checked by reading it back both ways. Originals go to <staging>\\btd_before_cover.
pad     : (diagnostic, 2026-11-24) no duplicates: inserts --count unique vanilla LTEX (Starfield.esm, not in the table)
          before the table's last entry (byte 6's LDefault) and sets byte 6 to the new length; bytes 0..4 keep their
          values, so a front reading (table[b - 1]) is unchanged and every end reading (table[n - b]) moves by count.
          The encoded table (set) made the renderer draw end-reading textures on a hill (owner): this tells whether
          duplicate entries or the end reading itself caused it.
restore : copies the originals back.
Reinstall afterwards (tools\\owner\\terrain_cover.ps1 does both). Do not run btd_byte6.py on the encoded files.

    python -I scripts\\terrain\\btd_cover.py set --staging C:\\Modding\\staging\\skyrim_all
"""
import argparse
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import btd  # noqa: E402

BACKUP = "btd_before_cover"
MAX_CODES = 255                # byte values; with byte 6 = 2k, k <= 127


def head(table, b):
    return table[b - 1] if 1 <= b <= len(table) else None


def tail(table, b):
    return table[len(table) - b] if 1 <= b <= len(table) else None


def cover_encode(t: btd.Btd, covered=None, none_fid=None):
    """(new Btd, stats). Raises ValueError when more than 255 (head, tail) pairs are needed. covered: LTEX that have
    ground cover; when given, every other tail becomes none_fid (ground cover only tells covered textures apart),
    which needs fewer pairs."""
    T = list(t.ltex)
    q = t.quad_map
    ny, nx = q.shape[:2]
    b6s = {head(T, int(v)) for v in np.unique(q[:, :, 6]) if v}
    if len(b6s) > 1:
        raise ValueError(f"byte 6 names {len(b6s)} different textures; one is needed (it becomes the table's length)")
    codes = {}
    if b6s:                                   # code 1: byte 6's texture; its tail entry is the table's last
        h6 = next(iter(b6s))
        codes[(h6, h6)] = 1
    out = q.copy()
    lost = 0
    for y in range(ny):
        for x in range(nx):
            b = [int(v) for v in q[y, x, :5]]
            heads = [head(T, v) for v in b]
            if not any(h is not None for h in heads):
                continue
            for j in range(5):
                if heads[j] is None:
                    if heads[4 - j] is not None:
                        lost += 1                 # ground cover pairs an empty byte with a used alpha slot
                    continue
                tl = heads[4 - j] if heads[4 - j] is not None else heads[j]
                if covered is not None and tl not in covered:
                    tl = none_fid
                pair = (heads[j], tl)
                c = codes.setdefault(pair, len(codes) + 1)
                out[y, x, j] = c if c <= MAX_CODES else 0
    k = len(codes)
    if 2 * k > MAX_CODES:
        raise ValueError(f"{k} (head, tail) pairs needed; byte 6 = the table's length ({2 * k}) must fit a byte "
                         f"({MAX_CODES})")
    # byte 6 = 2k = the table's length: head entry 2k - 1 (code 1's tail) is its texture, and a reading that counts
    # back from byte 6 (table[b6 - b]) gives the same entries as one that counts from the end (table[n - b])
    out[:, :, 6] = np.where(q[:, :, 6] > 0, 2 * k, 0).astype(np.uint8)
    table = [0] * (2 * k)
    for (h, tl), c in codes.items():
        table[c - 1] = h
        table[2 * k - c] = tl
    new = btd.Btd(t.version, t.hmin, t.hmax, table, t.heights_raw, t.weights, out)
    return new, {"pairs": k, "table": 2 * k, "lost": lost}


def pad_table(t: btd.Btd, extra):
    """t with the LTEX entries in extra inserted before its last entry (which byte 6 names) and byte 6 = the new
    length; bytes 0..4 untouched. Raises ValueError if byte 6 does not name the last entry or extra repeats one."""
    T = list(t.ltex)
    b6 = {int(v) for v in np.unique(t.quad_map[:, :, 6]) if v}
    if b6 != {len(T)}:
        raise ValueError(f"byte 6 must name the table's last entry ({len(T)}), it holds {sorted(b6)}")
    if set(extra) & set(T) or len(set(extra)) != len(extra):
        raise ValueError("the padding repeats a table entry")
    used = int(t.quad_map[:, :, :5].max())
    if used >= len(T):
        raise ValueError("bytes 0..4 name the last entry")
    table = T[:-1] + list(extra) + T[-1:]
    q = t.quad_map.copy()
    q[:, :, 6] = np.where(q[:, :, 6] > 0, len(table), 0).astype(np.uint8)
    if len(table) > MAX_CODES:
        raise ValueError("table would pass 255 entries")
    return btd.Btd(t.version, t.hmin, t.hmax, table, t.heights_raw, t.weights, q)


def check(old: btd.Btd, new: btd.Btd, covered=None):
    """Rendering unchanged (head reading of bytes 0..4 and 6) and ground cover's reading of byte j = what the renderer
    draws at slot 4 - j; returns the number of quadrant slots that disagree."""
    bad = 0
    T, N = list(old.ltex), list(new.ltex)
    for y in range(old.quad_map.shape[0]):
        for x in range(old.quad_map.shape[1]):
            ob, nb = old.quad_map[y, x], new.quad_map[y, x]
            for j in (0, 1, 2, 3, 4, 6):
                if head(T, int(ob[j])) != head(N, int(nb[j])):
                    bad += 1
            for j in range(5):
                want = head(T, int(ob[4 - j]))
                if covered is not None and want not in covered:
                    continue
                if want is not None and head(T, int(ob[j])) is not None and tail(N, int(nb[j])) != want:
                    bad += 1
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("set", "pad", "restore"))
    ap.add_argument("--count", type=int, default=40, help="pad: unique vanilla LTEX to insert")
    ap.add_argument("--sf-esm", default="", help="pad: Starfield.esm")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--grass", default="", help="the native-grass mod folder: when more than 255 codes are needed, "
                                                "only its covered slots (grass_native.json) are told apart")
    a = ap.parse_args(argv)
    import btd_byte6
    backup = os.path.join(a.staging, BACKUP)
    paths = btd_byte6.staged_btds(a.staging)
    if not paths:
        sys.exit("no staged BTD found (overlays_params.json btd_file)")
    if a.cmd == "restore":
        n = 0
        for p in paths:
            keep = os.path.join(backup, os.path.relpath(p, a.staging))
            if os.path.exists(keep):
                shutil.copy2(keep, p)
                n += 1
        if os.path.isdir(backup):
            shutil.rmtree(backup)
        print(f"{n} terrain file(s) put back")
        return 0
    for p in paths:
        keep = os.path.join(backup, os.path.relpath(p, a.staging))
        if not os.path.exists(keep):
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            shutil.copy2(p, keep)
        with open(keep, "rb") as fh:                    # always from the original: set twice = set once
            t = btd.read(fh.read())
        if a.cmd == "pad":
            if not a.sf_esm:
                sys.exit("pad needs --sf-esm")
            from fo4sf import sfplugin
            pool = sorted(fid for _t, _h, _s, fid in sfplugin.records(a.sf_esm, [b"LTEX"]) if fid not in set(t.ltex))
            try:
                new = pad_table(t, pool[:a.count])
            except ValueError as e:
                sys.exit(f"{os.path.relpath(p, a.staging)}: {e}")
            data = btd.write(new)
            back = btd.read(data)
            ok = all(head(t.ltex, int(o)) == head(back.ltex, int(n)) for o, n in
                     zip(t.quad_map[:, :, :5].ravel(), back.quad_map[:, :, :5].ravel()) if o)
            if not ok or not np.array_equal(back.weights, t.weights):
                sys.exit(f"{os.path.relpath(p, a.staging)}: check failed; file left as it was")
            with open(p, "wb") as fh:
                fh.write(data)
            print(f"{os.path.relpath(p, a.staging)}: {a.count} unique vanilla LTEX inserted, table {len(t.ltex)} -> "
                  f"{len(new.ltex)} (no duplicates), byte 6 = {len(new.ltex)}; front readings unchanged (checked)")
            continue
        covered = None
        try:
            new, st = cover_encode(t)
        except ValueError as e:
            if not a.grass:
                sys.exit(f"{os.path.relpath(p, a.staging)}: {e}; give --grass to tell only covered slots apart")
            import json
            with open(os.path.join(a.grass, "grass_native.json"), encoding="utf-8") as fh:
                covered = {int(k, 16) for k in json.load(fh).get("slots", {})}
            used = [f for f in t.ltex if f not in covered]
            none_fid = used[0] if used else 0
            try:
                new, st = cover_encode(t, covered, none_fid)
            except ValueError as e2:
                sys.exit(f"{os.path.relpath(p, a.staging)}: {e2} even with only the {len(covered)} covered slots")
            print(f"  {e}: only the {len(covered)} covered slots told apart for ground cover")
        data = btd.write(new)
        back = btd.read(data)
        bad = check(t, back, covered)
        if bad or not (np.array_equal(back.heights_raw, t.heights_raw) and np.array_equal(back.weights, t.weights)):
            sys.exit(f"{os.path.relpath(p, a.staging)}: check failed ({bad} slots disagree); file left as it was")
        with open(p, "wb") as fh:
            fh.write(data)
        print(f"{os.path.relpath(p, a.staging)}: {st['pairs']} (head, tail) codes, LTEX table {len(t.ltex)} -> "
              f"{st['table']} entries; {st['lost']} quadrant slot(s) where ground cover meets an empty byte; "
              f"rendering, heights and alphas unchanged (checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
