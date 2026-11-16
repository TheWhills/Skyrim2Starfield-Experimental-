"""Whether Skyrim clips chain without a jump: how far each clip B starts from where clip A ends (read-only).

2026-11-16: the forge's Discard + Pull flavor (retarget.concat) reported join_turn_deg 103.6 at the cut, so the Discard
does not end on the Pull's first pose (or a prop bone was counted). This prints, per pair A>B, the bones with the
largest local turn across the cut (AnimObject* marked, they are props) and the translation change, so the chain in
Skyrim's forge machine can be checked pair by pair: which clip really follows the Discard, and whether Pull starts
where the Hammer or the Temper ends.

    python -I scripts\\armor\\clip_join.py --skyrim-data "<Skyrim>\\Data"            (the forge pairs)
    python -I scripts\\armor\\clip_join.py --skyrim-data "<Skyrim>\\Data" a.hkx>b.hkx ...
"""
import argparse
import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

SKY_ANIM = "meshes\\actors\\character\\animations\\"
FORGE = ("blacksmithforgepull", "blacksmithforgehammer", "blacksmithforgetemper", "blacksmithforgediscard",
         "blacksmithforgeexit")


def forge_pairs() -> list:
    """Every ordered pair of the forge's clips (which can follow which)."""
    return [(a + ".hkx", b + ".hkx") for a, b in itertools.permutations(FORGE, 2)] + \
           [(a + ".hkx", a + ".hkx") for a in FORGE]


def summary(turns, top=6) -> str:
    body = [t for t in turns if not t[0].lower().startswith("animobject")]
    worst = body[0][1] if body else 0.0
    return f"body max {worst:6.1f} deg | " + ", ".join(
        f"{b}{' (prop)' if b.lower().startswith('animobject') else ''} {d} deg/{dt}" for b, d, dt in turns[:top])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("pairs", nargs="*", help="A.hkx>B.hkx under character\\animations (default: the forge's clips)")
    a = ap.parse_args(argv)
    from fo4sf import bsa, retarget, skyrimhkx
    import hkx_to_af
    sky = bsa.SkyrimArchives(a.skyrim_data)
    sk_desc = skyrimhkx.describe(hkx_to_af.read_any(hkx_to_af.SKY_SKELETON, sky))
    sk = retarget.rig_from_hkx_skeleton(next(s for s in sk_desc["skeletons"] if len(s["bones"]) > 20))
    pairs = [tuple(p.split(">")) for p in a.pairs] or forge_pairs()
    cache = {}

    def clip(name):
        if name not in cache:
            path = name if ("\\" in name or "/" in name) else SKY_ANIM + name
            cache[name] = retarget.resample(skyrimhkx.decode_clip(hkx_to_af.read_any(path, sky), sk.names), 30.0)
        return cache[name]
    for x, y in pairs:
        try:
            print(f"{x} > {y}: {summary(retarget.join_turns(clip(x), clip(y)))}")
        except SystemExit as e:
            print(f"{x} > {y}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
