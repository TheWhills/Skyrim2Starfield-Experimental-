"""Skyrim's own ground textures on Starfield terrain (make_skyrim_overlay.py build --skyrim-ground).

The BTD's LTEX table holds raw FormIDs. A new LTEX in a mod plugin has no fixed FormID at run time (its load-order
index varies), so instead the terrain plugin OVERRIDES spare Starfield.esm LTEX records: ones no vanilla BTD lists and
no biome / ground cover / planet / surface block record names. Each override keeps the vanilla record (material type,
friction) and points BNAM at a material made from a Skyrim landscape texture set (TXST TX00 diffuse, TX01 normal),
cloned from the plain ground's own vanilla material so the terrain shader sees what it expects. Vanilla planets do not
use those records, so they look the same.

Skyrim textures beyond the number of free records fall back to the converted texture of the same category with the
most coverage (else the category's Starfield pick). Supported hypothesis, not yet tested in game: that a terrain LTEX
override with a cloned single-layer material renders.
"""
import os
import struct
import zipfile
from typing import Dict, Iterable, List, Optional

from fo4sf import fo4land, landtex

REFERENCING = (b"BIOM", b"GCVR", b"PNDT", b"SFBK")      # records whose data may name an LTEX


def ltex_fields(sf_esm: str) -> Dict[int, dict]:
    """{LTEX form id: {"edid", "bnam"}} of every Starfield.esm LTEX."""
    out = {}
    with fo4land.Plugin(sf_esm) as p:
        rng = p.top_group(b"LTEX")
        if rng is None:
            return out
        for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
            if typ == "GRUP":
                continue
            rec = {"edid": "", "bnam": ""}
            for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                if sig == b"EDID":
                    rec["edid"] = fo4land.zstring(d)
                elif sig == b"BNAM":
                    rec["bnam"] = fo4land.zstring(d)
            out[fid] = rec
    return out


def referenced(sf_esm: str, fids: Iterable[int], sigs=REFERENCING) -> set:
    """The fids that appear as a 4-byte value anywhere in the data of the given record types (top groups)."""
    want = {struct.pack("<I", f): f for f in fids}
    hit = set()
    with fo4land.Plugin(sf_esm) as p:
        for sig in sigs:
            rng = p.top_group(sig)
            if rng is None:
                continue
            for typ, off, _fl, _fid in fo4land.iter_items(p.buf, *rng):
                if typ == "GRUP":
                    continue
                data = fo4land.record_data(p.buf, off)
                for k, f in want.items():
                    if f not in hit and k in data:
                        hit.add(f)
    return hit


def free_slots(sf_esm: str, usage: Dict[int, int], fields: Optional[Dict[int, dict]] = None) -> List[int]:
    """Starfield.esm LTEX records safe to override: listed by no vanilla BTD, named by no REFERENCING record, not the
    plain ground. Sorted by FormID (stable between builds)."""
    fields = fields if fields is not None else ltex_fields(sf_esm)
    cand = [f for f in sorted(fields) if usage.get(f, 0) == 0 and f != landtex.PLAIN_GROUND]
    used = referenced(sf_esm, cand)
    return [f for f in cand if f not in used]


def vertex_tints(cells, colours) -> Dict[int, tuple]:
    """{Skyrim LTEX: (r, g, b) 0..1}: the mean VCLR vertex colour where each texture is painted, weighted by its
    weight. Skyrim multiplies a ground texture by the vertex colour under it; Starfield has no per-vertex land colour,
    so --skyrim-ground-tint bakes this mean into each texture's colour (an approximation: one tint per texture)."""
    import numpy as np
    acc: Dict[int, np.ndarray] = {}
    tot: Dict[int, float] = {}
    for xy, ws in cells.items():
        vc = colours.get(xy)
        if vc is None:
            continue
        c = vc.astype(np.float64) / 255.0
        for fid, w in ws.items():
            s = float(w.sum())
            if s <= 0:
                continue
            acc[fid] = acc.get(fid, 0.0) + (c * w[..., None]).sum(axis=(0, 1))
            tot[fid] = tot.get(fid, 0.0) + s
    return {f: tuple(float(v) for v in acc[f] / tot[f]) for f in acc}


def coverage(cells) -> Dict[int, float]:
    """{Skyrim LTEX: summed weight over the map} from landtex.read_world_textures cells."""
    tot: Dict[int, float] = {}
    for ws in cells.values():
        for fid, w in ws.items():
            tot[fid] = tot.get(fid, 0.0) + float(w.sum())
    return tot


