"""AI packages (PACK) of Skyrim and Starfield, read side: both games use the same layout (xEdit wbDefinitionsTES5 /
wbDefinitionsSF1, checked 2026-11-08): PKDT (general flags u32, type u8 18 package / 19 template, interrupt override,
preferred speed, interrupt flags), PSDT schedule (month, day of week, date, hour, minute: s8; 3 unused; duration u32,
minutes), PKCU (data input count, package template FormID, version), then the data inputs: ANAM type name and its value
(CNAM bool / int / float, PLDT location, PTDA target), UNAM index + BNAM name per input, XNAM package group, and in a
template the procedure tree (ANAM branch type, PNAM procedure type, PKC2 input indexes). Differences: Skyrim's PLDT
radius is an int, Starfield's a float followed by a collection index; Starfield adds FLAV (anim flavour keyword).

A package names a template and fills the template's inputs (matched by UNAM index), so converting a Skyrim package
means: same schedule and flags, the Starfield template of the same kind, and its inputs with references / cells / objects
moved to our records (docs/npc/schedules.md).
"""
import struct
from typing import Dict, List, Optional

from . import fo4land

PACKAGE, TEMPLATE = 18, 19
LOCATION_TYPES = ["Near reference", "In cell", "Near package start location", "Near editor location", "Object ID",
                  "Object type", "Near linked reference", "At package location", "Alias (reference)",
                  "Alias (location)", "Interrupt data", "Package data target", "Unknown 12", "Unknown 13",
                  "Ref collection alias", "Unknown 15", "Keyword"]
TARGET_TYPES = ["Specific reference", "Object ID", "Object type", "Linked reference", "Ref alias", "Interrupt data",
                "Self", "Keyword", "Ref collection alias", "Scene primary actor"]
FORM_LOCATIONS = {0, 1, 4, 6, 16}       # location value is a FormID
FORM_TARGETS = {0, 1, 3, 7}             # target value is a FormID


def schedule(d: bytes) -> Dict:
    month, dow, date, hour, minute = struct.unpack_from("<5b", d)
    duration = struct.unpack_from("<I", d, 8)[0] if len(d) >= 12 else 0
    return {"month": month, "day_of_week": dow, "date": date, "hour": hour, "minute": minute,
            "duration_min": duration}


def location(d: bytes, starfield: bool) -> Dict:
    typ, val = struct.unpack_from("<iI", d)
    out = {"type": typ, "type_name": LOCATION_TYPES[typ] if 0 <= typ < len(LOCATION_TYPES) else "?",
           "value": val, "is_form": typ in FORM_LOCATIONS}
    if len(d) >= 12:
        out["radius"] = struct.unpack_from("<f" if starfield else "<i", d, 8)[0]
    if starfield and len(d) >= 16:
        out["collection_index"] = struct.unpack_from("<I", d, 12)[0]
    return out


def target(d: bytes) -> Dict:
    typ, val = struct.unpack_from("<iI", d)
    out = {"type": typ, "type_name": TARGET_TYPES[typ] if 0 <= typ < len(TARGET_TYPES) else "?", "value": val,
           "is_form": typ in FORM_TARGETS}
    if len(d) >= 12:
        out["count"] = struct.unpack_from("<i", d, 8)[0]
    return out


