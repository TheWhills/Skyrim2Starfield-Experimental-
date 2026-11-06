"""Give Outfit Studio Starfield's skeleton (2026-11-06: BodySlide's Config.xml names res\\skeleton_female_sf.nif as the
Starfield skeleton reference, the file is not in the owner's res folder, and Outfit Studio fell back to a Skyrim
skeleton: NPC Head [Head] at 120 units, the Starfield body lying on its side).

Copies the game's own skeleton NIF out of the Starfield archives into BodySlide's res folder under the name Config.xml
asks for (DefaultSkeletonReference). Leaves an existing file alone unless --force. Local only: nothing goes to Git.

    python -I scripts\\armor\\os_skeleton.py --bodyslide "<...>\\Tools\\BodySlide" --starfield "D:\\...\\Starfield"
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hkx_to_af  # noqa: E402  (archive helpers)

# HumanRace ANAM (owner's npc_face_probe): the skeletons the game itself uses
SKELETONS = {"female": "meshes/actors/human/characterassets/female/skeleton.nif",
             "male": "meshes/actors/human/characterassets/skeleton.nif"}


def configured_skeleton(config_text: str) -> str:
    m = re.search(r"<DefaultSkeletonReference>\s*([^<]+?)\s*</DefaultSkeletonReference>", config_text)
    return m.group(1) if m else "res\\skeleton_female_sf.nif"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bodyslide", required=True, help="the BodySlide folder (with Config.xml and res)")
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--sex", choices=sorted(SKELETONS), default="female",
                    help="which skeleton (default: female, as Config.xml's name says)")
    ap.add_argument("--force", action="store_true", help="replace an existing file")
    a = ap.parse_args(argv)
    cfg = os.path.join(a.bodyslide, "Config.xml")
    rel = "res\\skeleton_female_sf.nif"
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            rel = configured_skeleton(fh.read())
    target = os.path.join(a.bodyslide, *re.split(r"[\\/]", rel))
    if os.path.isfile(target) and not a.force:
        print(f"already there ({os.path.getsize(target)} bytes): {target}  (--force to replace)")
        return 0
    data, src = hkx_to_af.vanilla_file(SKELETONS[a.sex], os.path.join(a.starfield, "Data"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(data)
    print(f"wrote {target} ({len(data)} bytes) from the game's {src}")
    print("restart Outfit Studio so it loads the skeleton")
    return 0


if __name__ == "__main__":
    sys.exit(main())
