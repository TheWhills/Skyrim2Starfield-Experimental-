"""Which Starfield records an animation's SoundPlay names, and which of them could stand in for Skyrim's forge sounds.

2026-11-16 (owner's afx_events --name SoundPlay, verified): Starfield's descriptors play sounds as SoundPlay events
whose payload is a name (WPNGrenadeThrow, WPNMineThrow: 23 events, all grenade / mine throws). Skyrim's forge plays
SoundPlay.NPCHumanBlacksmithHammer etc. from its behaviour. This prints (read-only):
  1. Starfield.esm's top groups whose type looks like a sound record, with record counts;
  2. which of them holds the EditorID WPNGrenadeThrow (so: what kind of record a SoundPlay payload names);
  3. in those groups, the EditorIDs matching --match (hammer, anvil, metal impact, steam, water, fire, bellows ...);
  4. the WPNGrenadeThrow record's subrecords (signature, size, first bytes: how a sound record points at Wwise);
  5. with --skyrim-data: Skyrim's forge sounds (SKYRIM_FORGE) followed SOUN -> SNDR -> sound files, each file looked
     up in Skyrim's archives (2026-11-16, owner: "why can't we just grab the skyrim sounds ... We are already converted
     all the voices": the files to convert).

    python -I scripts\\armor\\sound_records.py --starfield "<Starfield>" --skyrim-data "<Skyrim>\\Data"
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

CANDIDATES = (b"WWED", b"SNDR", b"SOUN", b"SNCT", b"SOPM", b"AMBS", b"ASPC", b"MUSC", b"MUST", b"AECH", b"SDSC")
KNOWN = "WPNGrenadeThrow"
MATCH = (r"hammer|anvil|forge|smith|blacksmith|clang|metal.*(hit|impact)|impact.*metal|steam|hiss|sizzl|quench|"
         r"water.*splash|splash|bellows|fire|grind|sharpen|whetstone|repair|craft|workbench")


# smithing_probe (owner's run, verified): the forge machine's clip triggers
SKYRIM_FORGE = ("NPCHumanBlacksmithHammer", "NPCHumanBlacksmithHammerDistant", "NPCHumanBlacksmithForgeQuench",
                "NPCHumanBlacksmithForgeQuenchDrop", "OBJBlacksmithForge", "NPCHumanBlacksmithForgeTake")


def hexhead(data: bytes, n=48) -> str:
    return data[:n].hex(" ") + (" ..." if len(data) > n else "")


def zstr(d: bytes) -> str:
    return d.split(b"\0")[0].decode("utf-8", "replace")


def skyrim_sounds(sky_data, names=SKYRIM_FORGE) -> list:
    """Printable lines: each name's SOUN / SNDR record and the sound files its descriptor plays (ANAM), found or not
    in Skyrim's archives."""
    from fo4sf import bsa, packages
    ix = packages.Index(os.path.join(sky_data, "Skyrim.esm"))
    arcs = bsa.SkyrimArchives(sky_data)
    lines = []
    try:
        by_edid = {}
        for typ in (b"SOUN", b"SNDR"):
            for f in ix.by_type.get(typ, []):
                by_edid.setdefault((ix.edid(f) or "").lower(), []).append((typ, f))
        for name in names:
            hits = by_edid.get(name.lower(), [])
            if not hits:
                lines.append(f"  {name}: no SOUN / SNDR")
                continue
            for typ, f in hits:
                subs = ix.subs(f)
                sndr = [(typ, f, subs)]
                if typ == b"SOUN":
                    sd = next((int.from_bytes(d[:4], "little") for s_, d in subs if s_ == b"SDSC"), None)
                    lines.append(f"  {name}: SOUN {f:08X} -> SNDR {sd:08X}" if sd else f"  {name}: SOUN {f:08X}")
                    sndr = [(b"SNDR", sd, ix.subs(sd))] if sd else []
                for _t, sf_, ss in sndr:
                    files = [zstr(d) for s_, d in ss if s_ == b"ANAM"]
                    other = sorted({s_.decode() for s_, _d in ss} - {"ANAM", "EDID"})
                    lines.append(f"  {name}: SNDR {sf_:08X} {ix.edid(sf_)} ({', '.join(other)}), {len(files)} files")
                    for fn in files:
                        path = sound_path(fn)
                        d = arcs._read(bsa.norm(path))
                        lines.append(f"    {path}: {len(d)} bytes" if d is not None else f"    {path}: not found")
    finally:
        ix.close()
    return lines


