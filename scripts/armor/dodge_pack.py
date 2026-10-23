"""TK Dodge's step dodges as full-body dodge states in a melee pack (docs/armor/animation-port.md, "Dodge").

Converts the four step dodges (StepDodgeForward / Back / Left / Right.hkx) with their root motion from TK Dodge's
animationdatasinglefile (motion ids, default TK Dodge RE's 1656 / 1657 / 1658 / 1659 = forward 5.4 m, back 3.9 m,
left / right 3.3 m) as clips tagged S2S_Dodge<Direction> in the shared stance folder (melee\\s2s_stances\\common,
listed by S2SStances.esm for every stance and the neutral one; file names the Creation Kit knows: NAMES), with a
dodge's descriptor (dodge_descriptor: no attack, slide, throw or hit events; "Allow
Rotation" as every attack whose root motion plays), and
adds the dodge states to the pack's MeleeAttacks.agx and the attack switch of Player_Melee.agx (dodge_graph,
--attacks-graph). Needs S2SStances.esm with the shared folder and the Creation Kit's GenerateAnimInfo run.

    python -I scripts\\armor\\dodge_pack.py --tk <TK Dodge folder with Meshes\\...> --pack <stance pack root>
        --anims <vanilla animations> --player-graph <vanilla player_melee.agx> <hkx_to_af options: --calumi ...>
"""
import argparse
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import af_writer  # noqa: E402
import bfco_pack  # noqa: E402
import dodge_graph  # noqa: E402
import hkx_to_af  # noqa: E402
import stance_plugin  # noqa: E402

CLIPS = {"Forward": "StepDodgeForward.hkx", "Back": "StepDodgeBack.hkx", "Left": "StepDodgeLeft.hkx",
         "Right": "StepDodgeRight.hkx"}
MOTION_IDS = {"Forward": 1656, "Back": 1657, "Left": 1658, "Right": 1659}
TEMPLATE_FOLDER, TEMPLATE = "melee/onehanded/player", "slidefromsprint"
# New clips go to the shared stance folder (stance_plugin.common_folder): the Creation Kit lists loose files only in
# folders the archives do not hold (owner's run 2026-10-23: new S2S_Dodge*.af in onehanded\\player never reached
# AnimationFileData; the s2s_stances folders did). S2SStances.esm lists the shared folder for every stance and for the
# neutral one.
FOLDER = "melee/s2s_stances/" + stance_plugin.COMMON
# File names the Creation Kit lists: it does not scan a folder but looks for the clip names it knows (the graph's tags
# and their Sneak_ / ZeroG_ variants: the s2s_stances caches list MeleeAttack_A and sneak_meleeattack_a, in the
# vanilla file names' case), so a new name such as S2S_DodgeBack.af is never listed (owner's run 2026-10-23, v9).
# Not names any folder before the shared one already holds (a clip file seems to be found by name, first folder wins:
# owner's run 2026-10-23, v11, a sneak name in the shared folder broke the neutral combo power attack hosted on the
# same name in onehanded\player\sword). The zero-g staggers exist only in onehanded\player, after the shared folder;
# the dodges shadow the player's zero-g stagger with a melee weapon.
# Only three such names are known so far: at most three directions get converted clips (names() hands them out).
NAMES = ("ZeroG_StaggerForwardMedium", "ZeroG_StaggerBackwardMedium", "ZeroG_StaggerBackwardSmall")


def names(directions) -> dict:
    """{direction: file stem} for the directions that get converted clips, from NAMES in order."""
    directions = list(directions)
    if len(directions) > len(NAMES):
        raise SystemExit(f"only {len(NAMES)} file names for converted dodges ({', '.join(NAMES)}); give the others "
                         "an existing tag with --tag")
    return dict(zip(directions, NAMES))


