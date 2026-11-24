"""S2SGrass.ini for the S2SGrass SFSE plugin (2026-11-24, docs/re/ground-cover-density.md route B).

The plugin (native/combat/sfse/grass) gives every overlay palette entry whose ground texture is listed here that
ground cover, so each converted Skyrim texture grows its own Skyrim grass (no LDefault slot placeholders, no biome
override). Records are named by plugin and FormID inside it ("Starfield.esm:030137"); the load order is resolved in
the game.
"""
from typing import Dict, Iterable, List, Sequence, Tuple

INI_NAME = "S2SGrass.ini"
INI_DIR = ("SFSE", "Plugins")


def form_ref(fid: int, masters: Sequence[str], plugin: str) -> str:
    """'Plugin.esm:LLLLLL' for a FormID as written in `plugin` (high byte = master index, len(masters) = itself)."""
    i = fid >> 24
    if i > len(masters):
        raise ValueError(f"{fid:08X}: master index {i} but {plugin} has {len(masters)} masters")
    return f"{masters[i] if i < len(masters) else plugin}:{fid & 0xFFFFFF:06X}"


def hook_ini(covers: Iterable[Tuple[int, int]], masters: Sequence[str], plugin: str,
             names: Dict[int, str] = None, log_level: int = 1) -> str:
    """The INI text: covers = [(LTEX FormID, GCVR FormID)] as written in `plugin` (whose masters are `masters`);
    names: LTEX FormID -> Skyrim EditorID (the comment)."""
    names = names or {}
    lines: List[str] = [
        "; S2SGrass: Skyrim's own ground cover on every converted Skyrim ground texture. Written by",
        "; scripts/terrain/skyrim_grass_native.py --palette-hook; rebuilt with the grass mod.",
        "[Settings]",
        "bEnabled=1",
        "; 1: only textures without a ground cover of their own (the planet's slot placeholders keep theirs)",
        "bOnlyEmpty=1",
        "; 0 errors only, 1 one line per overlay palette, 2 every entry",
        f"iLogLevel={log_level}",
        "[Covers]",
        "; ground texture = ground cover ; Skyrim texture",
    ]
    for ltex, gcvr in sorted(covers):
        note = names.get(ltex, "")
        lines.append(f"{form_ref(ltex, masters, plugin)} = {form_ref(gcvr, masters, plugin)}"
                     + (f" ; {note}" if note else ""))
    return "\r\n".join(lines) + "\r\n"


def drop_underwater(slots: Dict[int, list], is_underwater) -> Tuple[Dict[int, list], List[int]]:
    """slots without underwater grasses; textures left with none are dropped (returned second)."""
    out, dropped = {}, []
    for k, gs in slots.items():
        keep = [g for g in gs if not is_underwater(g)]
        if keep:
            out[k] = keep
        else:
            dropped.append(k)
    return out, dropped
