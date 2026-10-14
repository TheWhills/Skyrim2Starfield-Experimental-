"""Reader for Havok tagfiles ("TAG0", the `bhkPhysicsSystem` payload in Starfield NIFs).

Layout: big-endian section headers (u32: 2 flag bits + 30-bit size including the 8-byte header, then a 4-char tag).
  TAG0 > SDKV (version string), DATA (object bytes), TYPE > TPTR, TST1 (type-name strings), TNA1 (type names +
  template parameters), FST1 (field-name strings), TBDY (type bodies: parent, size, fields), THSH, TPAD;
  INDX > ITEM (type, data offset, count per item), PTCH (pointer locations per type).
Numbers inside TYPE are Havok varints (1-5 bytes, length given by the leading bits of the first byte).
Each type's fields carry their byte offsets, so object layouts come straight from the file; no hand-written tables.
"""
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class TagfileError(ValueError):
    pass


def _varint(b: bytes, p: int) -> Tuple[int, int]:
    x = b[p]
    if x & 0x80 == 0:
        return x, p + 1
    if x & 0xC0 == 0x80:
        return ((x & 0x3F) << 8) | b[p + 1], p + 2
    if x & 0xE0 == 0xC0:
        return ((x & 0x1F) << 16) | (b[p + 1] << 8) | b[p + 2], p + 3
    if x & 0xF8 == 0xE0:                                  # 11100xxx: 27 bits
        return ((x & 0x07) << 24) | (b[p + 1] << 16) | (b[p + 2] << 8) | b[p + 3], p + 4
    if x & 0xF8 == 0xE8:                                  # 11101xxx: 35 bits
        return ((x & 0x07) << 32) | int.from_bytes(b[p + 1:p + 5], "big"), p + 5
    if x & 0xF8 == 0xF0:                                  # 11110xxx: 59 bits
        return ((x & 0x07) << 56) | int.from_bytes(b[p + 1:p + 8], "big"), p + 8
    if x == 0xF8:                                         # 11111000: 64 bits
        return int.from_bytes(b[p + 1:p + 9], "big"), p + 9
    raise TagfileError(f"unsupported varint prefix {x:#x} at {p}")


@dataclass
class Field:
    name: str
    flags: int
    offset: int
    type: int
    count: int = 1                                        # fixed-size C array fields (flags & 0x80) carry a count


@dataclass
class Type:
    index: int
    name: str = ""
    params: List[Tuple[str, int]] = field(default_factory=list)
    parent: int = 0
    format: int = 0
    subtype: int = 0
    version: int = 0
    size: int = 0
    align: int = 0
    flags: int = 0
    fields: List[Field] = field(default_factory=list)
    interfaces: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class Item:
    type: int
    flags: int
    offset: int
    count: int


def sections(b: bytes, off: int, end: int) -> List[Tuple[str, int, int]]:
    """[(tag, payload start, payload end)] of the sections between off and end."""
    out = []
    while off < end:
        h, = struct.unpack_from(">I", b, off)
        size = h & 0x3FFFFFFF
        if size < 8:
            raise TagfileError(f"bad section size at {off}")
        out.append((b[off + 4:off + 8].decode("latin-1"), off + 8, off + size))
        off += size
    return out


class Tagfile:
    def __init__(self, blob: bytes):
        self.blob = blob
        top = sections(blob, 0, len(blob))
        if not top or top[0][0] != "TAG0":
            raise TagfileError("not a TAG0 tagfile")
        secs = {t: (s, e) for t, s, e in sections(blob, top[0][1], top[0][2])}
        self.sdk = blob[secs["SDKV"][0]:secs["SDKV"][1]].decode("latin-1")
        self.data_start, self.data_end = secs["DATA"]
        tsec = {t: (s, e) for t, s, e in sections(blob, *secs["TYPE"])}
        isec = {t: (s, e) for t, s, e in sections(blob, *secs["INDX"])}
        strings = lambda t: blob[tsec[t][0]:tsec[t][1]].split(b"\0")
        self.type_strings = [s.decode("latin-1") for s in strings("TST1")]
        self.field_strings = [s.decode("latin-1") for s in strings("FST1")]
        self.types: List[Type] = [Type(0, "<none>")]
        self._read_names(*tsec["TNA1"])
        self._read_bodies(*tsec["TBDY"])
        self.items = self._read_items(*isec["ITEM"])
        self.patches = self._read_patches(*isec["PTCH"])

    def _read_names(self, s, e):
        b = self.blob
        n, p = _varint(b, s)
        for i in range(1, n):
            name, p = _varint(b, p)
            np_, p = _varint(b, p)
            t = Type(i, self.type_strings[name])
            for _ in range(np_):
                pn, p = _varint(b, p)
                pv, p = _varint(b, p)
                t.params.append((self.type_strings[pn], pv))
            self.types.append(t)

    def _read_bodies(self, s, e):
        b, p = self.blob, s
        while p < e:
            ti, p = _varint(b, p)
            if ti == 0:
                break
            t = self.types[ti]
            t.parent, p = _varint(b, p)
            opt, p = _varint(b, p)
            if opt & 0x1:
                t.format, p = _varint(b, p)
            if opt & 0x2:
                t.subtype, p = _varint(b, p)
            if opt & 0x4:
                t.version, p = _varint(b, p)
            if opt & 0x8:
                t.size, p = _varint(b, p)
                t.align, p = _varint(b, p)
            if opt & 0x10:
                t.flags, p = _varint(b, p)
            if opt & 0x20:
                nf, p = _varint(b, p)
                for _ in range(nf):
                    fn, p = _varint(b, p)
                    ff, p = _varint(b, p)
                    cnt = 1
                    if ff & 0x80:
                        cnt, p = _varint(b, p)
                    fo, p = _varint(b, p)
                    ft, p = _varint(b, p)
                    t.fields.append(Field(self.field_strings[fn], ff, fo, ft, cnt))
            if opt & 0x40:
                ni, p = _varint(b, p)
                for _ in range(ni):
                    it, p = _varint(b, p)
                    iv, p = _varint(b, p)
                    t.interfaces.append((it, iv))
            if opt & 0x80:
                _, p = _varint(b, p)                      # attribute string index (unused)

    def _read_items(self, s, e):
        out = []
        for p in range(s, e, 12):
            ft, off, cnt = struct.unpack_from("<III", self.blob, p)
            out.append(Item(ft & 0xFFFFFF, ft >> 24, off, cnt))
        return out

    def _read_patches(self, s, e):
        out, p = [], s
        while p < e:
            ti, n = struct.unpack_from("<II", self.blob, p)
            offs = list(struct.unpack_from(f"<{n}I", self.blob, p + 8))
            out.append((ti, offs))
            p += 8 + 4 * n
        return out

    # -- helpers ------------------------------------------------------------------------------------------------------
    def type_name(self, ti: int) -> str:
        t = self.types[ti]
        if not t.params:
            return t.name
        return t.name + "<" + ", ".join(self.type_name(v) if k.startswith("t") else str(v) for k, v in t.params) + ">"

    def all_fields(self, ti: int) -> List[Field]:
        """Fields of a type including its parents (parents first)."""
        chain, t = [], ti
        while t:
            chain.append(t)
            t = self.types[t].parent
        return [f for t in reversed(chain) for f in self.types[t].fields]

    def size_of(self, ti: int) -> int:
        t = ti
        while t and not self.types[t].size:
            t = self.types[t].parent
        return self.types[t].size if t else 0