def dodge_descriptor(afx: bytes, filename: str = None) -> bytes:
    """The converted clip's descriptor made a dodge's: tag, filename and rampout kept; flags "Allow Rotation" (zero-g
    hosts without it did not play root motion, owner 2026-10-23); no events, audios or variables (the slide template's
    Slide event and bIsSliding window are not a dodge's)."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    ramp = root.findtext("rampout")
    out = af_writer.descriptor(root.findtext("tag") or "", filename or root.findtext("filename") or "",
                               rampout=int(ramp) if (ramp or "").strip().isdigit() else None)
    return out.replace(b"<flags></flags>", b"<flags><flag>Allow Rotation</flag></flags>")


def find_clip(tk: str, name: str) -> str:
    for base, _dirs, files in os.walk(tk):
        for fn in files:
            if fn.lower() == name.lower():
                return os.path.join(base, fn)
    raise SystemExit(f"{name} not found under {tk}")


def find_motion(tk: str) -> str:
    for base, _dirs, files in os.walk(tk):
        for fn in files:
            if fn.lower() == "animationdatasinglefile.txt":
                return os.path.join(base, fn)
    raise SystemExit(f"animationdatasinglefile.txt not found under {tk}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tk", required=True, help="TK Dodge (RE) folder")
    ap.add_argument("--pack", required=True, help="the pack root: its meleeattacks.agx gets the dodge states")
    ap.add_argument("--anims", required=True, help="vanilla animations (for the descriptor template)")
    ap.add_argument("--player-graph", required=True, help="the vanilla Player_Melee.agx")
    ap.add_argument("--starfield-data")
    ap.add_argument("--tag", action="append", default=[], metavar="DIRECTION=TAG",
                    help="play an existing clip tag for a direction instead of its converted dodge (diagnostics)")
    ap.add_argument("--clip-tag", action="append", default=[], metavar="DIRECTION=TAG",
                    help="tag a converted dodge clip TAG instead of S2S_Dodge<Direction> (e.g. a tag name the game "
                         "already has)")
    a, rest = ap.parse_known_args(argv)
    given = dict(t.split("=", 1) for t in a.tag)
    clip_tags = dict(t.split("=", 1) for t in a.clip_tag)
    if any(d not in CLIPS or d in given for d in clip_tags):
        sys.exit("--clip-tag wants DIRECTION=TAG for a converted direction (not one given --tag)")
    if any(d not in CLIPS for d in given):
        sys.exit(f"--tag wants DIRECTION=TAG with DIRECTION one of {', '.join(CLIPS)}")
    pack = os.path.abspath(a.pack)
    if pack.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--pack must be outside the repository")
    motion = find_motion(a.tk)
    template = bfco_pack.anim_path(a.anims, TEMPLATE_FOLDER, TEMPLATE)
    specs, motions = [], []
    for d, clip in CLIPS.items():
        if d in given:
            continue
        path = find_clip(a.tk, clip)
        specs += ["--replace", f"{path}::{template}::{clip_tags.get(d) or f'S2S_Dodge{d}'}"]
        motions += ["--motion", f"{os.path.splitext(clip)[0]}={motion}:{MOTION_IDS[d]}"]
    base = ["--weapon-in-hand"] + (["--starfield-data", a.starfield_data] if a.starfield_data else [])
    files = names(d for d in CLIPS if d not in given)
    folder = os.path.join(pack, *bfco_pack.ANIMS.split("/"), *FOLDER.split("/"))
    os.makedirs(folder, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:              # the pack's own report.json stays
        rc = hkx_to_af.main(rest + ["--out", tmp] + base + specs + motions)
        src = os.path.join(tmp, *bfco_pack.ANIMS.split("/"), *TEMPLATE_FOLDER.split("/"))
        for d in CLIPS:
            if d in given:
                continue
            for ext in (".af", ".afx"):
                fn = f"{clip_tags.get(d) or f'S2S_Dodge{d}'}{ext}"
                if not os.path.isfile(os.path.join(src, fn)):
                    print(f"{fn} was not written")
                    rc |= 1
                    continue
                with open(os.path.join(src, fn), "rb") as fh:
                    data = fh.read()
                name = files[d] + ext
                if ext == ".afx":
                    data = dodge_descriptor(data, files[d] + ".af")
                with open(os.path.join(folder, name), "wb") as fh:
                    fh.write(data)
        if os.path.isfile(os.path.join(tmp, "report.json")):
            shutil.copy(os.path.join(tmp, "report.json"), os.path.join(pack, "dodge_report.json"))
    graph = os.path.join(pack, *dodge_graph.ATTACKS_REL)
    rc |= dodge_graph.main(["--attacks-graph", graph, "--player-graph", a.player_graph, "--out", pack]
                           + [x for d, t in list(given.items()) + list(clip_tags.items()) for x in ("--tag", f"{d}={t}")])
    return rc


if __name__ == "__main__":
    sys.exit(main())
