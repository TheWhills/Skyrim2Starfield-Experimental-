"""Writer for Havok tagfiles ("TAG0"), the counterpart of `hktagfile` (cloth payloads of BSClothExtraData).

The TYPE section (type names, layouts, hashes) is copied from a template tagfile of the same SDK, so every type the
new objects use must exist in the template. DATA and INDX are regenerated from Python values in the shape
`hktagfile.Tagfile.item_value` returns:

* record -> dict of field values; a pointer target carries "$class" (its full type name, e.g. a subclass)
* hkArray / fixed C array -> list; pointer -> the target dict (same Python object = same item) or None
* hkStringPtr / char* -> str or None; ints, floats, bools as such

Layout rules (verified 2026-10-27 by byte-identical round trips of Starfield cloth tagfiles, tests/test_hktagwrite.py):
* items in breadth-first order of discovery: item 1 is the root object; processing an item walks its values in
  field order and appends a new item for every non-empty array, not yet seen string (equal strings share one item)
  and not yet seen pointer target
* each item starts at the next multiple of its type's alignment (typedefs: 2, see _align); arrays, pointers and strings hold the item index
  (8 bytes; an array's size / capacity words stay 0); empty arrays and null pointers hold 0 and are not patched
* ITEM: 12 bytes (type | flags << 24, data offset, count), entry 0 all zero; flags 0x10 = one object (pointer
  target, also the root), 0x20 = array contents (strings included: char with the terminating NUL counted)
* PTCH: per field type, in order of first use, the DATA offsets of every non-null reference of that type
"""
import struct
from typing import Dict, List, Optional, Tuple

from .hktagfile import Tagfile, TagfileError, sections


def _section(tag: str, payload: bytes, leaf: bool) -> bytes:
    size = len(payload) + 8
    if size >= 1 << 30:
        raise TagfileError("section too large")
    return struct.pack(">I", size | (0x40000000 if leaf else 0)) + tag.encode("latin-1") + payload


