"""TK Dodge's four step dodges as a standalone mod on a SAM fragment: our own tags and file names, no Creation Kit run.

    python -I scripts\\armor\\sam_dodge_pack.py --tk <TK Dodge folder> --starfield-data "$sf\\Data" --out "$mods\\S2S SAM Dodge"
        --calumi "$calumi" --skyrim-data "$sky"   (other hkx_to_af options pass through)

Why (docs/armor/animation-port.md, "SAM"): the stance packs' dodges (dodge_pack.py, v15) had to borrow vanilla tags
(MeleeAttack05, FireSingle, MeleeAttackBash, FireAutoPush) and zero-g file names, because the game reads its tag tables
only from its own archive and the Creation Kit lists only file names it already knows. SAM (Nexus 18674) declares a
fragment's new tags in memory and adds its clips to the animation index (owner's one-tag test, 2026-11-23: verified).
This pack, needing only SAM and the S2SCombat plugin:
  * clips: StepDodgeForward / Back / Left / Right.hkx converted with their root motion from TK Dodge's
    animationdatasinglefile (motion ids looked up by clip generator name, TKDodge<Direction>, in DefaultMale) as S2S_Dodge<Direction>.af / .afx in melee\\onehanded\\player
    (a vanilla folder, so SAM's animations.txt adds them to every list that already uses it), tag = file stem, with
    dodge_pack's dodge descriptor (Allow Rotation, no slide events);
  * graphs: the game's MeleeAttacks.agx with one full-body dodge state per direction (dodge_graph.build_attacks) and
    its Player_Melee.agx whose attack switch learns the dodge events;
  * fragment: Meshes\\AnimTextData\\Fragments\\S2SDodge\\animations.txt (the eight files) and tables\\anim_actions.xtbl
    (the four tags). No animationoffsets / animeventinfo (the one-tag test played without them).
Events stay the NPC melee attack events (dodge_graph.KNOWN_EVENTS, the plugin's default sDodgeEvents): SAM's source
(2026-11-01) declares tags, not events. Conflicts with any other mod shipping MeleeAttacks.agx / Player_Melee.agx
(our stance and combo packs): test with those disabled.
"""
import argparse
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

import dodge_graph  # noqa: E402

FRAGMENT = "S2SDodge"
ANIMS = "meshes/actors/human/animations/"
FOLDER = "melee/onehanded/player"
TEMPLATE = ANIMS + FOLDER + "/slidefromsprint.afx"
ATTACKS_REL = "/".join(dodge_graph.ATTACKS_REL)
PLAYER_REL = "/".join(dodge_graph.PLAYER_REL)
DIRECTIONS = dodge_graph.FOUR


def tags(directions=DIRECTIONS) -> dict:
    """{direction: tag}; the tag is also the clip's file stem."""
    return {d: f"S2S_Dodge{d}" for d in directions}


def fragment_files(tag_map: dict, folder: str = FOLDER, name: str = FRAGMENT) -> dict:
    """{Data-relative path: bytes} of the SAM fragment: every clip file (paths from Meshes\\) and the new tags."""
    base = "Meshes\\actors\\human\\animations\\" + folder.replace("/", "\\")
    clips = "".join(f"{base}\\{t}.{ext}\r\n" for t in tag_map.values() for ext in ("af", "afx"))
    entries = "".join(f"\t<entry><name>{t}</name></entry>\r\n" for t in tag_map.values())
    xtbl = f"<root>\r\n<table>\r\n{entries}</table>\r\n</root>\r\n"
    root = f"meshes/animtextdata/fragments/{name}/"
    return {root + "animations.txt": clips.encode("ascii"), root + "tables/anim_actions.xtbl": xtbl.encode("ascii")}


def graphs(attacks_raw: bytes, player_raw: bytes, tag_map: dict):
    """({Data-relative path: bytes}, report) of the two graphs: dodge states in MeleeAttacks, events in Player_Melee."""
    attacks, report = dodge_graph.build_attacks(attacks_raw, tuple(tag_map), None, tag_map)
    player, n = dodge_graph.add_switch_events(player_raw, [st["event"] for st in report["states"].values()])
    report["player_switch_lists"] = n
    return {ATTACKS_REL: attacks, PLAYER_REL: player}, report


