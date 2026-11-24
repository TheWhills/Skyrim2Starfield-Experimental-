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
Starfield (owner's Jemison colour test, 2026-10-16: a spot whose five overlays all had alpha 0 showed overlay 4, not
the byte-5 base) reads only bytes 0..4: the base must be the last valid byte AMONG 0..4. So a quadrant here holds
at most four overlays in bytes 0..k-1 (least common on top) and the base in byte k, the rest 0 (vanilla's single
texture "1 0 0 0 0 0 0 0" is the k = 0 case).
"""
import json
import os
import re
import struct
from typing import Callable, Dict, List, Optional

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
# 2026-11-23 (owner's skyrim_ltex_scan.py run): Update.esm carries its own LAND for Riverwood's cell (4, -12), 27 GRAS
# and 15 LTEX overrides, and the game loads it (and the DLC) over Skyrim.esm. The readers here take Skyrim as the game
# loads it: Skyrim.esm, then the official masters found next to it, later records winning (a LAND per cell, an LTEX /
# GRAS per FormID). FormIDs are put in that load order (Skyrim.esm's keep their values).
OFFICIAL = ("Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm")


def official_plugins(esm: str, official: bool = True) -> List[str]:
    """[Skyrim.esm, then Update.esm / Dawnguard.esm / HearthFires.esm / Dragonborn.esm found in its folder]; just
    [esm] with official=False or when esm is not named Skyrim.esm."""
    if not official or os.path.basename(esm).lower() != "skyrim.esm":
        return [esm]
    d = os.path.dirname(os.path.abspath(esm))
    try:
        names = {n.lower(): n for n in os.listdir(d)}
    except OSError:
        return [esm]
    return [esm] + [os.path.join(d, names[n.lower()]) for n in OFFICIAL[1:] if n.lower() in names]


def plugin_masters(p: fo4land.Plugin) -> List[str]:
    return [fo4land.zstring(bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0))
            if s == b"MAST"]


def fid_remapper(paths: List[str], i: int, masters: List[str]) -> Callable[[int], int]:
    """FormID of plugin paths[i] (with these masters) -> the load order of paths (top byte = load index; a master
    not loaded keeps its own byte past the loaded ones, so its ids stay distinct). FormID 0 stays 0."""
    index = {os.path.basename(q).lower(): k for k, q in enumerate(paths)}
    table = [index.get(m.lower(), 0xF0 + k) for k, m in enumerate(masters)]

    def remap(fid: int) -> int:
        if fid == 0:
            return 0
        hi = fid >> 24
        top = table[hi] if hi < len(table) else i
        return (top << 24) | (fid & 0xFFFFFF)
    return remap


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


def read_ltex_loaded(esm: str, official: bool = True) -> Dict[int, dict]:
    """read_ltex over Skyrim as the game loads it (official_plugins; FormIDs in load order, later records win)."""
    out = {}
    paths = official_plugins(esm, official)
    for i, path in enumerate(paths):
        with fo4land.Plugin(path) as p:
            remap = fid_remapper(paths, i, plugin_masters(p))
            for fid, v in read_ltex(p).items():
                out[remap(fid)] = v
    return out


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


def cell_layer_presence(layers) -> Dict[int, np.ndarray]:
    """{ltex: (33, 33) raw opacity} of one cell, ignoring what lies on top: the base texture counts 1 over its
    quadrant, an alpha layer its own VTXT opacity (max if a texture appears twice). Skyrim grows a texture's grass
    wherever that texture is painted as a layer, even under an opaque layer above it (2026-11-23: modders' reports, and
    the owner's Riverwood screenshots: a dense carpet where the visible top textures are NoGrass / dirt)."""
    out: Dict[int, np.ndarray] = {}
    owner = np.zeros((33, 33), np.int64)
    owner[:, 17:] += 1
    owner[17:, :] += 2
    for q in range(4):
        r0, c0 = QUAD_ORIGIN[q]
        mask = owner == q
        for _q, fid, _layer, ops in (x for x in layers if x[0] == q):
            op = np.zeros((33, 33))
            if ops is None:
                op[:] = 1.0
            else:
                for pos, v in ops.items():
                    r, c = divmod(pos, 17)
                    if 0 <= r < 17 and 0 <= c < 17:
                        op[r0 + r, c0 + c] = min(max(v, 0.0), 1.0)
            cur = out.setdefault(fid, np.zeros((33, 33)))
            np.maximum(cur, op * mask, out=cur)
    return out


def land_colours(data: bytes) -> Optional[np.ndarray]:
    """A LAND record's VCLR vertex colours as (33, 33, 3) uint8 (row 0 = south; 255 = no tint), or None."""
    for sig, d in fo4land.iter_subrecords(data):
        if sig == b"VCLR" and len(d) >= 33 * 33 * 3:
            return np.frombuffer(d[:33 * 33 * 3], np.uint8).reshape(33, 33, 3).copy()
    return None


def read_world_textures(esm: str, world: str = "Tamriel", colours: Optional[dict] = None,
                        presence: Optional[dict] = None, official: bool = True):
    """({(cx, cy): {ltex: (33, 33) weight}}, {ltex: {"edid", "diffuse"}}) for every cell with LAND texture data.
    colours: a dict to fill with {(cx, cy): (33, 33, 3) VCLR} for those cells (Skyrim multiplies the ground textures
    by these per-vertex colours). presence: a dict to fill with {(cx, cy): cell_layer_presence(...)}.
    official: also read Update.esm and the DLC next to Skyrim.esm, as the game loads them (later LAND wins per cell;
    LTEX FormIDs in load order)."""
    cells, ltex = {}, {}
    paths = official_plugins(esm, official)
    for i, path in enumerate(paths):
        with fo4land.Plugin(path) as p:
            remap = fid_remapper(paths, i, plugin_masters(p))
            for fid, v in read_ltex(p).items():
                ltex[remap(fid)] = v
            try:
                _read_world_land(p, world, remap, cells, colours, presence)
            except (KeyError, TypeError):
                if i == 0:
                    raise
    return cells, ltex


def _read_world_land(p, world, remap, cells, colours, presence):
    """Fill cells / colours / presence from one plugin's LAND in world (FormIDs through remap)."""
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
                            data = fo4land.record_data(p.buf, it[1])
                            lay = [(q, remap(f), layer, ops) for q, f, layer, ops in land_layers(data)]
                            if lay:
                                cells[cell[1]] = cell_weights(lay)
                                if presence is not None:
                                    presence[cell[1]] = cell_layer_presence(lay)
                                if colours is not None:
                                    vc = land_colours(data)
                                    if vc is not None:
                                        colours[cell[1]] = vc
                continue
            typ, off, _fl, fid = item
            if typ == b"CELL":
                xy = None
                for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                    if sig == b"XCLC" and len(d) >= 8:
                        xy = struct.unpack_from("<ii", d)
                cell = (fid, xy)
    walk(start, end, None)


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
def merged_grid(cells_t, form_id, x0, x1, y0, y1, fill, consistent_edges=True):
    """One Starfield texture's weight over the inclusive Skyrim cell rectangle as a merged vertex grid (float32).
    Neighbouring cells share their edge row / column of vertices; the cell written last owns it, for every texture
    alike (consistent_edges). Before 2026-11-21 a cell without the texture wrote nothing, so the shared edge kept the
    previous cell's value for that texture while the cell's own textures were written over it: on the edge line two
    textures could both be at 100 % (owner's grey-blue strips: Skyrim paints 1 % rock at the spot, the build drew rock,
    a vertex-wide straight strip along a 58.5 m cell edge). consistent_edges=False keeps the old result (refresh_btd's
    spot check against terrain built that way)."""
    g = np.zeros(((y1 - y0 + 1) * 32 + 1, (x1 - x0 + 1) * 32 + 1), np.float32)
    for cy in range(y0, y1 + 1):
        for cx in range(x0, x1 + 1):
            d = cells_t.get((cx, cy))
            w = d.get(form_id) if d is not None else None
            if w is None:
                if d is None:
                    w = np.full((33, 33), fill, np.float32)
                elif consistent_edges:
                    w = np.zeros((33, 33), np.float32)
            if w is not None:
                g[(cy - y0) * 32:(cy - y0) * 32 + 33, (cx - x0) * 32:(cx - x0) * 32 + 33] = w
    return g


BLEND_MODES = ("solid", "dither", "noise", "smooth")
# "noise" (2026-11-21, owner: "spots in the terrain that are supposed to fade ... just got off like squares into each
# other"): "solid" cut each layer at alpha one half, and Skyrim's weights, bilinear between its vertices 1.83 m apart,
# cross one half along straight lines: every smooth Skyrim fade became a dead-straight border. "noise" cuts each layer
# against one coherent noise threshold instead: still only alpha 0 or 7 per sample (what rendered clean), but the border
# wanders through the whole fade, each texture covering about its weight's share of it in irregular patches. The
# textures are taken in a fixed order (by form id) and the threshold depends on the world position only, so the
# pattern continues across quadrants (whose stacks differ) and tiles.
NOISE_SCALES_M = ((6.0, 0.65), (2.0, 0.35))      # (lattice size m, weight): patches, then ragged edges (samples 0.78 m)
NOISE_STRETCH = 1.9                              # spreads the summed noise (std ~0.15) toward a uniform 0..1 threshold
# Skyrim's fades are mostly 1 - 2 vertex steps wide (1.8 - 3.7 m), too narrow for the threshold alone to bend a border
# by much. With "noise" the weights are also read at a position shifted by up to WARP_M (smooth in x and y, the same
# shift for every texture): any border, sharp or soft, wanders by that much in long, natural curves.
# 2026-11-21 20:58 (owner's ground_at --map at the grey strip): 3.5 m on 12 m waves did not bend Skyrim's sharp edges, it
# slid them sideways (a cell edge with rock on one side became a 2 - 3 m band of rock on the other: the strip). Now a
# small, quick wobble: edges ragged in place, never moved far.
WARP_M = 1.5
WARP_SCALES_M = ((5.0, 0.6), (1.8, 0.4))
INDEX_RULES = ("head", "tail")
MAX_OVERLAYS = 4                               # + the base = five textures in bytes 0..4 (Starfield ignores 5..7)
INDEX_RULE = "head"


def _lattice(ix, iy, key):
    """Deterministic pseudo-random 0..1 per integer lattice point and key (a 32-bit integer hash)."""
    h = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263 + int(key) * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return (h & 0xFFFFFF).astype(np.float64) / float(0x1000000)


def blend_noise(xs_m, ys_m, key: int, scales=None) -> np.ndarray:
    """Coherent noise threshold [len(ys), len(xs)] in 0..1 at world positions (metres) for one texture (key): value
    noise of NOISE_SCALES_M, smoothstep-interpolated, stretched toward uniform. Same position and key, same value."""
    xs = np.asarray(xs_m, np.float64)[None, :]
    ys = np.asarray(ys_m, np.float64)[:, None]
    total = np.zeros((ys.shape[0], xs.shape[1]))
    for octave, (size, weight) in enumerate(scales or NOISE_SCALES_M):
        gx, gy = xs / size, ys / size
        ix, iy = np.floor(gx), np.floor(gy)
        fx, fy = gx - ix, gy - iy
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        ix, iy = np.broadcast_to(ix, total.shape), np.broadcast_to(iy, total.shape)
        k = (int(key) * 31 + octave) & 0xFFFFFFFF
        v00, v10 = _lattice(ix, iy, k), _lattice(ix + 1, iy, k)
        v01, v11 = _lattice(ix, iy + 1, k), _lattice(ix + 1, iy + 1, k)
        top = v00 + (v10 - v00) * fx
        bot = v01 + (v11 - v01) * fx
        total += weight * (top + (bot - top) * fy)
    return np.clip(0.5 + (total - 0.5) * NOISE_STRETCH, 0.0, 0.9999).astype(np.float32)


def warp_offsets(xs_m, ys_m, amount_m: float = WARP_M):
    """(dx, dy) metres [len(ys), len(xs)]: the smooth shift at each sample's world position, within +-amount_m."""
    dx = (blend_noise(xs_m, ys_m, 0x5741, WARP_SCALES_M) - 0.5) * 2.0 * amount_m
    dy = (blend_noise(xs_m, ys_m, 0x5742, WARP_SCALES_M) - 0.5) * 2.0 * amount_m
    return dx, dy


def sample_warped(grid, origin_x, origin_y, spacing, xs, ys, dx, dy) -> np.ndarray:
    """Bilinear `grid` ([row, col], row 0 = south, as terrain_grid.resample_bilinear) at (xs[j] + dx[i, j],
    ys[i] + dy[i, j]) (all in the grid's units); points outside take the nearest edge value."""
    g = np.asarray(grid, np.float64)
    rows, cols = g.shape
    x = (np.asarray(xs, np.float64)[None, :] + dx - origin_x) / spacing
    y = (np.asarray(ys, np.float64)[:, None] + dy - origin_y) / spacing
    x = np.clip(x, 0.0, cols - 1.0)
    y = np.clip(y, 0.0, rows - 1.0)
    c0, r0 = np.minimum(np.floor(x).astype(np.int64), cols - 1), np.minimum(np.floor(y).astype(np.int64), rows - 1)
    c1, r1 = np.minimum(c0 + 1, cols - 1), np.minimum(r0 + 1, rows - 1)
    fx, fy = x - c0, y - r0
    top = g[r0, c0] * (1 - fx) + g[r0, c1] * fx
    bot = g[r1, c0] * (1 - fx) + g[r1, c1] * fx
    return top * (1 - fy) + bot * fy


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
                     index_rule: str = INDEX_RULE, coords=None):
    """weights [k, rows, cols] (rows, cols multiples of 64; one plane per id in `ids`) -> (quad map [rows/64, cols/64, 8]
    uint8, sample weights [rows, cols] uint16, stats). Per 64 x 64 quadrant: base = most weight, up to four more as
    overlays, least weight on top (byte 0), alphas solved top-down from the effective weights.
    blend "dither": each alpha quantised to 0..7 (the renderer shows layer i with probability alpha / 7, so a faint
    Skyrim layer becomes scattered hard-edged specks: owner's Jemison close-ups). "solid": each alpha snapped to 0 or 7
    at one half, so a sample shows the layer that covers most of what is left there and faint layers give way to
    the ones below: clean patches where Skyrim clearly paints a texture. "noise": as "solid" but each layer is cut
    against blend_noise at the samples' world positions, coords = (xs_m [cols], ys_m [rows]); without coords, sample
    indices stand in (metres = index x 0.78125)."""
    if blend not in BLEND_MODES:
        raise ValueError(f"blend {blend!r} not in {BLEND_MODES}")
    k, rows, cols = weights.shape
    n = len(table)
    if blend == "noise":
        xs_m, ys_m = coords if coords is not None else (np.arange(cols) * 0.78125, np.arange(rows) * 0.78125)
        u_all = blend_noise(xs_m, ys_m, 0)
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
            base, over = order[0], order[1:MAX_OVERLAYS + 1]
            dropped += float(sum(sums[i] for i in order[MAX_OVERLAYS + 1:]))
            qmap[qr, qc, len(over)] = byte_for(index[ids[base]], n, index_rule)   # base right after the overlays
            stack = list(reversed(over))                        # least weight first = byte 0 = top
            if blend == "noise":
                # one texture per sample, independent of the stack order (which changes from quadrant to quadrant):
                # the kept textures in a fixed order (by form id), their weights summed until they pass one shared
                # noise threshold; the chosen texture's byte gets 7, the others 0 (the base: all overlays 0)
                kept = [base] + over
                wk = w[kept]
                tot = wk.sum(axis=0)
                u = u_all[qr * 64:(qr + 1) * 64, qc * 64:(qc + 1) * 64]
                chosen = np.full((64, 64), -1, np.int64)
                cum = np.zeros((64, 64), np.float32)
                fixed = sorted(kept, key=lambda j: ids[j])
                for i in fixed:
                    cum = cum + np.where(tot > 0, w[i] / np.where(tot > 0, tot, 1.0), 1.0 if i == base else 0.0)
                    chosen = np.where((chosen < 0) & (u < cum), i, chosen)
                # u at the top of its range (clipped to 1) passes no sum below 1: the last texture in the fixed order,
                # as everywhere else (the base here drew rings round the noise's peaks where the stack flips)
                last = next((i for i in reversed(fixed) if float(w[i].max()) > 0), base)
                chosen = np.where(chosen < 0, last, chosen)
                word = np.zeros((64, 64), np.uint16)
                for byte, i in enumerate(stack):
                    qmap[qr, qc, byte] = byte_for(index[ids[i]], n, index_rule)
                    word |= np.where(chosen == i, 7, 0).astype(np.uint16) << (3 * byte)
                out[qr * 64:(qr + 1) * 64, qc * 64:(qc + 1) * 64] = word
                continue
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


