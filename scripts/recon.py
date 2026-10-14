"""Read-only recon of Fallout 4 (Creation Engine 1) and Starfield (Creation Engine 2) data.

Walks plugin record trees, BA2 name tables and a few sample NIF headers so the format gap
between the two engines is measured from the user's own files instead of guessed.
Never writes inside the game folders; output goes to --out.

usage: python -I recon.py --fo4-data <dir> [--fo4-data <dir> ...] --sf-data <dir> --out <dir>
"""
import argparse
import json
import mmap
import os
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict

# Record types whose subrecord layout we sample to compare schemas between the two games.
SAMPLE_TYPES = {
    "WEAP", "ARMO", "AMMO", "NPC_", "RACE", "CELL", "WRLD", "LAND", "REFR", "ACHR", "NAVM",
    "QUST", "DIAL", "INFO", "STAT", "SCOL", "LIGH", "MATT", "TXST", "SNDR", "LVLI", "LVLN",
    "PERK", "SPEL", "MGEF", "OMOD", "COBJ", "FURN", "CONT", "DOOR", "TERM", "BOOK", "ALCH",
    "MISC", "FACT", "PACK", "IDLE", "LCTN", "REGN", "WTHR", "IMGS", "EXPL", "PROJ", "HAZD",
}
SAMPLES_PER_TYPE = 300
COMPRESSED = 0x00040000


def iter_subrecords(data):
    p, big = 0, None
    n = len(data)
    while p + 6 <= n:
        sig = data[p:p + 4]
        size = struct.unpack_from("<H", data, p + 4)[0]
        p += 6
        if big is not None:
            size, big = big, None
        if sig == b"XXXX":
            big = struct.unpack_from("<I", data, p)[0]
            p += size
            continue
        yield sig.decode("ascii", "replace"), data[p:p + size]
        p += size


def scan_plugin(path):
    out = {"path": path, "size": os.path.getsize(path)}
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        size = len(m)
        typ, dsize, flags, _fid, _vc, ver, _ = struct.unpack_from("<4sIIIIHH", m, 0)
        if typ != b"TES4":
            raise ValueError(f"{path}: not a plugin (got {typ!r})")
        out["header_form_version"] = ver
        out["header_flags"] = hex(flags)
        masters = []
        for sig, data in iter_subrecords(m[24:24 + dsize]):
            if sig == "HEDR":
                hv, nrec, nextid = struct.unpack_from("<fII", data, 0)
                out["hedr_version"] = round(hv, 4)
                out["hedr_num_records"] = nrec
            elif sig == "MAST":
                masters.append(data.rstrip(b"\0").decode("utf-8", "replace"))
        out["masters"] = masters

        counts = Counter()
        versions = Counter()
        top_groups = []
        subsigs = defaultdict(Counter)
        sampled = Counter()
        decomp_fail = Counter()
        off = 24 + dsize
        while off + 24 <= size:
            typ = m[off:off + 4]
            if typ == b"GRUP":
                gsize, label, gtype = struct.unpack_from("<I4si", m, off + 4)
                if gtype == 0:
                    top_groups.append(label.decode("ascii", "replace"))
                off += 24
                continue
            dsize, flags = struct.unpack_from("<II", m, off + 4)
            ver = struct.unpack_from("<H", m, off + 20)[0]
            t = typ.decode("ascii", "replace")
            counts[t] += 1
            versions[ver] += 1
            if t in SAMPLE_TYPES and sampled[t] < SAMPLES_PER_TYPE:
                data = m[off + 24:off + 24 + dsize]
                ok = True
                if flags & COMPRESSED:
                    try:
                        data = zlib.decompress(data[4:])
                    except zlib.error:
                        decomp_fail[t] += 1
                        ok = False
                if ok:
                    for sig, _ in iter_subrecords(data):
                        subsigs[t][sig] += 1
                    sampled[t] += 1
            off += 24 + dsize
    out["record_counts"] = dict(counts.most_common())
    out["total_records"] = sum(counts.values())
    out["record_form_versions"] = dict(versions.most_common(10))
    out["top_groups"] = top_groups
    out["subrecord_sigs"] = {t: dict(c.most_common()) for t, c in subsigs.items()}
    out["sampled"] = dict(sampled)
    if decomp_fail:
        out["decompress_failures"] = dict(decomp_fail)
    return out