class Writer:
    def __init__(self, template: bytes):
        self.tf = Tagfile(template)
        top = sections(template, 0, len(template))
        secs = {t: (s, e) for t, s, e in sections(template, top[0][1], top[0][2])}
        s, e = secs["TYPE"]
        self.type_section = template[s - 8:e]                      # header included, copied verbatim
        self.by_name = {}
        for t in self.tf.types[1:]:
            self.by_name.setdefault(self.tf.type_name(t.index), t.index)

    # -- type helpers -------------------------------------------------------------------------------------------------
    def type_index(self, name: str) -> int:
        try:
            return self.by_name[name]
        except KeyError:
            raise TagfileError(f"type {name!r} is not in the template") from None

    def _align(self, ti: int) -> int:
        """Item alignment: a type with its own layout uses its own alignment; a typedef (no size of its own, e.g.
        hkVector4, hkUint32, hkQsTransform) starts on any even offset, whatever its target's alignment (measured on
        the game's files: hkVector4 arrays at offsets = 2 mod 16, hkQsTransform / hkMatrix4 at 8 mod 16)."""
        t = self.tf.types[ti]
        if not t.size:
            return 2
        return (t.align & 0xFF) or 1

    # -- serialisation ------------------------------------------------------------------------------------------------
    def write(self, root: Dict, root_type: str = "hkRootLevelContainer") -> bytes:
        tf = self.tf
        self.data = bytearray()
        self.items: List[Tuple[int, int, int, int]] = [(0, 0, 0, 0)]     # (type, flags, offset, count)
        self.queue: List[Tuple[int, int, object]] = []                   # (item index, type, values)
        self.ptr_items: Dict[int, int] = {}                              # id(dict) -> item index
        self.str_items: Dict[str, int] = {}                              # equal strings share one item
        self.patches: Dict[int, List[int]] = {}
        self.keep = []                                                   # keep ids alive
        self._new_item(self.type_index(root_type), 0x10, [root])
        k = 0
        while k < len(self.queue):
            idx, ti, vals = self.queue[k]
            off = self.items[idx][2]
            es = tf.size_of(ti)
            for i, v in enumerate(vals):
                self._put(ti, off + i * es, v)
            k += 1
        sdk = tf.sdk.encode("latin-1")
        item_bytes = b"".join(struct.pack("<III", t | (f << 24), o, c) for t, f, o, c in self.items)
        ptch = b"".join(struct.pack("<II", ti, len(offs)) + struct.pack(f"<{len(offs)}I", *offs)
                        for ti, offs in self.patches.items())
        body = (_section("SDKV", sdk, True) + _section("DATA", bytes(self.data), True) + self.type_section
                + _section("INDX", _section("ITEM", item_bytes, True) + _section("PTCH", ptch, True), False))
        return _section("TAG0", body, False)

    def _new_item(self, ti: int, flags: int, vals: list) -> int:
        a = self._align(ti)
        while len(self.data) % a:
            self.data.append(0)
        off = len(self.data)
        self.data.extend(bytes(self.tf.size_of(ti) * len(vals)))
        self.items.append((ti, flags, off, len(vals)))
        idx = len(self.items) - 1
        self.queue.append((idx, ti, vals))
        return idx

    def _patch(self, ti: int, off: int, idx: int):
        struct.pack_into("<Q", self.data, off, idx)
        self.patches.setdefault(ti, []).append(off)

    def _put(self, ti: int, off: int, v):
        tf = self.tf
        rt = tf._resolved(ti)
        t = tf.types[rt]
        f = t.format
        kind = f & 0x1F
        if kind == 2:
            self.data[off] = 1 if v else 0
        elif kind == 4:
            width = {0x2000: 1, 0x4000: 2, 0x8000: 4, 0x10000: 8}.get(f & 0x1E000, tf.size_of(rt) or 4)
            self.data[off:off + width] = int(v).to_bytes(width, "little", signed=bool(f & 0x200))
        elif kind == 5:
            struct.pack_into("<e" if tf.size_of(rt) == 2 else "<f", self.data, off, v)
        elif kind == 3:
            if v is not None:
                idx = self.str_items.get(v)
                if idx is None:
                    s = v.encode("latin-1") + b"\0"
                    idx = self.str_items[v] = self._new_item(self.type_index("char"), 0x20, list(s))
                self._patch(ti, off, idx)
        elif kind == 6:
            if v is not None:
                idx = self.ptr_items.get(id(v))
                if idx is None:
                    cls = v.get("$class") if isinstance(v, dict) else None
                    target = self.type_index(cls) if cls else t.subtype
                    if not target:
                        raise TagfileError(f"pointer of type {tf.type_name(rt)} needs a $class")
                    idx = self._new_item(target, 0x10, [v])
                    self.ptr_items[id(v)] = idx
                    self.keep.append(v)
                self._patch(ti, off, idx)
        elif kind == 8:
            if f & 0x20:                                                 # fixed C array
                es = tf.size_of(t.subtype)
                n = f >> 8
                if len(v) != n:
                    raise TagfileError(f"{tf.type_name(rt)} needs {n} values, got {len(v)}")
                for i, x in enumerate(v):
                    self._put(t.subtype, off + i * es, x)
            elif v:
                idx = self._new_item(t.subtype, 0x20, list(v))
                self._patch(ti, off, idx)
        elif kind == 7:
            if not isinstance(v, dict):
                raise TagfileError(f"{tf.type_name(rt)} needs a dict, got {type(v).__name__}")
            for fl in tf.all_fields(rt):
                if tf.types[tf._resolved(fl.type)].format & 0x1F and fl.name in v:
                    self._put(fl.type, off + fl.offset, v[fl.name])
        # kind 0 (opaque, e.g. vtable slots): left zero


def write(template: bytes, root: Dict) -> bytes:
    """A tagfile holding `root` (an hkRootLevelContainer value) with the template's types."""
    return Writer(template).write(root)


def container(variants: List[Tuple[str, Dict]]) -> Dict:
    """hkRootLevelContainer value for [(class name, object)]; the variant name is left empty as in the game's
    files."""
    out = []
    for cls, obj in variants:
        obj.setdefault("$class", cls)
        out.append({"name": None, "className": cls, "variant": obj})
    return {"namedVariants": out}