# 2026-11-22 (owner's grey-blue "snow" band; label test + ground_at): the band lies on the first 2 - 3 sample rows of
# a 50 m quadrant, drawing LGrassSnow01NoGrass / LPineForest03 (table entries 24 / 23) where the active layer's byte
# is 47 here and 7 in the quadrant to the south: entries between them, as if the engine blends the two quadrants'
# bytes near their shared edge (supported hypothesis). So "aligned" slots: a texture keeps the byte position its
# neighbours gave it, unused positions copy a neighbour's byte, and within EDGE_SAMPLES of a quadrant edge a sample
# only uses a position whose byte equals the neighbour's there (blending equal bytes changes nothing).
EDGE_SAMPLES = 4
SLOTS = 5                                    # bytes 0..4; byte 4 is the base (every alpha 0)

# 2026-11-24 (owner's Riverwood river bank, ground_at with a fresh merge shift): Skyrim paints LFieldGrass02 at 1.0,
# the BTD quadrant there holds LFieldGrass02NoGrass instead. Skyrim's "NoGrass" / "NoFern" / "NoRocks" twins share
# the diffuse and normal of their grassy texture; a 50 m quadrant covers ~800 Skyrim vertices with up to 14 textures,
# and the top-five cut kept the no-grass twin (4.8 % of the quadrant) over the grassy one (5.5 %) at random. Twins
# look the same, so they compete for one slot as a group and all of a group's weight goes to its kept members.
GRASSY_BIAS = 2.0                            # a grassy twin counts double when a group picks its members


