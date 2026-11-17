"""Bisect the chicken's distance freeze (docs/npc/creatures.md, fix 10 and after) on the VANILLA trilobite: put the
critter's own clips or its own rig through CALUMI, with nothing of the chicken's, as loose files in a mod folder.

  --what clips  every critter .af read back with CALUMI against the vanilla rig and written again against it
                (keys made dense, header root motion copied from the vanilla clip; the .afx stay vanilla)
  --what rig    the vanilla rig copied through CALUMI (af_writer.rig_prefix with all bones); clips stay vanilla

Then `player.placeatme 2C180F` (vanilla trilobite) and walk off: if it now freezes a few feet away as the chicken did,
the part rebuilt by CALUMI is the cause. Disable the mod after.

    python -I scripts\\npc\\critter_roundtrip.py --starfield-data "$sf\\Data" --calumi $calumi --what clips --out "$mods\\S2S Critter Clip Test"
"""
import argparse
import json
import os
import posixpath
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

import numpy as np  # noqa: E402

RIG = "meshes/actors/critter/characterassets/skeleton.rig"
ANIMS = "meshes/actors/critter/animations/"


def _nlerp(a, b, u):
    b = b if float(np.dot(a, b)) >= 0 else -b
    q = (1 - u) * a + u * b
    return q / np.linalg.norm(q)


def dense_track(keys, frames: int, rest, quat: bool) -> np.ndarray:
    """(frames, 3|4) from sparse [(frame, value)]: held before the first and after the last key, linear (normalised for
    quaternions) between keys; `rest` when there are no keys."""
    out = np.tile(np.asarray(rest, float), (frames, 1))
    ks = sorted((int(f), np.asarray(v, float)) for f, v in keys)
    if not ks:
        return out
    for f in range(frames):
        if f <= ks[0][0]:
            out[f] = ks[0][1]
        elif f >= ks[-1][0]:
            out[f] = ks[-1][1]
        else:
            j = next(j for j in range(1, len(ks)) if ks[j][0] >= f)
            (f0, a), (f1, b) = ks[j - 1], ks[j]
            u = (f - f0) / (f1 - f0)
            out[f] = _nlerp(a, b, u) if quat else (1 - u) * a + u * b
    return out


def densify(read: dict, names, rest_t, rest_q):
    """clip_t (F, B, 3), clip_q (F, B, 4) in rig order from af_writer.read_back(absolute=True), and the rig bones the
    clip has no track for (to omit, so they stay untracked as in the vanilla clip)."""
    F = int(read["frames"])
    clip_t = np.zeros((F, len(names), 3))
    clip_q = np.zeros((F, len(names), 4))
    tracked = set(read["bones"])
    for i, n in enumerate(names):
        clip_t[:, i] = dense_track(read["translations"].get(n, []), F, rest_t[i], False)
        clip_q[:, i] = dense_track(read["rotations"].get(n, []), F, rest_q[i], True)
    return clip_t, clip_q, [n for n in names if n not in tracked]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield-data", required=True)
    ap.add_argument("--calumi", required=True)
    ap.add_argument("--what", choices=("clips", "rig"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="", help="comma-separated clip stems (default: every critter clip)")
    a = ap.parse_args(argv)

    from fo4sf import af_writer, rootmotion
    import sf_anim_survey as SAS
    out = os.path.abspath(a.out)
    work = os.path.join(out, "_work")
    os.makedirs(work, exist_ok=True)
    index = {}
    for _label, ar in SAS.archives(a.starfield_data):
        for i, n in enumerate(ar.names):
            index.setdefault(SAS.norm(n), (ar, i))

    def sf_read(key):
        ar, i = index[key]
        return ar.read(i)

    rep = {"what": a.what, "written": [], "errors": {}}

    def put(rel, data):
        p = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
        rep["written"].append(rel)

    vanilla_rig = os.path.join(work, "critter_vanilla.rig")
    with open(vanilla_rig, "wb") as fh:
        fh.write(sf_read(RIG))
    rig = af_writer.load_rig(a.calumi, vanilla_rig)
    rep["rig_bones"] = len(rig["names"])

    if a.what == "rig":
        copy = af_writer.rig_prefix(a.calumi, vanilla_rig, len(rig["names"]), os.path.join(work, "skeleton.rig"))
        with open(copy, "rb") as fh:
            put(RIG, fh.read())
    else:
        only = {s.strip().lower() for s in a.only.split(",") if s.strip()}
        clips = sorted(k for k in index if k.startswith(ANIMS) and k.endswith(".af")
                       and (not only or posixpath.basename(k)[:-3] in only))
        for key in clips:
            stem = posixpath.basename(key)[:-3]
            src = os.path.join(work, stem + ".src.af")
            data = sf_read(key)
            with open(src, "wb") as fh:
                fh.write(data)
            try:
                read = af_writer.read_back(a.calumi, src, vanilla_rig, absolute=True)
                ct, cq, untracked = densify(read, rig["names"], rig["t"], rig["q"])
                af_writer.write(a.calumi, os.path.join(work, "out"), stem, rig["names"], rig["parents"], rig["t"],
                                rig["q"], ct, cq, rig_path=vanilla_rig, file_name=stem, omit=untracked)
                written = os.path.join(work, "out", stem + ".af")
                hq, ht = rootmotion.read_header(data)
                rootmotion.patch_header(written, ht, hq)
                with open(written, "rb") as fh:
                    put(key, fh.read())
            except Exception as e:                       # noqa: BLE001  (one bad clip must not stop the rest)
                rep["errors"][stem] = f"{type(e).__name__}: {e}"
    shutil.rmtree(work, ignore_errors=True)
    with open(os.path.join(out, "critter_roundtrip.json"), "w") as fh:
        json.dump(rep, fh, indent=1)
    print(f"wrote {len(rep['written'])} files to {out}; errors {len(rep['errors'])}")
    print("in game: enable the mod (S2S Chicken Test off), then  player.placeatme 2C180F  and walk away from it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
