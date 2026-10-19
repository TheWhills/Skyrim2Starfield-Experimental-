"""Convert Skyrim .hkx animations into Starfield .af clips: decode (skyrimhkx / hkxspline), retarget onto Starfield's
human skeleton (retarget, skeletonmap), write .af + .afx + events through CALUMI (af_writer), and read every file back
through CALUMI to check it (--no-verify skips that). Outputs go outside the repository.

    python -I scripts\\armor\\hkx_to_af.py --calumi "<CALUMI.Animation.dll>" --skyrim-data "$SKY" --starfield-data "$SF\\Data" ^
        --out C:\\Modding\\work\\af_test --clip "meshes\\actors\\character\\animations\\mt_idle.hkx" [--clip ...] [--tag Idle]

Sources (each either a file or read from the game's archives):
  clips             --clip <archive path inside Skyrim's BSAs or a .hkx file on disk> (repeatable), or --clip-dir
  Skyrim skeleton   --skyrim-skeleton <skeleton.hkx>, default meshes\\actors\\character\\character assets\\skeleton.hkx
  Starfield skeleton --starfield-skeleton <skeleton.nif>, default the human skeleton.nif from the Meshes BA2s
  Starfield rig     --starfield-rig <skeleton.rig>: save against the game's own rig (what the in-game test needs;
                    default: the human .rig found in Starfield - Animations.ba2, extracted next to the output);
                    --own-rig writes a rig built from the skeleton NIF instead
Writes <out>\\<clip>.af / .afx / .events.json and report.json (per clip: frames, keys, bytes, read-back error).

--replace "<clip>::<vanilla .afx>" (repeatable): replace a vanilla clip in place. The clip is written under the vanilla
path and file name (out\meshes\actors\...\Idle.af + .afx; copy out\meshes into Starfield's Data as loose files), and
its .afx is the vanilla descriptor fitted to the new clip (af_writer.retime_descriptor: tag, flags, payloads kept,
frames scaled, HitFrame / footsteps taken from the Skyrim clip). The vanilla .afx is a file, or a path read from the
game's archives (--starfield-data). Reusing the vanilla path should keep the AnimTextData caches valid (unverified).

--osf PACK: write the clips as an OSF Animation content pack instead (Nexus 17457, github.com/ozooma10/osf-animation;
plays .af / .glb clips on actors from an in-game browser, F10): <out>\\OSF\\Animations\\<PACK>\\*.af plus
<out>\\OSF\\<pack>.osf.json (a "clipLibrary" catalog, per OSF's docs/GETTING_STARTED.md). Copy <out>\\OSF into
Starfield's Data folder, then in game: cgf "OSF.ReloadPacks", F10, pick the clip, play it on the player or an NPC.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

import numpy as np  # noqa: E402

from fo4sf import af_writer, ba2, bsa, retarget, skyrimhkx  # noqa: E402

SKY_SKELETON = r"meshes\actors\character\character assets\skeleton.hkx"
SF_SKELETON_RX = re.compile(r"meshes/actors/human/characterassets/skeleton\.nif$", re.I)
SF_RIG_RX = re.compile(r"actors/human/.*characterassets/skeleton\.rig$", re.I)


def read_any(path, skyrim=None):
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            return fh.read()
    if skyrim is None:
        raise SystemExit(f"not found: {path}")
    d = skyrim._read(bsa.norm(path))
    if d is None:
        raise SystemExit(f"not in Skyrim's archives: {path}")
    return d


def starfield_find(data_dir, rx, prefixes=("starfield - meshes", "starfield - animations")):
    for fn in sorted(os.listdir(data_dir)):
        if fn.lower().startswith(prefixes) and fn.lower().endswith(".ba2"):
            arc = ba2.Ba2(os.path.join(data_dir, fn))
            for i, n in enumerate(arc.names):
                if rx.search(n.replace("\\", "/")):
                    return n, arc.read(i)
    return None, None


def vanilla_file(path, starfield_data):
    """(bytes, Data-relative path with forward slashes, lower case) of a vanilla file: a file on disk (its path from
    'meshes/' on is the Data path) or a path read from the game's archives."""
    p = path.replace("\\", "/")
    low = p.lower()
    rel = low[low.index("meshes/"):] if "meshes/" in low else low.lstrip("/")
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            return fh.read(), rel
    if not starfield_data:
        raise SystemExit(f"not a file and no --starfield-data to look in: {path}")
    _n, data = starfield_find(starfield_data, re.compile("^" + re.escape(rel) + "$", re.I),
                              ("starfield - animations", "starfield - meshes", "shatteredspace", "sfbgs"))
    if data is None:
        raise SystemExit(f"not in the game's archives: {rel}")
    return data, rel