def choose_layers(sums, looks=None, grassy=None, slots: int = SLOTS):
    """One quadrant's textures: sums [k] weights per plane; looks[j]: a key shared by planes that render the same
    (diffuse + normal; None = its own); grassy[j]: Skyrim grows grass on it. Returns (kept: plane indices, most
    (merged) weight first, at most `slots`; merge {dropped plane: kept plane of the same look}; kept weights {j: w}).
    A look group's first member is ranked by the group's total weight, later members by their own; within a group,
    members are taken grassy-first (GRASSY_BIAS). A dropped member's weight goes to a kept member of its group,
    grassy to grassy where possible. Without looks this is the plain top-`slots` cut."""
    k = len(sums)
    present = [j for j in range(k) if sums[j] > 0]
    if not present:
        return [0], {}, {0: 0.0}
    looks = looks or [None] * k
    grassy = grassy or [False] * k
    groups = {}
    for j in present:
        key = looks[j] if looks[j] is not None else ("own", j)
        groups.setdefault(key, []).append(j)
    entries = []
    for key, mem in groups.items():
        mem.sort(key=lambda j: -(float(sums[j]) * (GRASSY_BIAS if grassy[j] else 1.0)))
        total = float(sum(sums[j] for j in mem))
        entries.append((total, 0, mem[0], key))
        for i, j in enumerate(mem[1:], 1):
            entries.append((float(sums[j]), i, j, key))
    entries.sort(key=lambda e: (-e[0], e[1]))
    taken = {e[2] for e in entries[:slots]}
    merge = {}
    weights = {j: float(sums[j]) for j in taken}
    for key, mem in groups.items():
        kept = [j for j in mem if j in taken]
        for j in mem:
            if j in taken or not kept:
                continue
            same = [m for m in kept if grassy[m] == grassy[j]]
            dst = (same or kept)[0]
            merge[j] = dst
            weights[dst] += float(sums[j])
    kept = sorted(taken, key=lambda j: -weights[j])
    return kept, merge, weights


