"""Write FO4Port.esm's hidden exterior statics into the exterior plugin itself (in place; same record sizes, so no
FormID or group moves): every reference FO4Port.esm overrides as Initially Disabled that belongs to the exterior plugin
gets the Initially Disabled flag and FO4Port's position (sunk 1000 m) in the exterior plugin's own record.

Why (2026-11-14, owner, in game): the exterior statics under our outdoor furniture (and doors) still show although
FO4Port.esm overrides them correctly. ref_overrides.py showed both copies identical in place (world, block, sub-block,
cell, temporary group, cell record before it), FO4Port's disabled and sunk, loading last; on a fresh `coc` from the
main menu (no save) the static still stood under the chair (GetDisabled 0, original height). The game does not apply
FO4Port.esm's overrides of those temporary references, so the exterior plugin carries the change itself.

    python -I scripts\\terrain\\apply_ref_overrides.py --from "$sf\\Data\\FO4Port.esm"
        --into "$sf\\Data\\SkyrimTerrainTamriel.esm" --into C:\\Modding\\staging\\skyrim_all\\SkyrimTerrainTamriel.esm

Starfield must be closed. Each --into gets a one-time backup (<name>.before_ref_overrides) the first time it is patched.
Run again after every FO4Port.esm build and after every exterior rebuild (riverwood_doors.ps1 does).
"""
import argparse
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "tools"))

from fo4sf import fo4land  # noqa: E402
import ref_overrides  # noqa: E402

DISABLED = 0x800
BACKUP = ".before_ref_overrides"


def hidden_in(port_path, target_name):
    """{local id: DATA bytes (pos, rot)} of references port_path overrides as Initially Disabled that belong to
    target_name (a plugin file name)."""
    out = {}
    with fo4land.Plugin(port_path) as p:
        ml = ref_overrides.masters(p)
        own = os.path.basename(port_path)
        for typ, off, flags, fid, _chain in ref_overrides.walk(p, p.body, len(p.buf)):
            if typ not in ref_overrides.REF_TYPES or not flags & DISABLED:
                continue
            if ref_overrides.owner(fid, ml, own).lower() != target_name.lower():
                continue
            data = dict(fo4land.iter_subrecords(fo4land.record_data(p.buf, off))).get(b"DATA")
            out[fid & 0xFFFFFF] = bytes(data[:24]) if data and len(data) >= 24 else None
    return out


def field_offset(buf, rec_off, sig):
    """Absolute offset of a field's data in an uncompressed record, or None."""
    size = struct.unpack_from("<I", buf, rec_off + 4)[0]
    p, end = rec_off + 24, rec_off + 24 + size
    while p + 6 <= end:
        s, n = bytes(buf[p:p + 4]), struct.unpack_from("<H", buf, p + 4)[0]
        if s == b"XXXX":
            return None
        if s == sig:
            return p + 6
        p += 6 + n
    return None


def patch(target_path, hidden):
    """Set the flag and position of the target's own records listed in hidden. Returns (patched, already, missing,
    compressed)."""
    with open(target_path, "rb") as fh:
        buf = bytearray(fh.read())
    with fo4land.Plugin(target_path) as p:
        n_masters = len(ref_overrides.masters(p))
        found = {}
        for typ, off, flags, fid, _chain in ref_overrides.walk(p, p.body, len(p.buf)):
            if typ in ref_overrides.REF_TYPES and fid >> 24 == n_masters and (fid & 0xFFFFFF) in hidden:
                found[fid & 0xFFFFFF] = (off, flags)
    patched = already = compressed = 0
    for lid, (off, flags) in found.items():
        if flags & fo4land.COMPRESSED:
            compressed += 1
            continue
        data = hidden[lid]
        doff = field_offset(buf, off, b"DATA")
        same_pos = data is None or doff is None or bytes(buf[doff:doff + 24]) == data
        if flags & DISABLED and same_pos:
            already += 1
            continue
        struct.pack_into("<I", buf, off + 8, flags | DISABLED)
        if data is not None and doff is not None:
            buf[doff:doff + 24] = data
        patched += 1
    if patched:
        if not os.path.exists(target_path + BACKUP):
            shutil.copy2(target_path, target_path + BACKUP)
        tmp = target_path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(buf)
        os.replace(tmp, target_path)
    return patched, already, len(hidden) - len(found), compressed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="port", required=True, help="FO4Port.esm")
    ap.add_argument("--into", action="append", required=True, help="the exterior plugin (each copy); repeatable")
    a = ap.parse_args(argv)
    for target in a.into:
        hidden = hidden_in(a.port, os.path.basename(target))
        p, already, missing, comp = patch(target, hidden)
        print(f"{target}: {len(hidden)} hidden in {os.path.basename(a.port)}; {p} patched, {already} already, "
              f"{missing} not found, {comp} compressed (left)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
