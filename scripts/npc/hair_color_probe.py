"""Find Starfield's hair colours (owner 2026-11-05: "if we could get hair colour matched up too"). Starfield stores an
NPC's hair colour as a NAME (NPC_ HCOL / FHCL); what colour each name is lives somewhere else. This read-only probe
collects the evidence on the owner's PC:

  * every HCOL / FHCL name Starfield.esm's NPCs use, with counts;
  * Starfield.esm's colour records (CLFM) whose EditorID or name mentions hair, with their colour;
  * archive files (Starfield - *.ba2) and Creation Kit material files (ContentResources.zip) whose path mentions hair
    colour / gradients, or one of the HCOL names;
  * each such texture decoded (texconv): size, mean colour, the colour along its middle row, a PNG to look at.

  * (2026-11-13) the looks menu's own hair colour gradients: Starfield.esm's AVMD SimpleGroup_Hair_<group> records
    pair each colour name (LNAM) with a gradient texture (VNAM, e.g. textures/actors/human/faces/hair/
    long_straight_hair_shared_grey_color.dds), one set per hairstyle group; every one is decoded, and the palette
    comes from --group's (default Long_Straight: the material the converted Skyrim hairs use,
    skyrim_hairs.STRAND_MATERIAL).

Writes into --out: hair_color_probe.json (all of it) and hair_colors.json ({"palette": {name: [r, g, b]}} for every
HCOL name it could tie to a colour: a CLFM of that name, or a texture whose file name holds the name; empty when
none), which face_fit.py --hair-colors reads.

    python -I scripts\\npc\\hair_color_probe.py --starfield "<Starfield folder>" --texconv "<texconv.exe>"
        --out C:\\Modding\\work\\hair_colors
"""
import argparse
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

import numpy as np  # noqa: E402

from fo4sf import ba2, fo4land, sfplugin  # noqa: E402

HINTS = ("haircolor", "hair_color", "haircolour", "hair_colour", "hairtint", "hair_tint", "haircol", "hairgradient",
         "hair_gradient", "colorgradient", "color_gradient", "hairramp", "hair_ramp", "hairlut", "hair_lut")


def npc_color_names(esm: str) -> dict:
    """{"hair": {name: count}, "facial_hair": {...}} of the HCOL / FHCL names Starfield.esm's NPCs use."""
    out = {"hair": {}, "facial_hair": {}}
    for _t, _h, subs, _f in sfplugin.records(esm, [b"NPC_"]):
        for sig, d in subs:
            if sig in (b"HCOL", b"FHCL"):
                n = fo4land.zstring(d)
                if n:
                    k = "hair" if sig == b"HCOL" else "facial_hair"
                    out[k][n] = out[k].get(n, 0) + 1
    return out


def color_records(esm: str, names) -> list:
    """CLFM records whose EditorID / FULL mention hair or equal an HCOL name: {"edid", "full", "rgba"}."""
    want = {n.lower() for n in names}
    out = []
    for _t, _h, subs, fid in sfplugin.records(esm, [b"CLFM"]):
        e = sfplugin.edid(subs)
        full = next((fo4land.zstring(d) for s, d in subs if s == b"FULL" and len(d) != 4), "")
        rgba = next((list(bytes(d)[:4]) for s, d in subs if s == b"CNAM" and len(d) >= 4), None)
        if "hair" in e.lower() or "hair" in full.lower() or e.lower() in want or full.lower() in want:
            out.append({"form_id": f"{fid:08X}", "edid": e, "full": full, "rgba": rgba})
    return out


GRADIENT_PREFIX = "SimpleGroup_Hair_"
DEFAULT_GROUP = "Long_Straight"


def gradient_textures(records) -> dict:
    """{group: [(colour name, texture path)]} from AVMD records (sfplugin.records tuples): each SimpleGroup_Hair_*
    record's LNAM (name) / VNAM (texture) pairs, in order."""
    out = {}
    for _t, _h, subs, _f in records:
        e = sfplugin.edid(subs)
        if not e.startswith(GRADIENT_PREFIX):
            continue
        pairs, name = [], None
        for sig, d in subs:
            if sig == b"LNAM":
                name = fo4land.zstring(d)
            elif sig == b"VNAM" and name is not None:
                v = fo4land.zstring(d)
                if v.lower().endswith(".dds"):
                    pairs.append((name, v))
                name = None
        if pairs:
            out[e[len(GRADIENT_PREFIX):]] = pairs
    return out


