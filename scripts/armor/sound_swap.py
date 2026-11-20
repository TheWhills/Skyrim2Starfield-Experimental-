"""Skyrim's forge sounds played through vanilla Starfield events whose audio files they replace (the route Starfield
sound mods use). docs/npc/furniture.md, sounds.

2026-11-20 (owner's tests, verified): a bank of our own (sound_bank.py: 1490023241.bnk as the empty scratch bank, then
S2S_Sounds 4107597624.bnk, each listed in a patched soundbanksinfo.json) stayed silent, while a vanilla event named in
an <audio> foley of the same descriptors (the welder's ITM_Microscope_Up) played. Loose <id>.wem files in
Data\\Sound\\Soundbanks replace a vanilla streamed file (Nexus sound mods). So each Skyrim sound gets a vanilla NPC
event of Starfield_NPC (13 m, the crafting workbench bus, loaded by the game) whose streamed files no other event uses
- food-station sounds, so a Starfield NPC cooking would hear the forge - and Skyrim's file(s), converted to .wem as the
voices are, take those files' ids - 2026-11-20 (owner's wem_info): written as PCM in the vanilla file's own
format (pcm_wem), since Vorbis replacements stayed silent. The
forge descriptors then name the vanilla event (furniture_anim_pack --sound-map <work>\\sound_swap.json).

    python -I scripts\\armor\\sound_swap.py --skyrim-data "<Skyrim>\\Data" --starfield "<Starfield>" ^
        --work C:\\Modding\\work\\sound_swap --mod "<MO2 mods>\\S2S Sounds"
"""
import argparse
import collections
import json
import os
import struct
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


def riff_chunks(data: bytes) -> list:
    """[(tag, raw chunk bytes incl. header)] of a RIFF file after 'RIFF size WAVE'."""
    out, p = [], 12
    while p + 8 <= len(data):
        n = struct.unpack_from("<I", data, p + 4)[0]
        end = p + 8 + n + (n & 1)
        out.append((data[p:p + 4], data[p:end]))
        p = end
    return out


def read_wav(path: str):
    """(samples float32 (frames, channels) in -1..1, sample rate) of a PCM .wav (8 / 16 / 24 / 32-bit)."""
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / float(1 << 23)
    else:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / float(1 << 31)
    return x.reshape(-1, ch), rate


def pcm_wem(vanilla: bytes, samples, rate: int) -> bytes:
    """Our sound as a .wem in the vanilla file's own format. 2026-11-20 (owner's wem_info, verified): Starfield's
    food-station files are PCM - fmt 0xFFFE (extensible, 24 bytes), mono, 48000 Hz, 16-bit, then a 4-byte JUNK chunk
    and data - while convert-external-source gave Vorbis 32000 Hz, which the game left silent. So the vanilla fmt and
    JUNK chunks are kept byte for byte and only the data is ours: channels mixed / copied to the vanilla count,
    resampled (linear) to its rate, 16-bit."""
    import numpy as np
    chunks = riff_chunks(vanilla)
    fmt = next(c for t, c in chunks if t == b"fmt ")
    tag, ch, sr, _abps, _ba, bits = struct.unpack_from("<HHIIHH", fmt, 8)
    if tag not in (0x0001, 0xFFFE) or bits != 16:
        raise ValueError(f"vanilla file is not 16-bit PCM (format 0x{tag:04X}, {bits} bits)")
    x = np.asarray(samples, np.float32)
    x = x.reshape(len(x), -1)
    mono = x.mean(axis=1)
    if rate != sr and len(mono) > 1:
        t_new = np.arange(int(round(len(mono) * sr / rate))) * (rate / sr)
        mono = np.interp(t_new, np.arange(len(mono)), mono).astype(np.float32)
    out = np.repeat(mono[:, None], ch, axis=1)
    data = (np.clip(out, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()
    body = b"WAVE" + fmt + b"".join(c for t, c in chunks if t == b"JUNK") + b"data" + struct.pack("<I", len(data)) \
        + data + (b"\0" if len(data) & 1 else b"")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def vanilla_wems(sf_data: str, ids) -> dict:
    """{id: bytes} of vanilla streamed files sound/soundbanks/<id>.wem (the last archive holding each)."""
    from fo4sf import ba2
    want = {f"{i}.wem": i for i in ids}
    out = {}
    for fn in sorted(os.listdir(sf_data), key=lambda n: ("patch" in n.lower(), n.lower())):
        if fn.lower().startswith("starfield - wwisesounds") and fn.lower().endswith(".ba2"):
            arc = ba2.Ba2(os.path.join(sf_data, fn))
            for k, n in enumerate(arc.names):
                base = n.replace("\\", "/").split("/")[-1].lower()
                if base in want:
                    out[want[base]] = arc.read(k)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--mod", required=True, help="the .wem files go to <mod>\\Sound\\Soundbanks")
    ap.add_argument("--ffmpeg")
    a = ap.parse_args(argv)
    src_name, info = SB.starfield_info(os.path.join(a.starfield, "Data"))
    files, users = event_files(info)
    wavs = SB.extract(a.skyrim_data, list(SWAP), os.path.join(a.work, "wav"), a.ffmpeg)
    dst_dir = os.path.join(a.mod, "Sound", "Soundbanks")
    os.makedirs(dst_dir, exist_ok=True)
    rep = {"info": src_name, "sounds": {}}
    vanilla = vanilla_wems(os.path.join(a.starfield, "Data"), [t for ev in SWAP.values() for t in files.get(ev, [])])
    loaded = {}
    for sky, ev in SWAP.items():
        targets = files.get(ev, [])
        row = {"event": ev, "skyrim_files": len(wavs.get(sky, [])), "replaced": [], "shared": {}}
        for tid, wav in assign(wavs.get(sky, []), targets):
            if tid not in vanilla:
                row.setdefault("failed", []).append(f"{tid}: vanilla file not found")
                continue
            try:
                if wav not in loaded:
                    loaded[wav] = read_wav(wav)
                data = pcm_wem(vanilla[tid], *loaded[wav])
            except Exception as e:                        # noqa: BLE001
                row.setdefault("failed", []).append(f"{os.path.basename(wav)}: {e}")
                continue
            with open(os.path.join(dst_dir, f"{tid}.wem"), "wb") as fh:
                fh.write(data)
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
