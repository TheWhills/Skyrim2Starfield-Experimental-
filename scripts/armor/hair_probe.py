"""Look at how Starfield's own hairstyles are textured, to compare with the converted Skyrim hair (owner 2026-11-03:
"wondering if we need to get it adopting Starfield's stranding pattern").

For the vanilla looks-menu hairstyles (the bob, the hairstyle copied for the Skyrim ones, and a few more), on the
owner's PC: reads each hairstyle's model, its materials (.mat from the Creation Kit's ContentResources.zip), every
texture they name (from the game's own archives) and writes into --out:

  * hair_probe.json: per hairstyle its materials, their hair shader settings and texture slots, and per texture its
    size and value statistics (mean / spread per channel; for the opacity map the solid share and which way the
    strands run; for the depth-offset map its percentiles: whether vanilla hair is offset at all);
  * <hairstyle>_<slot>.png: each texture shrunk to --size pixels, to look at.

Read-only on the game's files.

    python -I scripts\\armor\\hair_probe.py --starfield "<Starfield folder>" --texconv "<texconv.exe>"
        --out C:\\Modding\\work\\hair_probe [--edid Bob --edid Long]
"""
import argparse
import json
import os
import re
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from fo4sf import convert_material as cm  # noqa: E402
from fo4sf import nif as nifmod, pipeline, sfplugin, textures  # noqa: E402
import hair_pack  # noqa: E402

CHARGEN = ("HeadPartsChargenOptionsFemale", "HeadPartsChargenOptionsMale")
SLOT_NAMES = {i: k for k, i in cm.HAIR_SLOTS.items()}