def plan_slots(kept, weights=None, rounds=3):
    """kept: {(qr, qc): [table index, ...] (the quadrant's textures, most weight first, at most SLOTS)} ->
    {(qr, qc): [table index per byte 0..4]}.
    2026-11-22 (owner's grey edge strips): each texture gets ONE position for the whole tile where it can (a greedy
    colouring of the textures with SLOTS colours: two textures conflict as much as they meet in one quadrant (must
    differ) or across a quadrant edge, 8 neighbours), so a texture on both sides of an edge has the same byte there.
    A quadrant whose textures still collide moves the lighter one to the free position its neighbours agree with
    most; unused positions take the byte most neighbours hold there (blending equal bytes changes nothing).
    weights: {(qr, qc): {table index: weight}} (default: 5, 4, 3, 2, 1 by rank)."""
    if weights is None:
        weights = {q: {t: float(SLOTS - i) for i, t in enumerate(ts)} for q, ts in kept.items()}
    nbr8 = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)]
    conflict = {}
    total = {}

    def add(a, b, w):
        if a != b:
            key = (a, b) if a < b else (b, a)
            conflict[key] = conflict.get(key, 0.0) + w
    for q, ts in kept.items():
        wq = weights[q]
        for t in ts:
            total[t] = total.get(t, 0.0) + wq.get(t, 0.0)
        for i, a in enumerate(ts):                              # same quadrant: must differ
            for b in ts[i + 1:]:
                add(a, b, 1e6)
        for dr, dc in nbr8:                                     # across an edge or corner
            o = (q[0] + dr, q[1] + dc)
            if o not in kept or o < q:
                continue
            wo = weights[o]
            for a in ts:
                for b in kept[o]:
                    if a != b and b not in ts and a not in kept[o]:
                        add(a, b, min(wq.get(a, 0.0), wo.get(b, 0.0)))
    colour = {}
    for t in sorted(total, key=lambda t: -total[t]):            # heaviest first
        cost = [0.0] * SLOTS
        for u, cu in colour.items():
            key = (t, u) if t < u else (u, t)
            cost[cu] += conflict.get(key, 0.0)
        colour[t] = min(range(SLOTS), key=lambda c: (cost[c], c))
    for _ in range(rounds):                                     # a few passes of local improvement
        changed = False
        for t in sorted(total, key=lambda t: -total[t]):
            cost = [0.0] * SLOTS
            for u, cu in colour.items():
                if u != t:
                    key = (t, u) if t < u else (u, t)
                    cost[cu] += conflict.get(key, 0.0)
            best = min(range(SLOTS), key=lambda c: (cost[c], c != colour[t], c))
            if best != colour[t]:
                colour[t], changed = best, True
        if not changed:
            break
    out = {}
    for q in sorted(kept):
        ts = sorted(kept[q][:SLOTS], key=lambda t: -weights[q].get(t, 0.0))
        slots = [None] * SLOTS
        homeless = []
        for t in ts:
            c = colour[t]
            if slots[c] is None:
                slots[c] = t
            else:
                homeless.append(t)
        for t in homeless:                                      # a free position, the one neighbours agree with most
            free = [c for c in range(SLOTS) if slots[c] is None]
            score = {c: sum(1 for dr, dc in nbr8 if (q[0] + dr, q[1] + dc) in kept
                            and t in kept[(q[0] + dr, q[1] + dc)]
                            and colour.get(t) == c) for c in free}
            slots[max(free, key=lambda c: (score[c], -c))] = t
        out[q] = slots
    # local clean-up: around Riverwood about ten textures meet in neighbouring quadrants, more than SLOTS colours can
    # keep apart, so within each quadrant swap two positions (a texture or an empty one) whenever more textures it
    # shares with its neighbours then sit at the neighbour's position (edges count 2, corners 1)
    real = {q: set(ts) for q, ts in kept.items()}
    near = [((dr, dc), 2 if dr == 0 or dc == 0 else 1) for dr, dc in nbr8]
    share = {}                                                  # each texture's share of its quadrant's weight
    for q, wq in weights.items():
        tot = sum(wq.get(t, 0.0) for t in kept[q]) or 1.0
        share[q] = {t: wq.get(t, 0.0) / tot for t in kept[q]}

    def matches(q, slots, c):
        """How much lines up at position c: per neighbour holding the same texture there, the smaller of its two
        shares (the texture that covers more of both quadrants matters more), edges twice corners."""
        t = slots[c]
        if t is None or t not in real[q]:
            return 0.0
        n_ = 0.0
        for (dr, dc), w in near:
            o = (q[0] + dr, q[1] + dc)
            if o in out and t in real[o] and out[o][c] == t:
                n_ += w * min(share[q][t], share[o][t])
        return n_
    import random
    rng = random.Random(1)

    def total_matches():
        return sum(matches(q, out[q], c) for q in out for c in range(SLOTS))

    def sweep(plateau):
        improved = False
        for q in sorted(out):
            slots = out[q]
            for c1 in range(SLOTS):
                for c2 in range(c1 + 1, SLOTS):
                    if slots[c1] is None and slots[c2] is None:
                        continue
                    before = matches(q, slots, c1) + matches(q, slots, c2)
                    slots[c1], slots[c2] = slots[c2], slots[c1]
                    after = matches(q, slots, c1) + matches(q, slots, c2)
                    if after > before + 1e-9:
                        improved = True
                    elif abs(after - before) <= 1e-9 and plateau and rng.random() < 0.5:
                        pass                                    # a sideways step, to get past local optima
                    else:
                        slots[c1], slots[c2] = slots[c2], slots[c1]
        return improved
    for _ in range(6):
        if not sweep(False):
            break
    best, best_out = total_matches(), {q: list(v) for q, v in out.items()}
    for _ in range(4):                                          # a few sideways walks, each polished; keep the best
        sweep(True)
        for _ in range(6):
            if not sweep(False):
                break
        sc = total_matches()
        if sc > best + 1e-9:
            best, best_out = sc, {q: list(v) for q, v in out.items()}
    out = best_out
    for _ in range(2):                                          # unused positions: the neighbours' byte there
        for q in sorted(out):
            for c in range(SLOTS):
                if out[q][c] is not None and out[q][c] in kept[q]:
                    continue
                votes = {}
                for dr, dc in nbr8:
                    o = out.get((q[0] + dr, q[1] + dc))
                    if o is not None and o[c] is not None:
                        votes[o[c]] = votes.get(o[c], 0) + (2 if dr == 0 or dc == 0 else 1)
                if votes:
                    out[q][c] = max(votes, key=lambda t: (votes[t], -t))
    for q in out:
        out[q] = [t if t is not None else kept[q][0] for t in out[q]]
    return out


