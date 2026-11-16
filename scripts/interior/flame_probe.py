"""What converting Skyrim's flames needs, from both games (read-only).

2026-11-15, owner: hearth and candle flames next (and Skyrim-like interior light). fire_survey.py (owner's run 11-09)
answered which assets: candles carry AddOnNode slots for ADDN MPSCandleFlame01 (candleflame01.dds / candleglow01.dds);
hearths are FireplaceWood01Burning (flame cards on FXFireAtlas02 / 04, particles, haze); Starfield models carry no
particle blocks but its materials have FlipbookComponent (Columns, Rows, FPS, Loops), emissive and effect settings.
This prints, so the converter can be written against facts:
  * Skyrim: the ADDN records matching --addon (model, DATA), and for each model (--model, plus those add-ons'): every
    effect-shader shape (texture, flags, UV offset / scale, emissive), each controller on it (type, frequency, phase,
    start / stop, controlled variable, interpolator keys) and its vertex count, and every AddOnNode's position;
  * Starfield: the .mat files in ContentResources.zip with a FlipbookComponent (the names; the first --show matching
    --mat-match printed in full): the JSON our flame materials copy.

    python -I scripts\\interior\\flame_probe.py --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield>"
"""
import argparse
import json
import os
import re
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import ba2, bsa, nif as nifmod, sfplugin, textures as tx  # noqa: E402

from fo4sf.skyrimfire import (CONTROLLED, EMITTERS, MODIFIER_FIELDS, controllers, float_keys,  # noqa: E402,F401
                               particle_modifier, particle_systems, time_controller)


def effect_shapes(data: bytes) -> dict:
    """{"shapes": [...], "addon_nodes": [(name, world translation)]} of a Skyrim NIF."""
    n = nifmod.parse(data)
    out = {"shapes": [], "addon_nodes": [], "particle_systems": []}
    try:
        out["particle_systems"] = particle_systems(n)
    except Exception as ex:                                         # noqa: BLE001
        out["particle_error"] = f"{type(ex).__name__}: {ex}"
    try:
        world = nifmod.world_transforms(n)                          # block -> (t, R, s); BS >= 130 layout
    except Exception:                                               # noqa: BLE001
        world = None
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        if t == "BSEffectShaderProperty":
            nm, = struct.unpack_from("<i", b, 0)
            n_extra, = struct.unpack_from("<I", b, 4)
            p = 8 + 4 * n_extra
            ctrl, = struct.unpack_from("<i", b, p)
            f1, f2 = struct.unpack_from("<II", b, p + 4)
            uv = struct.unpack_from("<4f", b, p + 12)
            texs = [x.decode("latin-1") for x in re.findall(rb"[\w\\/ .-]+\.dds", b)]
            out["shapes"].append({"shader_block": i, "textures": texs, "flags1": f"{f1:08X}", "flags2": f"{f2:08X}",
                                  "uv_offset": [round(v, 4) for v in uv[:2]], "uv_scale": [round(v, 4) for v in uv[2:]],
                                  "controllers": controllers(n, ctrl)})
        if t in ("BSValueNode", "NiNode", "BSFadeNode") and len(b) >= 4:
            k, = struct.unpack_from("<i", b, 0)
            name = n.strings[k] if 0 <= k < len(n.strings) else b""
            name = name.decode("latin-1") if isinstance(name, bytes) else str(name)
            if re.match(r"^AddOnNode\d+$", name, re.I):
                pos = None
                if world is not None:
                    try:
                        pos = [round(float(x), 2) for x in world(i)[0]]
                    except Exception:                               # noqa: BLE001
                        pos = None
                out["addon_nodes"].append((name, pos))
    try:                                                            # vertex count / shape name per effect shader
        from fo4sf import skyrimnif
        for s in skyrimnif.trishapes(n):
            for e in out["shapes"]:
                if s.shader_ref == e["shader_block"]:
                    e["shape"] = s.name.decode("latin-1") if isinstance(s.name, bytes) else s.name
                    e["vertices"] = len(s.positions)
                    e["shape_translation"] = [round(float(x), 2) for x in s.translation]
    except Exception as ex:                                         # noqa: BLE001
        out["shapes_error"] = f"{type(ex).__name__}: {ex}"
    return out


