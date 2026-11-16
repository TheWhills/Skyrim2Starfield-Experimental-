"""Skyrim's idle markers: how long an NPC stays at each (IDLT idle timer, IDLF flags) (read-only).

2026-11-16 (owner): Alvor stands at one idle spot (a PatrolIdleMarker, converted to Starfield standing furniture) most
of his work day, Hilde stays in her chair. Skyrim's IDLM records carry a timer (seconds at the marker before the
sandbox moves on); our conversion to furniture does not carry it. This prints the timer and flags of the idle markers
in --edids (default: the kinds placed around Riverwood), so the conversion can be judged.

    python -I scripts\\npc\\idle_marker_timers.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm"
"""
import argparse
import struct
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

RIVERWOOD = ("PatrolIdleMarker", "SweepIdleMarker", "BrowseIdleMarker", "FlowersIdleMarker", "IdleFarmingMarker",
             "CrossedArmsIdleMarker", "WarmHandsIdleMarker", "BigWoodPileIdleMarker", "GerdurTableIdleMarker",
             "DrunkIdleMarker", "LockPickIdleMarker", "CowEatingIdleMarker")


def marker_info(subs) -> dict:
    out = {"timer_s": None, "flags": None, "anims": 0}
    for s, d in subs:
        if s == b"IDLT" and len(d) >= 4:
            out["timer_s"] = round(struct.unpack_from("<f", d)[0], 2)
        elif s == b"IDLF" and len(d) >= 1:
            out["flags"] = d[0]
        elif s == b"IDLA":
            out["anims"] = len(d) // 4
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--edids", nargs="*", default=list(RIVERWOOD))
    a = ap.parse_args(argv)
    from fo4sf import packages
    ix = packages.Index(a.skyrim)
    try:
        for e in a.edids:
            fid = ix.find_edid(b"IDLM", e)
            if fid is None:
                print(f"{e}: no IDLM")
                continue
            i = marker_info(ix.subs(fid))
            fl = i["flags"]
            print(f"{e} {fid:08X}: timer {i['timer_s']} s, flags {fl if fl is None else f'0x{fl:02X}'}"
                  f" (0x01 run in sequence, 0x04 do once, 0x10 ignored by sandbox), {i['anims']} idles")
    finally:
        ix.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
