"""How Starfield stores skin tones and eye colours, for races of our own (races plan: Orc green, Dunmer grey, Altmer
gold skin; Dunmer red, Altmer gold eyes; 2026-11-10, written while the owner was away). Read-only.

    python -I scripts\\npc\\look_probe.py --starfield $sf --out C:\\Modding\\work\\races [--plugin <a race mod's .esm>]

Per race (HumanRace in Starfield.esm, plus every RACE in each --plugin, e.g. the Star Wars aliens mod whose green skin
the owner used) and sex: the chargen strings (xEdit SF1 RACE "Chargen and Skintones": FDDS Skin Tone AVMS Subtype,
BSTT / HSTT / FSTT body / hand / face skin tones, FCTP face custom textures base path), and the AVMD records ("AVMS
Data": MNAM group type, YNAM / TNAM names, entries LNAM name + VNAM value ...) those strings name, followed through
their entries' links up to --depth levels. Eyes: every eye head part (HDPT type Right Eye 2 / Left Eye 12) on
HeadPartsHumanRace (and the plugins' eye parts): its model, NAM2 colour mapping (an AVMD name) followed the same way,
NAM3 mask, TNAM texture set (TXST dumped). Writes look_probe.json and look_probe.md.
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import sfplugin  # noqa: E402

RACE_STRINGS = (b"FDDS", b"BSTT", b"HSTT", b"FCTP", b"FSTT")
EYE_TYPES = {2: "right eye", 12: "left eye"}
SEXES = {False: "male", True: "female"}


def text(d):
    d = bytes(d)
    if d.endswith(b"\0") and all(32 <= c < 127 for c in d[:-1]):
        return d[:-1].decode("latin-1")
    return None


def value(sig, d):
    """A readable form of a subrecord: its text, or u32 hex + float for 4 bytes, else hex (first 48 bytes)."""
    d = bytes(d)
    t = text(d)
    if t is not None and t:
        return t
    if len(d) == 4:
        u, = struct.unpack("<I", d)
        f, = struct.unpack("<f", d)
        return f"{u:08X} ({f:.4g})"
    if len(d) in (8, 12, 16) and len(d) % 4 == 0:
        return "[" + ", ".join(f"{x:.4g}" for x in struct.unpack(f"<{len(d) // 4}f", d)) + f"] hex {d.hex()}"
    return f"{len(d)} bytes {d[:48].hex()}{'...' if len(d) > 48 else ''}"


def race_strings(subs):
    """{sex: {sig: text}} of a RACE's chargen and skin-tone strings (sex sections by the empty MNAM / FNAM markers)."""
    out, sex = {}, None
    for s, d in subs:
        if s in (b"MNAM", b"FNAM") and len(d) == 0:
            sex = SEXES[s == b"FNAM"]
            continue
        if sex and s in RACE_STRINGS:
            t = text(d)
            if t:
                out.setdefault(sex, {})[s.decode()] = t
    return out


class Avmd:
    """AVMD records by EditorID (lower case) across plugins (later ones override)."""

    def __init__(self, recs):
        self.by = {}
        for _t, _h, subs, fid in recs:
            self.by[sfplugin.edid(subs).lower()] = (fid, subs)

    def tree(self, name, depth=2, seen=None, max_entries=40):
        """{"edid", "form", "fields": [(sig, value)], "links": {name: tree}} or None."""
        seen = set() if seen is None else seen
        key = (name or "").lower()
        if key in seen or key not in self.by:
            return None
        seen.add(key)
        fid, subs = self.by[key]
        fields, links, entries = [], {}, 0
        for s, d in subs:
            if s in (b"LNAM", b"VNAM"):
                entries += s == b"LNAM"
                if entries > max_entries:
                    continue
            fields.append((s.decode("latin-1"), value(s, d)))
            t = text(d)
            if depth > 0 and s in (b"LNAM", b"VNAM") and t:
                # entries name other AVMD records directly or as "<Prefix>_<Name>" (xEdit's link callback)
                for cand in (t, t.split("_", 1)[1] if "_" in t else ""):
                    sub = self.tree(cand, depth - 1, seen, max_entries)
                    if sub is not None:
                        links[t] = sub
                        break
        if entries > max_entries:
            fields.append(("...", f"{entries - max_entries} more entries"))
        return {"edid": sfplugin.edid(subs), "form": f"{fid:08X}", "fields": fields, "links": links}


def find_trees(av, name, depth):
    """The AVMD named name, else those whose EditorID / YNAM / TNAM contains it (at most 5)."""
    t = av.tree(name, depth)
    if t is not None:
        return [t]
    low = name.lower()
    hits = []
    for e, (_fid, subs) in av.by.items():
        names = [e] + [(text(d) or "").lower() for s, d in subs if s in (b"YNAM", b"TNAM")]
        if any(low and low in n for n in names):
            hits.append(av.tree(e, depth))
        if len(hits) >= 5:
            break
    return [h for h in hits if h]