def plan(ltex: Dict[int, dict], cov: Dict[int, float], slots: List[int]):
    """(chosen [(skyrim fid, slot fid)], fallback {skyrim fid: chosen skyrim fid}): the most-covering Skyrim textures
    with a diffuse get the free slots in order; every other covered Skyrim texture borrows the chosen one of its
    category with the most coverage (absent: no entry, the category's Starfield pick applies)."""
    ranked = [f for f in sorted(cov, key=lambda f: -cov[f]) if f in ltex and ltex[f].get("diffuse") and cov[f] > 0]
    chosen = list(zip(ranked, slots))
    picked = {f for f, _s in chosen}
    best = {}
    for f, _s in chosen:
        c = landtex.category(ltex[f]["edid"], ltex[f]["diffuse"])
        best.setdefault(c, f)                       # ranked order: first is the most covering
    fallback = {}
    for f in ranked:
        if f not in picked:
            c = landtex.category(ltex[f]["edid"], ltex[f]["diffuse"])
            if c in best:
                fallback[f] = best[c]
    return chosen, fallback


def template_material(content_resources: str, bnam: str) -> dict:
    """The vanilla material a Starfield LTEX names (BNAM), read from the Creation Kit's ContentResources.zip."""
    import json
    want = bnam.replace("\\", "/").lower().lstrip("/")
    base = want.rsplit("/", 1)[-1]
    with zipfile.ZipFile(content_resources) as z:
        names = z.namelist()
        hit = next((n for n in names if n.lower().endswith(want)), None) or \
            next((n for n in names if n.lower().rsplit("/", 1)[-1] == base), None)
        if hit is None:
            raise FileNotFoundError(f"ground material {bnam!r} not in {os.path.basename(content_resources)}")
        mat = json.loads(z.read(hit).decode("utf-8-sig"))
    if "Layer1" not in mat.get("Summary", {}):
        raise ValueError(f"ground material {hit} is not a single-layer material (Summary: {list(mat.get('Summary', {}))})")
    return mat


def texture_path(p: str) -> str:
    """A Skyrim TXST path as the archives store it: TXST values omit the leading 'textures\\' folder."""
    p = (p or "").replace("/", "\\").lstrip("\\")
    return p if not p or p.lower().startswith("textures\\") else "textures\\" + p


TEST_COLOURS = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
                "magenta": (255, 0, 255), "cyan": (0, 255, 255), "orange": (255, 128, 0), "white": (255, 255, 255),
                "black": (0, 0, 0)}


