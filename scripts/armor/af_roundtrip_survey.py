"""How completely is Starfield's .af animation format understood? Round-trip every vanilla .af through CALUMI.Animation
(github.com/Calaverah/CALUMI.Animation, LGPL-3.0; called at run time as a DLL, never copied into this repo) and count
what survives.

For each .af in the Starfield archives: find its skeleton.rig, load both through CALUMI, decode every bone track
(rotations, translations, scales per frame), save it back through CALUMI with the original rig, reload the written
file and compare the decoded values. CALUMI's writer stores every bone uncompressed (its own note: "Will need
compression algorithm eventually"), so byte-identical output is NOT expected; the measure is whether the decoded
animation survives. Bytes and size are recorded too.

What it proves and what it does not: load_failed / no_rig count what CALUMI cannot read at all; values_differ counts
what its own reader and writer disagree on. values_equal means CALUMI is self-consistent on that file, NOT that its
decoding matches the game's: that needs the in-game write test (docs/armor/af-format-status.md, step 2).

Classes per file: values_equal (bytes_identical also noted), values_differ (largest error per channel), load_failed,
save_failed, reload_failed, no_rig, crashed (the DLL took the process down while on that file: rerun with --resume and
the survey continues after it). Run on Windows with the owner's install; outputs stay outside the repository.

    python -I scripts\\armor\\af_roundtrip_survey.py --dll "<path>\\CALUMI.Animation.dll" ^
        --starfield-data "<Starfield>\\Data" --out C:\\Modding\\work\\af_survey [--limit 200] [--resume]

Then send <out>\\report.txt (short) and, if asked, report.json.
"""
import argparse
import bisect
import collections
import ctypes as c
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

ROT_TOL = 1e-3          # per quaternion component, after q / -q
TRANS_TOL = 1e-3        # metres (Starfield units)
SCALE_TOL = 1e-4


def norm(name):
    return name.replace("\\", "/").lower()


# ------------------------------------------------------------------------------------------------ archive side
def index_archives(data_dir):
    """{normalised path: (archive, entry index)} for every .af / .rig / .afx in the Starfield BA2s."""
    from fo4sf import ba2
    out = {}
    for fn in sorted(os.listdir(data_dir)):
        low = fn.lower()
        if not (low.startswith("starfield - ") and low.endswith(".ba2")):
            continue
        if "texture" in low or "voices" in low or "sound" in low:
            continue
        try:
            arc = ba2.Ba2(os.path.join(data_dir, fn))
        except Exception as e:                                 # noqa: BLE001
            print(f"skipping {fn}: {e}")
            continue
        for i, n in enumerate(arc.names):
            k = norm(n)
            if k.endswith((".af", ".rig")) and k not in out:
                out[k] = (arc, i)
    return out


def find_rig(af_path, rigs):
    """The skeleton.rig an animation plays on: nearest ancestor folder holding characterassets/skeleton.rig, else a
    single .rig in an ancestor folder. None if neither exists."""
    parts = norm(af_path).split("/")[:-1]
    for k in range(len(parts), 0, -1):
        base = "/".join(parts[:k])
        cand = base + "/characterassets/skeleton.rig"
        if cand in rigs:
            return cand
        here = [r for r in rigs if r.rsplit("/", 1)[0] == base]
        if len(here) == 1:
            return here[0]
    return None


