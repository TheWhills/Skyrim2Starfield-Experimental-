"""A vanilla Starfield grass model next to our converted Skyrim grass, block by block (read-only), 2026-11-23.

Why: with our GRAS / GCVR records Starfield grows grass on the Skyrim terrain when the grass keeps a vanilla model
(skyrim_grass_native.py --keep-template-model: the hellebore flowers, owner 2026-11-23 08:46) and grows nothing with
our converted Skyrim models (built as ordinary static props by skyrimconvert.convert_static_sse). So something in the
model differs from what the grass system needs: the NIF layout (root type, flags, BSXFlags, extra data), the
BSGeometry flags / mesh slots, the material (shader model VegetationTranslucent1Layer per the Creation Kit wiki), or the
.mesh data. This prints both side by side and zips the files (NIF, its .mesh files, its material: the vanilla source
.mat from Data\\Scripts\\Source\\Materials when present) for a closer look.

    python -I scripts\\terrain\\grass_model_compare.py --sf-data "<Starfield>\\Data" ^
        --ours "%LOCALAPPDATA%\\ModOrganizer\\Starfield\\mods\\S2S Grass Native" --zip C:\\Modding\\work\\grass_models.zip
"""
import argparse
import glob
import json
import os
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, nif as nifmod, sfnif, sfplugin  # noqa: E402


class Archives:
    """Name lookup over several BA2s (later ones win, as load order) plus loose files under Data."""

    def __init__(self, paths, loose=""):
        self.arcs = []
        for p in paths:
            try:
                self.arcs.append(ba2.Ba2(p))
            except Exception:                           # noqa: BLE001 (texture-only / unreadable: skipped)
                continue
        self.loose = loose

    def read(self, name):
        name = name.replace("/", "\\").lstrip("\\")
        if self.loose:
            p = os.path.join(self.loose, *name.split("\\"))
            if os.path.isfile(p):
                return open(p, "rb").read()
        for a in reversed(self.arcs):
            if a.find(name) is not None:
                return a.read(name)
        return None


def _name(n, idx):
    return n.strings[idx].decode("latin-1", "replace") if 0 <= idx < len(n.strings) else ""


def describe(data: bytes):
    """{header, blocks: [...], meshes: [paths], materials: [paths]} of a Starfield NIF."""
    n = nifmod.parse(data)
    out = {"bs_version": n.bs_version, "user_version": n.user_version, "sf_data": n.sf_data.hex(),
           "blocks": [], "meshes": [], "materials": []}
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        row = {"i": i, "type": t, "size": len(b)}
        if t == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            row.update(name=_name(n, g.name_idx), flags=hex(g.flags), extra=g.extra_refs, shader=g.shader,
                       alpha=g.alpha, skin=g.skin, scale=g.scale,
                       meshes=[None if m is None else {"verts": m.num_verts, "indices": m.indices_size,
                                                       "flags": hex(m.flags), "path": m.path.decode("latin-1")}
                               for m in g.meshes])
            out["meshes"] += ["geometries\\" + m.path.decode("latin-1") + ".mesh" for m in g.meshes if m]
        elif t in ("NiNode", "BSFadeNode", "BSLeafAnimNode", "BSOrderedNode", "BSMultiBoundNode"):
            name_idx, nextra = struct.unpack_from("<iI", b, 0)
            p = 8 + 4 * nextra
            ctrl, flags = struct.unpack_from("<iI", b, p)
            row.update(name=_name(n, name_idx), flags=hex(flags), extra=list(struct.unpack_from(f"<{nextra}i", b, 8)))
        elif t == "BSXFlags":
            row.update(value=struct.unpack_from("<I", b, 4)[0])
        elif t in ("BSLightingShaderProperty", "BSEffectShaderProperty"):
            idx = struct.unpack_from("<i", b, 0)[0]
            row.update(material=_name(n, idx))
            out["materials"].append(_name(n, idx))
        elif t in ("NiIntegerExtraData", "NiStringExtraData", "NiFloatExtraData", "BSBound"):
            idx = struct.unpack_from("<i", b, 0)[0]
            row.update(name=_name(n, idx), data=b[4:24].hex())
        else:
            row.update(head=b[:48].hex())
        out["blocks"].append(row)
    return out


def mesh_head(data: bytes):
    """The first fields of a .mesh (version, index count, then the first 64 bytes as hex)."""
    if not data or len(data) < 8:
        return None
    return {"size": len(data), "u32": list(struct.unpack_from("<4I", data, 0)), "head": data[:64].hex()}


def material_text(arcs, data_dir, path):
    """The material file: ours from the archives, a vanilla one from the Creation Kit sources (loose)."""
    if not path:
        return None
    rel = path.replace("/", "\\")
    for cand in (rel, "materials\\" + rel if not rel.lower().startswith("materials\\") else rel):
        d = arcs.read(cand)
        if d:
            return d
    src = os.path.join(data_dir, "Scripts", "Source", "Materials",
                       *rel.split("\\")[1 if rel.lower().startswith("materials\\") else 0:])
    return open(src, "rb").read() if os.path.isfile(src) else None