def write(out: str, files: dict):
    for rel, data in files.items():
        path = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)


def _numbers(line: str):
    out = []
    for tok in line.split():
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def _project_sections(lines, project: str):
    """(clip lines, motion lines) of one project, the others skipped by their line counts only (their contents are
    not read: other mods' copies can hold malformed lines, owner's run 2026-11-23: '0.066667 animmotion 0.0 0.0 0.0'
    in motion 32755)."""
    count = int(lines[0].strip())
    names = [ln.strip() for ln in lines[1:1 + count]]
    i = 1 + count
    for name in names:
        n = int(lines[i].strip())
        block = lines[i + 1:i + 1 + n]
        i += 1 + n
        files_n = int(block[1].strip())
        has_clips = 2 + files_n < len(block) and block[2 + files_n].strip() == "1"
        motion = []
        if has_clips:
            m = int(lines[i].strip())
            motion = lines[i + 1:i + 1 + m]
            i += 1 + m
        if name.lower().removesuffix(".txt") == project.lower():
            return block[3 + files_n:] if has_clips else [], motion
    raise SystemExit(f"no {project} project in the animationdatasinglefile")


def _motion_by_counts(lines, wanted):
    """{id: block} for the wanted ids, walking the motion section by its key counts; only wanted blocks are parsed."""
    out, i = {}, 0
    while i < len(lines) and len(out) < len(wanted):
        if not lines[i].strip():
            i += 1
            continue
        ident, dur = lines[i].strip(), _numbers(lines[i + 1])
        n = int(lines[i + 2].strip())
        tr_lines = lines[i + 3:i + 3 + n]
        j = i + 3 + n
        m = int(lines[j].strip())
        rot_lines = lines[j + 1:j + 1 + m]
        if ident in wanted:
            tr = [tuple(v[-4:]) for v in map(_numbers, tr_lines)]
            rot = [tuple(v[-5:]) for v in map(_numbers, rot_lines)]
            if any(len(t) != 4 for t in tr) or any(len(r) != 5 for r in rot) or not dur:
                raise SystemExit(f"motion block {ident}: unreadable keys")
            out[ident] = {"duration": dur[0], "translations": tr, "rotations": rot}
        i = j + 1 + m
    return out


def motion_blocks(text: str, directions=DIRECTIONS, project: str = "DefaultMale") -> dict:
    """{direction: (motion block id, block)} looked up by clip generator name (TKDodge<Direction>) in an
    animationdatasinglefile's third-person project. The ids differ between copies: TK Dodge RE's full copy has 1656
    for TKDodgeForward, TK Dodge SE's file does not (owner's run 2026-11-23: "no motion block 1656")."""
    clip_lines, motion_lines = _project_sections(text.splitlines(), project)
    ids, i = {}, 0
    while i + 5 < len(clip_lines):                # clip blocks: name, id, speed, crop start, crop end, event count
        if not clip_lines[i].strip():
            i += 1
            continue
        name, ident = clip_lines[i].strip().lower(), clip_lines[i + 1].strip()
        ids.setdefault(name, ident)
        i += 6 + int(clip_lines[i + 5].strip())
    want = {d: ids.get(f"tkdodge{d}".lower()) for d in directions}
    blocks = _motion_by_counts(motion_lines, {x for x in want.values() if x})
    missing = [d for d, x in want.items() if x not in blocks]
    if missing:
        near = sorted(n for n in ids if "dodge" in n)[:20]
        raise SystemExit(f"no motion for TKDodge{', TKDodge'.join(missing)} in {project}; dodge clip generators there: "
                         f"{', '.join(near) or 'none'}")
    return {d: (x, blocks[x]) for d, x in want.items()}