def eye_parts(recs, lists):
    """[(fid, edid, subs)] of eye head parts (types 2 / 12) whose valid-race list is one of lists (FormIDs), or any
    list when lists is None."""
    out = []
    for t, _h, subs, fid in recs:
        if t != b"HDPT":
            continue
        d = dict(subs)
        typ = struct.unpack("<I", bytes(d.get(b"PNAM", bytes(4)))[:4])[0]
        rl = struct.unpack("<I", bytes(d.get(b"RNAM", bytes(4)))[:4])[0]
        if typ in EYE_TYPES and (lists is None or rl in lists):
            out.append((fid, sfplugin.edid(subs), subs))
    return out


def probe(plugins, depth=2):
    """The report for plugins (Starfield.esm first)."""
    allr = []
    for p in plugins:
        allr += [(p, r) for r in sfplugin.records(p, [b"RACE", b"AVMD", b"HDPT", b"FLST", b"TXST"])]
    av = Avmd([r for _p, r in allr if r[0] == b"AVMD"])
    txst = {r[3]: r[2] for _p, r in allr if r[0] == b"TXST"}
    rep = {"plugins": [os.path.basename(p) for p in plugins], "avmd_records": len(av.by), "races": {}, "eyes": {}}
    races = [(p, r) for p, r in allr if r[0] == b"RACE" and
             (sfplugin.edid(r[2]) == "HumanRace" or p != plugins[0])]
    for p, r in races:
        rr = {"plugin": os.path.basename(p), "form": f"{r[3]:08X}", "strings": race_strings(r[2]), "avmd": {}}
        for sex, st in rr["strings"].items():
            for sig in ("FDDS", "BSTT", "HSTT", "FSTT"):
                if sig in st:
                    rr["avmd"].setdefault(sex, {})[sig] = find_trees(av, st[sig], depth)
        rep["races"][sfplugin.edid(r[2])] = rr
    human_list = {r[3] for _p, r in allr if r[0] == b"FLST" and sfplugin.edid(r[2]) == "HeadPartsHumanRace"}
    for p, (fid, edid, subs) in [(p, x) for p in plugins for x in
                                  eye_parts([r for q, r in allr if q == p], human_list if p == plugins[0] else None)]:
        d = dict(subs)
        e = {"plugin": os.path.basename(p), "form": f"{fid:08X}", "fields": [(s.decode("latin-1"), value(s, x))
                                                                            for s, x in subs]}
        cm = text(d.get(b"NAM2", b"")) or ""
        if cm:
            e["colour_mapping"] = find_trees(av, cm, depth)
        tn = struct.unpack("<I", bytes(d.get(b"TNAM", bytes(4)))[:4])[0] if b"TNAM" in d else 0
        if tn in txst:
            e["texture_set"] = [(s.decode("latin-1"), value(s, x)) for s, x in txst[tn]]
        rep["eyes"][edid] = e
    return rep


def markdown(rep):
    L = [f"# Looks probe ({', '.join(rep['plugins'])}; {rep['avmd_records']} AVMD records)", ""]

    def tree_lines(t, ind="  "):
        out = [f"{ind}- AVMD {t['edid']} [{t['form']}]"]
        for s, v in t["fields"]:
            out.append(f"{ind}  - {s}: {v}")
        for name, sub in t["links"].items():
            out.append(f"{ind}  - -> {name}:")
            out += tree_lines(sub, ind + "    ")
        return out
    for name, r in rep["races"].items():
        L += [f"## RACE {name} ({r['plugin']} {r['form']})", ""]
        for sex, st in r["strings"].items():
            L.append(f"- {sex}: " + ", ".join(f"{k} {v!r}" for k, v in st.items()))
            for sig, trees in r["avmd"].get(sex, {}).items():
                L.append(f"  - {sig}:" + ("" if trees else " (no AVMD found)"))
                for t in trees:
                    L += tree_lines(t, "    ")
        L.append("")
    L += ["## Eyes", ""]
    for name, e in rep["eyes"].items():
        L.append(f"- HDPT {name} ({e['plugin']} {e['form']})")
        L += [f"  - {s}: {v}" for s, v in e["fields"]]
        for t in e.get("colour_mapping", []):
            L += tree_lines(t, "    ")
        if "texture_set" in e:
            L.append("  - texture set:")
            L += [f"    - {s}: {v}" for s, v in e["texture_set"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--plugin", action="append", default=[], help="a race mod's plugin to read too (repeatable)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--depth", type=int, default=2, help="AVMD links followed this deep")
    a = ap.parse_args(argv)
    plugins = [os.path.join(a.starfield, "Data", "Starfield.esm")] + list(a.plugin)
    rep = probe(plugins, a.depth)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "look_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    with open(os.path.join(a.out, "look_probe.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(rep))
    print(f"{len(rep['races'])} races, {len(rep['eyes'])} eye parts, {rep['avmd_records']} AVMD records -> "
          f"{os.path.join(a.out, 'look_probe.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
