"""Skyrim with mods over it, as the game loads them (2026-11-19, children from Realistic RS Children over RS Children
Overhaul: docs/npc/children-mods.md, decision 2026-11-17).

The converters read Skyrim.esm and Skyrim's archives. A mod changes both: its plugins override records (the last
plugin to name a record wins) and add new ones, and its archives and loose files override assets. LoadOrder reads
Skyrim.esm and the given mod folders in order (MO2-style: each folder holds the plugins, BSAs and loose files of one
mod, as in <ModOrganizer>/<game>/mods/<name>):

  plugins   Skyrim.esm, then the vanilla masters the mods name that exist in Data (Update, Dawnguard, HearthFires,
            Dragonborn, in the game's order), then each folder's plugins (.esm, then .esp / .esl, by name).
  FormIDs   one load-order space: the top byte is the plugin's index in `order` (Skyrim.esm 0, so a run without mods
            keeps today's ids). A plugin's own FormIDs are mapped through its master list (top byte = master index,
            past the masters = the plugin itself). A master that is not loaded (e.g. USSEP) still gets an index, so
            its FormIDs stay distinct; `missing` lists those.
  records   per FormID the last plugin's version wins; `origin` keeps the first plugin (FaceGen paths are by the
            plugin that defined the NPC: skyrimnpc.facegen_paths).
  assets    archives: Skyrim's (bsa.SkyrimArchives), then each mod's BSAs in mod order; loose files: the last mod's
            first, then Skyrim's Data. Case-insensitive lookup in mod folders (mods ship mixed-case paths).

FormIDs inside records are the plugin's own: `remap(plugin)` gives the mapping, and remap_npc / remap_head_part /
race_head_parts apply it to the fields the converters use.
"""
import os
import struct
from typing import Dict, Iterable, List, Optional, Tuple

from . import bsa, fo4land

VANILLA_MASTERS = ("Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm")
PLUGIN_EXTS = (".esm", ".esp", ".esl")


def _u32(d) -> int:
    return struct.unpack_from("<I", bytes(d), 0)[0]


def masters_of(path: str) -> List[str]:
    """A plugin's master files (MAST in its TES4), in order."""
    with fo4land.Plugin(path) as p:
        return [fo4land.zstring(bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0))
                if s == b"MAST"]


def find_ci(root: str, parts) -> str:
    """The file under root whose path matches parts ignoring case, or ''."""
    cur = root
    for part in parts:
        try:
            names = {n.lower(): n for n in os.listdir(cur)}
        except OSError:
            return ""
        hit = names.get(part.lower())
        if hit is None:
            return ""
        cur = os.path.join(cur, hit)
    return cur if os.path.isfile(cur) else ""