def sound_path(fn: str) -> str:
    """A Skyrim SNDR file name (ANAM) as an archive path: 'fx\\...' -> 'sound\\fx\\...'; 'Data\\Sound\\fx\\...' (the
    Hearthfire / Update forge sounds, 2026-11-20: read as 'sound\\data\\sound\\...', not found) -> 'sound\\fx\\...'."""
    p = fn.lower().replace("/", "\\").lstrip("\\")
    if p.startswith("data\\"):
        p = p[5:]
    return p if p.startswith("sound\\") else "sound\\" + p


def shown_value(d: bytes) -> str:
    """A zero-terminated text subrecord as text, anything else as hex (outside the f-string: no backslash there
    before Python 3.12)."""
    return zstr(d) if d[-1:] == b"\0" and d[:-1].isascii() else hexhead(d)


def related(edids, name: str) -> list:
    """EditorIDs containing `name` (case-insensitive), e.g. WwiseEvent_WPNGrenadeThrow for WPNGrenadeThrow."""
    n = name.lower()
    return sorted(e for e in edids if e and n in e.lower())


def sound_groups(top_types, candidates=CANDIDATES) -> list:
    """The candidate sound types among a plugin's top groups (in the candidates' order)."""
    have = set(top_types)
    return [t for t in candidates if t in have]


def matching(edids, match=MATCH) -> list:
    rx = re.compile(match, re.I)
    return sorted(e for e in edids if rx.search(e))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--match", default=MATCH)
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--skyrim-data", help="also section 5: Skyrim's forge sounds and their files")
    a = ap.parse_args(argv)
    from fo4sf import fo4land, sfplugin
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    counts = {}
    with fo4land.Plugin(esm) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] == "GRUP" and item[4] == 0:
                counts[bytes(item[3])] = sum(1 for it in fo4land.iter_items(p.buf, item[1] + 24, item[2])
                                             if it[0] != "GRUP")
    groups = sound_groups(counts)
    print("== 1. sound-like top groups: " + ", ".join(f"{t.decode()} {counts[t]}" for t in groups))
    print("   other groups: " + ", ".join(sorted(t.decode("latin-1") for t in counts if t not in groups)))
    by_type = {}
    for t in groups:
        by_type[t] = [(sfplugin.edid(subs), fid) for _typ, _h, subs, fid in sfplugin.records(esm, [t])]
    print(f"== 2. {KNOWN}: " + (", ".join(f"{t.decode()} {fid:08X}" for t, rows in by_type.items()
                                         for e, fid in rows if e.lower() == KNOWN.lower()) or "not found"))
    # 2026-11-20 (owner's run: no record has the EditorID WPNGrenadeThrow): records whose EditorID contains it, and the
    # first WWED / SOUN records, every subrecord shown (how a sound record names its Wwise event)
    rel = {t: related([e for e, _f in rows], KNOWN) for t, rows in by_type.items()}
    print(f"== 2b. EditorIDs containing {KNOWN}: " + (", ".join(f"{t.decode()} {e}" for t, es in rel.items()
                                                              for e in es) or "none"))
    shown = {t: 0 for t in groups}
    for t in groups:
        for _typ, _h, subs, fid in sfplugin.records(esm, [t]):
            e = sfplugin.edid(subs)
            if e in rel.get(t, []) or (t in (b"WWED", b"SOUN") and shown[t] < 2):
                shown[t] += 1
                print(f"== 4. {t.decode()} {fid:08X} {e}: " + "; ".join(
                    f"{sg.decode('latin-1')} {len(d)}: {shown_value(d)}"
                    for sg, d in subs))
    if a.skyrim_data:
        print("== 5. Skyrim's forge sounds")
        for line in skyrim_sounds(a.skyrim_data):
            print(line)
    for t, rows in by_type.items():
        names = {e: fid for e, fid in rows if e}
        hits = matching(names, a.match)
        print(f"== 3. {t.decode()}: {len(hits)} of {len(names)} matching")
        for e in hits[:a.max]:
            print(f"  {names[e]:08X} {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
