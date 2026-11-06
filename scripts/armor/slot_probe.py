"""Which body slots Starfield's own body pieces and outfits use (2026-11-06: Starfield's undershirt, a separate mesh
clothes/naked/naked_m.nif "Naked_M_Swimsuit", shows between Ralof's short sleeves and the arm; our armor copies the
slots of the nightwear's lower body only). Reads Starfield.esm and prints, with each ARMA's BO64 slot bits and model:
  - HumanRace's skin armor (RACE WNAM) and its addons: the default body set an outfit hides by covering slots;
  - every ARMA whose model is under clothes\\naked (the undershirt / swimsuit);
  - the template armor our armor copies (Clothes_Nightwear_01) and a few full outfits for comparison.
Writes slot_probe.json into --out.

    python -I scripts\\armor\\slot_probe.py --starfield "D:\\...\\Starfield" --out "C:\\Modding\\work\\slot_probe"
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import sfnif, sfplugin  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402

sys.path.insert(0, HERE)

COMPARE = ("Clothes_Nightwear_01", "Clothes_Miner_UtilitySuit", "Clothes_Miner_Jumpsuit", "Outfit_UtilityOveralls_01")


def zstr(d) -> str:
    return bytes(d).split(b"\0")[0].decode("latin-1")


def slots(bo64) -> list:
    """Slot bit numbers set in a BO64 field (first 8 bytes, little endian)."""
    if not bo64:
        return []
    v = int.from_bytes(bytes(bo64)[:8], "little")
    return [i for i in range(64) if v >> i & 1]


def addon_row(fid, subs) -> dict:
    d = dict((s, x) for s, x in subs if s not in (b"MODL",))
    return {"form": f"{fid:08X}", "edid": sfplugin.edid(subs), "slots": slots(d.get(b"BO64")),
            "male": zstr(d[b"MOD2"]) if b"MOD2" in d else "", "female": zstr(d[b"MOD3"]) if b"MOD3" in d else ""}


def armor_addons(armo_subs, arma) -> list:
    out = []
    for s, d in armo_subs:
        if s == b"MODL" and len(d) >= 4:
            fid, = struct.unpack_from("<I", bytes(d), 0)
            if fid in arma:
                out.append(addon_row(fid, arma[fid]))
    return out


def model_shapes(nif_bytes: bytes) -> list:
    """[{shape, vertices (LOD0), material}] of a Starfield NIF (material: its BSLightingShaderProperty's name)."""
    n = nifmod.parse(nif_bytes)
    out = []
    for i, b in enumerate(n.blocks):
        if n.type_of(i) != "BSGeometry":
            continue
        g = sfnif.parse_bsgeometry(b)
        m = next((x for x in g.meshes if x is not None), None)
        mat = ""
        if 0 <= g.shader < len(n.blocks) and n.type_of(g.shader) == "BSLightingShaderProperty":
            idx, = struct.unpack_from("<i", n.blocks[g.shader], 0)
            mat = n.strings[idx].decode("latin-1") if 0 <= idx < len(n.strings) else ""
        name = n.strings[g.name_idx].decode("latin-1") if 0 <= g.name_idx < len(n.strings) else ""
        out.append({"shape": name, "vertices": m.num_verts if m else None, "material": mat})
    return out


def add_models(rep: dict, sf_data: str) -> None:
    """Each listed addon's male model: its shapes, vertex counts and materials."""
    import hkx_to_af
    rows = list(rep["skin"].get("addons", [])) + [r for rs in rep["compare"].values() for r in rs]
    for r in rows:
        if not r.get("male"):
            continue
        try:
            data, _ = hkx_to_af.vanilla_file("meshes/" + r["male"].replace("\\", "/"), sf_data)
            r["model"] = model_shapes(data)
        except (SystemExit, Exception) as e:              # report, keep going
            r["model"] = [{"error": str(e)}]


def probe(esm: str) -> dict:
    recs = sfplugin.records(esm, [b"RACE", b"ARMO", b"ARMA"])
    arma = {fid: subs for t, _h, subs, fid in recs if t == b"ARMA"}
    armo = {fid: subs for t, _h, subs, fid in recs if t == b"ARMO"}
    by_edid = {sfplugin.edid(subs): fid for fid, subs in armo.items()}
    rep = {"skin": {}, "naked_addons": [], "compare": {}}
    for t, _h, subs, fid in recs:
        if t == b"RACE" and sfplugin.edid(subs) == "HumanRace":
            w = next((bytes(d) for s, d in subs if s == b"WNAM" and len(d) >= 4), None)
            if w:
                skin, = struct.unpack_from("<I", w, 0)
                rep["skin"] = {"armor": f"{skin:08X}", "edid": sfplugin.edid(armo.get(skin, [])),
                               "addons": armor_addons(armo.get(skin, []), arma)}
    for fid, subs in arma.items():
        row = addon_row(fid, subs)
        if "clothes\\naked" in (row["male"] + row["female"]).lower().replace("/", "\\"):
            rep["naked_addons"].append(row)
    for name in COMPARE:
        if name in by_edid:
            rep["compare"][name] = armor_addons(armo[by_edid[name]], arma)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rep = probe(os.path.join(a.starfield, "Data", "Starfield.esm"))
    add_models(rep, os.path.join(a.starfield, "Data"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "slot_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    sk = rep["skin"]
    print(f"HumanRace skin armor {sk.get('armor')} {sk.get('edid')}:")
    for r in sk.get("addons", []):
        print(f"  {r['edid']}: slots {r['slots']}  {r['male']}")
        for m in r.get("model", []):
            print(f"      {m}")
    print("addons with models under clothes\\naked:")
    for r in rep["naked_addons"][:20]:
        print(f"  {r['edid']}: slots {r['slots']}  {r['male'] or r['female']}")
    for name, rows in rep["compare"].items():
        print(f"{name}:")
        for r in rows:
            print(f"  {r['edid']}: slots {r['slots']}  {r['male']}")
            for m in r.get("model", []):
                print(f"      {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