def write_png(path: str, img) -> None:
    """A minimal PNG writer (8-bit grey, RGB or RGBA) so the probe needs nothing beyond numpy."""
    a = np.asarray(img, np.uint8)
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, c = a.shape
    kind = {1: 0, 3: 2, 4: 6}[c]
    raw = b"".join(b"\0" + a[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, kind, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def shrink(img, size: int):
    """The image cut down (every n-th texel) to at most `size` on its longer side."""
    a = np.asarray(img)
    step = max(1, int(np.ceil(max(a.shape[:2]) / float(size))))
    return a[::step, ::step]


def material_paths(raw: bytes) -> list:
    """The .mat paths a Starfield NIF's shapes use (the names of its BSLightingShaderProperty blocks)."""
    n = nifmod.parse(raw)
    out = []
    for i in range(len(n.blocks)):
        if n.type_of(i) != "BSLightingShaderProperty":
            continue
        idx = struct.unpack_from("<i", n.blocks[i], 0)[0]
        if 0 <= idx < len(n.strings):
            p = n.strings[idx].decode("latin-1")
            if p and p not in out:
                out.append(p)
    return out


def read_material(cr_zip: str, path: str):
    """A vanilla .mat (JSON) from ContentResources.zip by the path a NIF names, or None."""
    p = path.replace("\\", "/").lstrip("/")
    for cand in (p, "materials/" + p if not p.lower().startswith("materials/") else p):
        try:
            return cm.read_template_path(cr_zip, cand)
        except (StopIteration, KeyError, OSError, ValueError):
            continue
    return None


def material_info(mat: dict) -> dict:
    """{'textures': {slot: game path}, 'hair_settings': {...}, 'shader': name} of a .mat's objects."""
    info = {"textures": {}, "hair_settings": None, "shader": None}
    for o in mat.get("Objects", []):
        for c in o.get("Components", []):
            t = c.get("Type", "")
            if t == "BSMaterial::MRTextureFile":
                slot = SLOT_NAMES.get(c.get("Index"), f"slot{c.get('Index')}")
                info["textures"].setdefault(slot, c["Data"]["FileName"])
            elif t == "BSMaterial::HairSettingsComponent":
                info["hair_settings"] = c.get("Data")
            elif t == "BSMaterial::ShaderModelComponent":
                info["shader"] = c.get("Data", {}).get("FileName")
    return info


def decode_rgba(dds: bytes, texconv: str):
    """(h, w, 4) uint8 of a DDS, its top mip, through texconv."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "t.dds")
        with open(p, "wb") as fh:
            fh.write(dds)
        textures.texconv(texconv, p, tmp, "R8G8B8A8_UNORM", ("-m", "1"))
        with open(p, "rb") as fh:
            raw = fh.read()
    hd = textures.read_dds_header(raw)
    n = hd["width"] * hd["height"] * 4
    return np.frombuffer(raw[hd["data_offset"]:hd["data_offset"] + n], np.uint8).reshape(hd["height"], hd["width"], 4)


def texture_stats(slot: str, px) -> dict:
    """Size and value statistics of a decoded texture (single-channel maps read from red)."""
    a = np.asarray(px)
    out = {"size": [int(a.shape[1]), int(a.shape[0])]}
    grey = a[:, :, 0].astype(np.float64)
    if slot == "Albedo":
        rgb = a[:, :, :3].astype(np.float64)
        out["mean_rgb"] = [round(float(x), 1) for x in rgb.reshape(-1, 3).mean(0)]
        out["luminance_spread"] = round(float((rgb @ [0.2126, 0.7152, 0.0722]).std()), 1)
    else:
        out["mean"] = round(float(grey.mean()), 1)
        out["percentiles_10_50_90"] = [round(float(np.percentile(grey, q)), 1) for q in (10, 50, 90)]
    if slot == "Opacity":
        out["solid_share"] = round(float((grey >= 128).mean()), 3)
        across = pipeline.strand_orientation(a[:, :, 0])
        out["strands_along_u_share"] = round(float(across.mean()), 3)
    return out


def chosen_parts(esm: str, wanted: list, limit: int = 4) -> list:
    """The vanilla hair head parts (type 3) to look at: those of the looks-menu lists whose EditorID contains one of
    `wanted`, else the bob plus the first few of each list."""
    recs = sfplugin.records(esm, [b"HDPT", b"FLST"])
    hdpt = {r[3]: r for r in recs if r[0] == b"HDPT"}
    ids = []
    for r in recs:
        if r[0] == b"FLST" and sfplugin.edid(r[2]) in CHARGEN:
            ids += [struct.unpack_from("<I", bytes(d), 0)[0] for s, d in r[2] if s == b"LNAM" and len(d) >= 4]
    parts = [hdpt[i] for i in ids if i in hdpt
             and next((struct.unpack_from("<I", bytes(d), 0)[0] for s, d in hdpt[i][2] if s == b"PNAM"), None) == 3]
    if wanted:
        keys = [w.lower() for w in wanted]
        return [p for p in parts if any(k in sfplugin.edid(p[2]).lower() for k in keys)]
    bob = [p for p in parts if "bob" in sfplugin.edid(p[2]).lower()][:2]
    return bob + [p for p in parts if p not in bob][:limit]


def probe(starfield: str, texconv: str, out: str, wanted=(), size: int = 512, read=None, cr_zip=None) -> dict:
    read = read or (lambda rel: hair_pack.read_game_file(starfield, rel))
    cr_zip = cr_zip or os.path.join(starfield, "Tools", "ContentResources.zip")
    os.makedirs(out, exist_ok=True)
    report = {"hairstyles": []}
    for rec in chosen_parts(os.path.join(starfield, "Data", "Starfield.esm"), list(wanted)):
        edid = sfplugin.edid(rec[2])
        model = next((bytes(x).rstrip(b"\0").decode("latin-1") for s, x in rec[2] if s == b"MODL"), "")
        row = {"edid": edid, "model": model, "materials": []}
        raw = read("meshes/" + model.replace("\\", "/")) if model else None
        if raw is None:
            row["error"] = "model not found in the game's archives"
            report["hairstyles"].append(row)
            continue
        for mp in material_paths(raw):
            mat = read_material(cr_zip, mp)
            m = {"path": mp}
            if mat is None:
                m["error"] = "not in ContentResources.zip"
                row["materials"].append(m)
                continue
            info = material_info(mat)
            m.update(shader=info["shader"], hair_settings=info["hair_settings"], textures={})
            for slot, game_path in info["textures"].items():
                rel = re.sub(r"^data[\\/]", "", game_path, flags=re.I).replace("\\", "/")
                dds = read(rel)
                if dds is None:
                    m["textures"][slot] = {"path": game_path, "error": "not in the game's archives"}
                    continue
                try:
                    px = decode_rgba(dds, texconv)
                except Exception as e:                       # noqa: BLE001 (report only)
                    m["textures"][slot] = {"path": game_path, "error": f"{type(e).__name__}: {e}"}
                    continue
                st = texture_stats(slot, px)
                st["path"] = game_path
                png = re.sub(r"[^A-Za-z0-9]+", "_", f"{edid}_{os.path.basename(mp)}_{slot}") + ".png"
                small = shrink(px, size)
                write_png(os.path.join(out, png), small if slot in ("Albedo",) else small[:, :, 0])
                st["png"] = png
                m["textures"][slot] = st
            row["materials"].append(m)
        report["hairstyles"].append(row)
    with open(os.path.join(out, "hair_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True, help="a folder outside the repository for the report and pictures")
    ap.add_argument("--edid", action="append", default=[], help="text the hairstyles' EditorIDs must contain")
    ap.add_argument("--size", type=int, default=512)
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    rep = probe(a.starfield, a.texconv, a.out, a.edid, a.size)
    for h in rep["hairstyles"]:
        print(h["edid"], "-", len(h["materials"]), "material(s)", h.get("error", ""))
    print("report:", os.path.join(a.out, "hair_probe.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