def motion_text(blocks: dict) -> str:
    """The chosen blocks alone, as an animationdatasinglefile motion section (ids are per project, and hkx_to_af
    --motion keeps the first block of an id anywhere in the file: a lone file cannot pick another project's)."""
    out = []
    for ident, b in blocks.values():
        out += [ident, f"{b['duration']:.6f}", str(len(b["translations"]))]
        out += [" ".join(repr(v) for v in t) for t in b["translations"]]
        out += [str(len(b["rotations"]))] + [" ".join(repr(v) for v in r) for r in b["rotations"]] + [""]
    return "\r\n".join(out) + "\r\n"


def convert(tk: str, tag_map: dict, starfield_data: str, rest: list):
    """(rc, {Data-relative path: bytes}, hkx_to_af report or None): the dodge clips converted beside the slide."""
    import dodge_pack                                     # hkx_to_af needs numpy and CALUMI: imported only here
    import hkx_to_af
    with open(dodge_pack.find_motion(tk), encoding="latin-1") as fh:
        blocks = motion_blocks(fh.read(), tuple(tag_map))
    print("motion: " + ", ".join(f"{d} id {i} ({b['duration']:.3f} s)" for d, (i, b) in blocks.items()))
    files, report = {}, None
    with tempfile.TemporaryDirectory() as tmp:
        motion = os.path.join(tmp, "dodge_motion.txt")
        with open(motion, "w", encoding="latin-1", newline="") as fh:
            fh.write(motion_text(blocks))
        specs = []
        for d, tag in tag_map.items():
            clip = dodge_pack.CLIPS[d]
            specs += ["--replace", f"{dodge_pack.find_clip(tk, clip)}::{TEMPLATE}::{tag}",
                      "--motion", f"{os.path.splitext(clip)[0]}={motion}:{blocks[d][0]}"]
        out_dir = os.path.join(tmp, "out")
        rc = hkx_to_af.main(rest + ["--out", out_dir, "--starfield-data", starfield_data, "--weapon-in-hand"] + specs)
        src = os.path.join(out_dir, *ANIMS.split("/"), *FOLDER.split("/"))
        for tag in tag_map.values():
            for ext in (".af", ".afx"):
                path = os.path.join(src, tag + ext)
                if not os.path.isfile(path):
                    print(f"{tag}{ext} was not written")
                    rc |= 1
                    continue
                with open(path, "rb") as fh:
                    data = fh.read()
                if ext == ".afx":
                    data = dodge_pack.dodge_descriptor(data, tag + ".af")
                files[f"{ANIMS}{FOLDER}/{tag}{ext}"] = data
        rep = os.path.join(out_dir, "report.json")
        if os.path.isfile(rep):
            with open(rep, encoding="utf-8") as fh:
                report = json.load(fh)
    return rc, files, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tk", required=True, help="TK Dodge folder (StepDodge*.hkx and animationdatasinglefile.txt)")
    ap.add_argument("--starfield-data", required=True, help="Starfield's Data folder (vanilla graphs and template)")
    ap.add_argument("--out", required=True, help="the mod's folder (e.g. $mods\\S2S SAM Dodge)")
    a, rest = ap.parse_known_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    import hkx_to_af
    tag_map = tags()
    attacks_raw, _ = hkx_to_af.vanilla_file(ATTACKS_REL, a.starfield_data)
    player_raw, _ = hkx_to_af.vanilla_file(PLAYER_REL, a.starfield_data)
    graph_files, report = graphs(attacks_raw, player_raw, tag_map)      # before converting: fails fast
    rc, clip_files, conv = convert(a.tk, tag_map, a.starfield_data, rest)
    files = {**clip_files, **graph_files, **fragment_files(tag_map)}
    write(out, files)
    with open(os.path.join(out, "sam_dodge.json"), "w", encoding="utf-8") as fh:
        json.dump({"states": report["states"], "player_switch_lists": report["player_switch_lists"],
                   "files": sorted(files), "conversion": conv}, fh, indent=1)
    for d, st in report["states"].items():
        print(f"{d}: event {st['event']} -> state playing {st['tag']}")
    print(f"{len(clip_files)} clip files, 2 graphs, fragment {FRAGMENT} -> {out}" + ("" if rc == 0 else " (ERRORS above)"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