# ------------------------------------------------------------------------------------------------ CALUMI side
class Calumi:
    """The few CALUMI extern "C" calls the survey needs (signatures from its headers at b0f3b5c)."""

    def __init__(self, dll_path):
        self.lib = c.CDLL(os.path.abspath(dll_path))
        p, b, s = c.c_void_p, c.c_bool, c.c_size_t
        self.err = self._f("CreateStringContainerC", [], p)()
        self._msg = self._f("GetStringFromContainerC", [p], c.c_char_p)
        self._load = self._f("LoadAnimationSceneFromSFBGSFormatC", [c.POINTER(c.c_wchar_p), c.c_int, p], p)
        self._del_scene = self._f("DeleteAnimationSceneC", [p], b)
        self._n_anim = self._f("GetAnimationCountC", [p], s)
        self._anim = self._f("GetAnimationC", [p, c.c_int, p], p)
        self._save = self._f("SaveAnimationToSFBGSFormatWithExistingRigDirectC", [p, c.c_wchar_p, c.c_wchar_p, p], b)
        self._frames = self._f("GetFrameCountC", [p], s)
        self._n_blk = self._f("GetAnimationBlockCountC", [p], s)
        self._blk = self._f("GetAnimationBlockC", [p, c.c_int, p], p)
        self._blk_name = self._f("GetAnimBlockBoneNameC", [p], c.c_char_p)
        self._blk_index = self._f("GetAnimBlockBoneIndexC", [p], c.c_int)
        self._n = {k: self._f(f"Get{k}SqSizeC", [p], s) for k in ("Rotation", "Translation", "Scalar")}
        self._get = {k: self._f(f"Get{k}FromSqC", [p, c.c_int, p], p) for k in ("Rotation", "Translation", "Scalar")}
        self._frame = {k: self._f(f"GetFrameFrom{k}EntryC", [p], c.c_uint16) for k in ("Rotation", "Translation", "Scalar")}
        self._rot = self._f("GetValueFromRotationEntryC", [p], c.POINTER(c.c_float))       # 4 floats
        self._trn = self._f("GetValueFromTranslationEntryC", [p], c.POINTER(c.c_double))   # 3 doubles
        self._scl = self._f("GetValueFromScalarEntryC", [p], c.c_float)

    def _f(self, name, args, res):
        fn = getattr(self.lib, name)
        fn.argtypes, fn.restype = args, res
        return fn

    def message(self):
        m = self._msg(self.err)
        return (m or b"").decode("utf-8", "replace").strip()

    def decode(self, rig_path, af_path):
        """{"frames": n, "tracks": {bone: {"index": i, "rot": [(f, q4)], "trn": [(f, v3)], "scl": [(f, s)]}}} or
        raises RuntimeError with CALUMI's message."""
        arr = (c.c_wchar_p * 2)(rig_path, af_path)
        scene = self._load(arr, 2, self.err)
        if not scene:
            raise RuntimeError(self.message() or "load returned null")
        try:
            if self._n_anim(scene) < 1:
                raise RuntimeError("scene has no animation")
            anim = self._anim(scene, 0, self.err)
            if not anim:
                raise RuntimeError(self.message() or "no animation 0")
            return self._read(anim), scene, anim
        except Exception:
            self._del_scene(scene)
            raise

    def _read(self, anim):
        tracks = {}
        for i in range(self._n_blk(anim)):
            blk = self._blk(anim, i, self.err)
            if not blk:
                continue
            name = (self._blk_name(blk) or b"").decode("utf-8", "replace")
            t = {"index": self._blk_index(blk), "rot": [], "trn": [], "scl": []}
            for kind, key in (("Rotation", "rot"), ("Translation", "trn"), ("Scalar", "scl")):
                for j in range(self._n[kind](blk)):
                    e = self._get[kind](blk, j, self.err)
                    if not e:
                        continue
                    f = int(self._frame[kind](e))
                    if kind == "Rotation":
                        q = self._rot(e)
                        t[key].append((f, [q[k] for k in range(4)]))
                    elif kind == "Translation":
                        v = self._trn(e)
                        t[key].append((f, [v[k] for k in range(3)]))
                    else:
                        t[key].append((f, float(self._scl(e))))
            tracks[name] = t
        return {"frames": int(self._frames(anim)), "tracks": tracks}

    def save(self, anim, out_path, rig_path):
        if not self._save(anim, out_path, rig_path, self.err):
            raise RuntimeError(self.message() or "save returned false")

    def free(self, scene):
        if scene:
            self._del_scene(scene)


# ------------------------------------------------------------------------------------------------ comparison
def _sample(seq, frames, frame):
    """Value of a keyed sequence at `frame`: the last key at or before it (keys are what the file stores; both sides
    are compared on the union of their key frames, so a stored-every-frame rewrite of a sparse original compares
    equal when it holds the same values on the original's keys and constant runs between them). `frames` = the
    sequence's key frames, for bisect."""
    if not seq:
        return None
    i = bisect.bisect_right(frames, frame) - 1
    return seq[max(i, 0)][1]


