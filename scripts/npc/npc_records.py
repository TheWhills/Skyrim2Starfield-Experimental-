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
    "red": ("red", "auburn", "ginger", "copper", "strawberry", "amber"),
    "black": ("black", "raven", "ebony", "jet"),
    "grey": ("grey", "gray", "silver", "ash", "white", "platinum", "salt"),
    "dark": ("dark", "deep"),
    "light": ("light", "pale", "bright", "platinum"),
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
    has_rgb = bool(rgb) and rgb[0] is not None
    table = palette if (palette and sum(1 for n in names if n in palette) >= 3) else NAME_RGB
    how = "palette" if table is palette else "name colours (approximate)"
    natural = [n for n in names if n in NAME_RGB] or \
        [n for n in names if not re.search(r"violet|blue|teal|fuchsia|purple|yellow|aqua|ruby|pink|green", n, re.I)]
    # Skyrim's colour EditorIDs say what the colour is (HairColor03BrightBlond, HairColor06Auburn); its CLFM RGB is a
    # tint multiplied into the texture and reads much darker (BrightBlond is 81, 77, 57), so the words decide the
    # family (owner 2026-11-05: Ralof came out red, then by RGB alone brown, Ysolda's Auburn black-brown)
    want = color_words(skyrim_color.get("edid", ""))
    hues = want - {"dark", "light"}
    if hues:
        fam = []
        for n in natural:
            have = color_words(n) - {"dark", "light"}
            if have & hues:
                fam.append((len(have & hues) - 0.5 * len(have - hues), n))
        if fam:
            top = max(f for f, _n in fam)
            slack = 0.5 if want & {"dark", "light"} else 0.0     # 'dark brown' may go to BlackBrown
            fam = [n for f, n in fam if f >= top - slack]
            light = lambda n: lightness(table.get(n, NAME_RGB.get(n, (128, 128, 128))))
            if "light" in want:
                return max(fam, key=light), f"colour words, lightest ({how})"
            if "dark" in want:
                return min(fam, key=light), f"colour words, darkest ({how})"
            if has_rgb and len(fam) > 1:
                return _nearest(rgb, table, fam) or fam[0], f"colour words, nearest rgb ({how})"
            return fam[0], "colour words"
    if has_rgb:
        best = _nearest(rgb, table, natural or names)
        if best:
            return best, f"rgb ({how})"
    return None, "no match"


# ---------------------------------------------------------------------------------- eyes, skin tone, brows (11-06)
# Starfield's NPC_ (owner's npc_face_probe 2026-11-06, 2,983 human NPCs with a face): ECOL eye colour by name, BCOL
# brow colour by name (the hair colour names), STON skin tone u8 0-8, eyebrows a head part (type 6). Vanilla order:
# ... DPLT, STON, HCOL, BCOL, ECOL
EYE_COLORS = ("Brown", "Hazel", "Iron", "Grey", "Green", "Blue", "Red", "BrownDark", "Copper", "RedDevil", "Sulfur")
# Skyrim eye head part EditorID words -> Starfield eye colour (judged from the names: approximate). Longest first.
EYE_WORDS = (("darkbrown", "BrownDark"), ("iceblue", "Blue"), ("lightblue", "Blue"), ("lightgrey", "Grey"),
             ("lightgray", "Grey"), ("blind", "Grey"), ("hazel", "Hazel"), ("amber", "Copper"),
             ("orange", "Copper"), ("brown", "Brown"), ("green", "Green"), ("blue", "Blue"), ("grey", "Grey"),
             ("gray", "Grey"), ("violet", "Blue"), ("yellow", "Sulfur"), ("gold", "Sulfur"), ("red", "Red"),
             ("white", "Grey"))
FACE_COLOR_ORDER = (b"STON", b"HCOL", b"BCOL", b"ECOL")
# Skyrim skin tone tint luminance (Y, sRGB 0-255) at Starfield's lightest and darkest tone: Ralof's tint is about 179,
# Nazeem's 41. ASSUMED: STON 0 is the lightest and 8 the darkest (unverified: the owner checks Nazeem / Saadia in game)
SKIN_LIGHT_Y, SKIN_DARK_Y, SKIN_TONES = 200.0, 45.0, 9


