"""How Starfield finds a Wwise event by name: which soundbank holds it, and how banks are named (docs/npc/furniture.md,
animation sounds). Read-only.

2026-11-20 (owner's sound_records run, verified): no record is named WPNGrenadeThrow (the SoundPlay payload of
Starfield's throw animations), WWED records are only EDID + WSED (16 bytes, a GUID), SOUN records point at two 16-byte
ids (SMLS). So an animation names a Wwise event directly; Wwise identifies an event by the FNV-1 32-bit hash of its
lower-case name. This probe hashes the names given (default: the throw payload and a few WWED names, with and without
"WwiseEvent_" / "Play_") and finds the banks holding an event of that id, and shows how bank file names relate to their
bank ids and events (one bank per event, named by its id, or shared banks) - which decides whether a new event can be
added as a bank of our own.

    python -I scripts\\armor\\wwise_probe.py --sf-data "<Starfield>\\Data" --out C:\\Modding\\work\\sound
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

NAMES = ("WPNGrenadeThrow", "WPNGrenadeThrowSD", "PHY_Metal_Chains_Impact", "WwiseEvent_PHY_Metal_Chains_Impact",
         "QST_UC08_Door_Remote_Unlock", "WwiseEvent_QST_UC08_Door_Remote_Unlock", "UIMenuShipRepairHull")
HIRC_EVENT = 4


def fnv1_32(name: str) -> int:
    """Wwise's short id of a name: FNV-1 32-bit of the lower-case bytes (multiply, then xor)."""
    h = 2166136261
    for b in name.lower().encode("utf-8"):
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= b
    return h


def chunks(b: bytes):
    """[(tag, start, end)] of a .bnk's top-level chunks."""
    out, p = [], 0
    while p + 8 <= len(b):
        tag, n = b[p:p + 4], struct.unpack_from("<I", b, p + 4)[0]
        if not tag.isalnum() or p + 8 + n > len(b):
            break
        out.append((tag.decode("latin-1"), p + 8, p + 8 + n))
        p += 8 + n
    return out


def parse_bank(b: bytes) -> dict:
    """{version, bank_id, chunks, objects: Counter of HIRC types, events: [ids], media: n} of a .bnk."""
    info = {"version": None, "bank_id": None, "chunks": [], "objects": collections.Counter(), "events": [], "media": 0}
    for tag, s, e in chunks(b):
        info["chunks"].append(tag)
        if tag == "BKHD" and e - s >= 8:
            info["version"], info["bank_id"] = struct.unpack_from("<II", b, s)
        elif tag == "DIDX":
            info["media"] = (e - s) // 12
        elif tag == "HIRC" and e - s >= 4:
            n, = struct.unpack_from("<I", b, s)
            p = s + 4
            for _ in range(n):
                if p + 9 > e:
                    break
                t, size, oid = struct.unpack_from("<BII", b, p)
                info["objects"][t] += 1
                if t == HIRC_EVENT:
                    info["events"].append(oid)
                p += 5 + size
    return info


def sound_archives(sf_data):
    from fo4sf import ba2
    out = []
    for fn in sorted(os.listdir(sf_data)):
        if fn.lower().endswith(".ba2") and re.search(r"sound|wwise|voice", fn, re.I) and "voices_" not in fn.lower():
            try:
                out.append(ba2.Ba2(os.path.join(sf_data, fn)))
            except Exception as e:                         # noqa: BLE001
                print(f"  {fn}: not read ({e})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", action="append", default=[], help="more event names to look for")
    ap.add_argument("--max-banks", type=int, default=0, help="parse at most this many banks (0: all)")
    a = ap.parse_args(argv)
    names = list(NAMES) + a.name
    names += [n[len("WwiseEvent_"):] for n in a.name if n.startswith("WwiseEvent_")]
    names += ["Play_" + n for n in list(names)]
    want = {fnv1_32(n): n for n in names}
    rep = {"archives": [], "extensions": {}, "other_files": [], "banks_parsed": 0, "found": {}, "bank_samples": [],
           "name_is_bank_id": 0, "name_is_an_event": 0, "numeric_names": 0, "events_per_bank": {},
           "hashes": {n: f"{fnv1_32(n)}" for n in names}}
    exts = collections.Counter()
    per_bank = collections.Counter()
    done = 0
    for arc in sound_archives(a.sf_data):
        rep["archives"].append(f"{os.path.basename(arc.path)}: {len(arc.names)} files")
        for i, nm in enumerate(arc.names):
            ext = os.path.splitext(nm)[1].lower()
            exts[ext] += 1
            if ext not in (".bnk", ".wem") and len(rep["other_files"]) < 60:
                rep["other_files"].append(nm)
            if ext != ".bnk" or (a.max_banks and done >= a.max_banks):
                continue
            try:
                info = parse_bank(arc.read(i))
            except Exception as e:                         # noqa: BLE001
                rep.setdefault("errors", []).append(f"{nm}: {e}")
                continue
            done += 1
            stem = os.path.splitext(os.path.basename(nm))[0]
            num = int(stem) if stem.isdigit() else None
            rep["numeric_names"] += num is not None
            rep["name_is_bank_id"] += num is not None and num == info["bank_id"]
            rep["name_is_an_event"] += num is not None and num in info["events"]
            per_bank[min(len(info["events"]), 10)] += 1
            if len(rep["bank_samples"]) < 25:
                rep["bank_samples"].append({"file": nm, "version": info["version"], "bank_id": info["bank_id"],
                                            "chunks": info["chunks"], "hirc": dict(info["objects"]),
                                            "events": info["events"][:8], "media": info["media"]})
            for ev in info["events"]:
                if ev in want:
                    rep["found"].setdefault(want[ev], []).append({"file": nm, "bank_id": info["bank_id"],
                                                                  "events_in_bank": len(info["events"])})
    rep["banks_parsed"] = done
    rep["extensions"] = dict(exts.most_common())
    rep["events_per_bank"] = {("10+" if k == 10 else str(k)): v for k, v in sorted(per_bank.items())}
    rep["not_found"] = [n for n in names if n not in rep["found"]]
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "wwise_probe.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{done} banks parsed; files: {rep['extensions']}")
    print(f"bank file named by its bank id: {rep['name_is_bank_id']} of {rep['numeric_names']} numeric names; "
          f"named by an event it holds: {rep['name_is_an_event']}")
    print(f"events per bank: {rep['events_per_bank']}")
    for n, hits in rep["found"].items():
        print(f"  {n} ({fnv1_32(n)}): {hits[:3]}")
    print(f"not found: {', '.join(rep['not_found'])}")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
