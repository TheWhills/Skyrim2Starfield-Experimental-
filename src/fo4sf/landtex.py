"""Ground textures: Skyrim LAND texture layers -> Starfield BTD texture layers (LTEX table, quadrant map, weights).

Skyrim (UESP "Skyrim Mod:Mod File Format/LAND", "LTEX"; verified only on synthetic files here):
* per cell quadrant (0 SW, 1 SE, 2 NW, 3 NE; 17 x 17 vertices each, sharing the middle row / column) one BTXT
  (LTEX FormID, quadrant u8, u8, i16 -1) and any number of ATXT (LTEX FormID, quadrant u8, u8, layer u16) each followed by
  VTXT (n x {u16 position = row * 17 + column inside the quadrant, u16, f32 opacity}). Layers draw in layer order over
  the base: colour = lerp(colour, layer, opacity). So a vertex's effective weight of layer k is
  opacity_k * prod(1 - opacity_j for the layers j above k), and the base keeps prod(1 - opacity_j) over all layers.
  BTXT FormID 0 is the engine's default land texture.
* LTEX: EDID, TNAM -> TXST whose TX00 is the diffuse texture (used to recognise what the texture is) and TX01 the
  normal map (both converted by --skyrim-ground, src/fo4sf/skyrimground.py).

Starfield BTD (docs/terrain/architecture.md 1.4 for the byte layout, verified; the meaning below is a SUPPORTED
hypothesis from fo76utils, which renders Starfield terrain: btdfile.cpp getCellTextureSet / getCellLandTexture and
landtxt.cpp renderPixel*):
* per cell quadrant 8 bytes; a byte b in 1..n names an LTEX table entry, 0 = none. Bytes 0..4 are the five overlay
  layers; the base (default) texture is the LAST valid byte (vanilla single-texture quadrants: "1 0 0 0 0 0 0 0").
  Which entry: fo76utils reads Fallout 76 BTDs as entry n - b ("tail"). Starfield reads entry b - 1 ("head", the
  default here; supported hypothesis from the owner's Jemison colour tests, docs/terrain/skyrim-tamriel.md): with
  "tail" every Skyrim texture showed in another one's place, and the mix-up moved when the table changed.
* per sample one u16: bits 3i..3i+2 = alpha 0..7 of the overlay in byte i. Rendering takes the first layer, from byte 0
  (top) to byte 4, whose alpha passes, else the base: layer i shows with probability alpha_i / 7 where every layer
  above it failed. So effective weights w (top first) invert to alpha_i = w_i / (1 - sum of w above), clamped.
Here a quadrant puts its base in byte 5 and up to five overlays in bytes 0..4 (least common texture on top).
"""
import json
import re
import struct
from typing import Dict, List, Optional

import numpy as np

from fo4sf import fo4land

DEFAULT_LTEX = 0                               # BTXT FormID 0: the engine's default land texture
PLAIN_GROUND = 0x001235C2                      # Starfield LDirtFootprints01, the base of most vanilla quadrants

# Skyrim texture -> category, by EditorID and diffuse path (first match wins)
CATEGORIES = [
    ("snow", r"snow"),
    ("ice", r"ice|glacier|frost"),
    ("road", r"road|path|cobble|brick|paved|street"),
    ("gravel", r"gravel|pebble|scree"),
    ("rock", r"rock|cliff|mountain|stone|boulder|crag"),
    ("sand", r"sand|beach|shore"),
    ("mud", r"mud|swamp|marsh|bog|wetland"),
    ("ash", r"ash|volcan|lava|soot|burn"),
    ("forest", r"forest|needle|pine|leaf|leaves|moss|mulch|fallforest"),
    ("grass", r"grass|field|tundra|meadow|lawn|reach|farm|crop|wheat"),
    ("dirt", r"dirt|soil|ground|earth|default"),
]
# category -> Starfield LTEX EditorID keywords to look for (first EditorID containing a keyword wins)
SF_KEYWORDS = {
    "snow": ["snow"], "ice": ["ice", "snow"], "road": ["road", "path", "gravel", "pave"], "gravel": ["gravel", "pebble"],
    "rock": ["rock", "cliff", "stone"], "sand": ["sand"], "mud": ["mud", "swamp", "wet"], "ash": ["ash", "volcan", "lava"],
    "forest": ["forest", "moss", "leaf", "needle", "mulch"], "grass": ["grass", "meadow", "lawn"], "dirt": ["dirt"],
}