def read_ba2(path):
    with open(path, "rb") as f:
        magic, version, atype, count, nameoff = struct.unpack("<4sI4sIQ", f.read(24))
        if magic != b"BTDX":
            raise ValueError(f"{path}: not a BA2")
        extra = {1: 0, 7: 0, 8: 0, 2: 8, 3: 12}.get(version, 0)
        comp = None
        if version == 3:
            comp = struct.unpack("<III", f.read(12))[2]
        f.seek(nameoff)
        table = f.read()
    names, p = [], 0
    for _ in range(count):
        n = struct.unpack_from("<H", table, p)[0]
        p += 2
        names.append(table[p:p + n].decode("utf-8", "replace"))
        p += n
    return {
        "path": path, "version": version, "type": atype.decode(), "file_count": count,
        "compression_method": comp, "entries_offset": 24 + extra, "names": names,
    }


def extract_gnrl(ba2, index):
    """Return the unpacked bytes of GNRL entry `index`, or None if the codec isn't zlib."""
    if ba2["type"] != "GNRL":
        return None
    with open(ba2["path"], "rb") as f:
        f.seek(ba2["entries_offset"] + 36 * index)
        _h, _ext, _d, _fl, off, packed, unpacked, _al = struct.unpack("<I4sIIQIII", f.read(36))
        f.seek(off)
        raw = f.read(packed or unpacked)
    if not packed:
        return raw
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return None


BLOCK_RE = re.compile(rb"(?:BS|Ni|bhk|hk)[A-Za-z0-9_]{3,40}")


def parse_nif_header(b):
    info = {}
    nl = b.index(b"\n")
    info["header"] = b[:nl].decode("ascii", "replace")
    p = nl + 1
    ver, = struct.unpack_from("<I", b, p); p += 4
    p += 1  # endian
    uver, nblocks, bsver = struct.unpack_from("<III", b, p); p += 12
    info.update(version=hex(ver), user_version=uver, bs_version=bsver, num_blocks=nblocks)
    try:
        def short_string(p):
            n = b[p]
            return b[p + 1:p + 1 + n].rstrip(b"\0").decode("ascii", "replace"), p + 1 + n
        _author, p = short_string(p)
        if bsver > 130:
            p += 4
        if bsver < 131:
            _proc, p = short_string(p)
        _export, p = short_string(p)
        if bsver == 130:
            _maxfp, p = short_string(p)
        ntypes, = struct.unpack_from("<H", b, p); p += 2
        types = []
        for _ in range(ntypes):
            n, = struct.unpack_from("<I", b, p); p += 4
            types.append(b[p:p + n].decode("ascii")); p += n
        if not all(re.fullmatch(r"[A-Za-z0-9_]+", t) for t in types):
            raise ValueError("garbled block types")
        info["block_types"] = types
    except Exception:
        info["block_types"] = sorted({m.decode() for m in BLOCK_RE.findall(b[:8192])})
        info["block_types_heuristic"] = True
    return info


def ext_of(name):
    base = name.replace("/", "\\").rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def top_dir(name):
    return name.replace("/", "\\").split("\\", 1)[0].lower()


def scan_archives(data_dirs, label, nif_picks):
    archives = []
    ext_total = Counter()
    dir_total = Counter()
    ext_samples = defaultdict(list)
    nif_samples = []
    for d in data_dirs:
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".ba2"):
                continue
            ba2 = read_ba2(os.path.join(d, fn))
            exts = Counter(ext_of(n) for n in ba2["names"])
            ext_total.update(exts)
            dir_total.update(top_dir(n) for n in ba2["names"])
            for n in ba2["names"]:
                e = ext_of(n)
                if len(ext_samples[e]) < 4:
                    ext_samples[e].append(n)
            archives.append({
                "file": fn, "version": ba2["version"], "type": ba2["type"],
                "compression_method": ba2["compression_method"], "file_count": ba2["file_count"],
                "extensions": dict(exts.most_common(12)),
            })
            if ba2["type"] == "GNRL":
                lowered = [n.lower().replace("/", "\\") for n in ba2["names"]]
                for pick in nif_picks:
                    if any(s["pick"] == pick for s in nif_samples):
                        continue
                    for i, n in enumerate(lowered):
                        if n.endswith(".nif") and pick in n:
                            data = extract_gnrl(ba2, i)
                            entry = {"pick": pick, "archive": fn, "name": ba2["names"][i]}
                            if data is None:
                                entry["error"] = f"could not unpack (ba2 v{ba2['version']}, codec {ba2['compression_method']})"
                            else:
                                entry["size"] = len(data)
                                try:
                                    entry.update(parse_nif_header(data))
                                except Exception as exc:
                                    entry["error"] = f"header parse failed: {exc}"
                                refs = sorted({r.decode("ascii", "replace") for r in
                                               re.findall(rb"[A-Za-z0-9_\\/ .-]{4,120}\.(?:mesh|mat|bgsm|bgem|dds|hkx|af)", data)})
                                entry["referenced_files"] = refs[:12]
                            nif_samples.append(entry)
                            break
    return {
        "label": label, "archives": archives,
        "extension_totals": dict(ext_total.most_common()),
        "top_dirs": dict(dir_total.most_common(40)),
        "extension_samples": {e: s for e, s in ext_samples.items() if ext_total[e] >= 1},
        "nif_samples": nif_samples,
    }


