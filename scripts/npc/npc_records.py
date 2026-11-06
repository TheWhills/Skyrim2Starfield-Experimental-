"""Pieces of a real NPC conversion (owner 2026-11-05: "getting Ralof and Ysolda in with their faces and generic
greetings", "use these hairs for conversion", "hair colour matched up too"), used by face_fit.py --hairs-plugin:

* the converted looks-menu hairs (S2SSkyrimHairs.esm, scripts/npc/skyrim_hairs.py) as the NPC's hair / beard, by the
  Skyrim head part's EditorID (that plugin names them 'S2S_<Skyrim EditorID>'), with that plugin as a master;
* the NPC's Skyrim name from Skyrim's string tables (Skyrim.esm is localized: FULL holds a string id);
* the Starfield hair colour name (HCOL / FHCL: the game picks colours by name) closest to the NPC's Skyrim hair
  colour: by RGB when a palette is known (hair_color_probe.py's hair_colors.json, {name: [r, g, b]}), else by the
  colour words in both games' names (Skyrim's CLFM EditorIDs say 'Blonde', 'Brown', 'Red' ...), else by lightness.
"""
import os
import re
import struct
from typing import Dict, Iterable, List, Optional, Tuple

from fo4sf import fo4land, sfplugin

HAIR, FACIAL_HAIR = 3, 4


def plugin_masters(path: str) -> List[str]:
    """The MAST names in a plugin's TES4 header, in order."""
    with open(path, "rb") as fh:
        head = fh.read(24)
        typ, size = struct.unpack_from("<4sI", head, 0)
        if typ != b"TES4":
            raise ValueError(f"{path}: not a plugin")
        body = fh.read(size)
    return [fo4land.zstring(d) for s, d in fo4land.iter_subrecords(body) if s == b"MAST"]


def hairs_index(path: str) -> Dict[str, int]:
    """{Skyrim head part EditorID (lower case): FormID as stored in the plugin} of a S2SSkyrimHairs.esm: its head
    parts 'S2S_<Skyrim EditorID>' (copies with a variant suffix, '_strands...', are left out)."""
    out = {}
    for _t, _h, subs, fid in sfplugin.records(path, [b"HDPT"]):
        e = sfplugin.edid(subs)
        if e.startswith("S2S_"):
            key = e[4:]
            variant = re.search(r"_(strands\w*|depth|notrans|rough|diag\w*)$", key, re.I)
            if not variant:
                out.setdefault(key.lower(), fid)
    return out


def with_parts(subs, sf_hdpt: Dict[int, tuple], new: Dict[int, int], drop: Iterable[int] = (),
               part_type=None) -> list:
    """NPC subrecords: head parts of each kind in `new` ({kind: FormID}) replaced or added, every head part of a kind
    in `drop` removed (a template's beard on an NPC Skyrim gives none). FormIDs not in sf_hdpt (our plugins') are
    kept."""
    drop = set(drop) - set(new)
    out, placed, at = [], set(), None
    for s, d in subs:
        if s == b"PNAM" and len(d) >= 4:
            at = len(out) + 1
            r = sf_hdpt.get(struct.unpack_from("<I", bytes(d), 0)[0])
            k = part_type(r[2]) if (r is not None and part_type) else None
            if k in drop:
                continue
            if k in new:
                if k not in placed:
                    out.append((s, struct.pack("<I", new[k])))
                    placed.add(k)
                continue
        out.append((s, d))
    rest = [(b"PNAM", struct.pack("<I", new[k])) for k in new if k not in placed]
    if rest:
        at = at if at is not None else next((i + 1 for i, (s, _d) in enumerate(out) if s == b"RNAM"), len(out))
        out[at:at] = rest
    return out


def read_strings(raw: bytes) -> Dict[int, str]:
    """A Skyrim .STRINGS table: u32 count, u32 data size, count x (id, offset), then zero-terminated strings."""
    if not raw or len(raw) < 8:
        return {}
    count, size = struct.unpack_from("<II", raw, 0)
    base = 8 + 8 * count
    out = {}
    for i in range(count):
        sid, off = struct.unpack_from("<II", raw, 8 + 8 * i)
        p = base + off
        if p >= len(raw):
            continue
        end = raw.find(b"\0", p)
        out[sid] = raw[p:end if end >= 0 else len(raw)].decode("utf-8", "replace")
    return out