def _err(kind, a, b):
    if a is None or b is None:
        return math.inf
    if kind == "rot":
        d1 = max(abs(x - y) for x, y in zip(a, b))
        d2 = max(abs(x + y) for x, y in zip(a, b))
        return min(d1, d2)
    if kind == "trn":
        return max(abs(x - y) for x, y in zip(a, b))
    return abs(a - b)


def compare(orig, back):
    """{"equal": bool, "max": {rot, trn, scl}, "missing_bones": [...], "extra_bones": n, "frames": (a, b)}."""
    tol = {"rot": ROT_TOL, "trn": TRANS_TOL, "scl": SCALE_TOL}
    worst = {"rot": 0.0, "trn": 0.0, "scl": 0.0}
    missing = sorted(b for b in orig["tracks"] if b not in back["tracks"])
    for bone, t in orig["tracks"].items():
        u = back["tracks"].get(bone)
        if u is None:
            continue
        for kind in worst:
            if not t[kind] and not u[kind]:
                continue
            ta, ua = sorted(t[kind]), sorted(u[kind])
            fa, fu = [f for f, _ in ta], [f for f, _ in ua]
            for f in sorted(set(fa) | set(fu)):
                worst[kind] = max(worst[kind], _err(kind, _sample(ta, fa, f), _sample(ua, fu, f)))
    extra = sum(1 for b in back["tracks"] if b not in orig["tracks"])
    equal = not missing and all(worst[k] <= tol[k] for k in worst) and orig["frames"] == back["frames"]
    return {"equal": equal, "max": {k: (None if v == math.inf else round(v, 7)) for k, v in worst.items()},
            "missing_bones": missing[:10], "extra_bones": extra, "frames": [orig["frames"], back["frames"]]}


# ------------------------------------------------------------------------------------------------ survey
def survey_one(cal, af, rig, rig_file, tmp):
    """One animation: returns a result dict (never raises for format problems)."""
    name, (arc, idx) = af
    res = {"af": name, "rig": rig}
    data = arc.read(idx)
    res["bytes"] = len(data)
    src = os.path.join(tmp, "in.af")
    out = os.path.join(tmp, "out.af")
    with open(src, "wb") as f:
        f.write(data)
    if os.path.exists(out):
        os.remove(out)
    try:
        orig, scene, anim = cal.decode(rig_file, src)
    except RuntimeError as e:
        return {**res, "class": "load_failed", "error": str(e)}
    try:
        res["frames"], res["tracks"] = orig["frames"], len(orig["tracks"])
        try:
            cal.save(anim, out, rig_file)
        except RuntimeError as e:
            return {**res, "class": "save_failed", "error": str(e)}
    finally:
        cal.free(scene)
    with open(out, "rb") as f:
        written = f.read()
    res["bytes_out"] = len(written)
    res["bytes_identical"] = written == data
    try:
        back, scene2, _ = cal.decode(rig_file, out)
        cal.free(scene2)
    except RuntimeError as e:
        return {**res, "class": "reload_failed", "error": str(e)}
    cmp_ = compare(orig, back)
    res.update(cmp_)
    res["class"] = "values_equal" if cmp_["equal"] else "values_differ"
    return res


def group_of(path):
    parts = norm(path).split("/")
    return "/".join(parts[1:3]) if parts[0] == "meshes" else "/".join(parts[:2])


