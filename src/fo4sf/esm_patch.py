"""Small in-place edits of a Starfield plugin that Mutagen wrote, without rebuilding it (2026-11-25, alternate textures on
the installed Skyrim exterior): every existing record keeps its FormID and bytes.

add_records    new top-level records at the end of a top group (STAT): copies of a template record with some fields
               replaced, FormIDs from HEDR's next object ID; the group size, HEDR's record count and next object ID are
               updated. Only a top group that comes before WRLD may grow: the WRLD cell index (OFST) counts from the
               WRLD record (scripts/tools/world_offsets.py), so it stays valid.
set_ref_bases  the base (NAME) of placed references, written in place (same size). Compressed references are refused.

Record header (24 bytes): type, data size, flags, FormID, version control, form version, unknown; group header
(24 bytes): 'GRUP', size including the header, label, group type, stamp. TES4 HEDR: f32 version, u32 record count,
u32 next object ID (verified on SkyrimTerrainTamriel.esm: 234,796 records, next 0x389B8, above its last REFR).
"""
import struct

from . import fo4land

COMPRESSED = 0x40000
_HDR = struct.Struct("<4sIIIIHH")


class PatchError(ValueError):
    pass


def _fields(data: bytes) -> list:
    return [(sig, bytes(d)) for sig, d in fo4land.iter_subrecords(data)]


def _pack_fields(fields) -> bytes:
    out = bytearray()
    for sig, d in fields:
        if len(d) > 0xFFFF:
            raise PatchError(f"field {sig} too large for a plain subrecord")
        out += sig + struct.pack("<H", len(d)) + d
    return bytes(out)


def header(buf) -> tuple:
    """(record count, next object ID, number of masters) from TES4."""
    count = nxt = None
    masters = 0
    for sig, d in fo4land.iter_subrecords(fo4land.record_data(buf, 0)):
        if sig == b"HEDR":
            _v, count, nxt = struct.unpack_from("<fII", d)
        elif sig == b"MAST":
            masters += 1
    if count is None:
        raise PatchError("no HEDR in TES4")
    return count, nxt, masters


def _set_hedr(buf: bytearray, count: int, nxt: int):
    size = struct.unpack_from("<I", buf, 4)[0]
    if struct.unpack_from("<I", buf, 8)[0] & COMPRESSED:
        raise PatchError("compressed TES4")
    p, end = 24, 24 + size
    while p + 6 <= end:
        sig, n = buf[p:p + 4], struct.unpack_from("<H", buf, p + 4)[0]
        if sig == b"HEDR":
            struct.pack_into("<II", buf, p + 6 + 4, count, nxt)
            return
        p += 6 + n
    raise PatchError("no HEDR in TES4")


def find_record(buf, group: bytes, fid: int):
    """(offset, flags) of the record with this full FormID in a top group, or None."""
    for item in fo4land.iter_items(buf, len_tes4(buf), len(buf)):
        if item[0] == "GRUP" and item[3] == group:
            for typ, off, flags, f in fo4land.iter_items(buf, item[1] + 24, item[2]):
                if typ != "GRUP" and f == fid:
                    return off, flags
    return None


def len_tes4(buf) -> int:
    return 24 + struct.unpack_from("<I", buf, 4)[0]


def add_records(data: bytes, group: bytes, records: list) -> tuple:
    """records: [(template FormID (full, as stored), {field sig: new bytes})]. Returns (new plugin bytes, [new FormIDs])
    in the order given. The new records take the template's header (flags, form version) and fields, with the given
    fields replaced (they must exist in the template)."""
    buf = bytearray(data)
    count, nxt, masters = header(buf)
    top = None
    for item in fo4land.iter_items(buf, len_tes4(buf), len(buf)):
        if item[0] == "GRUP":
            if item[3] == b"WRLD" and top is None:
                raise PatchError(f"no {group.decode()} group before WRLD")
            if item[3] == group:
                top = item
                break
    if top is None:
        raise PatchError(f"no top group {group.decode()}")
    _g, gstart, gend, _label, _gtype = top
    new, fids = bytearray(), []
    for template, repl in records:
        found = find_record(buf, group, template)
        if found is None:
            raise PatchError(f"template {template:08X} not in {group.decode()}")
        off, flags = found
        if flags & COMPRESSED:
            raise PatchError(f"template {template:08X} is compressed")
        typ, _size, _flags, _fid, vc, fv, unk = _HDR.unpack_from(buf, off)
        fields = _fields(fo4land.record_data(buf, off))
        have = {sig for sig, _d in fields}
        missing = set(repl) - have
        if missing:
            raise PatchError(f"template {template:08X} has no {sorted(missing)}")
        body = _pack_fields([(sig, repl.get(sig, d)) for sig, d in fields])
        fid = (masters << 24) | (nxt & 0xFFFFFF)
        nxt += 1
        new += _HDR.pack(typ, len(body), flags, fid, vc, fv, unk) + body
        fids.append(fid)
    out = buf[:gend] + new + buf[gend:]
    struct.pack_into("<I", out, gstart + 4, gend - gstart + len(new))
    _set_hedr(out, count + len(records), nxt)
    return bytes(out), fids


def set_ref_bases(data: bytes, bases: dict) -> tuple:
    """bases: {reference FormID: new base FormID} (full, as stored). Returns (new bytes, set count, missing ids)."""
    buf = bytearray(data)
    todo = dict(bases)

    def walk(s, e):
        for item in fo4land.iter_items(buf, s, e):
            if item[0] == "GRUP":
                walk(item[1] + 24, item[2])
                continue
            typ, off, flags, fid = item
            if fid not in todo or typ not in (b"REFR",):
                continue
            if flags & COMPRESSED:
                raise PatchError(f"reference {fid:08X} is compressed")
            size = struct.unpack_from("<I", buf, off + 4)[0]
            p, end = off + 24, off + 24 + size
            while p + 6 <= end:
                sig, n = bytes(buf[p:p + 4]), struct.unpack_from("<H", buf, p + 4)[0]
                if sig == b"NAME" and n == 4:
                    struct.pack_into("<I", buf, p + 6, todo.pop(fid))
                    break
                p += 6 + n
            else:
                raise PatchError(f"reference {fid:08X} has no NAME")

    want = len(todo)
    walk(len_tes4(buf), len(buf))
    return bytes(buf), want - len(todo), sorted(todo)


def zstring(s: str) -> bytes:
    return s.encode("cp1252") + b"\0"

