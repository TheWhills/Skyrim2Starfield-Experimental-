"""TK Dodge's step dodges as full-body dodge states in a melee pack (docs/armor/animation-port.md, "Dodge").

Converts the four step dodges (StepDodgeForward / Back / Left / Right.hkx) with their root motion from TK Dodge's
animationdatasinglefile (motion ids, default TK Dodge RE's 1656 / 1657 / 1658 / 1659 = forward 5.4 m, back 3.9 m,
left / right 3.3 m) into melee\\onehanded\\player as new clips tagged S2S_Dodge<Direction>, with a dodge's descriptor
(dodge_descriptor: no attack, slide or hit events; "Allow Rotation" as every attack whose root motion plays), and
adds the dodge states to the pack's MeleeAttacks.agx and the attack switch of Player_Melee.agx (dodge_graph,
--attacks-graph). New clips need the Creation Kit's GenerateAnimInfo run like the stance folders.

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

CLIPS = {"Forward": "StepDodgeForward.hkx", "Back": "StepDodgeBack.hkx", "Left": "StepDodgeLeft.hkx",
         "Right": "StepDodgeRight.hkx"}
MOTION_IDS = {"Forward": 1656, "Back": 1657, "Left": 1658, "Right": 1659}
FOLDER = "melee/onehanded/player"
TEMPLATE = "slidefromsprint"


def dodge_descriptor(afx: bytes) -> bytes:
    """The converted clip's descriptor made a dodge's: tag, filename and rampout kept; flags "Allow Rotation" (zero-g
    hosts without it did not play root motion, owner 2026-10-23); no events, audios or variables (the slide template's
    Slide event and bIsSliding window are not a dodge's)."""
    root = ET.fromstring(afx.decode("utf-8-sig"))
    ramp = root.findtext("rampout")
    out = af_writer.descriptor(root.findtext("tag") or "", root.findtext("filename") or "",
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
    a, rest = ap.parse_known_args(argv)
    pack = os.path.abspath(a.pack)
    if pack.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--pack must be outside the repository")
    motion = find_motion(a.tk)
    template = bfco_pack.anim_path(a.anims, FOLDER, TEMPLATE)
    specs, motions = [], []
    for d, clip in CLIPS.items():
        path = find_clip(a.tk, clip)
        specs += ["--replace", f"{path}::{template}::S2S_Dodge{d}"]
        motions += ["--motion", f"{os.path.splitext(clip)[0]}={motion}:{MOTION_IDS[d]}"]
    base = ["--weapon-in-hand"] + (["--starfield-data", a.starfield_data] if a.starfield_data else [])
    folder = os.path.join(pack, *bfco_pack.ANIMS.split("/"), *FOLDER.split("/"))
    os.makedirs(folder, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:              # the pack's own report.json stays
        rc = hkx_to_af.main(rest + ["--out", tmp] + base + specs + motions)
        src = os.path.join(tmp, *bfco_pack.ANIMS.split("/"), *FOLDER.split("/"))
        for d in CLIPS:
            for ext in (".af", ".afx"):
                fn = f"S2S_Dodge{d}{ext}"
                if not os.path.isfile(os.path.join(src, fn)):
                    print(f"{fn} was not written")
                    rc |= 1
                    continue
                with open(os.path.join(src, fn), "rb") as fh:
                    data = fh.read()
                if ext == ".afx":
                    data = dodge_descriptor(data)
                with open(os.path.join(folder, fn), "wb") as fh:
                    fh.write(data)
        if os.path.isfile(os.path.join(tmp, "report.json")):
            shutil.copy(os.path.join(tmp, "report.json"), os.path.join(pack, "dodge_report.json"))
    graph = os.path.join(pack, *dodge_graph.ATTACKS_REL)
    rc |= dodge_graph.main(["--attacks-graph", graph, "--player-graph", a.player_graph, "--out", pack])
    return rc


if __name__ == "__main__":
    sys.exit(main())
