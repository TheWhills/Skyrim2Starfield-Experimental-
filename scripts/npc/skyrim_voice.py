"""Skyrim voice lines to Starfield voice files (owner 2026-11-05: "I'm sure we could get voice lines as well";
Starfield's half is UNITY's proven chain, docs/npc/voice-pipeline.md).

For each --npc (Skyrim EditorID), the lines it speaks (its own, GetIsID it, and its voice type's, GetIsVoiceType):
  1. found in Skyrim.esm (topics and responses, src/fo4sf/skyrimdialog.py) with their text (the .dlstrings tables)
     and their voice file (.fuz in the voices archives);
  2. unpacked: the .fuz's .xwm audio -> .wav (ffmpeg);
  3. (on the owner's PC, with --wwise) .wav -> .wem: WwiseConsole convert-external-source, Starfield's Wwise project,
     "Vorbis Quality High", platform Windows;
  4. (with --lips) lip animation: LipGenerator on the raw .wav with the line's text as a plain string, a per-line
     .ffxcproj in Intermediate\\Slice_00 (male) / Slice_01 (female), ffxc compiling into a registered vanilla voice
     folder (NPCMBarrett / NPCFSarahMorgan), the .ffxanim copied out.

Writes into --out: lines.json (every line: topic, subtype, how the NPC speaks it, text, voice file, results) and
lines\\<voice type>\\<INFO FormID>_<response>.{xwm,wav,wem,ffxanim}. The files are named by the SKYRIM INFO FormID;
the plugin step (later) names them after the Starfield INFO records it writes. --scope: greetings (Hello topics,
default), own (every line with a GetIsID of the NPC), all.

    python -I scripts\\npc\\skyrim_voice.py --skyrim-data "<Skyrim>\\Data" --npc Ralof --out C:\\Modding\\work\\voice
        [--ffmpeg ffmpeg.exe] [--starfield "<Starfield>" --wwise "<WwiseConsole.exe>" --lips] [--limit 20]
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa, sfplugin, skyrimdialog, skyrimnpc  # noqa: E402

WWISE_DEFAULT = r"C:\Audiokinetic\Wwise_2021.1.14.8108\Authoring\x64\Release\bin\WwiseConsole.exe"
REGISTERED = {True: "NPCMBarrett", False: "NPCFSarahMorgan"}            # male: registered compile folder
GREETING_CODES = {"HELO"}


def make_wsources(wav_dir: str, stem: str, out_path: str) -> str:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<ExternalSourcesList SchemaVersion="1" Root="{wav_dir}">\n'
           f'    <Source Path="{stem}.wav" Conversion="Vorbis Quality High" Destination="{stem}"/>\n'
           '</ExternalSourcesList>')
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return out_path


def ffxcproj_text(actor: str, animset: str) -> str:
    return f"version: 10300\nitems:\n - facefx_file: {actor}\n   mount_files:\n    - {animset}\n"


def clean_wav(data: bytes):
    """A canonical 44-byte-header PCM WAV of `data` (UNITY's parse_wav_pcm / sanitize_wav_for_lipgen), or None."""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos, fmt, body = 12, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size, = struct.unpack_from("<I", data, pos + 4)
        start, end = pos + 8, pos + 8 + size
        if cid == b"data" and (size in (0, 0xFFFFFFFF) or end > len(data)):
            body = data[start:]
            break
        if end > len(data):
            break
        if cid == b"fmt ":
            fmt = data[start:end]
        elif cid == b"data":
            body = data[start:end]
        pos = end + (size & 1)
    if not fmt or len(fmt) < 16 or body is None:
        return None
    _f, ch, rate, _br, _ba, bits = struct.unpack("<HHIIHH", fmt[:16])
    block = ch * (bits // 8)
    return (b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE" + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, ch, rate, rate * block, block, bits) + b"data" + struct.pack("<I", len(body))
            + body)


def lines_for(npc, topics, texts, voice_edid, scope: str, keep_player_lines: bool = False, skipped=None):
    """The NPC's lines: [{topic, subtype, how, info, number, text, conditions}]; lines conditioned on the player
    (skyrimdialog.about_player: 'What do you want, little elf?', a hated player's greeting) left out unless
    keep_player_lines (counted in skipped)."""
    out = []
    for t in topics:
        if scope == "greetings" and t["subtype_code"] not in GREETING_CODES:
            continue
        for info in t["infos"]:
            how = skyrimdialog.speaks(info, npc["form_id"], npc.get("voice"))
            if how is None or (scope == "own" and how != "own") or (how == "anyone" and scope != "all"):
                continue
            if not keep_player_lines and any(skyrimdialog.about_player(c) for c in info["conditions"]):
                if skipped is not None:
                    skipped["about_the_player"] = skipped.get("about_the_player", 0) + 1
                continue
            conds = sorted({f"{c['name']}@{c['run_on']}" for c in info["conditions"]
                            if c["function"] not in (skyrimdialog.GET_IS_ID, skyrimdialog.GET_IS_VOICE_TYPE)})
            for r in info["responses"]:
                text = r["text"] if r["text"] is not None else texts.get(r["text_id"] or -1, "")
                out.append({"topic": t["edid"], "subtype": t["subtype_code"], "how": how,
                            "info": f"{info['form_id'] & 0xFFFFFF:08X}", "number": r["number"], "text": text,
                            "voice_type": voice_edid, "conditions": conds})
    return out


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def to_wav(xwm_path: str, wav_path: str, ffmpeg: str) -> bool:
    r = run([ffmpeg, "-y", "-loglevel", "error", "-i", xwm_path, "-acodec", "pcm_s16le", wav_path])
    return r.returncode == 0 and os.path.isfile(wav_path)


def to_wem(wav_path: str, stem: str, wwise: str, project: str, scratch: str):
    ws = make_wsources(os.path.dirname(os.path.abspath(wav_path)), stem, os.path.join(scratch, stem + ".wsources"))
    run([wwise, "convert-external-source", project, "--source-file", ws, "--output", scratch, "--platform",
         "Windows"])
    found = [p for p in Path(scratch).rglob(f"{stem}.wem") if p.stat().st_size > 0]
    return str(max(found, key=lambda p: p.stat().st_mtime)) if found else None


def to_lips(wav_path: str, stem: str, text: str, male: bool, starfield: str):
    """UNITY's build_lipsync for one line: the .ffxanim path, or None."""
    tools = os.path.join(starfield, "Tools")
    actor_name = "StarfieldHumanMale" if male else "StarfieldHumanFemale"
    actor = os.path.join(tools, "FaceFX", actor_name + ".facefx")
    inter = os.path.join(starfield, "Intermediate", "Slice_00" if male else "Slice_01")
    reg = os.path.join(starfield, "Data", "Sound", "Voice", "S2SVoiceBuild.esm", REGISTERED[male])
    group = f"{REGISTERED[male]}_{stem}"
    os.makedirs(inter, exist_ok=True)
    os.makedirs(reg, exist_ok=True)
    animset = os.path.join(inter, group + ".animset")
    run([os.path.join(tools, "LipGenerator", "LipGenerator.exe"), wav_path, text.strip() or "dialogue", actor,
         os.path.join(tools, "FaceFX", "GenesisDefault.facefx"), f"-OutputFileName:{animset}",
         f"-AnimationGroupName:{group}"], timeout=90)
    if not os.path.isfile(animset):
        return None
    proj = os.path.join(inter, group + ".ffxcproj")
    with open(proj, "w", encoding="utf-8") as fh:
        fh.write(ffxcproj_text(actor, animset))
    r = run([os.path.join(tools, "FaceFX", "ffxc.exe"), f"-o={reg}\\", "-p=x86", "--rebuild", proj], timeout=90)
    if r.returncode != 0:
        return None
    sub = os.path.join(reg, actor_name, "x86", group)
    hit = os.path.join(sub, stem + ".ffxanim")
    if os.path.isfile(hit):
        return hit
    found = list(Path(sub).glob("*.ffxanim")) if os.path.isdir(sub) else []
    return str(max(found, key=lambda p: p.stat().st_size)) if found else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--npc", action="append", required=True, help="Skyrim NPC EditorID (repeatable)")
    ap.add_argument("--out", required=True, help="a folder outside the repository")
    ap.add_argument("--scope", choices=("greetings", "own", "all"), default="greetings")
    ap.add_argument("--limit", type=int, default=0, help="at most this many lines per NPC (0: all)")
    ap.add_argument("--language", default="english")
    ap.add_argument("--keep-player-lines", action="store_true",
                    help="also lines conditioned on the player (race, relationship ...), left out by default")
    ap.add_argument("--ffmpeg", help="ffmpeg.exe: .xwm -> .wav")
    ap.add_argument("--starfield", help="Starfield folder (its Tools: the Wwise project, LipGenerator, FaceFX)")
    ap.add_argument("--wwise", nargs="?", const=WWISE_DEFAULT, help="WwiseConsole.exe (default: Wwise 2021.1.14)")
    ap.add_argument("--lips", action="store_true", help="LipGenerator + ffxc lip files (needs --starfield)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    if (a.wwise or a.lips) and not a.starfield:
        sys.exit("--wwise / --lips need --starfield")
    os.makedirs(out, exist_ok=True)
    esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    sky = bsa.SkyrimArchives(a.skyrim_data)
    npcs = {fid: skyrimnpc.parse_npc(s, fid) for _t, _h, s, fid in sfplugin.records(esm, [b"NPC_"])}
    vtyp = {fid: sfplugin.edid(s) for _t, _h, s, fid in sfplugin.records(esm, [b"VTYP"])}
    by_edid = {n["edid"].lower(): n for n in npcs.values()}
    tops = skyrimdialog.topics(esm)
    texts = skyrimdialog.response_texts(sky, a.language)
    names = [n for arc in sky.archives for n in arc.names if n.startswith("sound\\voice\\")]
    files = skyrimdialog.voice_index(names)
    report = {"topics": len(tops), "dialogue_strings": len(texts), "voice_files": len(files), "npcs": []}
    scratch = os.path.join(out, "_scratch")
    for e in a.npc:
        n = by_edid.get(e.lower())
        if n is None:
            report["npcs"].append({"npc": e, "error": "not in Skyrim.esm"})
            continue
        voice = vtyp.get(n.get("voice") or -1, "")
        male = not n["female"]
        skipped = {}
        rows = lines_for(n, tops, texts, voice, a.scope, a.keep_player_lines, skipped)
        if a.limit:
            rows = rows[:a.limit]
        folder = os.path.join(out, "lines", voice or "novoice")
        os.makedirs(folder, exist_ok=True)
        for row in rows:
            key = (voice.lower(), int(row["info"], 16), row["number"])
            path = files.get(key)
            row["voice_file"] = path
            if not path:
                row["result"] = "no voice file"
                continue
            stem = f"{row['info']}_{row['number']}"
            raw = sky._read(path)
            try:
                xwm = skyrimdialog.unpack_fuz(raw)[1] if path.endswith(".fuz") else raw
            except ValueError as err:
                row["result"] = str(err)
                continue
            xpath = os.path.join(folder, stem + ".xwm")
            with open(xpath, "wb") as fh:
                fh.write(xwm)
            row["result"] = "xwm"
            if not a.ffmpeg:
                continue
            wav = os.path.join(folder, stem + ".wav")
            if not to_wav(xpath, wav, a.ffmpeg):
                row["result"] = "ffmpeg failed"
                continue
            with open(wav, "rb") as fh:
                fixed = clean_wav(fh.read())
            if fixed:
                with open(wav, "wb") as fh:
                    fh.write(fixed)
            row["result"] = "wav"
            if a.wwise:
                os.makedirs(scratch, exist_ok=True)
                proj = os.path.join(a.starfield, "Tools", "wwise", "Starfield", "Starfield.wproj")
                wem = to_wem(wav, stem, a.wwise, proj, scratch)
                if wem:
                    shutil.copyfile(wem, os.path.join(folder, stem + ".wem"))
                    row["result"] = "wem"
                else:
                    row["result"] = "wem failed"
            if a.lips:
                anim = to_lips(wav, stem, row["text"], male, a.starfield)
                if anim:
                    shutil.copyfile(anim, os.path.join(folder, stem + ".ffxanim"))
                    row["lips"] = True
                else:
                    row["lips"] = False
        report["npcs"].append({"npc": n["edid"], "voice_type": voice, "male": male, "skipped": skipped,
                               "lines": rows})
        done = sum(1 for r in rows if r.get("result") in ("xwm", "wav", "wem"))
        print(f"{n['edid']} ({voice}): {len(rows)} lines, {done} with audio")
    shutil.rmtree(scratch, ignore_errors=True)
    with open(os.path.join(out, "lines.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print("report:", os.path.join(out, "lines.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