def colour_dds(rgb, size: int = 64) -> bytes:
    """A solid colour RGBA DDS with a faint 8 x 8 checker (so the tiling stays visible): --skyrim-ground-colours."""
    import tempfile
    import numpy as np
    from fo4sf import textures
    yy, xx = np.mgrid[0:size, 0:size] // (size // 8)
    on = ((yy + xx) % 2).astype(bool)
    px = np.zeros((size, size, 4), np.uint8)
    px[..., :3] = rgb
    px[on, :3] = (np.array(rgb) * 0.75).astype(np.uint8)
    px[..., 3] = 255
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "c.dds")
        textures.write_dds_dx10(p, size, size, textures.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
        with open(p, "rb") as f:
            return f.read()


def parse_colours(spec: str) -> dict:
    """'LDirt02=cyan,LPineForest01=red' -> {Skyrim LTEX EditorID (lower case): RGB}."""
    out = {}
    for part in (spec or "").split(","):
        if not part.strip():
            continue
        edid, _, name = part.partition("=")
        if name.strip().lower() not in TEST_COLOURS:
            raise ValueError(f"colour {name!r} not in {sorted(TEST_COLOURS)}")
        out[edid.strip().lower()] = TEST_COLOURS[name.strip().lower()]
    return out


def checker_dds(size: int = 256, cells: int = 8) -> bytes:
    """A loud magenta / green checkerboard RGBA DDS (--skyrim-ground-test): on the ground in game it proves that the
    overridden LTEX records and their materials are what the terrain draws, whatever the planet tints."""
    import tempfile
    import numpy as np
    from fo4sf import textures
    yy, xx = np.mgrid[0:size, 0:size] // (size // cells)
    on = ((yy + xx) % 2).astype(bool)
    px = np.zeros((size, size, 4), np.uint8)
    px[on] = (255, 0, 255, 255)
    px[~on] = (0, 255, 0, 255)
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "checker.dds")
        textures.write_dds_dx10(p, size, size, textures.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
        with open(p, "rb") as f:
            return f.read()


SKYRIM_TILING_M = 4096.0 / 12.0 / 70.0   # ~4.88 m: Skyrim-sized detail in the owner's side-by-sides (9.75 was 2x)


def flat_textures(staging: str, texconv: str, prefix: str = "skyrim") -> dict:
    """Shared neutral maps for every Skyrim ground material: AmbientOcclusion white (no occlusion) and Height at the
    terrain shader's displacement midpoint (flat). The vanilla template's own footprint AO / height maps showed as a
    white speckle and bumps under the Skyrim colours (owner's checkerboard test). Returns {slot: game path}."""
    import numpy as np
    from fo4sf import convert_material as cm, textures
    out = {}
    for slot, value, name in (("AmbientOcclusion", 255, "_flat_ao"), ("Height", 128, "_flat_height"),
                              ("RoughnessMatte", 255, "_flat_rough")):     # fully rough: Skyrim's matte ground
        rel = f"textures/{prefix}/ground/{name}.dds"
        dst = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        textures.write_r8(dst, np.full((4, 4), value, np.uint8))
        textures.texconv(texconv, dst, os.path.dirname(dst), "BC4_UNORM")
        out[slot] = cm.game_path(rel)
    return out


def height_from_diffuse(diffuse_dds: bytes, texconv: str, dst: str, size: int = 256) -> None:
    """A blend height map for one Skyrim ground texture, from its own detail: luminance, high-passed (texture-scale
    detail only, no overall brightness), normalised to mean 128 and a fixed spread so that every texture competes on
    equal terms when Terrain1Layer blends layers by height. With flat height maps the BTD's coarse 3-bit layer weights
    showed as hard-edged blobs (owner's Jemison close-ups: white snow patches over dirt). Written as BC4 to dst."""
    import tempfile
    import numpy as np
    from fo4sf import textures
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "h.dds")
        with open(src, "wb") as f:
            f.write(diffuse_dds)
        textures.texconv(texconv, src, tmp, "R8G8B8A8_UNORM", ("-m", "1"))
        raw = open(src, "rb").read()
    h = textures.read_dds_header(raw)
    px = np.frombuffer(raw[h["data_offset"]:h["data_offset"] + h["width"] * h["height"] * 4], np.uint8)
    rgb = px.reshape(h["height"], h["width"], 4)[:, :, :3].astype(np.float32)
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    step = max(1, min(lum.shape) // size)               # box-downsample to about `size`
    hh, ww = (lum.shape[0] // step) * step, (lum.shape[1] // step) * step
    lum = lum[:hh, :ww].reshape(hh // step, step, ww // step, step).mean(axis=(1, 3))
    k = max(1, min(lum.shape) // 16)                     # high-pass: minus a wide (wrapping) box blur
    blur = lum.copy()
    for ax in (0, 1):
        blur = sum(np.roll(blur, d, axis=ax) for d in range(-k, k + 1)) / (2 * k + 1)
    det = lum - blur
    sd = float(det.std()) or 1.0
    out = np.clip(128.0 + det / sd * 40.0, 0, 255).astype(np.uint8)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    textures.write_r8(dst, out)
    textures.texconv(texconv, dst, os.path.dirname(dst), "BC4_UNORM")


def terrain_settings(mat: dict, tiling_m: float, max_displacement: float = 0.0) -> int:
    """Set the Terrain1Layer TerrainSettingsComponent: TilingDistance (metres per texture repeat; vanilla dirt 3.2) and
    MaxDisplacement (0: the flat height map must not lift the ground). Returns how many components were changed."""
    n = 0
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            if c.get("Type") == "BSMaterial::TerrainSettingsComponent":
                c.setdefault("Data", {})["TilingDistance"] = f"{tiling_m:g}"
                c["Data"]["MaxDisplacement"] = f"{max_displacement:g}"
                n += 1
    return n


def bnam_for(material_rel: str, vanilla_bnam: str) -> str:
    """Our staged material path ('materials\\skyrim\\ground\\x.mat') written the way vanilla BNAM values are."""
    rel = material_rel.replace("/", "\\")
    if not vanilla_bnam.lower().replace("/", "\\").startswith("materials\\") and rel.lower().startswith("materials\\"):
        rel = rel[len("materials\\"):]
    return rel