def parse_pack(subs, starfield: bool = False) -> Dict:
    """One PACK record's fields (subs = [(sig, bytes)] in order)."""
    p = {"edid": None, "flags": None, "type": None, "interrupt_override": None, "speed": None,
         "interrupt_flags": None, "schedule": None, "template": None, "input_count": None, "inputs": [],
         "input_names": [], "group": None, "procedures": [], "conditions": 0, "combat_style": None,
         "owner_quest": None, "idles": [], "has_script": False}
    section = None                  # "values" (after PKCU), "tree", "names"
    cur = None
    for sig, d in subs:
        if sig == b"EDID":
            p["edid"] = d.rstrip(b"\0").decode("utf-8", "replace")
        elif sig == b"VMAD":
            p["has_script"] = True
        elif sig == b"PKDT" and len(d) >= 12:
            p["flags"], p["type"], p["interrupt_override"], p["speed"] = struct.unpack_from("<IBBB", d)
            p["interrupt_flags"] = struct.unpack_from("<H", d, 8)[0]
        elif sig == b"PSDT" and len(d) >= 8:
            p["schedule"] = schedule(d)
        elif sig == b"CTDA" and section is None:
            p["conditions"] += 1
        elif sig == b"CNAM" and section is None and len(d) == 4:
            p["combat_style"] = struct.unpack_from("<I", d)[0]
        elif sig == b"QNAM" and len(d) == 4:
            p["owner_quest"] = struct.unpack_from("<I", d)[0]
        elif sig == b"PKCU" and len(d) >= 8:
            p["input_count"], p["template"] = struct.unpack_from("<II", d)
            section = "values"
        elif sig == b"ANAM" and section == "values":
            cur = {"type": d.rstrip(b"\0").decode("utf-8", "replace"), "value": None}
            p["inputs"].append(cur)
        elif sig == b"CNAM" and section == "values" and cur is not None:
            t = cur["type"].lower()
            if t == "bool" and len(d) >= 1:
                cur["value"] = bool(d[0])
            elif t in ("int", "integer") and len(d) >= 4:
                cur["value"] = struct.unpack_from("<i", d)[0]
            elif t == "float" and len(d) >= 4:
                cur["value"] = struct.unpack_from("<f", d)[0]
            else:
                cur["value"] = d.hex()
        elif sig == b"PLDT" and section == "values" and cur is not None and len(d) >= 8:
            cur["value"] = location(d, starfield)
        elif sig == b"PTDA" and section == "values" and cur is not None and len(d) >= 8:
            cur["value"] = target(d)
        elif sig == b"STSC" and section == "values" and cur is not None and len(d) == 4:
            cur["value"] = {"scene": struct.unpack_from("<I", d)[0]}
        elif sig == b"UNAM":
            if section == "values":
                section = "names"
            p["input_names"].append({"index": struct.unpack_from("<b", d)[0], "name": None})
        elif sig == b"BNAM" and p["input_names"]:
            p["input_names"][-1]["name"] = d.rstrip(b"\0").decode("utf-8", "replace")
        elif sig == b"XNAM" and len(d) >= 1:
            p["group"] = d[0]
            section = "tree"
        elif sig == b"ANAM" and section == "tree":
            p["procedures"].append({"branch": d.rstrip(b"\0").decode("utf-8", "replace"), "procedure": None,
                                    "inputs": []})
        elif sig == b"PNAM" and section == "tree" and p["procedures"] and len(d) > 4:
            p["procedures"][-1]["procedure"] = d.rstrip(b"\0").decode("utf-8", "replace")
        elif sig == b"PKC2" and section == "tree" and p["procedures"] and len(d) >= 1:
            p["procedures"][-1]["inputs"].append(d[0])          # the data inputs (UNAM index) this branch uses
        elif sig == b"INAM" and len(d) == 4:
            v = struct.unpack_from("<I", d)[0]
            if v:
                p["idles"].append(v)
    return p


class Index:
    """Every record of a plugin: FormID -> (type, file offset, record flags), with the cell each placed reference is in
    (interior cells: the CELL whose children group holds it; exterior: its CELL too)."""

    def __init__(self, path: str, types: Optional[set] = None):
        self.path = path
        self.p = fo4land.Plugin(path)
        self.p.__enter__()
        self.records: Dict[int, tuple] = {}
        self.cell_of: Dict[int, int] = {}
        self.by_type: Dict[bytes, List[int]] = {}
        stack = [(self.p.body, len(self.p.buf), None)]
        while stack:
            start, end, cell = stack.pop()
            for it in fo4land.iter_items(self.p.buf, start, end):
                if it[0] == "GRUP":
                    _g, off, gend, label, gtype = it
                    lab = struct.unpack("<I", label)[0]
                    stack.append((off + 24, gend, lab if gtype == 6 else (cell if gtype in (8, 9, 10) else None)))
                    continue
                typ, off, flags, fid = it
                self.records[fid] = (typ, off, flags)
                self.by_type.setdefault(typ, []).append(fid)
                if typ != b"CELL" and cell is not None:
                    self.cell_of[fid] = cell
        self._edid: Dict[int, Optional[str]] = {}

    def close(self):
        self.p.__exit__(None, None, None)

    def subs(self, fid: int):
        rec = self.records.get(fid)
        if rec is None:
            return []
        return [(s, bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(self.p.buf, rec[1]))]

    def edid(self, fid: int) -> Optional[str]:
        if fid not in self._edid:
            self._edid[fid] = next((d.rstrip(b"\0").decode("utf-8", "replace") for s, d in self.subs(fid)
                                    if s == b"EDID"), None)
        return self._edid[fid]

    def kind(self, fid: int) -> Optional[str]:
        rec = self.records.get(fid)
        return rec[0].decode() if rec else None

    def find_edid(self, typ: bytes, edid: str) -> Optional[int]:
        want = edid.lower()
        for fid in self.by_type.get(typ, []):
            e = self.edid(fid)
            if e and e.lower() == want:
                return fid
        return None

    def name_of(self, fid: int) -> Dict:
        """{form, type, edid, base (for a placed reference: its base form's type and EditorID), cell}"""
        out = {"form": f"{fid:08X}", "type": self.kind(fid), "edid": self.edid(fid)}
        if out["type"] in ("REFR", "ACHR"):
            base = next((struct.unpack_from("<I", d)[0] for s, d in self.subs(fid) if s == b"NAME" and len(d) == 4),
                        None)
            if base is not None:
                out["base"] = {"form": f"{base:08X}", "type": self.kind(base), "edid": self.edid(base)}
            c = self.cell_of.get(fid)
            if c is not None:
                out["cell"] = {"form": f"{c:08X}", "edid": self.edid(c)}
        return out
