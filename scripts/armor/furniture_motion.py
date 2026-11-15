"""Where Skyrim's furniture clips move the actor's root (read-only): the root motion each clip of our furniture sets
carries in Skyrim's animationdatasinglefile (vanilla clips keep it there, not in the .hkx).

2026-11-15, owner, in game: Hod leans about a foot in front of the post, Hilde about a foot back from the rail, both on
Skyrim's own markers (the reference itself, offset 0: the owner's furniture.json). Hod is too far forward and Hilde too
far back, along the way each faces: what Skyrim's enter clips would do if they move the actor from the marker to the
wall / rail (furniture_anim_pack converts with --no-root-motion, so ours stay at the marker). This prints, per set and
clip, the root's end position (metres, actor frame: x right, y forward, z up) and turn (degrees).

    python -I scripts\\armor\\furniture_motion.py --skyrim-data "<Skyrim Special Edition>\\Data"
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import animdata, bsa, rootmotion  # noqa: E402
from fo4sf.retarget import SKYRIM_M_PER_UNIT  # noqa: E402

BEHAVIORS = "meshes\\actors\\character\\behaviors\\"


def end_of(block):
    """(x, y, z metres, yaw degrees) where a motion block leaves the root."""
    tr, rot = block.get("translations") or [], block.get("rotations") or []
    t = tr[-1][1:4] if tr else (0.0, 0.0, 0.0)
    yaw = rootmotion.yaw_degrees(rot[-1][1:5]) if rot else 0.0
    return tuple(round(float(v) * SKYRIM_M_PER_UNIT, 3) + 0.0 for v in t) + (round(float(yaw), 1) + 0.0,)


def set_motion(motion, sets):
    """{set: [(slot file, Skyrim clip, end or None)]} for furniture_anim_pack.SETS-style sets; motion: {clip file stem
    lower case: motion block}."""
    out = {}
    for name, (_folder, _template, rows) in sets.items():
        lines = []
        for slot, clip, _tag in rows:
            stem = os.path.splitext(os.path.basename(clip.replace("\\", "/")))[0].lower()
            blk = motion.get(stem)
            lines.append((slot, clip, end_of(blk) if blk else None))
        out[name] = lines
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--project", default="DefaultMale")
    a = ap.parse_args(argv)
    import furniture_anim_pack
    from fo4sf import skyrimbehavior
    arcs = bsa.SkyrimArchives(a.skyrim_data, loose=False)
    text = arcs._read("meshes\\animationdatasinglefile.txt")
    if text is None:
        sys.exit("meshes\\animationdatasinglefile.txt not in the Skyrim archives")
    projects = animdata.parse(text.decode("latin-1"))
    proj = next((p for k, p in projects.items() if k.lower() == a.project.lower()), None)
    if proj is None:
        sys.exit(f"project {a.project} not found ({', '.join(sorted(projects)[:10])} ...)")
    behaviors = []
    for n in sorted({bsa.norm(x) for ar in arcs.archives for x in ar.names}):
        if n.startswith(BEHAVIORS) and n.endswith(".hkx") and "\\" not in n[len(BEHAVIORS):]:
            try:
                behaviors.append(skyrimbehavior.read(arcs._read(n)))
            except Exception:                                      # noqa: BLE001 (not every file is a behaviour)
                pass
    rep = {}
    motion = animdata.clip_motion(proj, animdata.clip_generators(behaviors), rep)
    print(f"{a.project}: {len(motion)} clips with motion ({len(behaviors)} behaviours, {rep.get('by_behavior', 0)} "
          f"generators mapped)")
    for name, lines in set_motion(motion, furniture_anim_pack.SETS).items():
        print(f"== {name}")
        seen = set()
        for slot, clip, end in lines:
            if clip in seen:
                continue
            seen.add(clip)
            print(f"  {clip:44s} " + ("no root motion" if end is None else
                                      f"ends x {end[0]:+.3f} y {end[1]:+.3f} z {end[2]:+.3f} m, turn {end[3]:+.1f} deg"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