def sf_nif_layout(n, read_mesh=None) -> list:
    """Rows describing a Starfield NIF: block, type, name; nodes' children; BSGeometry transform, shader / material,
    LOD 0 mesh (vertex count, decoded position bounds and UV range when read_mesh(path) returns its bytes)."""
    from fo4sf import sfmesh, sfnif
    rows = []
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        row = {"block": i, "type": t}
        if len(b) >= 4:
            k = struct.unpack_from("<i", b, 0)[0]
            if 0 <= k < len(n.strings):
                nm = n.strings[k]
                row["name"] = nm.decode("latin-1") if isinstance(nm, bytes) else str(nm)
        if t == "BSGeometry":
            try:
                g = sfnif.parse_bsgeometry(b)
                row.update(translation=[round(x, 3) for x in g.translation], scale=round(g.scale, 3),
                           flags=g.flags, controller=g.controller, extra=g.extra_refs, shader=g.shader,
                           alpha=g.alpha, box=[round(x, 3) for x in g.box])
                m = g.meshes[0]
                if m is not None:
                    path = "geometries/" + m.path.decode("latin-1").replace("\\", "/") + ".mesh"
                    row.update(mesh=path, verts=m.num_verts, mesh_flags=m.flags)
                    data = read_mesh(path) if read_mesh else None
                    if data:
                        sm = sfmesh.parse(data)
                        pts = [sfmesh.decode_position(p, sm.scale) for p in sm.positions]
                        if pts:
                            row["pos_min"] = [round(min(p[j] for p in pts), 4) for j in range(3)]
                            row["pos_max"] = [round(max(p[j] for p in pts), 4) for j in range(3)]
                        row["triangles"] = len(sm.triangles)
                        row["colors"] = len(sm.colors)
                        if sm.uv1:
                            us = [sfmesh.half_to_float(u) for u, _v in sm.uv1]
                            vs = [sfmesh.half_to_float(v) for _u, v in sm.uv1]
                            row["uv"] = [round(min(us), 3), round(max(us), 3), round(min(vs), 3), round(max(vs), 3)]
            except Exception as e:                                  # noqa: BLE001
                row["error"] = f"{type(e).__name__}: {e}"
        elif t.endswith("Node") and len(b) >= 8:
            row["size"] = len(b)
        elif t.endswith("ShaderProperty"):
            pass
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--addon", default="CandleFlame", help="text the ADDN EditorIDs must contain")
    ap.add_argument("--model", action="append", default=[],
                    help="Skyrim models (default: the burning hearth and two candles)")
    ap.add_argument("--mat-match", default="fire|flame|candle|torch|ember", help="regex for the materials printed")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--mat", action="append", default=["FireCandleFlame.mat", "FiresGeneric_Sm_01_14x14.mat"],
                    help="material file names to print whole")
    ap.add_argument("--chars", type=int, default=5000)
    ap.add_argument("--mesh-match", default=r"candle|fire|flame|torch|brazier|hearth|lantern")
    ap.add_argument("--skip-skyrim", action="store_true")
    ap.add_argument("--skip-mesh-scan", action="store_true")
    ap.add_argument("--sf-nif", action="append", default=[],
                    help="Starfield NIFs to lay out block by block (with their LOD 0 mesh bounds)")
    ap.add_argument("--binding", default="", help="print the shortest .mat whose controllers drive this binding")
    a = ap.parse_args(argv)
    if not a.skip_skyrim:
        skyrim_side(a)
    starfield_side(a)
    return 0


def skyrim_side(a):
    sky = bsa.SkyrimArchives(a.skyrim_data)
    models = a.model or ["meshes\\clutter\\woodfires\\fireplacewood01burning.nif",
                         "meshes\\clutter\\candles\\candlehorntable01.nif",
                         "meshes\\clutter\\candles\\candlehornfloor01.nif"]
    print("== Skyrim ADDN")
    for _t, _h, subs, fid in sfplugin.records(os.path.join(a.skyrim_data, "Skyrim.esm"), [b"ADDN"]):
        e = sfplugin.edid(subs)
        if a.addon.lower() in e.lower():
            f = {s.decode(): bytes(d) for s, d in subs}
            model = f.get("MODL", b"").rstrip(b"\0").decode("latin-1")
            print(f"  {fid:08X} {e}: MODL {model} DATA {f.get('DATA', b'').hex()} DNAM {f.get('DNAM', b'').hex()}")
            if model:
                models.append("meshes\\" + model)
    textures = set()
    for m in models:
        data = sky.mesh(m)
        if data is None:
            print(f"== {m}: not found")
            continue
        try:
            info = effect_shapes(data)
        except Exception as e:                                       # noqa: BLE001
            print(f"== {m}: not read ({type(e).__name__}: {e})")
            continue
        print(f"== {m}: {len(info['shapes'])} effect shapes; add-on nodes {info['addon_nodes']}")
        for s in info["shapes"]:
            print("  " + json.dumps(s))
        for ps in info.get("particle_systems", []):
            print("  particles " + json.dumps(ps))
        if info.get("particle_error"):
            print("  particles not read: " + info["particle_error"])
        textures.update(t for s in info["shapes"] + info.get("particle_systems", []) for t in s.get("textures", []))
    print("== Skyrim effect textures")
    for t in sorted(textures, key=str.lower):
        d = sky.texture(t)
        if d is None:
            print(f"  {t}: not found")
            continue
        try:
            h = tx.read_dds_header(d)
            print(f"  {t}: {h['width']}x{h['height']} mips {h['mips']} {h['fourcc']!r} dxgi {h['dxgi']}")
        except Exception as e:                                      # noqa: BLE001
            print(f"  {t}: {type(e).__name__}: {e}")


