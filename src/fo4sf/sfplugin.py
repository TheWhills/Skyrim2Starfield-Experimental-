"""A small Starfield plugin writer for test content: records copied from Starfield.esm and edited, in a new master.

Layout (as fo4land reads it; xEdit's wbDefinitionsSF1 and Fallout 4's, which Starfield keeps for these parts):
record header 24 bytes = type, data size u32, flags u32, FormID u32, version control u32, form version u16, u16;
group header 24 bytes = "GRUP", total size u32, label (record type for top groups), group type i32 (0 = top),
stamp / version control u32, u32. TES4 subrecords: HEDR (version f32, record count u32, next object id u32), CNAM
(author), MAST + DATA (u64 0) per master. The HEDR version and the form version are copied from Starfield.esm itself
at run time (header_info), so the plugin matches the installed game.

New records get FormIDs 0x01000800 and up: master index 01 (after Starfield.esm, index 00), object ids below 0x800
being reserved by the engine. Records copied from Starfield.esm keep their header (flags, form version) without the
compressed flag; references inside them stay valid (index 00 = Starfield.esm).
Starfield.esm is localized (string-table IDs in FULL / DESC); this plugin is not, so names are written as text and
DESC is dropped.
"""
import struct
from typing import Dict, Iterable, List, Optional, Tuple

from . import fo4land

REC = struct.Struct("<4sIII")
MASTER = 0x1
COMPRESSED = 0x40000
FIRST_OBJECT = 0x800


def zs(text: str) -> bytes:
    return text.encode("utf-8") + b"\0"


def header_info(esm_path: str) -> Dict:
    """{"hedr_version", "form_version"} from a plugin's TES4 (Starfield.esm on the owner's PC)."""
    with open(esm_path, "rb") as fh:
        head = fh.read(24)
        typ, size, _flags, _fid = REC.unpack_from(head, 0)
        if typ != b"TES4":
            raise ValueError(f"{esm_path}: not a plugin")
        body = fh.read(size)
    form_version, = struct.unpack_from("<H", head, 20)
    version = None
    for s, d in fo4land.iter_subrecords(body):
        if s == b"HEDR" and len(d) >= 4:
            version, = struct.unpack_from("<f", bytes(d), 0)
    if version is None:
        raise ValueError(f"{esm_path}: TES4 without HEDR")
    return {"hedr_version": version, "form_version": form_version}


def records(esm_path: str, types: Iterable[bytes]) -> List[Tuple[bytes, bytes, list, int]]:
    """[(type, 24-byte header, [(sig, data)], FormID)] of every record of the given types (top groups only)."""
    want = set(types)
    out = []
    with fo4land.Plugin(esm_path) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP" or item[3] not in want:
                continue
            for it in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if it[0] == "GRUP":
                    continue
                typ, off, _fl, fid = it
                subs = [(s, bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))]
                out.append((typ, bytes(p.buf[off:off + 24]), subs, fid))
    return out


def edid(subs) -> str:
    return next((fo4land.zstring(d) for s, d in subs if s == b"EDID"), "")


def keywords(subs) -> List[int]:
    for s, d in subs:
        if s == b"KWDA":
            return list(struct.unpack(f"<{len(d) // 4}I", d[:len(d) // 4 * 4]))
    return []


def edit(subs, replace: Dict[bytes, bytes], drop: Iterable[bytes] = (), add_after: Optional[Dict] = None):
    """Subrecords with `replace` {sig: data} applied to the first occurrence of each sig, `drop` removed, and sigs of
    `replace` that were missing appended after EDID."""
    drop = set(drop)
    seen, out = set(), []
    for s, d in subs:
        if s in drop:
            continue
        if s in replace and s not in seen:
            seen.add(s)
            out.append((s, replace[s]))
            continue
        out.append((s, d))
    missing = [(s, d) for s, d in replace.items() if s not in seen]
    if missing:
        at = next((i + 1 for i, (s, _d) in enumerate(out) if s == b"EDID"), 0)
        out[at:at] = missing
    return out


def subrecord_bytes(sig: bytes, data: bytes) -> bytes:
    """One field; over 64 KiB as XXXX (u32 size) followed by the field with size 0, as the games write it."""
    if len(data) > 0xFFFF:
        return b"XXXX" + struct.pack("<HI", 4, len(data)) + sig + struct.pack("<H", 0) + data
    return sig + struct.pack("<H", len(data)) + data


def record_bytes(typ: bytes, header: bytes, subs, fid: int) -> bytes:
    data = b"".join(subrecord_bytes(s, d) for s, d in subs)
    _t, _size, flags, _fid = REC.unpack_from(header, 0)
    return struct.pack("<4sIII", typ, len(data), flags & ~COMPRESSED, fid) + header[16:24] + data


def group_bytes(typ: bytes, recs: List[bytes]) -> bytes:
    body = b"".join(recs)
    return struct.pack("<4sI4si", b"GRUP", 24 + len(body), typ, 0) + bytes(8) + body


def build(recs: List[Tuple[bytes, bytes, list, int]], info: Dict, author: str = "Skyrim2Starfield",
          masters=("Starfield.esm",)) -> bytes:
    """A master plugin holding recs [(type, template header, subs, FormID)], one top group per type in first-seen
    order."""
    by_type: Dict[bytes, List[bytes]] = {}
    for typ, header, subs, fid in recs:
        by_type.setdefault(typ, []).append(record_bytes(typ, header, subs, fid))
    own = [fid & 0xFFFFFF for _t, _h, _s, fid in recs if fid >> 24 == len(masters)]
    next_id = max(own + [FIRST_OBJECT - 1]) + 1
    tes4_subs = [(b"HEDR", struct.pack("<fII", info["hedr_version"], len(recs), next_id)), (b"CNAM", zs(author))]
    for m in masters:
        tes4_subs += [(b"MAST", zs(m)), (b"DATA", bytes(8))]
    data = b"".join(subrecord_bytes(s, d) for s, d in tes4_subs)
    tes4 = struct.pack("<4sIII", b"TES4", len(data), MASTER, 0) + bytes(4) + struct.pack("<HH", info["form_version"], 0)
    return tes4 + data + b"".join(group_bytes(t, r) for t, r in by_type.items())


def new_form_id(index: int, masters: int = 1) -> int:
    """FormID of this plugin's index-th new record (0-based)."""
    return (masters << 24) | (FIRST_OBJECT + index)
