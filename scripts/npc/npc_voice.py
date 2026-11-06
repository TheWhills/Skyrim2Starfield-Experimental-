"""The converted NPCs' own Skyrim greetings as Starfield records (owner 2026-11-05: Ralof and Ysolda speaking their
Skyrim lines; the audio from skyrim_voice.py, UNITY's chain). Built on what dialogue_probe.py read in Starfield.esm:

* a voice type per NPC (VTYP: EDID, DNAM u8 = 2 for a woman, 0 for a man, as NPCFSarahMorgan / NPCMBarrett: bit 0,
  'allow default dialogue', is set only on the generic voices; PNAM u8 0);
* one quest copied from the vanilla DialogueGeneric (EDID, FULL, DNAM, its own conditions dropped, NEXT, ANAM);
* in that quest's child group (type 10) one greeting topic (DIAL: EDID, PNAM f32 50, QNAM the quest, DATA 00 07 7D
  00, SNAM 'HELO', TIFL its responses' FormIDs, TIFC their count);
* in the topic's child group (type 7) one response (INFO) per line: ENAM 0, TRDA (no emotion keyword, 0, 0.0), NAM1
  the line's text (our plugin is not localized), NAM2-4 empty, NAM9 zero, CTDA GetIsID the NPC (function 72, the
  same index in both games: the probe saw vanilla greetings use it), NAM0 empty, INAM 1;
* the audio and lips as Data\\Sound\\Voice\\<plugin>\\<voice type>\\<response FormID, 8 hex, no load-order byte>.wem /
  .ffxanim (vanilla's generic voice files are named that way; UNITY's lines were found by it).
"""
import json
import os
import shutil
import struct
from typing import Dict, List, Tuple

from fo4sf import sfplugin

GET_IS_ID = 72
GREETING_DATA = bytes.fromhex("00077d00")


def ctda_get_is_id(npc_fid: int) -> bytes:
    """CTDA 'GetIsID <npc> == 1' run on the subject (layout as Starfield's own: type, 3 pad, f32 value, u16 function,
    2 pad, param 1, param 2, run on, reference, param 3 = -1)."""
    return bytes(4) + struct.pack("<fHHIIIIi", 1.0, GET_IS_ID, 0, npc_fid, 0, 0, 0, -1)


def voice_type(template, fid: int, edid: str, female: bool):
    t, h, _subs, _f = template
    return (b"VTYP", h, [(b"EDID", sfplugin.zs(edid)), (b"DNAM", bytes([2 if female else 0])), (b"PNAM", b"\0")], fid)


def quest(template, fid: int, edid: str, name: str):
    t, h, subs, _f = template
    out = sfplugin.edit(subs, {b"EDID": sfplugin.zs(edid), b"FULL": sfplugin.zs(name)},
                        drop=(b"CTDA", b"VMAD", b"FLTR"))
    return (b"QUST", h, out, fid)


def topic(header: bytes, fid: int, edid: str, quest_fid: int, infos: List[int]):
    return (b"DIAL", header, [(b"EDID", sfplugin.zs(edid)), (b"PNAM", struct.pack("<f", 50.0)),
                              (b"QNAM", struct.pack("<I", quest_fid)), (b"DATA", GREETING_DATA), (b"SNAM", b"HELO"),
                              (b"TIFL", b"".join(struct.pack("<I", i) for i in infos)),
                              (b"TIFC", struct.pack("<I", len(infos)))], fid)


def response(header: bytes, fid: int, text: str, npc_fid: int):
    return (b"INFO", header, [(b"ENAM", struct.pack("<I", 0)), (b"TRDA", struct.pack("<IIf", 0xFFFFFFFF, 0, 0.0)),
                              (b"NAM1", sfplugin.zs(text)), (b"NAM2", b"\0"), (b"NAM3", b"\0"), (b"NAM4", b"\0"),
                              (b"NAM9", bytes(8)), (b"CTDA", ctda_get_is_id(npc_fid)), (b"NAM0", b"\0"),
                              (b"INAM", struct.pack("<I", 1))], fid)


def load_lines(voice_dir: str) -> Dict[str, dict]:
    """{Skyrim NPC EditorID (lower): its lines.json entry} from skyrim_voice.py's --out folder."""
    with open(os.path.join(voice_dir, "lines.json"), encoding="utf-8") as fh:
        rep = json.load(fh)
    return {n["npc"].lower(): n for n in rep.get("npcs", []) if "lines" in n}


def add_voices(recs: list, npc_index: Dict[str, int], rows: list, voice_dir: str, masters: int, plugin: str,
               out_dir: str, vtyp_template, quest_template, report: dict) -> Tuple[list, dict]:
    """Voice types, the greeting quest / topic / responses for the NPCs in npc_index ({Skyrim EditorID: index of
    its NPC_ record in recs}); sets each NPC's VTCK; copies the .wem / .ffxanim under out_dir. Returns (records to
    add at the top level, children for sfplugin.build)."""
    lines = load_lines(voice_dir)
    new_top, infos, children = [], [], {}
    nxt = [len(recs)]

    def fid():
        f = sfplugin.new_form_id(nxt[0], masters)
        nxt[0] += 1
        return f
    header = quest_template[1]
    qfid = fid()
    new_top.append(quest(quest_template, qfid, "S2S_SkyrimGreetings", "S2S Skyrim greetings"))
    dfid = fid()
    for row in rows:
        k = npc_index.get(row["edid"])
        entry = lines.get(row["edid"].lower())
        if k is None or entry is None:
            continue
        t, h, subs, npc_fid = recs[k]
        vt_edid = f"S2S_{entry['voice_type'] or row['edid']}_{row['edid']}"
        vfid = fid()
        new_top.append(voice_type(vtyp_template, vfid, vt_edid, row["female"]))
        recs[k] = (t, h, sfplugin.edit(subs, {b"VTCK": struct.pack("<I", vfid)}), npc_fid)
        folder = os.path.join(out_dir, "Sound", "Voice", plugin, vt_edid)
        src = os.path.join(voice_dir, "lines", entry["voice_type"] or "novoice")
        done = []
        for ln in entry["lines"]:
            if ln.get("result") != "wem":
                continue
            ifid = fid()
            stem = f"{ln['info']}_{ln['number']}"
            os.makedirs(folder, exist_ok=True)
            name = f"{ifid & 0xFFFFFF:08x}"
            shutil.copyfile(os.path.join(src, stem + ".wem"), os.path.join(folder, name + ".wem"))
            lip = os.path.join(src, stem + ".ffxanim")
            if os.path.isfile(lip):
                shutil.copyfile(lip, os.path.join(folder, name + ".ffxanim"))
            infos.append(response(header, ifid, ln["text"], npc_fid))
            done.append({"text": ln["text"], "info": f"{ifid:08X}", "file": name, "lips": os.path.isfile(lip)})
        row["voice"] = {"voice_type": vt_edid, "form_id": f"{vfid:08X}", "greetings": done}
    if not infos:
        report["voice"] = "no lines with audio for these NPCs"
        return [], {}
    children[qfid] = (10, [topic(header, dfid, "S2S_SkyrimGreetings_Hellos", qfid, [i[3] for i in infos])])
    children[dfid] = (7, infos)
    report["voice"] = {"quest": f"{qfid:08X}", "topic": f"{dfid:08X}", "responses": len(infos)}
    return new_top, children