def show(label, desc):
    print(f"\n== {label}: bs_version {desc['bs_version']}, user {desc['user_version']}, sf_data {desc['sf_data']}")
    for r in desc["blocks"]:
        rest = {k: v for k, v in r.items() if k not in ("i", "type", "size")}
        print(f"  [{r['i']}] {r['type']} ({r['size']} B) {json.dumps(rest)[:400]}")


def vanilla_grass_models(sf_esm, names):
    """{GRAS EditorID: MODL} for the given EditorIDs (or the first 3 grasses of GC_MossMoundsGrass01)."""
    recs = sfplugin.records(sf_esm, [b"GRAS", b"GCVR"])
    gras = {r[3]: r for r in recs if r[0] == b"GRAS"}
    if not names:
        cover = next((r for r in recs if r[0] == b"GCVR" and sfplugin.edid(r[2]) == "GC_MossMoundsGrass01"), None)
        ids = [struct.unpack_from("<I", bytes(d))[0] for s, d in (cover[2] if cover else []) if s == b"GNAM"][:3]
        pick = [gras[i] for i in ids if i in gras]
    else:
        want = {x.lower() for x in names}
        pick = [r for r in gras.values() if sfplugin.edid(r[2]).lower() in want]
    return {sfplugin.edid(r[2]): dict((s, bytes(d)) for s, d in r[2]).get(b"MODL", b"").rstrip(b"\0").decode("latin-1")
            for r in pick}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--ours", required=True, help="the S2S Grass Native mod folder (its BA2s and grass_native.json)")
    ap.add_argument("--vanilla", action="append", default=[], help="vanilla GRAS EditorID (repeatable; default: the "
                                                                   "first grasses of GC_MossMoundsGrass01)")
    ap.add_argument("--count", type=int, default=2, help="how many of our grasses (default 2)")
    ap.add_argument("--zip", default="")
    a = ap.parse_args(argv)
    if a.zip and os.path.abspath(a.zip).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--zip must be outside the repository")
    van = Archives(sorted(glob.glob(os.path.join(a.sf_data, "Starfield - *.ba2"))))
    ours = Archives(sorted(glob.glob(os.path.join(a.ours, "*.ba2"))), loose=a.ours)
    with open(os.path.join(a.ours, "grass_native.json"), encoding="utf-8") as fh:
        rep = json.load(fh)
    items = [("vanilla " + e, van, "meshes\\" + m) for e, m in
             vanilla_grass_models(os.path.join(a.sf_data, "Starfield.esm"), a.vanilla).items()]
    items += [("ours " + e, ours, "meshes\\" + g["model"]) for e, g in list(rep.get("grasses", {}).items())[:a.count]]
    files, summary = {}, {}
    for label, arcs, nif_path in items:
        data = arcs.read(nif_path)
        if data is None:
            print(f"\n== {label}: {nif_path} NOT FOUND")
            summary[label] = {"nif": nif_path, "error": "not found"}
            continue
        try:
            d = describe(data)
        except Exception as e:                           # noqa: BLE001 (reported)
            print(f"\n== {label}: {nif_path}: {type(e).__name__}: {e}")
            summary[label] = {"nif": nif_path, "error": str(e)}
            continue
        show(f"{label} ({nif_path})", d)
        files[f"{label}/{os.path.basename(nif_path)}"] = data
        d["mesh_heads"] = {}
        for mp in d["meshes"][:2]:
            md = arcs.read(mp)
            d["mesh_heads"][mp] = mesh_head(md)
            print(f"  mesh {mp}: {d['mesh_heads'][mp]['u32'] if md else 'NOT FOUND'}"
                  f"{'' if not md else ', %d bytes' % len(md)}")
            if md:
                files[f"{label}/{os.path.basename(mp)}"] = md
        for mat in dict.fromkeys(d["materials"]):
            mt = material_text(arcs, a.sf_data, mat)
            print(f"  material {mat}: {'found, ' + str(len(mt)) + ' bytes' if mt else 'NOT FOUND (compiled only)'}")
            if mt:
                files[f"{label}/{os.path.basename(mat)}"] = mt
                try:
                    j = json.loads(mt.decode("utf-8", "replace"))
                    shader = [o.get("Data", {}).get("ShaderModel") or
                              next((c.get("Data", {}).get("FileName") for c in o.get("Components", [])
                                    if "ShaderModel" in json.dumps(c)), None) for o in j.get("Objects", [])]
                    print(f"    shader models / layer files: {[s for s in shader if s][:4]}")
                except Exception:                         # noqa: BLE001 (not JSON)
                    pass
        summary[label] = {"nif": nif_path, **d}
    if a.zip:
        with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("summary.json", json.dumps(summary, indent=1))
            for k, v in files.items():
                z.writestr(k.replace(" ", "_"), v)
        print(f"\n-> {a.zip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