def encode_band_aligned(weights, ids, slot_rows, neighbours, coords, n, index_rule=INDEX_RULE, edge=EDGE_SAMPLES,
                        stats=None, partial=False):
    """One 64-row band with planned slots. weights [k, 64, cols] (plane j = table entry j, form id ids[j]); slot_rows
    [nq][5] table indices
    for this band's quadrants; neighbours(qc, side) -> the neighbour's 5 table indices or None (side: 'w', 'e', 's',
    'n'); n: table length. Each sample takes one of its quadrant's textures by the shared noise threshold (as "noise");
    within `edge` samples of a side whose neighbour holds a different index at that position, positions that differ
    are not used. Returns (quad map row [nq, 8] uint8, words [64, cols] uint16)."""
    k, rows, cols = weights.shape
    nq = cols // 64
    xs_m, ys_m = coords
    u_all = blend_noise(xs_m, ys_m, 0)
    qrow = np.zeros((nq, 8), np.uint8)
    out = np.zeros((rows, cols), np.uint16)
    rr, cc = np.mgrid[0:64, 0:64]
    near = {"w": cc < edge, "e": cc >= 64 - edge, "s": rr < edge, "n": rr >= 64 - edge}
    for qc in range(nq):
        slots = slot_rows[qc]
        for b in range(SLOTS):
            qrow[qc, b] = byte_for(slots[b], n, index_rule)
        w = weights[:, :, qc * 64:(qc + 1) * 64]
        u = u_all[:, qc * 64:(qc + 1) * 64]
        allowed = np.ones((SLOTS, 64, 64), bool)
        for side, mask in near.items():
            nb = neighbours(qc, side)
            if nb is None:
                continue
            for b in range(SLOTS):
                if nb[b] != slots[b]:
                    allowed[b] &= ~mask
        texs = []                                             # distinct textures, fixed order (by form id)
        for b in range(SLOTS):
            if slots[b] not in texs:
                texs.append(slots[b])
        texs.sort(key=lambda t: ids[t])
        wts = np.stack([w[t] for t in texs])
        # a texture is usable at a sample if any of its positions is allowed there
        ok = np.stack([np.any([allowed[b] for b in range(SLOTS) if slots[b] == t], axis=0) for t in texs])
        if partial:
            # 2026-11-22 ("smooth": vanilla hand-made worlds use partial alphas 1..6 on most samples, verified by
            # vanilla_btd_survey.py): Skyrim's own mix, each texture at its planned position, alphas solved top-down
            # (byte 0 on top, byte 4 the base: shows what the overlays leave). Near an edge, textures whose position
            # differs from the neighbour's give their share to the others where any allowed one has weight.
            pos = {}
            for b in range(SLOTS):
                pos.setdefault(slots[b], b)
            wts = np.stack([w[t] for t in texs])
            wr = np.where(ok, wts, 0.0)
            use = wr.sum(axis=0) > 0
            wf = np.where(use[None], wr, wts)
            tot = wf.sum(axis=0)
            frac = np.where(tot > 0, wf / np.where(tot > 0, tot, 1.0), 0.0)
            share = {t: frac[i] for i, t in enumerate(texs)}
            base_t = slots[SLOTS - 1]
            if stats is not None:
                moved = np.abs(np.where(tot > 0, wf / np.where(tot > 0, tot, 1.0), 0.0)
                               - wts / np.maximum(wts.sum(axis=0), 1e-9)).sum(axis=0) / 2
                stats["edge_changed"] = stats.get("edge_changed", 0) + float(moved.sum())
                stats["samples"] = stats.get("samples", 0) + 64 * 64
            rem = np.ones((64, 64))
            word = np.zeros((64, 64), np.uint16)
            for b in range(SLOTS - 1):
                t = slots[b]
                if t == base_t or pos.get(t) != b:              # the base (and duplicates) take no alpha
                    continue
                a = np.clip(share[t] / np.maximum(rem, 1e-6), 0.0, 1.0)
                q = np.rint(a * 7.0).astype(np.uint16)
                word |= q << (3 * b)
                rem = rem * (1.0 - q / 7.0)
            out[:, qc * 64:(qc + 1) * 64] = word
            continue
        free_pick = None
        pick = np.full((64, 64), -1, np.int64)
        for mask in (np.ones_like(ok), ok, np.ones_like(ok)):  # unrestricted (for the stats), allowed first, then any
            if free_pick is None:
                wm = wts
                tot = wm.sum(axis=0)
                cum = np.cumsum(wm, axis=0) / np.where(tot > 0, tot, 1.0)
                free_pick = np.where((u[None] < cum).any(axis=0), np.argmax(u[None] < cum, axis=0),
                                     np.argmax(wm, axis=0))
                continue
            wm = np.where(mask, wts, 0.0)
            tot = wm.sum(axis=0)
            cum = np.cumsum(wm, axis=0) / np.where(tot > 0, tot, 1.0)
            first = np.argmax(u[None] < cum, axis=0)
            first = np.where((u[None] < cum).any(axis=0), first, np.argmax(wm, axis=0))
            pick = np.where((pick < 0) & (tot > 0), first, pick)
        pick = np.where(pick < 0, int(np.argmax(wts.reshape(len(texs), -1).sum(axis=1))), pick)
        if stats is not None:
            stats["edge_changed"] = stats.get("edge_changed", 0) + int((pick != free_pick).sum())
            stats["samples"] = stats.get("samples", 0) + 64 * 64
        chosen = np.full((64, 64), -1, np.int64)
        for b in range(SLOTS):                                # the texture's allowed position, else its first one
            hit = (pick >= 0) & (np.asarray(texs)[pick] == slots[b])
            chosen = np.where((chosen < 0) & hit & allowed[b], b, chosen)
        for b in range(SLOTS):
            hit = (np.asarray(texs)[pick] == slots[b])
            chosen = np.where((chosen < 0) & hit, b, chosen)
        word = np.zeros((64, 64), np.uint16)
        for b in range(SLOTS - 1):                            # byte 4 is the base: every alpha 0 shows it
            word |= np.where(chosen == b, 7, 0).astype(np.uint16) << (3 * b)
        out[:, qc * 64:(qc + 1) * 64] = word
    return qrow, out


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

