"""What a race's skin tones are in Skyrim and in Starfield, to plan the Orc's green skin (2026-11-11, owner: test the
Orc's skin tone before building every race). Read-only.

    python -I scripts\\npc\\skin_tone_probe.py --skyrim-data "<Skyrim>\\Data" --starfield "<Starfield>" --out <folder>

Skyrim (verified layout, xEdit TES5 RACE "Tint Masks", per sex after the empty MNAM / FNAM markers): TINI index, TINT
mask texture, TINP mask type (6 = skin tone), TIND default preset, then per preset TINC colour (a CLFM: CNAM r g b a),
TINV value, TIRS index. Printed per race: the skin tone presets' colours and values.

Starfield (look_probe 2026-11-10: RACE BSTT / HSTT name body / hand skin tone AVMD groups, face tones are groups named
FaceSkinTones_<phenotype>; each lists 9 colour textures sk0..sk8): per skin tone group, its textures and, from the
texture archives, the first one's DDS header (size, format) - what recoloured copies would have to match.
Writes skin_tone_probe.json and prints a summary.
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, sfplugin, textures  # noqa: E402

SKIN_TONE_MASK = 6
SKY_RACES = ("NordRace", "ImperialRace", "BretonRace", "RedguardRace", "HighElfRace", "WoodElfRace", "DarkElfRace",
             "OrcRace", "ElderRace")
TONE_WORDS = ("skin_tones", "faceskintones", "_hands")


def _u(d, fmt="<I"):
    return struct.unpack_from(fmt, bytes(d), 0)[0]


def tint_masks(subs):
    """{sex: [{"index", "texture", "type", "default", "presets": [(CLFM, value, index)]}]} of a Skyrim RACE."""
    out, sex, cur = {}, None, None
    for s, d in subs:
        if s in (b"MNAM", b"FNAM") and len(d) == 0:
            sex, cur = ("female" if s == b"FNAM" else "male"), None
            continue
        if sex is None:
            continue
        if s == b"TINI":
            cur = {"index": _u(d, "<H"), "texture": "", "type": None, "default": None, "presets": []}
            out.setdefault(sex, []).append(cur)
        elif cur is None:
            continue
        elif s == b"TINT":
            cur["texture"] = bytes(d).rstrip(b"\0").decode("latin-1")
        elif s == b"TINP":
            cur["type"] = _u(d, "<H")
        elif s == b"TIND":
            cur["default"] = _u(d)
        elif s == b"TINC":
            cur["presets"].append([_u(d), None, None])
        elif s == b"TINV" and cur["presets"]:
            cur["presets"][-1][1] = round(_u(d, "<f"), 4)
        elif s == b"TIRS" and cur["presets"]:
            cur["presets"][-1][2] = _u(d, "<H")
    return out


def clfm_colours(recs):
    """{FormID: (EditorID, (r, g, b))} of CLFM records."""
    out = {}
    for t, _h, subs, fid in recs:
        if t == b"CLFM":
            c = dict(subs).get(b"CNAM", b"\0\0\0\0")
            out[fid] = (sfplugin.edid(subs), tuple(bytes(c)[:3]))
    return out


def skyrim_tones(sky_esm, races=SKY_RACES):
    recs = sfplugin.records(sky_esm, [b"RACE", b"CLFM"])
    col = clfm_colours(recs)
    out = {}
    for t, _h, subs, _fid in recs:
        e = sfplugin.edid(subs)
        if t != b"RACE" or e not in races:
            continue
        for sex, masks in tint_masks(subs).items():
            for m in masks:
                if m["type"] != SKIN_TONE_MASK:
                    continue
                out.setdefault(e, {})[sex] = {
                    "mask": m["texture"], "default": col.get(m["default"], (f"{m['default'] or 0:08X}", None))[0],
                    "presets": [{"colour": col.get(c, (f"{c:08X}", None))[0], "rgb": col.get(c, (None, None))[1],
                                 "value": v} for c, v, _i in m["presets"]]}
    return out


def tone_groups(recs):
    """[{edid, ynam, tnam, textures}] of Starfield AVMD skin tone groups (body / hand / face)."""
    out = []
    for t, _h, subs, fid in recs:
        if t != b"AVMD":
            continue
        d = dict(subs)
        names = [bytes(d.get(s, b"")).rstrip(b"\0").decode("latin-1") for s in (b"YNAM", b"TNAM")]
        if not any(w in n.lower() for n in names for w in TONE_WORDS):
            continue
        tex = [bytes(v).rstrip(b"\0").decode("latin-1") for s, v in subs if s == b"VNAM"]
        out.append({"edid": sfplugin.edid(subs), "form": f"{fid:08X}", "ynam": names[0], "tnam": names[1],
                    "textures": [x for x in tex if x.lower().endswith(".dds")]})
    return out


class TextureArchives:
    def __init__(self, data):
        self.where = {}
        for fn in sorted(os.listdir(data)):
            if fn.lower().endswith(".ba2") and "texture" in fn.lower():
                try:
                    a = ba2.Ba2(os.path.join(data, fn))
                except Exception:                                  # noqa: BLE001
                    continue
                for n in a.names:
                    self.where.setdefault(n.replace("\\", "/").lower(), (a, fn))

    def header(self, path):
        k = path.replace("\\", "/").lower()
        k = k if k.startswith("textures/") else "textures/" + k
        hit = self.where.get(k)
        if hit is None:
            return None
        a, fn = hit
        data = a.read(a.find(k))
        h = textures.read_dds_header(data)
        return {"archive": fn, "width": h["width"], "height": h["height"], "mips": h["mips"], "dxgi": h["dxgi"],
                "bytes": len(data)}


def probe(sky_esm, sf_data, arcs=None):
    rep = {"skyrim": skyrim_tones(sky_esm) if sky_esm else {}}
    groups = tone_groups(sfplugin.records(os.path.join(sf_data, "Starfield.esm"), [b"AVMD"]))
    arcs = arcs if arcs is not None else TextureArchives(sf_data)
    for g in groups:
        g["first_texture"] = arcs.header(g["textures"][0]) if g["textures"] else None
    rep["starfield_groups"] = groups
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="the game folder (with Data)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rep = probe(os.path.join(a.skyrim_data, "Skyrim.esm"), os.path.join(a.starfield, "Data"))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "skin_tone_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    for race, per in rep["skyrim"].items():
        for sex, x in per.items():
            print(f"Skyrim {race} {sex}: {len(x['presets'])} skin tones, default {x['default']}: "
                  + ", ".join(f"{p['colour']} {p['rgb']} x{p['value']}" for p in x["presets"][:12]))
    for g in rep["starfield_groups"]:
        print(f"Starfield {g['edid']} ({g['ynam']} / {g['tnam']}): {len(g['textures'])} textures; first "
              f"{g['textures'][0] if g['textures'] else '-'} {g['first_texture']}")
    print(f"-> {os.path.join(a.out, 'skin_tone_probe.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