def folder_plugins(folder: str) -> List[str]:
    """A mod folder's plugins (top level): .esm first, then .esp / .esl, each by name."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    plugs = [n for n in names if n.lower().endswith(PLUGIN_EXTS) and os.path.isfile(os.path.join(folder, n))]
    return sorted(plugs, key=lambda n: (not n.lower().endswith(".esm"), n.lower()))


def mod_folders(mods_dir: str, names) -> List[str]:
    """Mod folder paths from names under mods_dir (MO2's mods folder) or paths, in the given order."""
    out = []
    for n in names or []:
        p = n if (os.path.isabs(n) or not mods_dir) else os.path.join(mods_dir, n)
        if not os.path.isdir(p):
            raise SystemExit(f"Skyrim mod folder not found: {p}")
        out.append(p)
    return out


class LoadOrderArchives(bsa.SkyrimArchives):
    """Skyrim's archives and Data folder with mod folders over them (later wins): the mods' BSAs after Skyrim's, the
    mods' loose files over everything."""

    def __init__(self, data_dir: str, mods=()):
        super().__init__(data_dir)
        self.mods = [os.path.abspath(m) for m in mods]
        for m in self.mods:
            for n in sorted(os.listdir(m), key=str.lower):
                if n.lower().endswith(".bsa") and os.path.isfile(os.path.join(m, n)):
                    self.archives.append(bsa.Bsa(os.path.join(m, n)))

    def _loose(self, name):
        parts = bsa.norm(name).split("\\")
        for root in reversed(self.mods):
            hit = find_ci(root, parts)
            if hit:
                with open(hit, "rb") as fh:
                    return fh.read()
        return super()._loose(name)

    def source_of(self, name: str) -> str:
        """Where a file comes from: a mod folder's name, a BSA's file name, 'Data' (loose) or ''."""
        n = bsa.norm(name)
        for root in reversed(self.mods):
            if find_ci(root, n.split("\\")):
                return os.path.basename(root)
        if super()._loose(n) is not None:
            return "Data"
        for a in reversed(self.archives):
            if a.find(n) is not None:
                return os.path.basename(getattr(a, "path", "") or "?")
        return ""


class LoadOrder:
    def __init__(self, skyrim_data: str, mods=()):
        self.data = skyrim_data
        self.mods = [os.path.abspath(m) for m in mods]
        mod_plugins = [(name, os.path.join(m, name)) for m in self.mods for name in folder_plugins(m)]
        wanted, cased = set(), {}
        for _n, p in mod_plugins:
            for x in masters_of(p):
                wanted.add(x.lower())
                cased.setdefault(x.lower(), x)
        self.paths: Dict[str, str] = {}
        order = ["Skyrim.esm"]
        self.paths["skyrim.esm"] = os.path.join(skyrim_data, "Skyrim.esm")
        for v in VANILLA_MASTERS[1:]:
            p = os.path.join(skyrim_data, v)
            if v.lower() in wanted and os.path.isfile(p):
                order.append(v)
                self.paths[v.lower()] = p
        for n, p in mod_plugins:
            if n.lower() in self.paths:
                raise ValueError(f"{n} is in two mod folders")
            order.append(n)
            self.paths[n.lower()] = p
        self.missing = sorted({cased[m] for m in wanted if m not in self.paths}, key=str.lower)
        self.order = order + [m for m in self.missing]          # unloaded masters: an index each, no records
        self.index = {n.lower(): i for i, n in enumerate(self.order)}
        self._masters: Dict[str, List[str]] = {}
        self.archives = LoadOrderArchives(skyrim_data, self.mods) if self.mods else bsa.SkyrimArchives(skyrim_data)

    def loaded(self) -> List[str]:
        return [n for n in self.order if n.lower() in self.paths]

    def remap(self, plugin: str):
        """FormID in `plugin` -> load-order FormID."""
        key = plugin.lower()
        if key not in self._masters:
            self._masters[key] = masters_of(self.paths[key]) if key != "skyrim.esm" else []
        masters = [self.index[m.lower()] for m in self._masters[key]]
        own = self.index[key]

        def rm(fid: Optional[int]) -> Optional[int]:
            if fid is None:
                return None
            hi = fid >> 24
            idx = masters[hi] if hi < len(masters) else own
            return (idx << 24) | (fid & 0xFFFFFF)
        return rm

    def records(self, types: Iterable[bytes]) -> Dict[int, Tuple[bytes, bytes, list, str]]:
        """{load-order FormID: (type, header, subrecords, plugin of the winning version)}; FormIDs inside the
        subrecords are still that plugin's own (remap(plugin))."""
        from . import sfplugin
        types = list(types)
        out: Dict[int, Tuple[bytes, bytes, list, str]] = {}
        for name in self.loaded():
            rm = self.remap(name)
            for typ, hdr, subs, fid in sfplugin.records(self.paths[name.lower()], types):
                out[rm(fid)] = (typ, hdr, subs, name)
        return out

    def flat_records(self, types: Iterable[bytes]) -> List[Tuple[bytes, bytes, list, int]]:
        """[(type, header, subrecords, load-order FormID)] of the winning versions, FormID fields rewritten
        (rewrite): sfplugin.records' shape."""
        out = []
        for fid, (typ, hdr, subs, plugin) in self.records(types).items():
            out.append((typ, hdr, rewrite(typ, subs, self.remap(plugin)), fid))
        return out

    def facegen_paths(self, fid: int) -> Dict[str, str]:
        from . import skyrimnpc
        plugin, local = self.origin(fid)
        return skyrimnpc.facegen_paths(plugin, local)

    def origin(self, fid: int) -> Tuple[str, int]:
        """(plugin that defines the record, its FormID there without the master byte): what FaceGen paths use."""
        return self.order[fid >> 24], fid & 0xFFFFFF

    def facegen_mesh(self, fid: int) -> str:
        from . import skyrimnpc
        plugin, local = self.origin(fid)
        return skyrimnpc.facegen_paths(plugin, local)["mesh"]


# FormID fields inside the records the converters read (UESP / xEdit record layouts; a subrecord is rewritten only at
# its expected size, so a same-named field of another layout is left alone). "fid": the first 4 bytes; "fids": the
# whole subrecord is an array of FormIDs; "fid@N": 4 bytes at offset N.
FID_FIELDS = {
    b"NPC_": {b"RNAM": "fid", b"TPLT": "fid", b"WNAM": "fid", b"VTCK": "fid", b"CNAM": "fid", b"HCLF": "fid",
              b"DOFT": "fid", b"SOFT": "fid", b"FTST": "fid", b"PKID": "fid", b"PNAM": "fid", b"ZNAM": "fid",
              b"INAM": "fid", b"SPLO": "fid", b"ECOR": "fid", b"GNAM": "fid", b"DPLT": "fid", b"OCOR": "fid",
              b"CRIF": "fid", b"ANAM": "fid", b"SNAM": "fid", b"PRKR": "fid", b"CNTO": "fid", b"KWDA": "fids",
              b"ATKR": "fid", b"SPOR": "fid", b"ACBS": None},
    b"HDPT": {b"HNAM": "fid", b"TNAM": "fid", b"RNAM": "fid", b"CNAM": "fid"},
    b"RACE": {b"HEAD": "fid", b"WNAM": "fid", b"RNAM": "fid", b"NAM8": "fid", b"VTCK": "fids", b"HCLF": "fids",
              b"ATKR": "fid", b"SPLO": "fid", b"KWDA": "fids", b"FTSM": "fids", b"FTSF": "fids",
              b"DFTM": "fid", b"DFTF": "fid", b"RPRM": "fid", b"RPRF": "fid", b"AHCM": "fid", b"AHCF": "fid",
              b"TINC": "fid", b"TIRS": "fid", b"NAM4": "fid", b"NAM5": "fid", b"NAM7": "fid", b"ONAM": "fid",
              b"LNAM": "fid", b"QNAM": "fid", b"UNWP": "fid", b"WKMV": "fid", b"RNMV": "fid", b"SWMV": "fid",
              b"FLMV": "fid", b"SNMV": "fid", b"SPMV": "fid", b"GNAM": "fid"},
    b"OTFT": {b"INAM": "fids"},
    b"ARMO": {b"MODL": "fid", b"RNAM": "fid", b"KWDA": "fids", b"EITM": "fid", b"ETYP": "fid", b"BIDS": "fid",
              b"BAMT": "fid", b"YNAM": "fid", b"ZNAM": "fid", b"TNAM": "fid", b"BMCT": None},
    b"ARMA": {b"RNAM": "fid", b"MODL": "fid", b"NAM0": "fid", b"NAM1": "fid", b"NAM2": "fid", b"NAM3": "fid",
              b"SNDD": "fid", b"ONAM": "fid"},
    b"TXST": {},
    b"CLFM": {},
}


def rewrite(typ: bytes, subs, rm) -> list:
    """subs with the FormID fields of FID_FIELDS[typ] mapped by rm (other fields, and fields of unexpected size, as
    they are)."""
    table = FID_FIELDS.get(typ, {})
    out = []
    for sig, d in subs:
        kind = table.get(sig)
        d = bytes(d)
        if kind == "fid" and len(d) >= 4 and (sig != b"MODL" or len(d) == 4):
            d = struct.pack("<I", rm(_u32(d))) + d[4:]
        elif kind == "fids" and len(d) % 4 == 0 and d:
            d = b"".join(struct.pack("<I", rm(v)) for v in struct.unpack(f"<{len(d) // 4}I", d))
        out.append((sig, d))
    return out


def records(source, types) -> List[Tuple[bytes, bytes, list, int]]:
    """sfplugin.records' shape from a plugin path or a LoadOrder (its winning versions, FormIDs in load-order space
    inside the FID_FIELDS too): lets the converters take either."""
    from . import sfplugin
    if isinstance(source, LoadOrder):
        return source.flat_records(types)
    return sfplugin.records(source, types)


NPC_FID_FIELDS = ("race", "template", "skin", "voice", "class", "hair_color", "outfit", "sleep_outfit", "head_texture")


def remap_npc(n: Dict, rm) -> Dict:
    """skyrimnpc.parse_npc's dict with its FormIDs in load-order space (form_id is left to the caller)."""
    out = dict(n)
    for k in NPC_FID_FIELDS:
        if out.get(k) is not None:
            out[k] = rm(out[k])
    out["head_parts"] = [rm(f) for f in n.get("head_parts", [])]
    out["packages"] = [rm(f) for f in n.get("packages", [])]
    out["factions"] = [(rm(f), r) for f, r in n.get("factions", [])]
    return out


def remap_head_part(h: Dict, rm) -> Dict:
    out = dict(h)
    out["extra_parts"] = [rm(f) for f in h.get("extra_parts", [])]
    for k in ("texture_set", "races"):
        if out.get(k) is not None:
            out[k] = rm(out[k])
    return out


def race_head_parts(subs, rm=lambda f: f) -> Dict[bool, List[int]]:
    """{female: [HDPT FormIDs]} of a Skyrim RACE's head data: HEAD entries after NAM0, in the MNAM (male) / FNAM
    (female) sections."""
    out: Dict[bool, List[int]] = {False: [], True: []}
    head, sex = False, None
    for s, d in subs:
        if s == b"NAM0":
            head = True
        elif s == b"MNAM" and len(d) == 0:
            sex = False
        elif s == b"FNAM" and len(d) == 0:
            sex = True
        elif head and sex is not None and s == b"HEAD" and len(d) >= 4:
            out[sex].append(rm(_u32(d)))
    return out
