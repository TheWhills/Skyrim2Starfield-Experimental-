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
        self.spans, self.path = {}, []                    # field path -> (type, start, end) of every leaf value

    def num(self, fmt):
        v = struct.unpack_from("<" + fmt, self.d, self.p)[0]
        self.p += struct.calcsize("<" + fmt)
        return v

    def value(self, t):
        start, key = self.p, ".".join(self.path)
        if t in NUM:
            v = self.num(NUM[t])
            self.spans[key] = (t, start, self.p)
            return bool(v) if t == "Bool" else v
        if t in ("String", "Enum"):
            n = self.num("H")
            s = self.d[self.p:self.p + n]
            self.p += n
            self.spans[key] = (t, start, self.p)
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
        out = {}
        for n, ft in cls["fields"]:
            self.path.append(n)
            out[n] = self.value(ft)
            self.path.pop()
        return out


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


def _encode(t, v) -> bytes:
    if t in NUM:
        return struct.pack("<" + NUM[t], int(v) if t != "Float" and t != "Double" else v)
    raw = str(v).encode("latin1") + b"\0"
    return struct.pack("<H", len(raw)) + raw


def patch(data: bytes, changes: dict) -> bytes:
    """The blob with leaf fields replaced: {"Settings.Exposure.CameraExposureMode": "EXPOSURE_MODE_AUTO",
    "Settings.Exposure.AutoExposure.ExposureMin.Value": 3.0, ...} (paths as flat() gives them, without the root).
    Enum / string values may change length: the OBJT chunk's size follows. Unknown paths raise KeyError."""
    cs = chunks(data)
    name, classes = schema(cs)
    user = {k[5:]: v for k, v in changes.items() if k.startswith("USER:")}
    lists = {k[5:]: v for k, v in changes.items() if k.startswith("LIST:")}
    changes = {k: v for k, v in changes.items() if not k.startswith(("USER:", "LIST:"))}
    for path, v in lists.items():
        # "LIST:BSFloatCurve::Control.Value": that field in every entry of every LIST chunk of that element type
        # (LIST = u32 element type, u32 count, then the entries' fields in order; verified on DefaultImageSpace's
        # compensation curve: BSFloatCurve::Control, 2 entries of Input, Value)
        cls, field = path.rsplit(".", 1)
        hit = False
        for i, (t, c) in enumerate(cs):
            if t != "LIST" or name(struct.unpack_from("<I", c, 0)[0]) != cls:
                continue
            count = struct.unpack_from("<I", c, 4)[0]
            lr = _Reader(c, classes)
            lr.p = 8
            spans = []
            for _k in range(count):
                for n, ft in classes[cls]["fields"]:
                    lr.path = [n]
                    lr.value(ft)
                    if n == field:
                        spans.append(lr.spans[field])
            body = c
            for t2, a, b in sorted(spans, key=lambda x: -x[1]):
                body = body[:a] + _encode(t2, v) + body[b:]
            cs[i] = ("LIST", body)
            hit = hit or bool(spans)
        if not hit:
            raise KeyError("LIST:" + path)
    if user:
        # "USER:BSFloatCurve.DefaultValue": a user-serialised object (its own chunk: u32 type, u32 type, then its
        # fields in order, maps elsewhere); the first USER chunk of that class
        for i, (t, c) in enumerate(cs):
            if t != "USER":
                continue
            cls = name(struct.unpack_from("<I", c, 0)[0])
            mine = {k.split(".", 1)[1]: v for k, v in user.items() if k.split(".", 1)[0] == cls}
            if not mine:
                continue
            ur = _Reader(c, classes)
            ur.p = 8
            for n, ft in classes[cls]["fields"]:
                ur.path = [n]
                ur.value(ft)
            body = c
            for path, v in sorted(mine.items(), key=lambda kv: -ur.spans[kv[0]][1]):
                if path not in ur.spans:
                    raise KeyError("USER:" + cls + "." + path)
                t2, a, b = ur.spans[path]
                body = body[:a] + _encode(t2, v) + body[b:]
            cs[i] = ("USER", body)
            user = {k: v for k, v in user.items() if k.split(".", 1)[0] != cls}
        if user:
            raise KeyError(next(iter(user)))
    idx = next(i for i, (t, _c) in enumerate(cs) if t == "OBJT")
    objt = cs[idx][1]
    r = _Reader(objt, classes)
    root = name(r.num("I"))
    r.value(root)
    edits = []
    for path, v in changes.items():
        if path not in r.spans:
            raise KeyError(path)
        t, a, b = r.spans[path]
        edits.append((a, b, _encode(t, v)))
    for a, b, new in sorted(edits, reverse=True):
        objt = objt[:a] + new + objt[b:]
    cs[idx] = ("OBJT", objt)
    out = data[:16]
    for t, c in cs:
        out += t.encode("latin1") + struct.pack("<I", len(c)) + c
    return out


def read_imgs(esm: str, form_id: int) -> bytes:
    """The REFL blob of one IMGS record of a Starfield plugin."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
    from fo4sf import sfplugin
    for _t, _h, subs, fid in sfplugin.records(esm, [b"IMGS"]):
        if fid & 0xFFFFFF == form_id & 0xFFFFFF:
            for sig, d in subs:
                if sig == b"REFL":
                    return d
    raise KeyError(f"IMGS {form_id:06X} with a REFL not found in {esm}")


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
