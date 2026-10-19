"""Starfield RACE subgraph data: which graph and which animation folders an actor uses, by actor and target (weapon)
keywords. Read and written as subrecord lists (fo4land.iter_subrecords pairs).

Verified 2026-10-19 on Alternate Recoil Animations (Nexus 16838), whose plugin carries a full HumanRace copy with
400 entries: an entry is SAKD (actor keyword FormID, repeated), STKD (target keyword FormID, repeated), SGNM (graph
path, e.g. AnimTextData\\Tables\\Graphs\\1stPerson_Gun.agx), SAPT (animation folder, repeated, MOST SPECIFIC FIRST:
the mod puts actors\\human\\_1stperson\\animations\\_AlternateRecoilAnimations\\Rifle\\Medium\\Rank0 before the
vanilla gun\\gripcompact\\grendel, gun\\gripcompact, gun\\common, common), SRAF (4 bytes, 01 00 01 00 in every entry
seen). STKD sits before SGNM in some entries and after the SAPT list in others (350 / 50 of 400); SRAF ends each
entry. The race also names the root graph (NAM6, Human_Root.agx), rig (NAM5), skeleton (ANAM) and default folder
(DNAM actors\\human\\animations\\common) per sex.
So a new weapon animation set = a keyword on the WEAP + an entry with that keyword in STKD, the graph, and its own
folder first in SAPT (supported: the mechanism; unverified: what SRAF's bits mean).
"""
import struct
from typing import Dict, List, Tuple

FIELDS = (b"SAKD", b"STKD", b"SGNM", b"SAPT", b"SRAF")


def parse(subs: List[Tuple[bytes, bytes]]) -> List[Dict]:
    """Entries from a RACE's subrecords: [{"actor_keywords", "target_keywords", "graph", "paths", "flags"}]."""
    entries, cur = [], None
    for sig, d in subs:
        sig = sig if isinstance(sig, bytes) else sig.encode("latin-1")
        if sig not in FIELDS:
            continue
        if cur is None:
            cur = {"actor_keywords": [], "target_keywords": [], "graph": None, "paths": [], "flags": None}
        d = bytes(d)
        if sig == b"SAKD":
            cur["actor_keywords"].append(struct.unpack("<I", d[:4])[0])
        elif sig == b"STKD":
            cur["target_keywords"].append(struct.unpack("<I", d[:4])[0])
        elif sig == b"SGNM":
            cur["graph"] = d.rstrip(b"\0").decode("latin-1")
        elif sig == b"SAPT":
            cur["paths"].append(d.rstrip(b"\0").decode("latin-1"))
        elif sig == b"SRAF":
            cur["flags"] = d.hex(" ")
            entries.append(cur)
            cur = None
    if cur is not None:
        entries.append(cur)
    return entries


def build(entry: Dict) -> List[Tuple[bytes, bytes]]:
    """Subrecords for one entry, in the majority order seen (SAKD, SGNM, SAPT..., STKD, SRAF)."""
    out = [(b"SAKD", struct.pack("<I", k)) for k in entry.get("actor_keywords", [])]
    out.append((b"SGNM", entry["graph"].encode("latin-1") + b"\0"))
    out += [(b"SAPT", p.encode("latin-1") + b"\0") for p in entry["paths"]]
    out += [(b"STKD", struct.pack("<I", k)) for k in entry.get("target_keywords", [])]
    out.append((b"SRAF", bytes.fromhex((entry.get("flags") or "01 00 01 00").replace(" ", ""))))
    return out


def summary(entries: List[Dict], keyword_names: Dict[int, str] = None) -> Dict:
    names = keyword_names or {}
    graphs = {}
    for e in entries:
        graphs[e["graph"]] = graphs.get(e["graph"], 0) + 1

    def kw(ids):
        return [names.get(i, f"{i:08X}") for i in ids]
    return {"entries": len(entries), "graphs": graphs,
            "examples": [{"actor": kw(e["actor_keywords"]), "target": kw(e["target_keywords"]), "graph": e["graph"],
                          "paths": e["paths"]} for e in entries[:12]]}