def compare_plugins(fo4, sf):
    a, b = set(fo4["record_counts"]), set(sf["record_counts"])
    shared = sorted(a & b)
    schema = {}
    for t in sorted(SAMPLE_TYPES):
        sa = set(fo4["subrecord_sigs"].get(t, {}))
        sb = set(sf["subrecord_sigs"].get(t, {}))
        if not sa and not sb:
            continue
        union = sa | sb
        schema[t] = {
            "in_fo4": t in a, "in_sf": t in b,
            "fo4_count": fo4["record_counts"].get(t, 0), "sf_count": sf["record_counts"].get(t, 0),
            "subrecord_overlap": round(len(sa & sb) / len(union), 2) if union else None,
            "fo4_only_subrecords": sorted(sa - sb), "sf_only_subrecords": sorted(sb - sa),
        }
    return {
        "shared_record_types": shared,
        "fo4_only_record_types": sorted(a - b),
        "sf_only_record_types": sorted(b - a),
        "schema_by_type": schema,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fo4-data", action="append", required=True)
    ap.add_argument("--fo4-esm", required=True)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    print("scanning Fallout4.esm ...", flush=True)
    fo4 = scan_plugin(args.fo4_esm)
    print("scanning Starfield.esm ...", flush=True)
    sf = scan_plugin(os.path.join(args.sf_data, "Starfield.esm"))
    cmp_ = compare_plugins(fo4, sf)

    print("scanning archives ...", flush=True)
    picks = ["weapons\\", "architecture\\", "actors\\character\\", "furniture\\"]
    fo4_ba2 = scan_archives(args.fo4_data, "Fallout 4", picks)
    sf_ba2 = scan_archives([args.sf_data], "Starfield", picks)

    for name, obj in [("fo4_esm.json", fo4), ("sf_esm.json", sf), ("esm_compare.json", cmp_),
                      ("fo4_ba2.json", fo4_ba2), ("sf_ba2.json", sf_ba2)]:
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1)

    def head(p):
        return {k: p[k] for k in ("header_form_version", "hedr_version", "hedr_num_records",
                                  "total_records", "record_form_versions", "masters")}
    print(json.dumps({"fo4": head(fo4), "sf": head(sf)}, indent=1))
    print(f"record types: FO4 {len(fo4['record_counts'])}, SF {len(sf['record_counts'])}, "
          f"shared {len(cmp_['shared_record_types'])}")
    print("FO4-only:", " ".join(cmp_["fo4_only_record_types"]))
    print("SF-only :", " ".join(cmp_["sf_only_record_types"]))
    print("\nschema overlap (subrecord signature Jaccard, sampled):")
    for t, s in cmp_["schema_by_type"].items():
        print(f"  {t}: fo4={s['fo4_count']:>7} sf={s['sf_count']:>7} overlap={s['subrecord_overlap']}")
    for lab, inv in [("FO4", fo4_ba2), ("SF", sf_ba2)]:
        print(f"\n{lab} archives: " + ", ".join(sorted({f'v{a['version']}/{a['type']}/c{a['compression_method']}' for a in inv['archives']})))
        print(f"{lab} top extensions: " + ", ".join(f"{e}:{n}" for e, n in list(inv["extension_totals"].items())[:25]))
        for s in inv["nif_samples"]:
            print(f"  NIF {s['name']}: bs={s.get('bs_version')} uv={s.get('user_version')} "
                  f"blocks={s.get('block_types')} refs={s.get('referenced_files', [])[:4]} {s.get('error', '')}")


if __name__ == "__main__":
    sys.exit(main())
