"""How does Starfield choose the animations an actor plays for the weapon it holds? Read-only survey of Starfield.esm
for the Skyrim weapon port (bows first; docs/armor/animation-port.md "Weapons").

Evidence so far: the Alternate Recoil Animations mod (Nexus 16838) edits "about 400 subgraph data records" with xEdit
and gives "weapons using custom animation sets"; in Fallout 4 (same engine line) a race's subgraph data maps actor
keywords + weapon keywords (Anims* keywords on the WEAP) to the animation folders the behaviour graph plays from.
Supported hypothesis to test here: Starfield keeps that scheme, so a converted bow becomes a WEAP with its own
animation keyword plus subgraph entries pointing at a folder of converted clips, with no graph edits.

The survey does not assume record layouts. It writes report.txt with:
  1. every top-level record type with its count and sample EditorIDs (a ~hundreds group named like subgraph data
     should stand out)
  2. which record types contain animation-path text (animations\\, .agx, .afx, subgraph) and how often, with samples
  3. the keywords whose EditorID looks animation-related (Anims*, *Anim*, *Grip*, *Archetype*, *Subgraph*), and how
     many WEAP records carry each
  4. a full subrecord dump of a few weapons: a melee weapon, a rifle, a pistol, a heavy weapon (or --weapon)
  5. the subrecord field list of HumanRace

    python -I scripts\\armor\\weapon_anim_survey.py --esm "<Starfield>\\Data\\Starfield.esm" --out C:\\Modding\\work\\weapon_anims
"""
import argparse
import collections
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

ANIM_TEXT = re.compile(rb"animations\\|animations/|\.agx|\.afx|subgraph|AnimTextData|\\Anims", re.I)
ANIM_KEYWORD = re.compile(r"^Anims|Anim(Type|Arch|Flavor|Grip|Set)|Grip|Archetype|Subgraph|WeaponType|AnimFace", re.I)
DEFAULT_WEAPONS = r"^(Rifle_Grendel|Pistol_Eon|Rifle_Kraken|Melee_Knife|Melee_Sword|Melee_.*Axe|.*Bow.*|Heavy_Arc.*)"


def walk(p, start, end, depth=0):
    for item in fo4land.iter_items(p.buf, start, end):
        if item[0] == "GRUP":
            yield from walk(p, item[1] + 24, item[2], depth + 1)
        else:
            yield item


def text_of(d: bytes):
    s = d.rstrip(b"\0")
    return s.decode("latin-1") if len(s) >= 3 and all(32 <= c < 127 for c in s) else None


def fields(p, off):
    return [(s, bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))]


def dump(fs, w, names=None, n=80):
    for s, d in fs:
        t = text_of(d)
        extra = ""
        if names is not None and len(d) % 4 == 0 and 4 <= len(d) <= 256 and t is None:
            ids = struct.unpack(f"<{len(d) // 4}I", d)
            known = [names[i] for i in ids if i in names]
            if known:
                extra = "   -> " + ", ".join(known[:12])
        w(f"    {s.decode('latin-1')} [{len(d)}] {d[:n].hex(' ')}{' ...' if len(d) > n else ''}"
          + (f"   '{t}'" if t else "") + extra)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--weapon", default=DEFAULT_WEAPONS, help="regex on WEAP EditorIDs to dump in full")
    ap.add_argument("--max-weapons", type=int, default=8)
    ap.add_argument("--samples", type=int, default=6)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    lines = []
    w = lines.append
    by_type = collections.Counter()
    edids = collections.defaultdict(list)
    anim_hits = collections.Counter()
    anim_samples = collections.defaultdict(list)
    kw_names, weapons, races = {}, [], []
    kw_use = collections.Counter()
    with fo4land.Plugin(a.esm) as p:
        for typ, off, _flags, fid in walk(p, p.body, len(p.buf)):
            t = typ.decode("latin-1")
            by_type[t] += 1
            try:
                fs = fields(p, off)
            except Exception:                              # noqa: BLE001
                continue
            edid = next((fo4land.zstring(d) for s, d in fs if s == b"EDID"), "")
            if len(edids[t]) < 5 and edid:
                edids[t].append(edid)
            if t == "KYWD":
                kw_names[fid] = edid
            elif t == "WEAP":
                weapons.append((fid, edid, off))
            elif t == "RACE" and edid.lower() == "humanrace":
                races.append((fid, edid, fs))
            if t in ("WRLD", "CELL", "REFR", "NAVM", "LAND", "ACHR"):
                continue
            hit = sorted(((s, d) for s, d in fs if ANIM_TEXT.search(d)), key=lambda x: x[0] == b"EDID")
            if hit:
                anim_hits[t] += 1
                if len(anim_samples[t]) < a.samples:
                    s, d = hit[0]
                    m = ANIM_TEXT.search(d)
                    ctx = re.sub(r"[^ -~]", ".", d[max(0, m.start() - 60):m.end() + 80].decode("latin-1", "replace"))
                    anim_samples[t].append(f"{fid:08X} {edid!r} field {s.decode('latin-1')}: ...{ctx}...")
        w("1. record types (count, sample EditorIDs)")
        for t, n in sorted(by_type.items()):
            w(f"  {t:5} {n:7,}  {', '.join(edids[t][:5])}")
        w("\n2. record types holding animation-path text (animations\\, .agx, .afx, subgraph, AnimTextData)")
        for t, n in anim_hits.most_common():
            w(f"  {t:5} {n:6,} records")
            for s in anim_samples[t]:
                w(f"      {s}")
        # keyword use on weapons
        for fid, edid, off in weapons:
            for s, d in fields(p, off):
                if s == b"KWDA":
                    for k in struct.unpack(f"<{len(d) // 4}I", d):
                        kw_use[k] += 1
        anim_kw = sorted(((kw_names[k], n) for k, n in kw_use.items() if k in kw_names and ANIM_KEYWORD.search(kw_names[k])),
                         key=lambda x: -x[1])
        w(f"\n3. animation-looking keywords on weapons ({len(weapons):,} WEAP records): keyword, weapons carrying it")
        for name, n in anim_kw[:150]:
            w(f"  {n:5}  {name}")
        unused = sorted(v for k, v in kw_names.items() if ANIM_KEYWORD.search(v) and kw_use.get(k, 0) == 0)
        w(f"  animation-looking keywords on no weapon ({len(unused)}): " + ", ".join(unused[:120]))
        rx = re.compile(a.weapon, re.I)
        picked = [x for x in weapons if rx.search(x[1])][:a.max_weapons] or weapons[:4]
        w("\n4. weapons in full (keyword lists resolved)")
        for fid, edid, off in picked:
            w(f"  WEAP {fid:08X} {edid}")
            dump(fields(p, off), w, kw_names)
        w("\n5. HumanRace fields")
        for fid, edid, fs in races:
            w(f"  RACE {fid:08X} {edid}: {len(fs)} subrecords; types: " +
              ", ".join(f"{s.decode('latin-1')}x{n}" for s, n in collections.Counter(s for s, _ in fs).items()))
            subg = [(s, d) for s, d in fs if ANIM_TEXT.search(d)]
            w(f"    {len(subg)} subrecords with animation-path text; first 30:")
            dump(subg[:30], w, kw_names, n=60)
    rep = os.path.join(a.out, "report.txt")
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {rep}: {len(by_type)} record types, animation text in {sum(anim_hits.values()):,} records, "
          f"{len(weapons):,} weapons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
