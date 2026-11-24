"""Which Skyrim ground texture takes which biome ground-cover slot (2026-11-24, docs/re/ground-cover-density.md).

An overlay texture grows ground cover only as one of Starfield's per-mask placeholder textures: the anchor biome's
entry for that mask then gives the placeholder its ground (the mask's ANAM texture) and its cover (the mask's first
LNAM GCVR). Starfield.exe (FUN_1409e14f0, the BIOM LNAM / ANAM reader): an entry {mask, LTEX, GCVR} fills slot
`mask` (0..6; records older than form version 457 use 5 - mask); slot order (name table 0x144a57018) Base, Flow,
FlatOuter, FlatInner, Talus, Solid, Path; the placeholders are the LDefault00N<Slot> textures of Starfield.esm
(FUN_140794510 matches the name after 11 characters) and LDirtFootprints01 for Path (FUN_140794170). So at most
seven Skyrim textures per overlay can carry their grass this way.
"""
from typing import Dict

SLOT_NAMES = ("Base", "Flow", "FlatOuter", "FlatInner", "Talus", "Solid", "Path")
PLACEHOLDERS = {0: 0x00010861,    # LDefault006Base
                1: 0x00010860,    # LDefault005Flow
                2: 0x0001085F,    # LDefault004FlatOut
                3: 0x0001085E,    # LDefault003FlatIn
                4: 0x0001085D,    # LDefault002Talus
                5: 0x0001085C,    # LDefault001Solid
                6: 0x001235C2}    # LDirtFootprints01 (the Path slot's placeholder)

# The seven land textures covering most grassy ground of the staged Tamriel (owner's build, 73 x 73 cells, weighted by
# layer strength; underwater LCoastOceanFloor01 / LRiverMud01 / LRiverBottom01 left out: our river beds are dry).
DEFAULT_SLOT_MAP = ("LFieldGrass02=0,LPineForest02=1,LRocks01=2,LGrassSnow01=3,LFieldGrass01=4,LTundra01=5,"
                    "LFallForestGrass01NoFern=6")


def parse_slot_map(spec: str) -> Dict[str, int]:
    """'EDID=mask,...' -> {edid lower: mask}. ValueError on a bad mask or a mask used twice."""
    out: Dict[str, int] = {}
    used = set()
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"slot map wants EDID=mask, got {item!r}")
        edid, mask = item.split("=", 1)
        m = int(mask)
        if m not in PLACEHOLDERS:
            raise ValueError(f"mask {m} for {edid}: 0..6 only")
        if m in used:
            raise ValueError(f"mask {m} given twice")
        used.add(m)
        out[edid.strip().lower()] = m
    return out
