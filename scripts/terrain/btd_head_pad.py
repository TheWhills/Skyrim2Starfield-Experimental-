"""Pad the staged Skyrim terrain's LTEX table head (2026-11-24, fo4sf.btd.with_head_padding): read-modify-write.

Every 50 m quadrant that used byte value 3 drew the default ground in game (owner's Rift label test); the converter now
puts Starfield's per-mask placeholders at the head of the table, as vanilla does, so no byte we use is below 8. This
applies that to an existing staging (both BTD copies), losslessly: every quadrant byte still names the same FormID.
Idempotent. Reinstall the exterior afterwards (tools\owner\grass_hook.ps1 does it).

    python -I scripts\terrain\btd_head_pad.py --staging C:\Modding\staging\skyrim_all
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import btd  # noqa: E402


def same_forms(a: btd.Btd, b: btd.Btd) -> bool:
    """Every quadrant byte of a and b names the same FormID (0 = none), weights and heights equal."""
    fa = np.array([0] + list(a.ltex), np.int64)[a.quad_map.astype(np.int64)]
    fb = np.array([0] + list(b.ltex), np.int64)[b.quad_map.astype(np.int64)]
    return (np.array_equal(fa, fb) and np.array_equal(a.weights, b.weights)
            and np.array_equal(a.heights_raw, b.heights_raw))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", required=True)
    a = ap.parse_args(argv)
    with open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    n = 0
    for o in prm["overlays"]:
        for rel in [o["btd_file"]] + list(o.get("btd_copies") or []):
            p = os.path.join(a.staging, *rel.split("/"))
            if not os.path.exists(p):
                continue
            with open(p, "rb") as fh:
                t = btd.read(fh.read())
            new = btd.with_head_padding(t)
            if new is t:
                print(f"{rel}: already padded")
                continue
            data = btd.write(new)
            if not same_forms(t, btd.read(data)):
                sys.exit(f"{rel}: check failed; file left as it was")
            with open(p, "wb") as fh:
                fh.write(data)
            low = int(new.quad_map[new.quad_map > 0].min()) if (new.quad_map > 0).any() else 0
            print(f"{rel}: table {len(t.ltex)} -> {len(new.ltex)}, lowest byte used {low}; same textures everywhere "
                  f"(checked)")
            n += 1
    print(f"{n} terrain file(s) padded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