def starfield_side(a):
    cr = os.path.join(a.starfield, "Tools", "ContentResources.zip")
    with zipfile.ZipFile(cr) as z:
        names = [x for x in z.namelist() if x.lower().endswith(".mat")]
        flip, shown, animated = [], 0, []
        from collections import Counter
        kinds, binds, bound = Counter(), Counter(), []
        rx = re.compile(a.mat_match, re.I)
        for x in names:
            txt = z.read(x).decode("utf-8", "replace")
            if "FlipbookComponent" in txt and '"IsAFlipbook"' in txt and re.search(r'"IsAFlipbook"\s*:\s*"?true', txt, re.I):
                flip.append(x)
                if rx.search(x) and shown < a.show:
                    print(f"== Starfield flipbook material {x}:\n{txt[:6000]}")
                    shown += 1
            if '"MappingsA"' in txt:
                for m in re.finditer(r'"MappingsA"\s*:\s*\{\s*"Data"\s*:\s*(null|\[)', txt):
                    if m.group(1) == "[":
                        animated.append(x)
                        kinds.update(re.findall(r'"Type"\s*:\s*"(BSBind::[A-Za-z0-9_:]+)"', txt))
                        binds.update(re.findall(r'"Binding"\s*:\s*"([^"]+)"', txt))
                        break
            if a.binding and '"MappingsA"' in txt and re.search(r'"Path"[^\]]*\[\s*"%s"' % re.escape(a.binding), txt):
                bound.append((len(txt), x))
            if x.lower().endswith(tuple(w.lower() for w in a.mat)):
                print(f"== Starfield material {x}:\n{txt[:a.chars]}")
        print(f"== Starfield .mat with an active flipbook: {len(flip)} of {len(names)}; fire-like: "
              f"{[x for x in flip if rx.search(x)][:30]}")
        print(f"== Starfield .mat with controllers: {len(animated)}; BSBind types {dict(kinds.most_common(30))}")
        print(f"   bindings {dict(binds.most_common(40))}")
        if bound:
            bound.sort()
            print(f"== {len(bound)} materials drive {a.binding}; shortest {bound[0][1]}:")
            print(z.read(bound[0][1]).decode("utf-8", "replace")[:a.chars])
        uv = [x for x in animated if re.search(r"Offset|Scroll|UV|Flow", z.read(x).decode('utf-8', 'replace'))][:3]
        for x in uv[:1]:
            txt = z.read(x).decode("utf-8", "replace")
            k = txt.find('"upControllers"')
            print(f"== controllers of {x} (of {uv}):\n{txt[k:k + a.chars]}")
    arcs = [os.path.join(a.starfield, "Data", f) for f in sorted(os.listdir(os.path.join(a.starfield, "Data")))
            if f.lower().endswith(".ba2") and "mesh" in f.lower()]
    if a.sf_nif:
        opened = [ba2.Ba2(p) for p in arcs]

        def read_any(name):
            for arc in opened:
                i = arc.find(name)
                if i is not None:
                    return arc.read(i)
            return None
        for name in a.sf_nif:
            data = read_any(name)
            print(f"== Starfield NIF {name}: {'not found' if data is None else ''}")
            if data is None:
                continue
            n = nifmod.parse(data)
            print("  strings: " + json.dumps([x.decode('latin-1') if isinstance(x, bytes) else str(x) for x in n.strings]))
            for row in sf_nif_layout(n, read_any):
                print("  " + json.dumps(row))
    if a.skip_mesh_scan:
        return
    print("== Starfield meshes named like fire / candle, and the materials they name")
    mrx = re.compile(a.mesh_match, re.I)
    for path in arcs:
        arc = ba2.Ba2(path)
        for i, nm in enumerate(arc.names):
            ln = nm.lower().replace("\\", "/")
            if ln.endswith(".nif") and mrx.search(ln.rsplit("/", 1)[-1]):
                try:
                    b = arc.read(i)
                except Exception as e:                              # noqa: BLE001
                    print(f"  {nm}: {type(e).__name__}")
                    continue
                mats = sorted({x.decode("latin-1") for x in re.findall(rb"[\w\\/ .-]+\.mat", b)})
                print(f"  {nm}: {mats[:8]}")


if __name__ == "__main__":
    sys.exit(main())
