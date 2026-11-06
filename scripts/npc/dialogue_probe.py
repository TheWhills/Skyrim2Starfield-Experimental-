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
    """Walks every group at every depth (the owner's first run found no topic at the top level: Starfield keeps its
    topics inside their quests' child groups); a topic's responses are the INFOs of the type-7 group labelled with
    its FormID."""
    topics, by_fid, quests, vtyp = [], {}, {}, []
    index, idx_fid, funcs, quest_recs = [], {}, {}, {}
    counts = {"info_total": 0, "info_voice": 0, "dial_total": 0, "dial_greeting": 0}
    where = {}

    def walk(buf, start, end, path):
        for it in fo4land.iter_items(buf, start, end):
            if it[0] == "GRUP":
                label, gtype = it[3], it[4]
                owner = struct.unpack_from("<I", label, 0)[0] if len(label) == 4 else None
                walk(buf, it[1] + 24, it[2], path + [(gtype, owner if gtype else label.decode("latin-1"))])
                continue
            typ, off, flags, fid = it
            if typ not in (b"DIAL", b"INFO", b"QUST", b"VTYP"):
                continue
            subs = list(fo4land.iter_subrecords(fo4land.record_data(buf, off)))
            if typ == b"QUST":
                quests[fid] = _edid(subs)
                if "generic" in quests[fid].lower() and len(quest_recs) < 4:
                    quest_recs[fid] = {"edid": quests[fid], "subs": dump_subs(subs, 24)}
            elif typ == b"VTYP":
                if _edid(subs) in VOICE_TYPES:
                    vtyp.append({"form_id": f"{fid:08X}", "edid": _edid(subs), "subs": dump_subs(subs)})
            elif typ == b"DIAL":
                counts["dial_total"] += 1
                if is_greeting(subs):
                    counts["dial_greeting"] += 1
                    q = next((struct.unpack_from("<I", bytes(d), 0)[0] for s_, d in subs if s_ == b"QNAM"), None)
                    row = {"topic": f"{fid:08X}", "edid": _edid(subs), "quest": q, "infos": 0}
                    index.append(row)
                    idx_fid[fid] = row
                    if len(topics) < max_topics:
                        t = {"form_id": f"{fid:08X}", "edid": _edid(subs), "subs": dump_subs(subs), "infos": [],
                             "info_count": 0,
                             "groups": [f"type {g}: {o:08X}" if isinstance(o, int) else f"type {g}: {o}"
                                        for g, o in path]}
                        topics.append(t)
                        by_fid[fid] = t
            else:
                counts["info_total"] += 1
                if any(s == b"CTDA" and len(d) >= 10 and struct.unpack_from("<H", bytes(d), 8)[0] == 426
                       for s, d in subs):
                    counts["info_voice"] += 1
                owner = next((o for g, o in reversed(path) if g == 7), None)
                if owner in idx_fid:
                    idx_fid[owner]["infos"] += 1
                    for s_, d in subs:
                        if s_ == b"CTDA" and len(d) >= 10:
                            f = struct.unpack_from("<H", bytes(d), 8)[0]
                            funcs[f] = funcs.get(f, 0) + 1
                t = by_fid.get(owner)
                if t is not None:
                    t["info_count"] += 1
                    if len(t["infos"]) < max_infos:
                        t["infos"].append({"form_id": f"{fid:08X}", "flags": f"{flags:08X}", "subs": dump_subs(subs)})
                    where.setdefault("info_group_path", [f"type {g}" for g, _o in path])

    with fo4land.Plugin(esm) as p:
        walk(p.buf, p.body, len(p.buf), [])
    for t in topics:
        q = next((r.get("u32") for r in t["subs"] if r["sig"] == "QNAM"), None)
        t["quest"] = quests.get(int(q, 16)) if q else None
    for row in index:
        row["quest"] = quests.get(row["quest"], f"{row['quest']:08X}" if row["quest"] is not None else None)
    by_quest = {}
    for row in index:
        by_quest[row["quest"]] = by_quest.get(row["quest"], 0) + row["infos"]
    return {"greeting_topics": topics, "infos_total": counts["info_total"],
            "infos_with_voice_type_condition": counts["info_voice"], "topics_total": counts["dial_total"],
            "greeting_topics_total": counts["dial_greeting"], "voice_types": vtyp,
            "greeting_quests_by_responses": sorted(by_quest.items(), key=lambda kv: -kv[1])[:40],
            "greeting_condition_functions": sorted(funcs.items(), key=lambda kv: -kv[1])[:30],
            "generic_quests": list(quest_recs.values()), **where}


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
