"""Which face texture layer is the looks menu's "Facial Forms 2" (owner 2026-11-13: options 14 / 15 age a face, the
look Elder-race NPCs need) and what its textures are. Read-only.

    python -I scripts\\npc\\face_layer_probe.py --starfield $sf --out C:\\Modding\\work\\races\\face_layers

Starfield NPC_ records carry their face texture layers as blocks (MNAM, TNAM layer name, QNAM texture name, VNAM
texture file, NNAM, INTV ...; npc_face_probe.py counted 22 layer names: Dermaesthetic, ComplexionMask1/2,
Complexion1/2, Accents1/2, ColorlessAccents1/2, Scars ...). Writes face_layers.json and face_layers.md:
1. per layer name: how many NPCs use it, its texture names (most used first) with a texture file and the block's
   other subrecords for each;
2. AVMD records whose EditorID or strings match --match (the looks menu's option lists), all their subrecords;
3. the full layer blocks of --npc NPCs (default: the generic templates, and up to 6 NPCs whose Dermaesthetic is an
   old (ol) face).
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import sfplugin  # noqa: E402

LAYER_SIGS = (b"MNAM", b"TNAM", b"QNAM", b"VNAM", b"NNAM", b"INTV", b"LNAM", b"ENAM", b"FNAM", b"XNAM")


def show(d):
    """Text for a zero-terminated printable string, else u32 / f32 for 4 bytes, else hex (first 48 bytes)."""
    d = bytes(d)
    if d.endswith(b"\0") and all(32 <= c < 127 for c in d[:-1]):
        return d[:-1].decode("latin-1")
    if len(d) == 4:
        return f"{struct.unpack('<I', d)[0]:08X} / {struct.unpack('<f', d)[0]:.4g}"
    return d[:48].hex(" ") + (" ..." if len(d) > 48 else "")


def layer_blocks(subs):
    """[[(sig, shown value)]] per texture layer: from each TNAM (with an MNAM just before it) to the next layer."""
    out, cur = [], None
    for i, (s, d) in enumerate(subs):
        if s == b"TNAM":
            cur = [(s.decode(), show(d))]
            if i and subs[i - 1][0] == b"MNAM":
                cur.insert(0, ("MNAM", show(subs[i - 1][1])))
            out.append(cur)
        elif cur is not None and s in LAYER_SIGS and s != b"MNAM":
            cur.append((s.decode(), show(d)))
        elif cur is not None and s not in LAYER_SIGS:
            cur = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--match", default=r"accent|form|complexion|wrinkl|aging|elder|old")
    ap.add_argument("--npc", action="append", default=[])
    a = ap.parse_args(argv)
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    want = set(a.npc or ["ChargenPresetFemale04", "ChargenPresetFemale04_Swap"])
    layers = collections.defaultdict(lambda: {"npcs": 0, "textures": collections.Counter(), "example": {}})
    picked, old = {}, []
    for _t, _h, subs, fid in sfplugin.records(esm, [b"NPC_"]):
        e = sfplugin.edid(subs)
        blocks = layer_blocks(subs)
        for b in blocks:
            name = dict(b).get("TNAM")
            tex = dict(b).get("QNAM", "")
            L = layers[name]
            L["npcs"] += 1
            L["textures"][tex] += 1
            L["example"].setdefault(tex, {"npc": e, "block": b})
        if e in want:
            picked[e] = {"form_id": f"{fid:08X}", "layers": blocks}
        derma = next((dict(b).get("QNAM", "") for b in blocks if dict(b).get("TNAM") == "Dermaesthetic"), "")
        if re.search(r"_ol\d_", derma) and len(old) < 6 and not a.npc:
            old.append(e)
            picked[e] = {"form_id": f"{fid:08X}", "layers": blocks, "why": "old Dermaesthetic"}
    rx = re.compile(a.match, re.I)
    avmd = []
    for _t, _h, subs, fid in sfplugin.records(esm, [b"AVMD"]):
        strings = [show(d) for _s, d in subs]
        if rx.search(sfplugin.edid(subs)) or any(isinstance(x, str) and rx.search(x) and not re.fullmatch(
                r"[0-9A-F]{8} / .*|[0-9a-f ]+( \.\.\.)?", x) for x in strings):
            avmd.append({"edid": sfplugin.edid(subs), "form_id": f"{fid:08X}",
                         "subs": [(s.decode("latin-1"), show(d)) for s, d in subs][:400]})
    rep = {"layers": {n: {"npcs": L["npcs"], "distinct_textures": len(L["textures"]),
                          "textures": [{"name": t, "npcs": c, "example": L["example"][t]}
                                       for t, c in L["textures"].most_common(80)]}
                      for n, L in sorted(layers.items(), key=lambda kv: -kv[1]["npcs"])},
           "avmd": avmd, "npcs": picked}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "face_layers.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    lines = ["# Face texture layers (Starfield.esm NPCs)", ""]
    for n, L in rep["layers"].items():
        lines.append(f"## {n}: {L['npcs']} NPCs, {L['distinct_textures']} textures")
        for t in L["textures"][:40]:
            blk = "; ".join(f"{s} {v}" for s, v in t["example"]["block"] if s not in ("TNAM", "QNAM"))
            lines.append(f"- {t['name']} ({t['npcs']}; e.g. {t['example']['npc']}): {blk}")
        lines.append("")
    lines.append(f"## AVMD records matching /{a.match}/: {len(avmd)}")
    for r in avmd[:80]:
        lines.append(f"- {r['edid']} {r['form_id']}: " + "; ".join(f"{s} {v}" for s, v in r["subs"][:30]))
    lines.append("")
    for e, p in picked.items():
        lines.append(f"## {e} {p['form_id']} {p.get('why', '')}")
        for b in p["layers"]:
            lines.append("- " + "; ".join(f"{s} {v}" for s, v in b))
    with open(os.path.join(a.out, "face_layers.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{len(rep['layers'])} layer names, {len(avmd)} AVMD matches, {len(picked)} NPCs -> "
          f"{os.path.join(a.out, 'face_layers.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