def summarise(results):
    cls = collections.Counter(r["class"] for r in results)
    by_group = collections.defaultdict(collections.Counter)
    for r in results:
        by_group[group_of(r["af"])][r["class"]] += 1
    errors = collections.Counter(re.sub(r"\d+", "#", r.get("error", ""))[:120] for r in results if r.get("error"))
    differ = [r for r in results if r["class"] == "values_differ"]
    worst = {k: max((r["max"][k] for r in differ if r["max"][k] is not None), default=0.0) for k in ("rot", "trn", "scl")}
    ok = [r for r in results if r["class"] == "values_equal"]
    ratio = sorted(r["bytes_out"] / r["bytes"] for r in ok if r.get("bytes"))
    return {"files": len(results), "classes": dict(cls), "bytes_identical": sum(1 for r in results if r.get("bytes_identical")),
            "by_group": {g: dict(v) for g, v in sorted(by_group.items(), key=lambda kv: -sum(kv[1].values()))[:25]},
            "errors": dict(errors.most_common(15)), "worst_differences": worst,
            "differ_examples": [{k: r.get(k) for k in ("af", "max", "missing_bones", "extra_bones", "frames")}
                                for r in differ[:10]],
            "size_ratio_out_over_in": {"median": ratio[len(ratio) // 2] if ratio else None,
                                       "max": ratio[-1] if ratio else None}}


def report_text(s, seconds):
    L = [".af round-trip survey through CALUMI.Animation", "=" * 46,
         f"{s['files']} animations in {seconds:.0f} s; classes: {s['classes']}",
         f"byte-identical rewrites: {s['bytes_identical']} (not expected: CALUMI writes every bone uncompressed)",
         f"written / original size: median {s['size_ratio_out_over_in']['median']}, max {s['size_ratio_out_over_in']['max']}",
         f"largest value differences (values_differ files): {s['worst_differences']}", "", "by folder:"]
    L += [f"  {g}: {v}" for g, v in s["by_group"].items()]
    if s["errors"]:
        L += ["", "errors (grouped):"] + [f"  x{n}: {e}" for e, n in s["errors"].items()]
    if s["differ_examples"]:
        L += ["", "examples that differ:"] + [f"  {d}" for d in s["differ_examples"]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("--dll", required=True, help="CALUMI.Animation.dll (e.g. from the Animation IO add-on or built)")
    ap.add_argument("--starfield-data", required=True, help="Starfield\\Data (read-only)")
    ap.add_argument("--out", required=True, help="output folder OUTSIDE the repository")
    ap.add_argument("--limit", type=int, default=0, help="only the first N animations (sorted by path)")
    ap.add_argument("--filter", default="", help="regex on the animation path (forward slashes, lower case)")
    ap.add_argument("--resume", action="store_true", help="continue a previous run (a file it died on = crashed)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "tmp")
    os.makedirs(tmp, exist_ok=True)

    t0 = time.time()
    index = index_archives(a.starfield_data)
    rigs = {k for k in index if k.endswith(".rig")}
    anims = sorted(k for k in index if k.endswith(".af"))
    if a.filter:
        rx = re.compile(a.filter, re.I)
        anims = [k for k in anims if rx.search(k)]
    if a.limit:
        anims = anims[:a.limit]
    print(f"{len(anims)} .af and {len(rigs)} .rig files in the archives")

    log = os.path.join(out, "progress.jsonl")
    done, started = {}, None
    if a.resume and os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("start"):
                    started = rec["start"]
                else:
                    done[rec["af"]] = rec
                    started = None
        if started and started not in done:                  # the DLL died on this file last time
            done[started] = {"af": started, "class": "crashed"}
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(done[started]) + "\n")
    elif os.path.exists(log):
        os.remove(log)

    cal = Calumi(a.dll)
    rig_files = {}
    with open(log, "a", encoding="utf-8") as lf:
        for n, af in enumerate(anims):
            if af in done:
                continue
            rig = find_rig(af, rigs)
            if rig is None:
                rec = {"af": af, "class": "no_rig"}
            else:
                if rig not in rig_files:
                    rp = os.path.join(tmp, f"rig_{len(rig_files)}.rig")
                    arc, i = index[rig]
                    with open(rp, "wb") as f:
                        f.write(arc.read(i))
                    rig_files[rig] = rp
                lf.write(json.dumps({"start": af}) + "\n")
                lf.flush()
                rec = survey_one(cal, (af, index[af]), rig, rig_files[rig], tmp)
            lf.write(json.dumps(rec) + "\n")
            lf.flush()
            done[af] = rec
            if n % 500 == 0:
                print(f"  {n}/{len(anims)} {collections.Counter(r['class'] for r in done.values())}")

    results = [done[k] for k in anims if k in done]
    s = summarise(results)
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": s, "results": results}, f, indent=1)
    text = report_text(s, time.time() - t0)
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text + f"\nSend {os.path.join(out, 'report.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
