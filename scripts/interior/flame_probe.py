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

CONTROLLED = {0: "Emissive Multiple", 1: "Falloff Start Angle", 2: "Falloff Stop Angle", 3: "Falloff Start Opacity",
              4: "Falloff Stop Opacity", 5: "Alpha Transparency", 6: "U Offset", 7: "U Scale", 8: "V Offset",
              9: "V Scale"}          # BSEffectShaderPropertyFloatController (nif.xml EffectShaderControlledVariable)


def time_controller(b: bytes) -> dict:
    """NiTimeController: next, flags, frequency, phase, start, stop, target (nif.xml, 20.2.0.7)."""
    nxt, flags, freq, phase, start, stop, target = struct.unpack_from("<iHffffi", b, 0)
    return {"next": nxt, "flags": flags, "frequency": round(freq, 3), "phase": round(phase, 3),
            "start": round(start, 3), "stop": round(stop, 3)}


def float_keys(n, data_ref, limit=10) -> dict:
    """NiFloatData keys: {count, type, keys [(time, value)]}."""
    if not (0 <= data_ref < len(n.blocks)) or n.type_of(data_ref) != "NiFloatData":
        return {}
    b = n.blocks[data_ref]
    count, = struct.unpack_from("<I", b, 0)
    if count == 0:
        return {"count": 0}
    ktype, = struct.unpack_from("<I", b, 4)
    size = {1: 8, 2: 16, 3: 20, 5: 8}.get(ktype, 8)          # linear, quadratic (+2 tangents), TBC (+3), const
    keys = []
    for k in range(min(count, limit)):
        t, v = struct.unpack_from("<ff", b, 8 + k * size)
        keys.append((round(t, 3), round(v, 4)))
    return {"count": count, "type": ktype, "keys": keys}


def controllers(n, ref) -> list:
    out, seen = [], set()
    while 0 <= ref < len(n.blocks) and ref not in seen:
        seen.add(ref)
        t, b = n.type_of(ref), n.blocks[ref]
        c = {"type": t}
        try:
            c.update(time_controller(b))
            p = 26
            if (t.endswith("Controller") or t.endswith("Ctlr")) and len(b) >= p + 4:
                interp, = struct.unpack_from("<i", b, p)
                c["interpolator"] = n.type_of(interp) if 0 <= interp < len(n.blocks) else None
                if "EffectShaderProperty" in t and len(b) >= p + 8:
                    var, = struct.unpack_from("<I", b, p + 4)
                    c["variable"] = CONTROLLED.get(var, var) if "Float" in t else var
                if c["interpolator"] == "NiFloatInterpolator":
                    ib = n.blocks[interp]
                    c["value"], data = round(struct.unpack_from("<f", ib, 0)[0], 4), struct.unpack_from("<i", ib, 4)[0]
                    c["data"] = float_keys(n, data)
        except struct.error:
            c["error"] = "short block"
        out.append(c)
        ref = c.get("next", -1)
    return out


MODIFIER_FIELDS = {          # floats after NiPSysModifier (name, order, target, active = 13 bytes); nif.xml, SSE
    "NiPSysEmitter": ["speed", "speed_var", "declination", "declination_var", "planar_angle", "planar_angle_var",
                      "color_r", "color_g", "color_b", "color_a", "radius", "radius_var", "life_span", "life_span_var"],
    "BSPSysSimpleColorModifier": ["fade_in", "fade_out", "color1_end", "color1_start", "color2_end", "color2_start",
                                  "c1r", "c1g", "c1b", "c1a", "c2r", "c2g", "c2b", "c2a", "c3r", "c3g", "c3b", "c3a"],
    "BSPSysSubTexModifier": ["start_frame(u32)", "start_frame_fudge", "end_frame", "loop_start", "loop_start_fudge",
                             "frame_count", "frame_count_fudge"],
    "NiPSysAgeDeathModifier": [],
    "NiPSysGravityModifier": [],
}
EMITTERS = ("NiPSysCylinderEmitter", "NiPSysBoxEmitter", "NiPSysSphereEmitter", "NiPSysMeshEmitter")


