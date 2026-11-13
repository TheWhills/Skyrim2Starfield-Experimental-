"""S2STimeSync.esm: one start-game-enabled quest running S2S_LocalTimeSync (scripts/terrain/papyrus), which keeps
Nirn's local time (the sun) equal to the game hour that NPC schedules use (2026-11-13; docs/terrain/skyrim-tamriel.md
"Day length, tilt and the sun").

    python -I scripts\\terrain\\time_sync.py --starfield $sf --out "$mods\\S2S Time Sync"

The quest is a copy of the vanilla DialogueGeneric (as npc_voice.py's, which the game runs: EDID, FULL, DNAM, its
conditions and script dropped) with the Start Game Enabled flag set and a script block (VMAD) naming our script. The
VMAD is built from a vanilla quest that has exactly one script with no properties: its header and everything after
that script (the quest's fragment / alias part) are kept, only the script name is ours, so the layout is the game's
own (the shortest such tail is taken: no fragments, no aliases). The .pex is compiled by tools\\owner\\time_sync.ps1
with the Creation Kit's Papyrus compiler.
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))

from fo4sf import sfplugin  # noqa: E402

PLUGIN = "S2STimeSync.esm"
SCRIPT = "S2S_LocalTimeSync"
QUEST_TEMPLATE = "DialogueGeneric"
START_GAME_ENABLED = 0x0001          # QUST DNAM u16 flags, bit 0 (Skyrim / Fallout 4 layout, Starfield keeps it)


def wstr(text: str) -> bytes:
    b = text.encode("latin-1")
    return struct.pack("<H", len(b)) + b


def one_script_vmad(vmad: bytes):
    """(header 6 bytes, script name, status flags u8, tail) of a VMAD holding exactly one script with no
    properties, else None."""
    if len(vmad) < 6:
        return None
    _ver, _fmt, count = struct.unpack_from("<hhH", vmad, 0)
    if count != 1:
        return None
    n, = struct.unpack_from("<H", vmad, 6)
    if 8 + n + 3 > len(vmad):
        return None
    name = vmad[8:8 + n].decode("latin-1")
    flags = vmad[8 + n]
    props, = struct.unpack_from("<H", vmad, 9 + n)
    if props != 0:
        return None
    return vmad[:6], name, flags, vmad[11 + n:]


def vmad_template(quests):
    """The vanilla quest VMAD to build ours from: one script, no properties, the shortest tail. (edid, parts)."""
    best = None
    for _t, _h, subs, _f in quests:
        vm = next((d for s, d in subs if s == b"VMAD"), None)
        parts = one_script_vmad(vm) if vm else None
        if parts and (best is None or len(parts[3]) < len(best[1][3])):
            best = (sfplugin.edid(subs), parts)
    return best


def our_vmad(parts, script: str = SCRIPT) -> bytes:
    head, _name, flags, tail = parts
    return head + wstr(script) + bytes([flags]) + struct.pack("<H", 0) + tail


def sync_quest(template, vmad: bytes, fid: int):
    """The quest record: the template's subrecords (conditions, script, filters dropped), our EDID / FULL / VMAD,
    DNAM flags with Start Game Enabled."""
    _t, h, subs, _f = template
    out = sfplugin.edit(subs, {b"EDID": sfplugin.zs("S2S_LocalTimeSync"), b"FULL": sfplugin.zs("S2S local time sync")},
                        drop=(b"CTDA", b"VMAD", b"FLTR"))
    dn = next((i for i, (s, _d) in enumerate(out) if s == b"DNAM"), None)
    if dn is None or len(out[dn][1]) < 2:
        raise SystemExit(f"{QUEST_TEMPLATE}: no DNAM flags")
    d = bytearray(out[dn][1])
    struct.pack_into("<H", d, 0, struct.unpack_from("<H", d, 0)[0] | START_GAME_ENABLED)
    out[dn] = (b"DNAM", bytes(d))
    at = next(i + 1 for i, (s, _d) in enumerate(out) if s == b"EDID")
    out.insert(at, (b"VMAD", vmad))
    return (b"QUST", h, out, fid)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True, help="Starfield's folder (holds Data)")
    ap.add_argument("--out", required=True, help="the mod folder (MO2) to write S2STimeSync.esm into")
    a = ap.parse_args(argv)
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    quests = sfplugin.records(esm, [b"QUST"])
    template = next((q for q in quests if sfplugin.edid(q[2]) == QUEST_TEMPLATE), None)
    if template is None:
        raise SystemExit(f"{QUEST_TEMPLATE} not in Starfield.esm")
    vt = vmad_template(quests)
    if vt is None:
        raise SystemExit("no vanilla quest with one script and no properties to copy the script block from")
    rec = sync_quest(template, our_vmad(vt[1]), sfplugin.new_form_id(0))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build([rec], sfplugin.header_info(esm)))
    rep = {"plugin": PLUGIN, "quest": f"{rec[3]:08X}", "script": SCRIPT, "quest_template": QUEST_TEMPLATE,
           "vmad_from": vt[0], "vmad_template_script": vt[1][1], "vmad_tail_bytes": len(vt[1][3])}
    with open(os.path.join(a.out, "time_sync.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{os.path.join(a.out, PLUGIN)}: quest S2S_LocalTimeSync {rec[3]:08X} (script block from {vt[0]}: "
          f"{vt[1][1]}, {len(vt[1][3])} bytes after the script)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
