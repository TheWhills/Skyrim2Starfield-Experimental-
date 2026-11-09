"""A one-tag test of SAM (Starfield Animation Merger, Nexus 18674): does a NEW animation tag play once SAM declares it?

    python -I scripts\\armor\\sam_test_pack.py --starfield-data "$sf\\Data" --out "$mods\\S2S SAM Test"

Why (docs/armor/animation-port.md, 2026-11-09): the game reads its tag tables only from its own archive, so a clip
under a tag of our own never played (owner's run 2026-10-23: a dodge tagged S2S_DodgeRight snapped back, while the
same clip under a vanilla tag played) and our packs borrow spare vanilla tags. SAM adds the tags of every fragment
(Meshes\\AnimTextData\\Fragments\\<Name>\\tables\\anim_actions.xtbl) to the game in memory and merges the fragments'
clip lists into the animation index. This pack tests exactly that, with no Skyrim conversion in the way:
  * the clip: a vanilla clip (default MeleeAttackPower_A, the one-handed overhead power attack) written again as
    S2S_SamTest.af / .afx in melee\\onehanded\\player, its descriptor retagged (tag S2S_SamTest, filename);
  * the graph: MeleeAttacks.agx (the game's, or --graph) with the first combo attack (MeleeAttack_A in the
    MeleeAttackCombo machine) playing S2S_SamTest instead;
  * the fragment Fragments\\S2SSamTest\\: animations.txt (the two files, paths from Data starting with Meshes\\) and
    tables\\anim_actions.xtbl (the tag). No animationoffsets / animeventinfo yet (the Creation Kit writes those; if the
    swing plays but root motion or hit events are missing, that is the next step).
In game (SAM installed, game started with sfse_loader.exe, this mod after any other mod that ships MeleeAttacks.agx):
draw a one-handed melee weapon and attack once. The overhead power swing = SAM declared our tag; a snap / nothing =
it did not (SfAnimIndexLoader.log says why). --tag / --clip / --host change the test.
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import agx_edit  # noqa: E402

FRAGMENT = "S2SSamTest"
ANIMS = "meshes/actors/human/animations/"
GRAPH_REL = "meshes/animtextdata/tables/graphs/meleeattacks.agx"
MACHINE = "MeleeAttackCombo"


def read_vanilla(path, starfield_data):
    """(bytes, Data path) of a file on disk or in the game's archives (hkx_to_af.vanilla_file)."""
    import hkx_to_af
    return hkx_to_af.vanilla_file(path, starfield_data)


def retag(afx: bytes, tag: str, filename: str) -> bytes:
    """The descriptor with <tag> and <filename> replaced (and any <prefix> / <suffix> variant fields dropped: ours is
    the plain clip of a new tag); everything else as it was."""
    root = ET.fromstring(afx)
    for name, val in (("tag", tag), ("filename", filename)):
        el = root.find(name)
        if el is None:
            el = ET.SubElement(root, name)
        el.text = val
    for name in ("prefix", "suffix"):
        for el in root.findall(name):
            root.remove(el)
    return agx_edit.dump(root, afx)


def point_host(graph_raw: bytes, host: str, tag: str):
    """(graph bytes, how many states changed): the combo machine's state playing `host` plays `tag` instead."""
    root = agx_edit.load(graph_raw)
    g = agx_edit.machine(root, MACHINE)
    i = agx_edit.state(g, host)
    if not agx_edit.set_tag(g.findall("node")[i], tag):
        raise agx_edit.AgxEditError(f"state {host!r} has no TagName")
    return agx_edit.dump(root, graph_raw), 1


def fragment_files(tag: str, folder: str):
    """{relative path: bytes} of the SAM fragment: the clip list and the new tag."""
    base = "Meshes\\actors\\human\\animations\\" + folder.replace("/", "\\")
    clips = "".join(f"{base}\\{tag}.{ext}\r\n" for ext in ("af", "afx"))
    xtbl = f"<root>\r\n<table>\r\n\t<entry><name>{tag}</name></entry>\r\n</table>\r\n</root>\r\n"
    root = f"meshes/animtextdata/fragments/{FRAGMENT}/"
    return {root + "animations.txt": clips.encode("ascii"), root + "tables/anim_actions.xtbl": xtbl.encode("ascii")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield-data", default="", help="Starfield's Data folder (vanilla graph and clip)")
    ap.add_argument("--out", required=True, help="the test mod's folder (e.g. $mods\\S2S SAM Test)")
    ap.add_argument("--graph", default="", help="MeleeAttacks.agx to start from (default: the game's)")
    ap.add_argument("--clip", default="meleeattackpower_a", help="vanilla clip in --folder to copy")
    ap.add_argument("--folder", default="melee/onehanded/player")
    ap.add_argument("--host", default="MeleeAttack_A", help="the combo state that plays the new tag")
    ap.add_argument("--tag", default="S2S_SamTest")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,63}", a.tag):
        ap.error("--tag: letters, digits and _ only")
    graph_raw, graph_src = read_vanilla(a.graph or GRAPH_REL, a.starfield_data)
    af = afx = af_src = None
    for src in (a.folder, a.folder + "/sword", a.folder + "/knife"):      # the clip's own folder, else a weapon's
        try:
            af, af_src = read_vanilla(f"{ANIMS}{src}/{a.clip}.af", a.starfield_data)
            afx, _ = read_vanilla(f"{ANIMS}{src}/{a.clip}.afx", a.starfield_data)
            break
        except (SystemExit, KeyError):
            af = None
    if af is None:
        raise SystemExit(f"{a.clip}.af / .afx not found in {a.folder} (or its sword / knife folders)")
    graph, n = point_host(graph_raw, a.host, a.tag)
    files = {GRAPH_REL: graph,
             f"{ANIMS}{a.folder}/{a.tag}.af": af,
             f"{ANIMS}{a.folder}/{a.tag}.afx": retag(afx, a.tag, a.tag + ".af")}
    files.update(fragment_files(a.tag, a.folder))
    for rel, data in files.items():
        path = os.path.join(a.out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    rep = {"tag": a.tag, "clip_from": af_src, "graph_from": graph_src, "host_state": a.host, "states_changed": n,
           "files": sorted(files)}
    with open(os.path.join(a.out, "sam_test.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{a.host} in {MACHINE} now plays {a.tag} (a copy of {a.clip}); fragment {FRAGMENT}: {len(files) - 3} files")
    for f in sorted(files):
        print("  " + f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