def particle_modifier(n, i) -> dict:
    """A particle modifier / emitter block: its target system, named fields (best reading of nif.xml, raw floats kept
    beside them so a wrong layout shows), and the volume emitter's extra floats."""
    t, b = n.type_of(i), n.blocks[i]
    out = {"block": i, "type": t}
    if len(b) < 13:
        return out
    out["target"] = struct.unpack_from("<i", b, 8)[0]
    body = b[13:]
    floats = [round(x, 4) for x in struct.unpack_from(f"<{len(body) // 4}f", body)]
    names = MODIFIER_FIELDS["NiPSysEmitter"] if t in EMITTERS else MODIFIER_FIELDS.get(t)
    if names:
        out["fields"] = dict(zip(names, floats))
        if t == "BSPSysSubTexModifier" and len(body) >= 4:
            out["fields"]["start_frame(u32)"] = struct.unpack_from("<I", body, 0)[0]
        if t in EMITTERS:
            out["volume"] = floats[len(names) + 1:]                 # after the emitter object ref
    elif t == "BSPSysScaleModifier" and len(body) >= 4:
        k = struct.unpack_from("<I", body, 0)[0]
        out["scales"] = [round(x, 4) for x in struct.unpack_from(f"<{min(k, 32)}f", body, 4)] if k < 1000 else []
    out["raw"] = floats[:24]
    return out


def particle_systems(n) -> list:
    """Every NiParticleSystem: the effect shader it draws with (textures), its modifiers / emitters, and the
    controllers (birth rate) found by scanning for refs to it."""
    shaders = {i for i in range(len(n.blocks)) if n.type_of(i) == "BSEffectShaderProperty"}
    systems = {}
    for i, b in enumerate(n.blocks):
        if n.type_of(i) in ("NiParticleSystem", "BSStripParticleSystem", "NiMeshParticleSystem"):
            refs = [struct.unpack_from("<i", b, k)[0] for k in range(0, len(b) - 3)]   # any offset: bools misalign
            sh = [r for r in refs if r in shaders]
            name = ""
            k = struct.unpack_from("<i", b, 0)[0] if len(b) >= 4 else -1
            if 0 <= k < len(n.strings):
                name = n.strings[k].decode("latin-1") if isinstance(n.strings[k], bytes) else str(n.strings[k])
            systems[i] = {"block": i, "type": n.type_of(i), "name": name,
                          "shader_block": sh[0] if sh else None,
                          "textures": [x.decode("latin-1") for x in re.findall(rb"[\w\\/ .-]+\.dds", n.blocks[sh[0]])]
                          if sh else [], "modifiers": []}
    for i in range(len(n.blocks)):
        t = n.type_of(i)
        if (t.startswith("NiPSys") or t.startswith("BSPSys")) and not t.endswith(("Data", "Ctlr")) \
                and "Collider" not in t:
            m = particle_modifier(n, i)
            if m.get("target") in systems:
                systems[m["target"]]["modifiers"].append(m)
        elif t.endswith("Ctlr") and (t.startswith("NiPSys") or t.startswith("BSPSys")):
            c = controllers(n, i)[0]
            tg = struct.unpack_from("<i", n.blocks[i], 22)[0] if len(n.blocks[i]) >= 26 else -1
            if tg in systems:
                systems[tg]["modifiers"].append({"block": i, "controller": c})
    return list(systems.values())


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
    a = ap.parse_args(argv)
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
    cr = os.path.join(a.starfield, "Tools", "ContentResources.zip")
    with zipfile.ZipFile(cr) as z:
        names = [x for x in z.namelist() if x.lower().endswith(".mat")]
        flip, shown, animated = [], 0, []
        from collections import Counter
        kinds, binds = Counter(), Counter()
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
            if x.lower().endswith(tuple(w.lower() for w in a.mat)):
                print(f"== Starfield material {x}:\n{txt[:a.chars]}")
        print(f"== Starfield .mat with an active flipbook: {len(flip)} of {len(names)}; fire-like: "
              f"{[x for x in flip if rx.search(x)][:30]}")
        print(f"== Starfield .mat with controllers: {len(animated)}; BSBind types {dict(kinds.most_common(30))}")
        print(f"   bindings {dict(binds.most_common(40))}")
        uv = [x for x in animated if re.search(r"Offset|Scroll|UV|Flow", z.read(x).decode('utf-8', 'replace'))][:3]
        for x in uv[:1]:
            txt = z.read(x).decode("utf-8", "replace")
            k = txt.find('"upControllers"')
            print(f"== controllers of {x} (of {uv}):\n{txt[k:k + a.chars]}")
    print("== Starfield meshes named like fire / candle, and the materials they name")
    arcs = [os.path.join(a.starfield, "Data", f) for f in sorted(os.listdir(os.path.join(a.starfield, "Data")))
            if f.lower().endswith(".ba2") and "mesh" in f.lower()]
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
