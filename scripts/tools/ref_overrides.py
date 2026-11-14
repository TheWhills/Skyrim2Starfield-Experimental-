"""Which plugins carry a reference, and what each says about it (read-only). For "my override does not take": the
console shows a FormID whose first two digits are a load-order slot, so only the last six are looked up here; every
plugin given that has a record with those six digits is listed with the plugin the record belongs to (resolved through
that plugin's own master list), its Initially Disabled flag, position and enable parent. An override only takes if it
belongs to the same plugin as the original and its plugin loads after every other plugin that has the record.

    python -I scripts\\tools\\ref_overrides.py --ref 0400502E --plugin <SkyrimTerrainTamriel.esm>
        --plugin <SkyrimTerrainTamriel_Mars.esm> --plugin <FO4Port.esm>

2026-11-14 (owner): the exterior static under each outdoor bench still shows in game (console: GetDisabled 0, z 184.88,
not 1000 m lower), although FO4Port.esm's build reports disabling them.
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

DISABLED = 0x800
REF_TYPES = (b"REFR", b"ACHR", b"PGRE", b"PHZD")


def masters(p):
    """The plugin's master file names, in header order."""
    return [fo4land.zstring(d) for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0)) if sig == b"MAST"]


def owner(fid, master_list, own_name):
    """The plugin a FormID written in a plugin belongs to: its top byte indexes the plugin's masters, past them itself."""
    i = fid >> 24
    return master_list[i] if i < len(master_list) else own_name


def describe(fields, flags, master_list, own_name):
    out = {"disabled": bool(flags & DISABLED), "deleted": bool(flags & 0x20)}
    for sig, d in fields:
        if sig == b"DATA" and len(d) >= 24:
            out["pos"] = [round(v, 2) for v in struct.unpack_from("<3f", d)]
        elif sig == b"XESP" and len(d) >= 5:
            parent, fl = struct.unpack_from("<IB", d)
            out["enable_parent"] = f"{parent & 0xFFFFFF:06X}:{owner(parent, master_list, own_name)} flags {fl}"
        elif sig == b"NAME" and len(d) >= 4:
            b = struct.unpack_from("<I", d)[0]
            out["base"] = f"{b & 0xFFFFFF:06X}:{owner(b, master_list, own_name)}"
    return out


def walk(p, start, end):
    for item in fo4land.iter_items(p.buf, start, end):
        if item[0] == "GRUP":
            yield from walk(p, item[1] + 24, item[2])
        else:
            yield item


def find(path, local_id):
    """[(owner plugin, record type, raw FormID, description)] for records of `path` whose low 24 bits are local_id."""
    name = os.path.basename(path)
    hits = []
    with fo4land.Plugin(path) as p:
        ml = masters(p)
        for typ, off, flags, fid in walk(p, p.body, len(p.buf)):
            if (fid & 0xFFFFFF) != local_id or typ not in REF_TYPES:
                continue
            fields = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
            hits.append((owner(fid, ml, name), typ.decode(), fid, describe(fields, flags, ml, name)))
    return ml, hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, help="the FormID the console shows (its first two digits are ignored)")
    ap.add_argument("--plugin", action="append", required=True, help="plugin file; repeatable, in load order")
    a = ap.parse_args(argv)
    local_id = int(a.ref, 16) & 0xFFFFFF
    for path in a.plugin:
        ml, hits = find(path, local_id)
        print(f"== {os.path.basename(path)}  masters: {', '.join(ml) or '-'}")
        for own, typ, fid, d in hits:
            print(f"  {typ} {fid:08X} = {local_id:06X}:{own}  " + "  ".join(f"{k} {v}" for k, v in d.items()))
        if not hits:
            print(f"  no reference ending {local_id:06X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
