"""Describe Skyrim SE .hkx animation files with skyrimhkx (read-only) and summarise them: the real-data check of the
reader's object offsets, and a first look at what the animation converter will face.

    python -I scripts\\armor\\hkx_survey.py --skyrim-data "<Skyrim Special Edition>\\Data" --out C:\\Modding\\work\\hkx
        [--limit 2000] [--filter "character/animations"]

Also decodes every spline-compressed animation's tracks (hkxspline) and reports failures and rotation encodings.
--skyrim-data may also be an animation mod's folder (loose files, its BSAs). Reads every .hkx in the BSAs (and loose files under meshes\\) in load order, sorted by path, up to --limit (spread
over the whole list). Writes report.txt (send it) and report.json. Nothing is written into the game folder.
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa, skyrimhkx  # noqa: E402


def hkx_names(src, data_dir):
    names = {n for arc in src.archives for n in arc.names if n.lower().endswith(".hkx")}
    root = os.path.join(data_dir, "meshes")
    if os.path.isdir(root):
        for r, _d, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(".hkx"):
                    names.add(os.path.relpath(os.path.join(r, fn), data_dir).replace("/", "\\").lower())
    return sorted(names)


def survey(src, names):
    res = {"files": len(names), "missing": 0, "failed": 0, "with_checks": 0}
    kinds, types, errors, checks, events, bones = (collections.Counter() for _ in range(6))
    decoded, decode_errors, encodings = collections.Counter(), collections.Counter(), collections.Counter()
    durations, examples, skeletons = [], [], []
    for n in names:
        data = src._read(bsa.norm(n))
        if data is None:
            res["missing"] += 1
            continue
        try:
            d = skyrimhkx.describe(data)
        except skyrimhkx.HkxError as e:
            res["failed"] += 1
            errors[re.sub(r"\d+", "#", str(e))[:100]] += 1
            continue
        if d["skeletons"] and not d["animations"]:
            kinds["skeleton"] += 1
            for sk in d["skeletons"]:
                skeletons.append({"file": n, "name": sk["name"], "bones": len(sk["bones"])})
                bones.update(sk["bones"])
        elif d["animations"]:
            kinds["animation"] += 1
        else:
            kinds["other (behavior, character, project...)"] += 1
        if any(a["class"] == "hkaSplineCompressedAnimation" for a in d["animations"]):
            try:                                     # the track decoder (hkxspline) on every spline animation
                c = skyrimhkx.decode_clip(data)
                decoded["ok"] += 1
                encodings.update(c["rotation_encodings"])
            except Exception as e:                   # noqa: BLE001 - every failure is a finding
                decoded["failed"] += 1
                decode_errors[re.sub(r"\d+", "#", f"{type(e).__name__}: {e}")[:100]] += 1
        for a in d["animations"]:
            types[f"{a['class']} / {a['type']}"] += 1
            durations.append(a["duration"])
            events.update(e["text"].split(".")[0].split(" ")[0] for e in a["annotations"])
        if d["checks"]:
            res["with_checks"] += 1
            checks.update(re.sub(r"[-\d.]+", "#", c)[:100] for c in d["checks"])
            if len(examples) < 10:
                examples.append({"file": n, "checks": d["checks"]})
    durations.sort()
    res.update(kinds=dict(kinds), animation_types=dict(types), errors=dict(errors.most_common(12)),
               checks=dict(checks.most_common(12)), check_examples=examples,
               duration_s={"median": durations[len(durations) // 2] if durations else None,
                           "max": durations[-1] if durations else None},
               annotation_events=dict(events.most_common(40)), decoded=dict(decoded),
               decode_errors=dict(decode_errors.most_common(12)), rotation_encodings=dict(encodings), skeletons=skeletons[:20],
               skeleton_bones=list(bones))
    return res


def report_text(r):
    L = ["Skyrim .hkx survey", "=" * 18,
         f"{r['files']} files: {r['kinds']}; missing {r['missing']}, failed {r['failed']}, "
         f"with implausible values {r['with_checks']}",
         f"animation types: {r['animation_types']}", f"durations (s): {r['duration_s']}",
         f"track decoding: {r.get('decoded')}; rotation encodings (tracks x blocks): {r.get('rotation_encodings')}",
         f"skeletons: {r['skeletons'][:8]}", f"annotation events (top): {r['annotation_events']}"]
    if r["errors"]:
        L += ["errors:"] + [f"  x{n}: {e}" for e, n in r["errors"].items()]
    if r.get("decode_errors"):
        L += ["decode errors:"] + [f"  x{n}: {e}" for e, n in r["decode_errors"].items()]
    if r["checks"]:
        L += ["implausible values (an offset in skyrimhkx is probably wrong):"] + \
             [f"  x{n}: {c}" for c, n in r["checks"].items()] + [f"  e.g. {e}" for e in r["check_examples"][:3]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("--skyrim-data", required=True,
                    help="Skyrim's Data folder, or any folder of loose .hkx files (a mod: its meshes\\ folder is read)")
    ap.add_argument("--out", required=True, help="output folder OUTSIDE the repository")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--filter", default="", help="regex on the path (forward slashes, lower case)")
    ap.add_argument("--extract", action="store_true",
                    help="copy every file matching --filter (no --limit sampling) into <out>\\extract\\<path> "
                         "instead of surveying (clips to convert elsewhere)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    src = bsa.SkyrimArchives(a.skyrim_data)
    names = hkx_names(src, a.skyrim_data)
    if a.filter:
        rx = re.compile(a.filter, re.I)
        names = [n for n in names if rx.search(n.replace("\\", "/"))]
    if a.extract:
        if not a.filter:
            sys.exit("--extract needs --filter")
        n_ok = 0
        for n in names:
            data = src._read(n)
            if data is None:
                continue
            dst = os.path.join(out, "extract", *n.replace("/", "\\").split("\\"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(data)
            n_ok += 1
        print(f"extracted {n_ok} of {len(names)} files into {os.path.join(out, 'extract')}")
        return 0
    if a.limit and len(names) > a.limit:
        step = len(names) / a.limit
        names = [names[int(i * step)] for i in range(a.limit)]
    r = survey(src, names)
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1)
    text = report_text(r)
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text + f"\nSend {os.path.join(out, 'report.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