def compare(rb, res, sf_index):
    """Largest read-back error over every frame (sign-aligned nlerp between keys)."""
    def at(keys, f, quat):
        fr = [k for k, _ in keys]
        j = int(np.searchsorted(fr, f))
        if j < len(fr) and fr[j] == f:
            return np.array(keys[j][1])
        a, b = np.array(keys[j - 1][1]), np.array(keys[j][1])
        t = (f - keys[j - 1][0]) / (keys[j][0] - keys[j - 1][0])
        if quat and np.dot(a, b) < 0:
            b = -b
        v = a * (1 - t) + b * t
        return v / np.linalg.norm(v) if quat else v
    mq = mt = 0.0
    for n in rb["bones"]:
        i = sf_index[n]
        for f in range(res["frames"]):
            q, w = at(rb["rotations"][n], f, True), res["q"][f, i]
            mq = max(mq, min(np.max(np.abs(q - w)), np.max(np.abs(q + w))))
            mt = max(mt, float(np.max(np.abs(at(rb["translations"][n], f, False) - res["t"][f, i]))))
    return round(float(mq), 5), round(mt, 6)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calumi", required=True, help="CALUMI.Animation.dll (Windows) or libcalumi.so (Linux build)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--clip", action="append", default=[])
    ap.add_argument("--clip-dir", help="convert every .hkx animation in this folder")
    ap.add_argument("--skyrim-data")
    ap.add_argument("--starfield-data")
    ap.add_argument("--skyrim-skeleton")
    ap.add_argument("--starfield-skeleton")
    ap.add_argument("--starfield-rig")
    ap.add_argument("--own-rig", action="store_true", help="write a rig from the skeleton NIF instead of the game's")
    ap.add_argument("--tag", help="the .afx tag (default: the clip's file name)")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--no-foot-plant", action="store_true", help="skip the foot-planting IK pass")
    ap.add_argument("--osf", metavar="PACK", help="write an OSF Animation content pack named PACK (see above)")
    ap.add_argument("--replace", action="append", default=[], metavar="CLIP::VANILLA_AFX",
                    help="replace a vanilla clip in place (see above); repeatable")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    sky = bsa.SkyrimArchives(a.skyrim_data) if a.skyrim_data else None
    sk_desc = skyrimhkx.describe(read_any(a.skyrim_skeleton or SKY_SKELETON, sky))
    sk = retarget.rig_from_hkx_skeleton(next(s for s in sk_desc["skeletons"] if len(s["bones"]) > 20))
    if a.starfield_skeleton:
        sf_nif = read_any(a.starfield_skeleton)
    else:
        if not a.starfield_data:
            sys.exit("give --starfield-skeleton or --starfield-data")
        name, sf_nif = starfield_find(a.starfield_data, SF_SKELETON_RX)
        if sf_nif is None:
            sys.exit("Starfield human skeleton.nif not found in the Meshes archives")
        print(f"Starfield skeleton: {name}")
    sf = retarget.rig_from_nif(sf_nif)
    rig_path = None
    if not a.own_rig:
        if a.starfield_rig:
            rig_path = a.starfield_rig
        elif a.starfield_data:
            name, data = starfield_find(a.starfield_data, SF_RIG_RX, ("starfield - animations",))
            if data is not None:
                rig_path = os.path.join(out, "vanilla_skeleton.rig")
                with open(rig_path, "wb") as fh:
                    fh.write(data)
                print(f"Starfield rig: {name} (saved against it)")
        if rig_path is None:
            print("no game rig found: writing our own (--own-rig); the in-game test needs the game's rig")
    game_rig = None
    if rig_path is not None:                     # clips index the game rig's bones, in its order and hierarchy
        g = af_writer.load_rig(a.calumi, rig_path)
        game_rig = retarget.Rig(g["names"], g["parents"], g["t"], g["q"])
        if game_rig.names != g["names"]:
            sys.exit("the game rig does not list parents before children")
        missing = [n for n in game_rig.names if n.lower() not in {x.lower() for x in sf.names}]
        print(f"game rig: {len(game_rig.names)} bones ({g['animated']} animated); kept at rest (not in the skeleton "
              f"NIF): {missing}")
    clip_dir = out
    if a.osf:
        pack_id = re.sub(r"[^A-Za-z0-9_]+", "", a.osf) or "SkyrimPort"
        clip_dir = os.path.join(out, "OSF", "Animations", pack_id)
        os.makedirs(clip_dir, exist_ok=True)
    clips = [(c, None) for c in a.clip]
    for r in a.replace:
        if "::" not in r:
            sys.exit(f"--replace wants CLIP::VANILLA_AFX, got {r}")
        clip, vafx = r.split("::", 1)
        clips.append((clip, vafx))
    if a.clip_dir:
        for d, _ds, fns in os.walk(a.clip_dir):
            clips += [(os.path.join(d, f), None) for f in sorted(fns) if f.lower().endswith(".hkx")]
    report = []
    for c, vafx in clips:
        name = os.path.splitext(os.path.basename(c.replace("\\", "/")))[0]
        row = {"clip": c, "name": name}
        target_dir, like, file_name = clip_dir, None, None
        try:
            if vafx:
                like, rel = vanilla_file(vafx, a.starfield_data)
                fn_m = re.search(rb"<filename>\s*([^<]+?)\s*</filename>", like)
                file_name = os.path.splitext((fn_m.group(1).decode() if fn_m else os.path.basename(rel)))[0]
                target_dir = os.path.join(out, *os.path.dirname(rel).split("/"))
                row["replaces"] = f"{os.path.dirname(rel)}/{file_name}.af"
            data = read_any(c, sky)
            try:
                clip = skyrimhkx.decode_clip(data, sk.names)
            except skyrimhkx.HkxError as e:
                if "no hkaSplineCompressedAnimation" in str(e):  # skeletons, behaviours: not clips
                    row["skipped"] = "not an animation"
                    report.append(row)
                    continue
                raise
            res = retarget.retarget(clip, sk, sf)
            if not a.no_foot_plant:
                res = retarget.plant_feet(clip, sk, sf, res)
            chk = retarget.check(clip, sk, sf, res)
            out_rig, out_t, out_q = sf, res["t"], res["q"]
            if game_rig is not None:
                out_t, out_q = retarget.rehome(sf, res["t"], res["q"], game_rig.names, game_rig.parents,
                                               game_rig.t, game_rig.q)
                out_rig = game_rig
            w = af_writer.write(a.calumi, target_dir, name, out_rig.names, out_rig.parents, out_rig.t, out_rig.q,
                                out_t, out_q, tag=a.tag or name, rig_path=rig_path, events=clip["annotations"],
                                like_afx=like, file_name=file_name)
            if w.get("retime"):
                row["afx_retime"] = w["retime"]
            row.update(frames=w["frames"], keys=w["keys"], bytes=os.path.getsize(w["af"]), af=w["af"],
                       foot_lowest_m=chk["foot_lowest_m"], events=len(clip["annotations"]))
            if not a.no_verify:
                rb = af_writer.read_back(a.calumi, w["af"], w["rig"])
                missing = [n for n in rb["bones"] if n not in out_rig.index]
                row["readback_bones"] = len(rb["bones"])
                if missing:
                    row["readback_unknown_bones"] = missing[:10]
                else:
                    row["readback_max_rotation_err"], row["readback_max_translation_err_m"] = compare(
                        rb, {"frames": res["frames"], "t": out_t, "q": out_q}, out_rig.index)
        except Exception as e:                               # noqa: BLE001 - reported per clip
            row["error"] = f"{type(e).__name__}: {e}"
        report.append(row)
        print({k: v for k, v in row.items() if k not in ("clip", "af")})
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    if a.osf:
        done_rows = [r for r in report if "af" in r]
        pack = {"schema": 1, "pack": a.osf, "clipRoot": f"OSF/Animations/{pack_id}", "folder": "Skyrim",
                "clipLibrary": [{"file": os.path.basename(r["af"]), "name": r["name"].replace("_", " ")}
                                for r in done_rows]}
        pj = os.path.join(out, "OSF", f"{pack_id.lower()}.osf.json")
        with open(pj, "w", encoding="utf-8") as fh:
            json.dump(pack, fh, indent=1)
        print(f"OSF pack: {pj} ({len(done_rows)} clips); copy {os.path.join(out, 'OSF')} into Starfield's Data")
    done = sum("error" not in r and "skipped" not in r for r in report)
    print(f"{done} clips written, {sum('skipped' in r for r in report)} skipped (not animations), "
          f"{sum('error' in r for r in report)} failed; {os.path.join(out, 'report.json')}")
    return 0 if all("error" not in r for r in report) else 1


if __name__ == "__main__":
    sys.exit(main())
