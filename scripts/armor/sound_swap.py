"""Skyrim's forge sounds played through vanilla Starfield events whose audio files they replace (the route Starfield
sound mods use). docs/npc/furniture.md, sounds.

2026-11-20 (owner's tests, verified): a bank of our own (sound_bank.py: 1490023241.bnk as the empty scratch bank, then
S2S_Sounds 4107597624.bnk, each listed in a patched soundbanksinfo.json) stayed silent, while a vanilla event named in
an <audio> foley of the same descriptors (the welder's ITM_Microscope_Up) played. Loose <id>.wem files in
Data\\Sound\\Soundbanks replace a vanilla streamed file (Nexus sound mods). So each Skyrim sound gets a vanilla NPC
event of Starfield_NPC (13 m, the crafting workbench bus, loaded by the game) whose streamed files no other event uses
- food-station sounds, so a Starfield NPC cooking would hear the forge - and Skyrim's file(s), converted to .wem as the
voices are (WwiseConsole convert-external-source, the CK's project, Vorbis Quality High), take those files' ids. The
forge descriptors then name the vanilla event (furniture_anim_pack --sound-map <work>\\sound_swap.json).

    python -I scripts\\armor\\sound_swap.py --skyrim-data "<Skyrim>\\Data" --starfield "<Starfield>" ^
        --work C:\\Modding\\work\\sound_swap --mod "<MO2 mods>\\S2S Sounds"
"""
import argparse
import collections
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

import sound_bank as SB  # noqa: E402

# Skyrim sound -> vanilla event (Starfield_NPC, streamed files used by no other event: checked on the owner's
# soundbanksinfo.json 2026-11-20). The distant hammer is left out: Skyrim plays it with the near one at every blow,
# and both would come from the same 13 m event here.
SWAP = {"NPCHumanBlacksmithHammer": "NPC_Human_FoodStation_Stockpot_Fidget",        # 3 files
        "NPCHumanBlacksmithForgeQuench": "NPC_Human_FoodStation_FryPan_FidgetSizzle",  # 3
        "NPCHumanBlacksmithForgeQuenchDrop": "NPC_Human_FoodStation_Drawer_Close",     # 2
        "NPCHumanBlacksmithForgeTake": "NPC_Human_FoodStation_Drawer_Open",            # 2
        "OBJBlacksmithForge": "NPC_Human_FoodStation_Heat_Off"}                        # 1


def event_files(sf_info: dict) -> tuple:
    """({event name: [streamed file ids]}, {file id: {event names using it}})."""
    files, users = {}, collections.defaultdict(set)
    for b in sf_info["SoundBanksInfo"]["SoundBanks"]:
        for e in b.get("IncludedEvents", []):
            ids = [f["Id"] for f in e.get("ReferencedStreamedFiles", [])]
            files.setdefault(e["Name"], ids)
            for i in ids:
                users[i].add(e["Name"])
    return files, users


def assign(ours: list, targets: list) -> list:
    """[(target file id, our file)]: every vanilla file replaced, ours reused in turn when there are fewer."""
    return [(t, ours[k % len(ours)]) for k, t in enumerate(targets)] if ours else []


def to_wem(wav: str, wwise: str, project: str, scratch: str):
    """One .wav -> .wem through WwiseConsole convert-external-source (as skyrim_voice.to_wem)."""
    sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))
    import skyrim_voice
    stem = os.path.splitext(os.path.basename(wav))[0]
    return skyrim_voice.to_wem(wav, stem, wwise, project, scratch)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--mod", required=True, help="the .wem files go to <mod>\\Sound\\Soundbanks")
    ap.add_argument("--wwise", default=SB.WWISE_CONSOLE)
    ap.add_argument("--ffmpeg")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.wwise):
        sys.exit(f"no WwiseConsole.exe at {a.wwise} (--wwise)")
    src_name, info = SB.starfield_info(os.path.join(a.starfield, "Data"))
    files, users = event_files(info)
    wavs = SB.extract(a.skyrim_data, list(SWAP), os.path.join(a.work, "wav"), a.ffmpeg)
    project = os.path.join(a.starfield, "Tools", "wwise", "Starfield", "Starfield.wproj")
    scratch = os.path.join(a.work, "wem")
    os.makedirs(scratch, exist_ok=True)
    dst_dir = os.path.join(a.mod, "Sound", "Soundbanks")
    os.makedirs(dst_dir, exist_ok=True)
    rep = {"info": src_name, "sounds": {}}
    converted = {}
    for sky, ev in SWAP.items():
        targets = files.get(ev, [])
        row = {"event": ev, "skyrim_files": len(wavs.get(sky, [])), "replaced": [], "shared": {}}
        for tid, wav in assign(wavs.get(sky, []), targets):
            if wav not in converted:
                converted[wav] = to_wem(wav, a.wwise, project, scratch)
            if not converted[wav]:
                row.setdefault("failed", []).append(os.path.basename(wav))
                continue
            shutil.copyfile(converted[wav], os.path.join(dst_dir, f"{tid}.wem"))
            row["replaced"].append(f"{tid}.wem <- {os.path.basename(wav)}")
            other = sorted(users.get(tid, set()) - {ev})
            if other:
                row["shared"][tid] = other
        if not targets:
            row["error"] = "event not in soundbanksinfo.json"
        rep["sounds"][sky] = row
    smap = {sky: r["event"] for sky, r in rep["sounds"].items() if r["replaced"]}
    with open(os.path.join(a.work, "sound_swap.json"), "w", encoding="utf-8") as fh:
        json.dump(smap, fh, indent=1)
    with open(os.path.join(a.work, "sound_swap_report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    for sky, r in rep["sounds"].items():
        print(f"{sky} -> {r['event']}: {len(r['replaced'])} files"
              + (f", FAILED {r['failed']}" if r.get("failed") else "") + (f", {r['error']}" if r.get("error") else "")
              + (f", shared with {r['shared']}" if r["shared"] else ""))
    print(f"-> {os.path.join(a.work, 'sound_swap.json')} (furniture_anim_pack --sound-map)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