def eye_color(skyrim_edid: Optional[str]) -> Tuple[Optional[str], str]:
    """(Starfield ECOL name, how) for a Skyrim eyes head part EditorID (MaleEyesHumanIceBlue -> Blue)."""
    if not skyrim_edid:
        return None, "no Skyrim eyes"
    low = skyrim_edid.lower()
    for word, name in EYE_WORDS:
        if word in low:
            return name, f"'{word}' in the EditorID"
    return None, "no colour word"


def skin_tone(rgb) -> Optional[int]:
    """STON 0-8 for a Skyrim skin colour (the skin tone tint's RGB, 0-255) by its luminance."""
    if not rgb or rgb[0] is None:
        return None
    y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    t = (SKIN_LIGHT_Y - y) / (SKIN_LIGHT_Y - SKIN_DARK_Y)
    return int(round(min(1.0, max(0.0, t)) * (SKIN_TONES - 1)))


def skyrim_skin_rgb(npc: Dict, race_tints: Dict) -> Tuple[Optional[list], str]:
    """The NPC's skin colour: its skin tone tint layer's colour (race_tints {(female, index): (mask, kind)}), else
    its texture lighting (QNAM, 0-1 floats)."""
    for t in npc.get("tints") or []:
        if race_tints.get((npc.get("female", False), t["index"]), ("", None))[1] == "skin tone" and t.get("color"):
            return list(t["color"][:3]), "skin tone tint"
    tl = npc.get("texture_lighting")
    if tl:
        return [round(c * 255) for c in tl], "texture lighting"
    return None, "none"


def with_face_colors(subs, values: Dict[bytes, bytes]) -> list:
    """subs with STON / HCOL / BCOL / ECOL set: replaced where present, else placed in vanilla's order."""
    out = list(subs)
    for sig, data in values.items():
        at = next((i for i, (s, _d) in enumerate(out) if s == sig), None)
        if at is not None:
            out[at] = (sig, data)
            continue
        k = FACE_COLOR_ORDER.index(sig)
        before = [i for i, (s, _d) in enumerate(out) if s in FACE_COLOR_ORDER[:k]]
        after = [i for i, (s, _d) in enumerate(out) if s in FACE_COLOR_ORDER[k + 1:]]
        pos = before[-1] + 1 if before else (after[0] if after else len(out))
        out.insert(pos, (sig, data))
    return out


def race_defaults(race_subs) -> Dict[bool, List[int]]:
    """{female: [default head part FormIDs]} of a Skyrim RACE (its head data: HEAD after MNAM / FNAM)."""
    out, female = {False: [], True: []}, False
    for s, d in race_subs:
        if s == b"MNAM":
            female = False
        elif s == b"FNAM":
            female = True
        elif s == b"HEAD" and len(d) >= 4:
            out[female].append(struct.unpack_from("<I", bytes(d), 0)[0])
    return out


# Skyrim RACE tint mask types (TINP; xEdit wbDefinitionsTES5)
TINT_KINDS = {0: "none", 1: "lip color", 2: "cheek color", 3: "eyeliner", 4: "eye socket upper",
              5: "eye socket lower", 6: "skin tone", 7: "paint", 8: "laugh lines", 9: "cheek color lower", 10: "nose",
              11: "chin", 12: "neck", 13: "forehead", 14: "dirt"}


def race_tints(subs) -> Dict:
    """{(female, TINI index): (mask path, kind)} of a Skyrim RACE (MNAM / FNAM switch the sex of what follows)."""
    out, female, cur = {}, False, None
    for s, d in subs:
        d = bytes(d)
        if s == b"MNAM":
            female = False
        elif s == b"FNAM":
            female = True
        elif s == b"TINI" and len(d) >= 2:
            cur = [struct.unpack_from("<H", d, 0)[0], "", None]
            out[(female, cur[0])] = cur
        elif s == b"TINT" and cur is not None:
            cur[1] = fo4land.zstring(d)
        elif s == b"TINP" and cur is not None and len(d) >= 2:
            k = struct.unpack_from("<H", d, 0)[0]
            cur[2] = TINT_KINDS.get(k, str(k))
    return {k: (v[1], v[2]) for k, v in out.items()}