def skyrim_names(sky, language: str = "english") -> Dict[int, str]:
    """Skyrim.esm's FULL strings (Strings\\Skyrim_<language>.STRINGS, loose or in the archives); {} when missing."""
    rel = f"strings\\skyrim_{language}.strings"
    raw = sky._read(rel) if hasattr(sky, "_read") else None
    return read_strings(raw) if raw else {}


def npc_name(npc: Dict, strings: Dict[int, str]) -> str:
    return npc.get("full_name") or strings.get(npc.get("full_name_id") or -1) or npc["edid"]


# colour words, each with the words that mean the same
COLOR_WORDS = {
    "blonde": ("blond", "blonde", "golden", "gold", "honey", "flax", "straw", "sandy"),
    "brown": ("brown", "brunette", "chestnut", "chocolate", "umber", "hazel", "mousy", "mousey"),
    "red": ("red", "auburn", "ginger", "copper", "strawberry"),
    "black": ("black", "raven", "ebony", "jet"),
    "grey": ("grey", "gray", "silver", "ash", "white", "platinum", "salt"),
    "dark": ("dark", "deep"),
    "light": ("light", "pale", "bright"),
}


def color_words(name: str) -> set:
    toks = {t.lower() for t in re.findall(r"[A-Za-z]+?(?=[A-Z0-9_ \-]|$)|[a-z]+", name.replace("_", " "))}
    toks |= {t.lower() for t in re.split(r"[^A-Za-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", name)) if t}
    out = set()
    for key, words in COLOR_WORDS.items():
        if toks & set(words):
            out.add(key)
    return out


def lightness(rgb) -> float:
    r, g, b = (float(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# Starfield's hair colour names (the owner's probe 2026-11-05: 22 names on Starfield.esm's NPCs; no colour record or
# texture ties a name to a colour) with a colour judged from the NAME (approximate, not measured), the natural ones
# only: a Skyrim NPC's natural colour should not land on Violet / Teal / Fuchsia.
NAME_RGB = {"Jet": (14, 13, 14), "Black": (26, 22, 20), "BlackBrown": (46, 33, 25), "Brown": (86, 58, 38),
            "Auburn": (112, 46, 30), "Copper": (156, 82, 42), "Amber": (168, 112, 52), "DirtyBlonde": (160, 130, 86),
            "Blonde": (202, 168, 108), "Platinum": (216, 206, 182), "SaltAndBrown": (120, 104, 92),
            "SaltAndPepper": (128, 126, 123), "Grey": (152, 152, 150), "White": (226, 224, 218)}


def _nearest(rgb, table: Dict[str, Iterable[float]], names) -> Optional[str]:
    cand = [n for n in names if n in table]
    if not cand:
        return None
    w = (0.3, 0.59, 0.11)

    def dist(n):
        return sum(wi * (float(a) - float(b)) ** 2 for wi, a, b in zip(w, list(table[n])[:3], rgb))
    return min(cand, key=dist)


def match_hair_color(skyrim_color: Optional[Dict], names: Iterable[str],
                     palette: Optional[Dict[str, List[float]]] = None) -> Tuple[Optional[str], str]:
    """(Starfield hair colour name, how) for a Skyrim CLFM {"edid", "rgba"}: the nearest colour by RGB in the measured
    palette when it covers at least 3 of the names; else in NAME_RGB (colours judged from the names); else the most
    shared colour words; else None."""
    names = sorted({n for n in names if n})
    if not names or not skyrim_color:
        return None, "no colour"
    rgb = (skyrim_color.get("rgba") or [None])[:3]
    if rgb and rgb[0] is not None:
        if palette and sum(1 for n in names if n in palette) >= 3:
            best = _nearest(rgb, palette, names)
            if best:
                return best, "palette rgb"
        best = _nearest(rgb, NAME_RGB, names)
        if best:
            return best, "rgb of the name (approximate)"
    want = color_words(skyrim_color.get("edid", ""))
    if want:
        scored = []
        for n in names:
            have = color_words(n)
            hue = len((want - {"dark", "light"}) & have)
            tone = len((want & {"dark", "light"}) & have)
            if hue:
                scored.append((-hue, -tone, n))
        if scored:
            return min(scored)[2], "colour words"
    return None, "no match"