def category(edid: str, diffuse: str) -> str:
    text = f"{edid} {diffuse}".lower()
    for name, rx in CATEGORIES:
        if re.search(rx, text):
            return name
    return "dirt"


# ------------------------------------------------------------------------------------------------- Skyrim side
def read_ltex(p: fo4land.Plugin) -> Dict[int, dict]:
    """{LTEX form id: {"edid", "diffuse"}} with the diffuse path from the LTEX's texture set (TXST TX00)."""
    txst, ltex = {}, {}
    for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
        if item[0] != "GRUP" or item[3] not in (b"TXST", b"LTEX"):
            continue
        for typ, off, _flags, fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
            if typ == "GRUP":
                continue
            fields = dict((s, d) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
            if typ == b"TXST":
                txst[fid] = (fo4land.zstring(fields.get(b"TX00", b"")), fo4land.zstring(fields.get(b"TX01", b"")))
            else:
                tn = struct.unpack_from("<I", fields[b"TNAM"])[0] if len(fields.get(b"TNAM", b"")) >= 4 else 0
                ltex[fid] = {"edid": fo4land.zstring(fields.get(b"EDID", b"")), "txst": tn}
    for v in ltex.values():
        v["diffuse"], v["normal"] = txst.get(v.pop("txst"), ("", ""))
    return ltex


def land_layers(data: bytes):
    """[(quadrant, ltex, layer, {position: opacity} or None for the base)] of one LAND record's fields."""
    out, pending = [], None
    for sig, d in fo4land.iter_subrecords(data):
        if sig == b"BTXT" and len(d) >= 8:
            fid, quad = struct.unpack_from("<IB", d)
            out.append((quad, fid, -1, None))
        elif sig == b"ATXT" and len(d) >= 8:
            fid, quad, _u, layer = struct.unpack_from("<IBBH", d)
            pending = [quad, fid, layer, {}]
            out.append(pending)
        elif sig == b"VTXT" and pending is not None:
            for k in range(len(d) // 8):
                pos, _u, op = struct.unpack_from("<HHf", d, 8 * k)
                pending[3][pos] = op
            pending = None
    return [tuple(x) for x in out]


QUAD_ORIGIN = {0: (0, 0), 1: (0, 16), 2: (16, 0), 3: (16, 16)}     # (row, col) of a quadrant's SW vertex in 33 x 33


def cell_weights(layers) -> Dict[int, np.ndarray]:
    """{ltex: (33, 33) effective weight} of one cell (row 0 = south). Each vertex takes the quadrant whose 17 x 17 block
    holds it (shared middle row / column: the south-west quadrant wins, as Skyrim's own data repeats it)."""
    out: Dict[int, np.ndarray] = {}
    owner = np.zeros((33, 33), np.int64)
    owner[:, 17:] += 1
    owner[17:, :] += 2
    for q in range(4):
        r0, c0 = QUAD_ORIGIN[q]
        base = [x for x in layers if x[0] == q and x[3] is None]
        overlay = sorted((x for x in layers if x[0] == q and x[3] is not None), key=lambda x: x[2])
        mask = owner == q
        # w stack from the top: remaining = 1, each layer from top down takes opacity * remaining
        remaining = np.ones((33, 33))
        for _q, fid, _layer, ops in reversed(overlay):
            op = np.zeros((33, 33))
            for pos, v in ops.items():
                r, c = divmod(pos, 17)
                if 0 <= r < 17 and 0 <= c < 17:
                    op[r0 + r, c0 + c] = min(max(v, 0.0), 1.0)
            w = op * remaining * mask
            remaining = remaining * (1.0 - op)
            out[fid] = out.get(fid, np.zeros((33, 33))) + w
        bfid = base[0][1] if base else DEFAULT_LTEX
        out[bfid] = out.get(bfid, np.zeros((33, 33))) + remaining * mask
    return out


def read_world_textures(esm: str, world: str = "Tamriel"):
    """({(cx, cy): {ltex: (33, 33) weight}}, {ltex: {"edid", "diffuse"}}) for every cell with LAND texture data."""
    cells = {}
    with fo4land.Plugin(esm) as p:
        ltex = read_ltex(p)
        _wfid, start, end, _f = p.find_world(world)

        def walk(s, e, cell):
            for item in fo4land.iter_items(p.buf, s, e):
                if item[0] == "GRUP":
                    _g, off, gend, label, gtype = item
                    if gtype in (4, 5):
                        walk(off + 24, gend, None)
                    elif gtype == 6 and cell is not None and struct.unpack("<I", label)[0] == cell[0]:
                        walk(off + 24, gend, cell)
                    elif gtype in (8, 9) and cell is not None and cell[1] is not None:
                        for it in fo4land.iter_items(p.buf, off + 24, gend):
                            if it[0] != "GRUP" and it[0] == b"LAND":
                                lay = land_layers(fo4land.record_data(p.buf, it[1]))
                                if lay:
                                    cells[cell[1]] = cell_weights(lay)
                    continue
                typ, off, _fl, fid = item
                if typ == b"CELL":
                    xy = None
                    for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                        if sig == b"XCLC" and len(d) >= 8:
                            xy = struct.unpack_from("<ii", d)
                    cell = (fid, xy)
        walk(start, end, None)
    return cells, ltex


# ------------------------------------------------------------------------------------------------- mapping
def starfield_ltex(sf_esm: str) -> Dict[str, int]:
    """{EditorID: FormID} of every Starfield.esm LTEX."""
    out = {}
    with fo4land.Plugin(sf_esm) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP" or item[3] != b"LTEX":
                continue
            for typ, off, _fl, fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if typ == "GRUP":
                    continue
                for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                    if sig == b"EDID":
                        out[fo4land.zstring(d)] = fid
                        break
    return out


TERRAIN_ARCHIVES = ("Starfield - Terrain01.ba2", "Starfield - Terrain02.ba2", "Starfield - Terrain03.ba2",
                    "Starfield - Terrain04.ba2", "Starfield - TerrainPatch.ba2")
BTD_LTEX_TABLE = 0x28                   # u32 n, n x u32 LTEX FormIDs (docs/terrain/architecture.md 1.4)


def vanilla_usage(sf_data: str):
    """(Counter {LTEX form id: vanilla BTDs listing it}, Counter {form id: BTDs where it is the first entry}, BTDs read,
    BTDs skipped). Only each BTD's header is read: the vanilla terrain archives store BTDs uncompressed."""
    import os
    from collections import Counter
    from fo4sf import ba2
    listed, first, n, skipped = Counter(), Counter(), 0, 0
    for name in TERRAIN_ARCHIVES:
        path = os.path.join(sf_data, name)
        if not os.path.exists(path):
            continue
        arc = ba2.Ba2(path)
        with open(path, "rb") as f:
            for e in arc.entries:
                if not e.name.lower().endswith(".btd"):
                    continue
                if e.kind != "GNRL" or e.packed:
                    skipped += 1
                    continue
                f.seek(e.offset)
                head = f.read(BTD_LTEX_TABLE + 4)
                k = struct.unpack_from("<I", head, BTD_LTEX_TABLE)[0] if len(head) == BTD_LTEX_TABLE + 4 else 1 << 30
                if k > 4096:
                    skipped += 1
                    continue
                t = struct.unpack(f"<{k}I", f.read(4 * k))
                n += 1
                listed.update(set(t))
                if t:
                    first[t[0]] += 1
    return listed, first, n, skipped


def build_mapping(ltex: Dict[int, dict], sf: Dict[str, int], override: Optional[dict] = None,
                  usage: Optional[Dict[int, int]] = None) -> dict:
    """{"skyrim": {ltex: {"edid", "diffuse", "category", "starfield"}}, "categories": {category: {"edid", "form_id"}}}.
    override (ltex_mapping.json): {"categories": {category: SF EditorID}, "skyrim": {Skyrim EditorID: SF EditorID}}.
    usage ({SF LTEX form id: vanilla BTDs listing it}, from vanilla_usage): among the LTEX whose EditorID matches a
    category, the one vanilla terrain uses most wins, and one no vanilla BTD uses is never picked automatically (the
    plain ground is used instead). Without usage: the first match alphabetically (owner's first in-game test of that:
    pale pink ground everywhere)."""
    override = override or {}
    lower = {k.lower(): k for k in sorted(sf)}
    fallback = next((k for k, v in sf.items() if v == PLAIN_GROUND), None) or (sorted(sf)[0] if sf else None)
    cats = {}
    for cat, words in SF_KEYWORDS.items():
        pick = override.get("categories", {}).get(cat)
        if pick is None:
            matches = list(dict.fromkeys(lower[k] for w in words for k in sorted(lower) if w in k))
            if usage is not None:
                used = sorted((m for m in matches if usage.get(sf[m], 0) > 0), key=lambda m: -usage[sf[m]])
                pick = used[0] if used else fallback
            else:
                pick = matches[0] if matches else fallback
        if pick is not None and pick not in sf:
            raise ValueError(f"Starfield LTEX {pick!r} (category {cat}) is not in Starfield.esm")
        cats[cat] = {"edid": pick, "form_id": sf.get(pick)}
        if usage is not None and pick is not None:
            cats[cat]["vanilla_btds"] = int(usage.get(sf[pick], 0))
    sky = {}
    for fid, v in sorted(ltex.items()):
        cat = category(v["edid"], v["diffuse"])
        pick = override.get("skyrim", {}).get(v["edid"]) or cats[cat]["edid"]
        if pick not in sf:
            raise ValueError(f"Starfield LTEX {pick!r} (for Skyrim {v['edid']}) is not in Starfield.esm")
        sky[fid] = {"edid": v["edid"], "diffuse": v["diffuse"], "category": cat, "starfield": pick}
    default = override.get("default") or cats["dirt"]["edid"]
    sky[DEFAULT_LTEX] = {"edid": "(engine default)", "diffuse": "", "category": "dirt", "starfield": default}
    return {"skyrim": sky, "categories": cats}


def target_cells(cells, mapping, sf: Dict[str, int]):
    """Per-cell weights summed per Starfield LTEX: ({(cx, cy): {sf form id: (33, 33) float32}}, [sf form ids])."""
    out, used = {}, set()
    for xy, ws in cells.items():
        d = {}
        for fid, w in ws.items():
            m = mapping["skyrim"].get(fid) or mapping["skyrim"][DEFAULT_LTEX]
            t = sf[m["starfield"]]
            d[t] = d.get(t, 0) + w.astype(np.float32)
            used.add(t)
        out[xy] = d
    return out, sorted(used)


# ------------------------------------------------------------------------------------------------- BTD encoding
def merged_grid(cells_t, form_id, x0, x1, y0, y1, fill):
    """One Starfield texture's weight over the inclusive Skyrim cell rectangle as a merged vertex grid (float32)."""
    g = np.zeros(((y1 - y0 + 1) * 32 + 1, (x1 - x0 + 1) * 32 + 1), np.float32)
    for cy in range(y0, y1 + 1):
        for cx in range(x0, x1 + 1):
            d = cells_t.get((cx, cy))
            w = d.get(form_id) if d is not None else None
            if w is None:
                w = np.full((33, 33), fill, np.float32) if d is None else None
            if w is not None:
                g[(cy - y0) * 32:(cy - y0) * 32 + 33, (cx - x0) * 32:(cx - x0) * 32 + 33] = w
    return g


BLEND_MODES = ("solid", "dither")
INDEX_RULES = ("head", "tail")
INDEX_RULE = "head"


def byte_for(index: int, n: int, rule: str = INDEX_RULE) -> int:
    """The quadrant byte naming LTEX table entry `index` of n (rule: INDEX_RULES, see the module notes)."""
    if rule not in INDEX_RULES:
        raise ValueError(f"index rule {rule!r} not in {INDEX_RULES}")
    return index + 1 if rule == "head" else n - index


def entry_for(b: int, n: int, rule: str = INDEX_RULE) -> int:
    """The LTEX table index a quadrant byte b (1..n) names."""
    if rule not in INDEX_RULES:
        raise ValueError(f"index rule {rule!r} not in {INDEX_RULES}")
    return b - 1 if rule == "head" else n - b


def encode_quadrants(weights: np.ndarray, table: List[int], ids: List[int], blend: str = "dither",
                     index_rule: str = INDEX_RULE):
    """weights [k, rows, cols] (rows, cols multiples of 64; one plane per id in `ids`) -> (quad map [rows/64, cols/64, 8]
    uint8, sample weights [rows, cols] uint16, stats). Per 64 x 64 quadrant: base = most weight, up to five more as
    overlays, least weight on top (byte 0), alphas solved top-down from the effective weights.
    blend "dither": each alpha quantised to 0..7 (the renderer shows layer i with probability alpha / 7, so a faint
    Skyrim layer becomes scattered hard-edged specks: owner's Jemison close-ups). "solid": each alpha snapped to 0 or 7
    at one half, so a sample shows the layer that covers most of what is left there and faint layers give way to
    the ones below: clean patches where Skyrim clearly paints a texture."""
    if blend not in BLEND_MODES:
        raise ValueError(f"blend {blend!r} not in {BLEND_MODES}")
    k, rows, cols = weights.shape
    n = len(table)
    index = {fid: table.index(fid) for fid in ids}
    qmap = np.zeros((rows // 64, cols // 64, 8), np.uint8)
    out = np.zeros((rows, cols), np.uint16)
    dropped = 0.0
    total = float(weights.sum()) or 1.0
    for qr in range(rows // 64):
        for qc in range(cols // 64):
            w = weights[:, qr * 64:(qr + 1) * 64, qc * 64:(qc + 1) * 64]
            sums = w.reshape(k, -1).sum(axis=1)
            order = [i for i in np.argsort(-sums) if sums[i] > 0]
            if not order:
                order = [0]
            base, over = order[0], order[1:6]
            dropped += float(sum(sums[i] for i in order[6:]))
            qmap[qr, qc, 5] = byte_for(index[ids[base]], n, index_rule)
            stack = list(reversed(over))                        # least weight first = byte 0 = top
            s = w.sum(axis=0)
            s[s <= 0] = 1.0
            remaining = np.ones((64, 64), np.float32)
            word = np.zeros((64, 64), np.uint16)
            for byte, i in enumerate(stack):
                qmap[qr, qc, byte] = byte_for(index[ids[i]], n, index_rule)
                wi = w[i] / s
                a = np.clip(wi / np.maximum(remaining, 1e-6), 0.0, 1.0)
                if blend == "solid":
                    on = a >= 0.5
                    q = np.where(on, 7, 0).astype(np.uint16)
                    word |= q << (3 * byte)
                    # a sample this layer took is fully covered; elsewhere its weight passes to the layers below
                    remaining = np.where(on, 0.0, remaining).astype(np.float32)
                    continue
                q = np.rint(a * 7.0).astype(np.uint16)
                word |= q << (3 * byte)
                remaining = np.maximum(remaining - wi, 0.0)
            out[qr * 64:(qr + 1) * 64, qc * 64:(qc + 1) * 64] = word
    return qmap, out, {"weight_beyond_six_layers": round(dropped / total, 5)}


def decode_quadrants(qmap, word, table, index_rule: str = INDEX_RULE):
    """Effective weights {form id: [rows, cols]} implied by a quad map + sample words (the rendering rule above)."""
    rows, cols = word.shape
    n = len(table)
    out = {}
    for qr in range(rows // 64):
        for qc in range(cols // 64):
            b = qmap[qr, qc]
            valid = [i for i in range(8) if 0 < b[i] <= n]
            base = table[entry_for(int(b[valid[-1]]), n, index_rule)]
            wd = word[qr * 64:(qr + 1) * 64, qc * 64:(qc + 1) * 64].astype(np.int64)
            remaining = np.ones((64, 64))
            for i in range(5):
                if 0 < b[i] <= n and i != valid[-1]:
                    a = ((wd >> (3 * i)) & 7) / 7.0
                    w = a * remaining
                    t = table[entry_for(int(b[i]), n, index_rule)]
                    out.setdefault(t, np.zeros((rows, cols)))[qr * 64:(qr + 1) * 64, qc * 64:(qc + 1) * 64] += w
                    remaining = remaining - w
            out.setdefault(base, np.zeros((rows, cols)))[qr * 64:(qr + 1) * 64, qc * 64:(qc + 1) * 64] += remaining
    return out


def save_mapping(path, mapping, coverage=None):
    sky = {str(k): v for k, v in mapping["skyrim"].items()}
    doc = {"note": "Edit and pass back with --ltex-mapping: {\"categories\": {category: Starfield LTEX EditorID}, "
                   "\"skyrim\": {Skyrim LTEX EditorID: Starfield LTEX EditorID}, \"default\": Starfield EditorID}",
           "categories": mapping["categories"], "skyrim": sky, "coverage": coverage or {}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)


def coverage(cells_t, used, names):
    tot = {t: 0.0 for t in used}
    for d in cells_t.values():
        for t, w in d.items():
            tot[t] += float(w.sum())
    s = sum(tot.values()) or 1.0
    return {names.get(t, "%08X" % t): round(v / s, 4) for t, v in sorted(tot.items(), key=lambda kv: -kv[1])}

