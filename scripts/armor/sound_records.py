"""Which Starfield records an animation's SoundPlay names, and which of them could stand in for Skyrim's forge sounds.

2026-11-16 (owner's afx_events --name SoundPlay, verified): Starfield's descriptors play sounds as SoundPlay events
whose payload is a name (WPNGrenadeThrow, WPNMineThrow: 23 events, all grenade / mine throws). Skyrim's forge plays
SoundPlay.NPCHumanBlacksmithHammer etc. from its behaviour. This prints (read-only):
  1. Starfield.esm's top groups whose type looks like a sound record, with record counts;
  2. which of them holds the EditorID WPNGrenadeThrow (so: what kind of record a SoundPlay payload names);
  3. in those groups, the EditorIDs matching --match (hammer, anvil, metal impact, steam, water, fire, bellows ...).

    python -I scripts\\armor\\sound_records.py --starfield "<Starfield>"
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
    for t, rows in by_type.items():
        names = {e: fid for e, fid in rows if e}
        hits = matching(names, a.match)
        print(f"== 3. {t.decode()}: {len(hits)} of {len(names)} matching")
        for e in hits[:a.max]:
            print(f"  {names[e]:08X} {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
