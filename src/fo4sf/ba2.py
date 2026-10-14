"""BA2 archive reader for Fallout 4 (v1) and Starfield (v2): general files and DX10 textures.

    a = Ba2("Fallout4 - Textures1.ba2")
    a.names                    # file names as stored (backslashes)
    data = a.read(name)        # general file bytes, or a complete DDS (DX10 header) for a texture
Lookup is case-insensitive and slash-agnostic: a.find("textures/setdressing/x_d.dds").
Starfield v3 (LZ4) textures are not supported (raises); v1/v2 zlib and uncompressed are.
"""
import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional


class Ba2Error(ValueError):
    pass


@dataclass
class Entry:
    name: str
    kind: str                  # "GNRL" | "DX10"
    # GNRL
    offset: int = 0
    packed: int = 0
    unpacked: int = 0
    # DX10
    width: int = 0
    height: int = 0
    mips: int = 0
    dxgi: int = 0
    cubemap: bool = False
    chunks: Optional[list] = None      # (offset, packed, unpacked, start_mip, end_mip)


def _dds_header_dx10(width, height, mips, dxgi, cubemap):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x20000 if mips > 1 else 0)
    caps = 0x1000 | (0x8 | 0x400000 if mips > 1 else 0)
    caps2 = 0xFE00 | 0x200 if cubemap else 0
    h = b"DDS " + struct.pack("<7I", 124, flags, height, width, 0, 0, mips) + b"\0" * 44
    h += struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    h += struct.pack("<5I", caps, caps2, 0, 0, 0)
    h += struct.pack("<5I", dxgi, 3, 4 if cubemap else 0, 6 if cubemap else 1, 0)
    return h


class Ba2:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            magic, version, kind, count, name_off = struct.unpack("<4sI4sIQ", f.read(24))
            if magic != b"BTDX":
                raise Ba2Error(f"{path}: not a BA2")
            self.version, self.kind = version, kind.decode()
            if self.kind not in ("GNRL", "DX10"):
                raise Ba2Error(f"{path}: unsupported archive type {self.kind}")
            extra = {1: 0, 2: 8, 3: 12}.get(version)
            if extra is None:
                raise Ba2Error(f"{path}: unsupported version {version}")
            self.compression = struct.unpack("<I", f.read(12)[8:12])[0] if version == 3 else 0
            if version == 2:
                f.read(8)
            f.seek(24 + extra)
            raw = []
            for _ in range(count):
                if self.kind == "GNRL":
                    _h, _e, _d, _fl, off, pk, up, _al = struct.unpack("<I4sIIQIII", f.read(36))
                    raw.append(("GNRL", off, pk, up))
                else:
                    _h, _e, _d, _u, nch, _chsz, hgt, wid, mips, fmt, fl, _tile = struct.unpack("<I4sIBBHHHBBBB", f.read(24))
                    chunks = [struct.unpack("<QIIHHI", f.read(24))[:5] for _ in range(nch)]
                    raw.append(("DX10", wid, hgt, mips, fmt, bool(fl & 1), chunks))
            f.seek(name_off)
            names = []
            for _ in range(count):
                n, = struct.unpack("<H", f.read(2))
                names.append(f.read(n).decode("utf-8", "replace"))
        self.entries: List[Entry] = []
        for name, r in zip(names, raw):
            if r[0] == "GNRL":
                self.entries.append(Entry(name, "GNRL", offset=r[1], packed=r[2], unpacked=r[3]))
            else:
                self.entries.append(Entry(name, "DX10", width=r[1], height=r[2], mips=r[3], dxgi=r[4], cubemap=r[5], chunks=r[6]))
        self.names = names
        self._index = {self._norm(n): i for i, n in enumerate(names)}

    @staticmethod
    def _norm(n: str) -> str:
        return n.replace("/", "\\").lower().lstrip("\\")

    def find(self, name: str) -> Optional[int]:
        return self._index.get(self._norm(name))

    def read(self, name_or_index) -> bytes:
        i = name_or_index if isinstance(name_or_index, int) else self.find(name_or_index)
        if i is None:
            raise KeyError(name_or_index)
        e = self.entries[i]
        with open(self.path, "rb") as f:
            if e.kind == "GNRL":
                f.seek(e.offset)
                raw = f.read(e.packed or e.unpacked)
                return zlib.decompress(raw) if e.packed else raw
            if self.version == 3 and self.compression == 3:
                raise Ba2Error("LZ4-compressed (v3) textures are not supported")
            out = [_dds_header_dx10(e.width, e.height, e.mips, e.dxgi, e.cubemap)]
            for off, pk, up, _s, _e in e.chunks:
                f.seek(off)
                raw = f.read(pk or up)
                out.append(zlib.decompress(raw) if pk else raw)
            return b"".join(out)
