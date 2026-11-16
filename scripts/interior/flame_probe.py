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

from fo4sf import bsa, nif as nifmod, sfplugin  # noqa: E402

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
            if t.endswith("Controller") and len(b) >= p + 4:
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


def effect_shapes(data: bytes) -> dict:
    """{"shapes": [...], "addon_nodes": [(name, world translation)]} of a Skyrim NIF."""
    n = nifmod.parse(data)
    out = {"shapes": [], "addon_nodes": []}
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
    ap.add_argument("--show", type=int, default=2)
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
    cr = os.path.join(a.starfield, "Tools", "ContentResources.zip")
    with zipfile.ZipFile(cr) as z:
        names = [x for x in z.namelist() if x.lower().endswith(".mat")]
        flip, shown = [], 0
        rx = re.compile(a.mat_match, re.I)
        for x in names:
            txt = z.read(x).decode("utf-8", "replace")
            if "FlipbookComponent" in txt and '"IsAFlipbook"' in txt and re.search(r'"IsAFlipbook"\s*:\s*"?true', txt, re.I):
                flip.append(x)
                if rx.search(x) and shown < a.show:
                    print(f"== Starfield flipbook material {x}:\n{txt[:6000]}")
                    shown += 1
        print(f"== Starfield .mat with an active flipbook: {len(flip)} of {len(names)}; fire-like: "
              f"{[x for x in flip if rx.search(x)][:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
