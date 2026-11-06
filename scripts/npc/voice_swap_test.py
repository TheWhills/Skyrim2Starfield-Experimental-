"""Which half of a silent greeting is wrong: our records / file names, or our .wem files (owner 2026-11-05: Ralof's
subtitles change, no audio, while Sound\\Voice\\S2SFaceTest.esm\\S2S_MaleNord_Ralof\\00000805.wem etc. are in place).

Writes a vanilla voice line (a generic voice type's .wem from the game's voice archives) under every one of our
greeting file names (faces.json's voice section), in a separate mod folder to put ABOVE the face test mod in MO2:

  * heard (the vanilla voice, any words): the game finds our files by these names -> our .wem conversion is at fault;
  * still silent: the game never looks for / never plays these names -> the records or the naming are at fault.

    python -I scripts\\npc\\voice_swap_test.py --starfield "D:\\...\\Starfield" --faces "<mod>\\faces.json" --out "<mods>\\S2S Voice Swap Test"
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2  # noqa: E402

VOICES = {False: "genericmaleeventoned", True: "genericfemaleeventoned"}


def vanilla_wem(data_dir: str, voice: str):
    """(archive entry name, bytes) of the first .wem of `voice` in Starfield's voice archives."""
    rx = re.compile(r"sound[\\/]voice[\\/]starfield\.esm[\\/]" + voice + r"[\\/][^\\/]+\.wem$", re.I)
    for fn in sorted(os.listdir(data_dir)):
        low = fn.lower()
        if not (low.startswith("starfield - voices") and low.endswith(".ba2")):
            continue
        arc = ba2.Ba2(os.path.join(data_dir, fn))
        for n in arc.names:
            if rx.search(n):
                return n, arc.read(n)
    return None, None


def plan(faces: dict, plugin: str = "S2SFaceTest.esm"):
    """[(female, relative folder, file stem)] of every greeting in a faces.json."""
    out = []
    for row in faces.get("npcs", []):
        v = row.get("voice")
        if not v:
            continue
        for g in v.get("greetings", []):
            out.append((bool(row.get("female")), os.path.join("Sound", "Voice", plugin, v["voice_type"]), g["file"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--faces", required=True, help="face_fit.py's faces.json (with --voice-lines)")
    ap.add_argument("--out", required=True, help="a new mod folder (outside the repository)")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    with open(a.faces, encoding="utf-8") as fh:
        rows = plan(json.load(fh))
    if not rows:
        sys.exit("faces.json has no voice greetings (build with --voice-lines)")
    data = os.path.join(a.starfield, "Data")
    src = {}
    for female in {f for f, _d, _s in rows}:
        name, raw = vanilla_wem(data, VOICES[female])
        if raw is None:
            sys.exit(f"no {VOICES[female]} .wem in the voice archives")
        src[female] = raw
        print(f"{'female' if female else 'male'}: {name} ({len(raw)} bytes)")
    for female, folder, stem in rows:
        os.makedirs(os.path.join(a.out, folder), exist_ok=True)
        with open(os.path.join(a.out, folder, stem + ".wem"), "wb") as fh:
            fh.write(src[female])
    print(f"{len(rows)} files under {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
