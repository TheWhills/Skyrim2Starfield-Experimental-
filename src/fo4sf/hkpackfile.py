"""Minimal reader for Havok 2014 binary packfiles (the `bhkPhysicsSystem` payload in Fallout 4 NIFs, "hk_2014.1.0-r1",
64-bit little-endian layout). Enough to locate objects by class and follow their array / pointer fields; no class
reflection is used (the layouts we need are decoded by hand in fo4collision.py).

Packfile layout: 64-byte header, then one 64-byte header per section (tag[20], absoluteDataStart, localFixupsOffset,
globalFixupsOffset, virtualFixupsOffset, exportsOffset, importsOffset, endOffset; offsets relative to the section start).
  local fixups   (src, dst)                 pointer at src points to dst, same section
  global fixups  (src, dst section, dst)    pointer at src points into another section
  virtual fixups (obj, class section, name) an object of class <name> starts at obj
"""
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MAGIC = b"\x57\xe0\xe0\x57\x10\xc0\xc0\x10"


class PackfileError(ValueError):
    pass


@dataclass
class Section:
    tag: str
    start: int
    end: int
    local: Dict[int, int] = field(default_factory=dict)              # src -> dst (section-relative)
    glob: Dict[int, Tuple[int, int]] = field(default_factory=dict)   # src -> (section, dst)
    virtual: List[Tuple[int, str]] = field(default_factory=list)     # (obj offset, class name)


class Packfile:
    def __init__(self, data: bytes):
        if data[:8] != MAGIC:
            raise PackfileError("not a Havok packfile")
        self.data = data
        version, = struct.unpack_from("<i", data, 12)
        if data[16] != 8:
            raise PackfileError("only 64-bit packfiles are supported")
        nsec, = struct.unpack_from("<i", data, 20)
        self.version = data[40:56].split(b"\0")[0].decode("latin-1")
        hdr = 64 + (16 if version >= 11 else 0) - 16       # v11: section headers start at 64 (padding inside header)
        hdr = 64
        self.sections: List[Section] = []
        for i in range(nsec):
            h = hdr + 64 * i
            tag = data[h:h + 20].split(b"\0")[0].decode("latin-1")
            start, loc, glo, vir, exp, imp, end = struct.unpack_from("<7i", data, h + 20)
            s = Section(tag, start, end)
            for p in range(start + loc, start + glo - 7, 8):
                a, b = struct.unpack_from("<ii", data, p)
                if a != -1:
                    s.local[a] = b
            for p in range(start + glo, start + vir - 11, 12):         # tables are padded: skip a partial tail
                a, sec, b = struct.unpack_from("<iii", data, p)
                if a != -1:
                    s.glob[a] = (sec, b)
            self.sections.append(s)
        cls = self.sections[0]
        for s in self.sections:                              # virtual fixups need the class-name section
            h = hdr + 64 * self.sections.index(s)
            start, loc, glo, vir, exp = struct.unpack_from("<5i", data, h + 20)
            for p in range(start + vir, start + exp - 11, 12):
                a, sec, b = struct.unpack_from("<iii", data, p)
                if a != -1:
                    nm_at = self.sections[sec].start + b
                    s.virtual.append((a, data[nm_at:data.index(b"\0", nm_at)].decode("latin-1")))
        self.data_section = next(s for s in self.sections if s.tag == "__data__")
        del cls

    # -- access in the data section (offsets are section-relative) ---------------------------------------------------
    def objects(self, class_name: Optional[str] = None) -> List[Tuple[int, str]]:
        return [(o, c) for o, c in self.data_section.virtual if class_name is None or c == class_name]

    def raw(self, off: int, n: int) -> bytes:
        s = self.data_section
        return self.data[s.start + off:s.start + off + n]

    def unpack(self, fmt: str, off: int):
        return struct.unpack_from(fmt, self.data, self.data_section.start + off)

    def pointer(self, off: int) -> Optional[int]:
        """Target (section-relative offset) of the pointer stored at `off`, or None if null / external."""
        s = self.data_section
        if off in s.local:
            return s.local[off]
        if off in s.glob and s.glob[off][0] == self.sections.index(s):
            return s.glob[off][1]
        return None

    def array(self, off: int) -> Tuple[Optional[int], int]:
        """(data offset, element count) of the hkArray stored at `off` (pointer 8, size 4, capacity|flags 4)."""
        size, = self.unpack("<i", off + 8)
        return self.pointer(off), size
