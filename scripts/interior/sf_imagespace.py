"""Read Starfield image space settings (read-only, 2026-11-21): the IMGS REFL / RDIF blobs SfInspect imgsdump writes, in
Bethesda's binary reflection format, decoded to their fields.

    python -I scripts/interior/sf_imagespace.py C:\\Modding\\work\\imgs\\*_REFL.bin [--all]

Format (verified on 15 vanilla blobs: every OBJT decodes to exactly its length): "BETH" + u32 version + u32 4 + u32
chunk count, then chunks (tag, u32 size, data): STRT (NUL-separated strings; types and names are offsets into it),
TYPE (u32 class count), CLAS per class (u32 name, u32, u16 flags, u16 field count, then per field u32 name, u32 type,
u16 offset, u16 size), OBJT (u32 root type, then the root's fields in order), USER (classes with flag 0x4, e.g.
BSFloatCurve, serialised apart), LIST / MAPC. Types 0xFFFFFFxx are built-ins (BUILTIN); 0xFFFFFF02 fields hold enums,
written as a u16-length string; 0xFFFFFF05 (pParent) is 8 bytes. Field values in OBJT: bool 1 byte, numbers raw
little-endian, strings u16 length + bytes, structs their fields in order, user classes nothing (in USER).
Prints the exposure, tone mapping and cinematic settings (--all: every field)."""
import argparse
import glob
import os
import struct
import sys

BUILTIN = {0xFFFFFF01: "String", 0xFFFFFF02: "Enum", 0xFFFFFF03: "Map", 0xFFFFFF04: "Ref", 0xFFFFFF05: "FormRef",
           0xFFFFFF08: "Int8", 0xFFFFFF09: "UInt8", 0xFFFFFF0A: "Int16", 0xFFFFFF0B: "UInt16", 0xFFFFFF0C: "Int32",
           0xFFFFFF0D: "UInt32", 0xFFFFFF0E: "Int64", 0xFFFFFF0F: "UInt64", 0xFFFFFF10: "Bool", 0xFFFFFF11: "Float",
           0xFFFFFF12: "Double"}
NUM = {"Bool": "B", "Float": "f", "Double": "d", "Int8": "b", "UInt8": "B", "Int16": "h", "UInt16": "H", "Int32": "i",
       "UInt32": "I", "Int64": "q", "UInt64": "Q"}
USER_FLAG = 0x4
KEYS = ("Settings.Exposure.CameraExposureMode", "Settings.Exposure.FixedValue.Value",
        "Settings.Exposure.AutoExposure.ExposureMin.Value", "Settings.Exposure.AutoExposure.ExposureMax.Value",
        "Settings.Exposure.AutoExposure.AdaptSpeedUp.Value", "Settings.Exposure.AutoExposure.AdaptSpeedDown.Value",
        "Settings.OverrideToneMapping", "Settings.ToneMapping.CurveType", "Settings.Cinematic.Saturation.Value",
        "Settings.Cinematic.Brightness.Value", "Settings.Cinematic.Contrast.Value",
        "Settings.Cinematic.ColorGradingTexture", "Settings.Cinematic.ColorGradingAmount")


def chunks(data: bytes) -> list:
    if data[:4] != b"BETH":
        raise ValueError("not a BETH reflection blob")
    out, pos = [], 16
    while pos + 8 <= len(data):
        tag, size = data[pos:pos + 4].decode("latin1"), struct.unpack_from("<I", data, pos + 4)[0]
        out.append((tag, data[pos + 8:pos + 8 + size]))
        pos += 8 + size
    return out


def schema(cs: list):
    strt = next(c for t, c in cs if t == "STRT")

    def name(o):
        if o in BUILTIN:
            return BUILTIN[o]
        if o >= len(strt):
            return hex(o)
        return strt[o:strt.index(b"\0", o)].decode("latin1")
    classes = {}
    for t, c in cs:
        if t == "CLAS":
            nm, _u, flags, n = struct.unpack_from("<IIHH", c, 0)
            classes[name(nm)] = {"flags": flags, "fields": [
                (name(fn), name(ft)) for fn, ft, _o, _s in (struct.unpack_from("<IIHH", c, 12 + 12 * i) for i in range(n))]}
    return name, classes


class _Reader:
    def __init__(self, data, classes):
        self.d, self.p, self.c = data, 0, classes

    def num(self, fmt):
        v = struct.unpack_from("<" + fmt, self.d, self.p)[0]
        self.p += struct.calcsize("<" + fmt)
        return v

    def value(self, t):
        if t in NUM:
            v = self.num(NUM[t])
            return bool(v) if t == "Bool" else v
        if t in ("String", "Enum"):
            n = self.num("H")
            s = self.d[self.p:self.p + n]
            self.p += n
            return s.rstrip(b"\0").decode("latin1")
        if t == "FormRef":
            return (self.num("I"), self.num("I"))
        if t == "Map":
            return None                                    # its entries are in a chunk of their own (empty in IMGS)
        cls = self.c.get(t)
        if cls is None:
            raise ValueError(f"unknown type {t} at byte {self.p}")
        if cls["flags"] & USER_FLAG:
            return None                                    # serialised in the USER chunk
        return {n: self.value(ft) for n, ft in cls["fields"]}


def decode(data: bytes) -> tuple:
    """(root type, value dict, bytes consumed, OBJT length) of a REFL blob; RDIF (a diff) is not decoded."""
    cs = chunks(data)
    name, classes = schema(cs)
    objt = next((c for t, c in cs if t == "OBJT"), None)
    if objt is None:
        raise ValueError("no OBJT chunk (a diff blob?)")
    r = _Reader(objt, classes)
    root = name(r.num("I"))
    return root, r.value(root), r.p, len(objt)


def flat(v, pre=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from flat(x, f"{pre}.{k}" if pre else k)
    else:
        yield pre, v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--all", action="store_true", help="every field, not only exposure / tone mapping / cinematic")
    a = ap.parse_args(argv)
    paths = [p for f in a.files for p in (sorted(glob.glob(f)) or [f])]
    for path in paths:
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            root, val, used, size = decode(data)
        except ValueError as e:
            print(f"{os.path.basename(path)}: {e}")
            continue
        fields = dict(flat(val))
        print(f"== {os.path.basename(path)}: {root}, {used} / {size} bytes decoded")
        for k, v in (fields.items() if a.all else ((k, fields.get(k)) for k in KEYS)):
            print(f"   {k} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