# ------------------------------------------------------------------------------------- face skin texture (11-06)
# Starfield's face skin is a texture layer, not STON (owner 2026-11-06: Nazeem's body went dark with STON 8, his face
# stayed the template's light skin): a TNAM "Dermaesthetic" layer whose QNAM names the texture,
# <Ethnicity>_<Sex>_<age>_Sk<n> (African / Asian / European; yo1, md1, md2, ol1; Sk1, 3, 6, 8; capitalisation varies),
# 2,901 of 2,983 faced human NPCs (probe). Read as Sk = the skin tone it was painted for (assumed: vanilla NPCs pair
# them loosely, e.g. European_Female_md1_Sk8 with STON 0).
DERMA = re.compile(r"^(african|asian|european)_(male|female)_([a-z]+\d)_sk(\d+)$", re.I)
SKYRIM_ETHNICITY = {"redguard": "african", "nord": "european", "imperial": "european", "breton": "european",
                    "elder": "european"}


def dermaesthetic_names(npc_recs) -> List[str]:
    """Every Dermaesthetic texture name Starfield's NPCs use."""
    out = set()
    for _t, _h, subs, _f in npc_recs:
        layer = None
        for s, d in subs:
            if s == b"TNAM":
                layer = fo4land.zstring(d)
            elif s == b"QNAM" and layer == "Dermaesthetic":
                out.add(fo4land.zstring(d))
                layer = None
    return sorted(out)


def skyrim_ethnicity(race_edid: str) -> str:
    low = (race_edid or "").lower()
    return next((v for k, v in SKYRIM_ETHNICITY.items() if k in low), "european")


def choose_dermaesthetic(names, ethnicity: str, female: bool, ston: Optional[int], age: str = "md1"
                         ) -> Tuple[Optional[str], str]:
    """The face skin texture for an ethnicity / sex / age, its Sk nearest the skin tone (STON 0-8)."""
    sex = "female" if female else "male"
    cand = []
    for n in names:
        m = DERMA.match(n)
        if m and m.group(1).lower() == ethnicity and m.group(2).lower() == sex:
            cand.append((m.group(3).lower(), int(m.group(4)), n))
    if not cand:
        return None, f"no {ethnicity} {sex} face skin texture"
    ages = [c for c in cand if c[0] == age] or cand
    want = 4 if ston is None else ston
    best = min(ages, key=lambda c: (abs(c[1] - want), c[0] != age, c[2]))
    return best[2], f"{ethnicity} {sex}, Sk{best[1]} nearest skin tone {ston}"


def with_layer_texture(subs, layer: str, texture: str) -> Tuple[list, bool]:
    """subs with the texture (QNAM) of texture layer `layer` (TNAM) replaced; False when the NPC has no such layer."""
    out, cur, done = [], None, False
    for s, d in subs:
        if s == b"TNAM":
            cur = fo4land.zstring(d)
        elif s == b"QNAM" and cur == layer and not done:
            out.append((s, sfplugin.zs(texture)))
            done, cur = True, None
            continue
        out.append((s, d))
    return out, done


# Skyrim NPCs without a hair colour (HCLF) of their own (Nazeem, Saadia) show their race's dark default; the test
# NPC otherwise keeps its template's colour (2026-11-06: Saadia came out brown, dark grey-black in Skyrim)
RACE_HAIR_COLOR = {"redguard": "Black", "nord": "Brown", "imperial": "BlackBrown", "breton": "Brown"}


def default_hair_color(race_edid: str, names) -> Optional[str]:
    low = (race_edid or "").lower()
    pick = next((v for k, v in RACE_HAIR_COLOR.items() if k in low), None)
    return pick if pick in set(names) else None
