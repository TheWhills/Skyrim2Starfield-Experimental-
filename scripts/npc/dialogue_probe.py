"""How Starfield builds its greetings, before writing our own (owner 2026-11-05: Ralof and Ysolda speaking their
Skyrim lines). Read-only on the owner's PC; dumps from Starfield.esm:

  * greeting topics (DIAL whose subtype code is HELO, or EditorID mentions Hello / Greeting): every subrecord (sig,
    size, the first bytes in hex, text when it reads as text), their quest's EditorID, and their first responses
    (INFO, from the topic's child group) the same way;
  * how many of all INFOs carry a voice type condition, a few voice types (VTYP) in full;
  * the voice files of one generic voice type in the voices archives (how they are named: by INFO FormID?).

Writes --out\\dialogue_probe.json.

    python -I scripts\\npc\\dialogue_probe.py --starfield "<Starfield folder>" --out C:\\Modding\\work\\dialogue_probe
"""
import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, fo4land  # noqa: E402

VOICE_TYPES = ("GenericMaleEvenToned", "GenericFemaleEvenToned", "NPCMBarrett", "NPCFSarahMorgan")


def dump_subs(subs, limit: int = 48) -> list:
    out = []
    for sig, d in subs:
        d = bytes(d)
        row = {"sig": sig.decode("latin-1"), "size": len(d), "hex": d[:limit].hex()}
        if d and d[-1:] == b"\0" and all(32 <= b < 127 for b in d[:-1]):
            row["text"] = d[:-1].decode("latin-1")
        elif len(d) == 4:
            row["u32"] = f"{struct.unpack_from('<I', d, 0)[0]:08X}"
        out.append(row)
    return out


def _edid(subs) -> str:
    return next((fo4land.zstring(d) for s, d in subs if s == b"EDID"), "")


def is_greeting(subs) -> bool:
    e = _edid(subs).lower()
    snam = next((bytes(d)[:4] for s, d in subs if s == b"SNAM"), b"")
    return snam == b"HELO" or "hello" in e or "greeting" in e


def probe(esm: str, max_topics: int = 8, max_infos: int = 4) -> dict:
    topics, quests, vtyp = [], {}, []
    info_total = info_voice = 0
    with fo4land.Plugin(esm) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP":
                continue
            if item[3] == b"QUST":
                for it in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                    if it[0] != "GRUP" and it[0] == b"QUST":
                        subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, it[1])))
                        quests[it[3]] = _edid(subs)
            elif item[3] == b"VTYP":
                for it in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                    if it[0] == b"VTYP":
                        subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, it[1])))
                        if _edid(subs) in VOICE_TYPES:
                            vtyp.append({"form_id": f"{it[3]:08X}", "edid": _edid(subs), "subs": dump_subs(subs)})
            elif item[3] == b"DIAL":
                last = None
                for it in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                    if it[0] == "GRUP":
                        infos = []
                        for r in fo4land.iter_items(p.buf, it[1] + 24, it[2]):
                            if r[0] != b"INFO":
                                continue
                            subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, r[1])))
                            info_total += 1
                            if any(s == b"CTDA" and len(d) >= 10 and struct.unpack_from("<H", bytes(d), 8)[0] == 426
                                   for s, d in subs):
                                info_voice += 1
                            if last is not None and len(last["infos"]) < max_infos:
                                last["infos"].append({"form_id": f"{r[3]:08X}", "flags": f"{r[2]:08X}",
                                                      "subs": dump_subs(subs)})
                            infos.append(r[3])
                        if last is not None:
                            last["info_count"] = len(infos)
                            last["group_type"] = it[4]
                        last = None
                        continue
                    if it[0] != b"DIAL":
                        continue
                    subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, it[1])))
                    if is_greeting(subs) and len(topics) < max_topics:
                        last = {"form_id": f"{it[3]:08X}", "edid": _edid(subs), "subs": dump_subs(subs),
                                "infos": []}
                        topics.append(last)
                    else:
                        last = None
    for t in topics:
        q = next((r.get("u32") for r in t["subs"] if r["sig"] == "QNAM"), None)
        t["quest"] = quests.get(int(q, 16)) if q else None
    return {"greeting_topics": topics, "infos_total": info_total, "infos_with_voice_type_condition": info_voice,
            "voice_types": vtyp}


def voice_files(data_dir: str, voice: str = "genericmaleeventoned", limit: int = 30) -> list:
    out = []
    rx = re.compile(r"sound[\\/]voice[\\/]starfield\.esm[\\/]" + voice + r"[\\/]", re.I)
    for fn in sorted(os.listdir(data_dir)):
        if not (fn.lower().startswith("starfield - voices") and fn.lower().endswith(".ba2")):
            continue
        try:
            arc = ba2.Ba2(os.path.join(data_dir, fn))
        except Exception:                                   # noqa: BLE001 (report only)
            continue
        out += [f"{fn}: {n}" for n in arc.names if rx.search(n)][:limit - len(out)]
        if len(out) >= limit:
            break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True, help="a folder outside the repository")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(a.out, exist_ok=True)
    data = os.path.join(a.starfield, "Data")
    rep = probe(os.path.join(data, "Starfield.esm"))
    rep["voice_files_genericmaleeventoned"] = voice_files(data)
    with open(os.path.join(a.out, "dialogue_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"greeting topics dumped: {len(rep['greeting_topics'])}; INFOs: {rep['infos_total']} "
          f"({rep['infos_with_voice_type_condition']} with a voice type condition); "
          f"voice files listed: {len(rep['voice_files_genericmaleeventoned'])}")
    print("report:", os.path.join(a.out, "dialogue_probe.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
