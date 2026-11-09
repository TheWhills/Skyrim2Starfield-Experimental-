"""Why one NPC's converted outfit shows skin where another's with "the same" clothes does not (owner, 2026-11-09:
Delphine's dress shows bare skin through stitched patches on both shoulders; Ysolda's, the same dress, does not; both
test NPCs now have the same body, so the body is ruled out). Read-only, Skyrim side only.

    python -I scripts\\armor\\outfit_probe.py --skyrim-data "$sky" --npc Delphine --npc Ysolda --out C:\\Modding\\work\\outfits

Per NPC: its default outfit's armors, the worn mesh for its race / sex (os_convert.worn_meshes, as gear_fit picks it),
and per shape of each mesh: the texture set, Skyrim's NiAlphaProperty (test / blend / threshold), double-sided, the
diffuse texture's format and alpha: share of texels under the alpha-test threshold over the whole texture, at the
shape's vertices, and at its shoulder vertices (weighted mostly to clavicle / upper-arm bones). The Starfield cutout
keeps Skyrim's alpha test (pipeline: opacity map + AlphaTestThreshold), so a dress whose diffuse alpha is low at the
shoulders comes out with holes there. Writes outfit_probe.json.
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import bsa, skyrimarmor, skyrimnif, skyrimskin, textures  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
import os_convert  # noqa: E402

SHOULDER_BONES = ("clavicle", "upperarm")


def _bc1_alpha(blocks: np.ndarray) -> np.ndarray:
    """(N, 16) alpha (0 / 255) of BC1 blocks (N, 8): 0 where the block is in 3-colour mode (c0 <= c1) and the texel
    uses index 3 (punch-through)."""
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    word = np.zeros(len(blocks), np.uint32)
    for i in range(4):
        word |= blocks[:, 4 + i].astype(np.uint32) << np.uint32(8 * i)
    out = np.full((len(blocks), 16), 255, np.uint8)
    three = c0 <= c1
    for px in range(16):
        idx = (word >> np.uint32(2 * px)) & np.uint32(3)
        out[three & (idx == 3), px] = 0
    return out


def alpha_plane(dds: bytes):
    """(alpha plane (H, W) uint8 of mip 0, format name) of a BC1 / BC3 DDS; (None, format) for others."""
    h = textures.read_dds_header(dds)
    fmt = h["fourcc"].decode("latin-1", "replace").strip("\0") if h["dxgi"] is None else f"DXGI {h['dxgi']}"
    w, ht = h["width"], h["height"]
    bw, bh = max(1, (w + 3) // 4), max(1, (ht + 3) // 4)
    off = h["data_offset"]
    if h["fourcc"] == b"DXT1" or h["dxgi"] in (71, 72):
        blocks = np.frombuffer(dds, np.uint8, bw * bh * 8, off).reshape(-1, 8)
        vals = _bc1_alpha(blocks)
    elif h["fourcc"] == b"DXT5" or h["dxgi"] in (77, 78):
        blocks = np.frombuffer(dds, np.uint8, bw * bh * 16, off).reshape(-1, 16)[:, :8]
        vals = textures._bc4_block_values(np.ascontiguousarray(blocks))
    else:
        return None, fmt
    plane = vals.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)[:ht, :w]
    return plane, fmt


def sample(plane: np.ndarray, uvs) -> np.ndarray:
    uv = np.asarray(uvs, float).reshape(-1, 2) % 1.0
    h, w = plane.shape
    x = np.clip((uv[:, 0] * w).astype(int), 0, w - 1)
    y = np.clip((uv[:, 1] * h).astype(int), 0, h - 1)
    return plane[y, x]


def shoulder_vertices(shape) -> np.ndarray:
    bones = [b.decode("latin-1", "replace").lower() for b in shape.bones]
    out = []
    for v, ws in enumerate(shape.weights):
        w = sum(x for b, x in ws if b < len(bones) and any(k in bones[b] for k in SHOULDER_BONES))
        if w >= 0.5:
            out.append(v)
    return np.array(out, int)


def shape_rows(nif_bytes: bytes, read) -> list:
    n = nifmod.parse(nif_bytes)
    rows = []
    for s in skyrimskin.skinned_shapes(n):
        tex = skyrimnif.texture_set(n, s.shader_ref) or []
        test, blend, thr = skyrimnif.alpha_test(n, s.alpha_ref)
        row = {"shape": s.name.decode("latin-1", "replace"), "vertices": len(s.positions),
               "diffuse": tex[0] if tex else None, "normal": tex[1] if len(tex) > 1 else None,
               "alpha_test": test, "alpha_blend": blend, "alpha_threshold": thr,
               "double_sided": skyrimnif.double_sided(n, s.shader_ref)}
        if tex and tex[0]:
            p = tex[0] if tex[0].lower().startswith("textures") else "textures\\" + tex[0]
            data = read(p)
            if data is None:
                row["diffuse_error"] = "not in Skyrim's archives"
            else:
                try:
                    plane, fmt = alpha_plane(data)
                except (textures.DdsError, ValueError) as e:
                    plane, fmt = None, f"? {e}"
                row["diffuse_format"] = fmt
                if plane is not None:
                    row["texture_under_threshold"] = round(float((plane < thr).mean()), 4)
                    if s.uvs:
                        at = sample(plane, s.uvs)
                        row["vertices_under_threshold"] = round(float((at < thr).mean()), 4)
                        sh = shoulder_vertices(s)
                        row["shoulder_vertices"] = int(len(sh))
                        if len(sh):
                            row["shoulder_under_threshold"] = round(float((at[sh] < thr).mean()), 4)
                            row["shoulder_alpha_min_median"] = [int(at[sh].min()), int(np.median(at[sh]))]
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True, help="Skyrim's Data folder (Skyrim.esm and the BSAs)")
    ap.add_argument("--npc", action="append", required=True, help="Skyrim NPC EditorID (repeat)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    inv = skyrimarmor.read_armor(esm)
    sky = bsa.SkyrimArchives(a.skyrim_data)
    read = lambda p: sky._read(bsa.norm(p))      # noqa: E731
    report = {}
    for who in a.npc:
        o = os_convert.outfit_armor(esm, who)
        female = o["npc"]["female"]
        rows = []
        for m in os_convert.worn_meshes(inv, o["armor"], o["race"], female):
            data = read(m["mesh"])
            row = dict(m)
            row["shapes"] = shape_rows(data, read) if data is not None else "not in Skyrim's archives"
            rows.append(row)
        report[who] = {"race": o["race"], "female": female,
                       "outfit": f"{o['npc'].get('outfit') or 0:08X}", "worn": rows, "skipped": o.get("skipped", [])}
        print(f"{who} ({o['race']}, {'female' if female else 'male'}), outfit {report[who]['outfit']}:")
        for r in rows:
            print(f"  {r['armor']}  {r['mesh']}")
            for s in r["shapes"] if isinstance(r["shapes"], list) else []:
                print(f"    {s['shape']}: {s['diffuse']}  test={s['alpha_test']} thr={s['alpha_threshold']} "
                      f"{s.get('diffuse_format', '')}  under thr: texture {s.get('texture_under_threshold')}, "
                      f"shoulders {s.get('shoulder_under_threshold')} ({s.get('shoulder_vertices')} vertices)")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "outfit_probe.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print("->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