def gradient_profile(px, samples: int = 16) -> list:
    """The texture's colour along its longer axis (the other axis averaged), `samples` points, 0-255 RGB."""
    a = np.asarray(px)[:, :, :3].astype(np.float64)
    line = a.mean(0) if a.shape[1] >= a.shape[0] else a.mean(1)
    idx = np.linspace(0, len(line) - 1, min(samples, len(line))).round().astype(int)
    return [[int(round(v)) for v in line[i]] for i in idx]


def lightness(rgb) -> float:
    r, g, b = (float(x) for x in rgb[:3])
    return round(0.2126 * r + 0.7152 * g + 0.0722 * b, 1)


def _tokens(text: str) -> set:
    return {t.lower() for t in re.split(r"[^A-Za-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text)) if t}


def matches(path: str, names) -> bool:
    """A hair colour hint in the path, or a colour name as a whole word of the file name under a hair folder (the
    owner's first run matched 'Ruby' inside 'shrubyucca')."""
    p = path.lower().replace("\\", "/")
    if any(h in p for h in HINTS):
        return True
    if "hair" not in p:
        return False
    toks = _tokens(os.path.splitext(os.path.basename(path))[0])
    return any(n and n.lower() in toks for n in names)


def archive_hits(data_dir: str, names, limit: int = 400) -> list:
    """[(archive, path)] of archive files that look like hair colour data."""
    out = []
    for fn in sorted(os.listdir(data_dir)):
        if not (fn.lower().startswith("starfield - ") and fn.lower().endswith(".ba2")):
            continue
        try:
            arc = ba2.Ba2(os.path.join(data_dir, fn))
        except Exception:                                   # noqa: BLE001 (report only)
            continue
        for n in arc.names:
            if matches(n, names):
                out.append((fn, n))
                if len(out) >= limit:
                    return out
    return out


def material_hits(cr_zip: str, names, limit: int = 200) -> list:
    """ContentResources.zip entries (materials and the like) that look like hair colour data, with the texture
    files each names."""
    out = []
    if not os.path.isfile(cr_zip):
        return out
    with zipfile.ZipFile(cr_zip) as z:
        for info in z.infolist():
            if not matches(info.filename, names):
                continue
            row = {"path": info.filename}
            if info.filename.lower().endswith((".mat", ".json")) and info.file_size < 2_000_000:
                txt = z.read(info).decode("utf-8", "replace")
                found = re.findall(r'"FileName"\s*:\s*"([^"]+\.dds)"', txt, re.I)
                row["textures"] = sorted({f.replace("\\\\", "\\") for f in found})[:20]
            out.append(row)
            if len(out) >= limit:
                break
    return out


def texture_stats(px) -> dict:
    a = np.asarray(px)[:, :, :3].astype(np.float64)
    h = a.shape[0]
    row = a[h // 2]
    step = max(1, len(row) // 8)
    return {"size": [int(a.shape[1]), int(a.shape[0])],
            "mean_rgb": [round(float(x), 1) for x in a.reshape(-1, 3).mean(0)],
            "middle_row_rgb": [[int(round(v)) for v in row[i]] for i in range(0, len(row), step)][:8],
            "middle_column_rgb": [[int(round(v)) for v in a[i, a.shape[1] // 2]] for i in range(0, h, max(1, h // 8))][:8]}


def palette_from(names, clfm, textures) -> dict:
    """{name: [r, g, b]} for each HCOL name tied to a colour: a CLFM of that EditorID / name, else a decoded texture
    whose file name holds the name (its mean colour)."""
    pal = {}
    for n in names:
        rec = next((c for c in clfm if n.lower() in (c["edid"].lower(), c["full"].lower()) and c["rgba"]), None)
        if rec:
            pal[n] = rec["rgba"][:3]
            continue
        tex = next((t for t in textures if "mean_rgb" in t and "hair" in t["path"].lower()
                    and n.lower() in _tokens(os.path.splitext(os.path.basename(t["path"]))[0])), None)
        if tex:
            pal[n] = tex["mean_rgb"]
    return pal


def decode_gradients(groups: dict, read, texconv: str, out: str) -> dict:
    """{group: {name: {"path", "mean_rgb", "lightness", "profile", "png"} or {"path", "error"}}}."""
    import hair_probe
    res = {}
    for g, pairs in groups.items():
        for name, rel in pairs:
            row = {"path": rel}
            raw = read(rel)
            if raw is None:
                row["error"] = "not found in the archives"
            else:
                try:
                    px = hair_probe.decode_rgba(raw, texconv)
                    row["mean_rgb"] = [round(float(x), 1) for x in np.asarray(px)[:, :, :3].reshape(-1, 3).mean(0)]
                    row["lightness"] = lightness(row["mean_rgb"])
                    row["profile"] = gradient_profile(px)
                    png = f"gradient_{g}_{name}.png"
                    hair_probe.write_png(os.path.join(out, png), hair_probe.shrink(px, 256)[:, :, :3])
                    row["png"] = png
                except Exception as e:                    # noqa: BLE001 (report only)
                    row["error"] = f"{type(e).__name__}: {e}"
            res.setdefault(g, {})[name] = row
    return res


def gradient_palette(gradients: dict, group: str = DEFAULT_GROUP) -> dict:
    """{name: mean RGB} from `group`'s decoded gradients (case-insensitive group name); empty when absent."""
    g = next((k for k in gradients if k.lower() == group.lower()), None)
    return {n: r["mean_rgb"] for n, r in (gradients.get(g) or {}).items() if "mean_rgb" in r}


def probe(starfield: str, texconv: str, out: str, decode_limit: int = 60, read=None,
          group: str = DEFAULT_GROUP) -> dict:
    import hair_probe
    import hair_pack
    read = read or (lambda rel: hair_pack.read_game_file(starfield, rel))
    data = os.path.join(starfield, "Data")
    esm = os.path.join(data, "Starfield.esm")
    os.makedirs(out, exist_ok=True)
    names = npc_color_names(esm)
    every = sorted(set(names["hair"]) | set(names["facial_hair"]))
    clfm = color_records(esm, every)
    hits = archive_hits(data, every)
    mats = material_hits(os.path.join(starfield, "Tools", "ContentResources.zip"), every)
    want = [p for _a, p in hits if p.lower().endswith(".dds")]
    for m in mats:
        want += [re.sub(r"^data[\\/]", "", t, flags=re.I) for t in m.get("textures", [])]
    textures, seen = [], set()
    for rel in want:
        key = rel.lower().replace("\\", "/")
        if key in seen or len(textures) >= decode_limit:
            continue
        seen.add(key)
        row = {"path": rel}
        raw = read(rel if rel.lower().startswith("textures") else rel)
        if raw is None and not rel.lower().startswith("textures"):
            raw = read("textures/" + rel)
        if raw is None:
            row["error"] = "not found in the archives"
        elif texconv:
            try:
                px = hair_probe.decode_rgba(raw, texconv)
                row.update(texture_stats(px))
                png = re.sub(r"[^A-Za-z0-9]+", "_", rel)[-80:] + ".png"
                hair_probe.write_png(os.path.join(out, png), hair_probe.shrink(px, 256)[:, :, :3])
                row["png"] = png
            except Exception as e:                        # noqa: BLE001 (report only)
                row["error"] = f"{type(e).__name__}: {e}"
        textures.append(row)
    gradients = decode_gradients(gradient_textures(sfplugin.records(esm, [b"AVMD"])), read, texconv, out)
    pal = gradient_palette(gradients, group) or palette_from(every, clfm, textures)
    report = {"npc_color_names": names, "clfm": clfm, "gradient_group": group,
              "gradients": gradients, "archive_hits": [{"archive": a, "path": p} for a, p in hits],
              "material_hits": mats, "textures": textures, "palette": pal}
    with open(os.path.join(out, "hair_color_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    with open(os.path.join(out, "hair_colors.json"), "w", encoding="utf-8") as fh:
        json.dump({"palette": pal}, fh, indent=1)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True, help="a folder outside the repository")
    ap.add_argument("--group", default=DEFAULT_GROUP,
                    help="the hairstyle group whose gradients make the palette (SimpleGroup_Hair_<group>)")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    rep = probe(a.starfield, a.texconv, a.out, group=a.group)
    print(f"hair colour names: {len(rep['npc_color_names']['hair'])} (hair), "
          f"{len(rep['npc_color_names']['facial_hair'])} (facial hair)")
    print(f"colour records: {len(rep['clfm'])}; archive files: {len(rep['archive_hits'])}; "
          f"material files: {len(rep['material_hits'])}; textures decoded: "
          f"{sum(1 for t in rep['textures'] if 'mean_rgb' in t)}")
    grad = rep["gradients"]
    print(f"hair colour gradients: {sum(len(v) for v in grad.values())} in {len(grad)} groups, decoded "
          f"{sum(1 for v in grad.values() for r in v.values() if 'mean_rgb' in r)}")
    for n, r in sorted((rep["gradients"].get(a.group) or {}).items(), key=lambda kv: -kv[1].get("lightness", -1)):
        print(f"  {n:13s} {r.get('lightness', '-'):>6} {r.get('mean_rgb', r.get('error'))}")
    print(f"palette: {len(rep['palette'])} names with a colour")
    print("report:", os.path.join(a.out, "hair_color_probe.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
