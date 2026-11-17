"""Our furniture records next to the vanilla ones they copy (read-only): what could keep NPCs from choosing them.

2026-11-16 (owner): Alvor plays the whole forge sequence when forced in (cf "Actor.SnapIntoInteraction"), but never
walks to the forge by himself on his work schedule (two in-game hours after a coc); "something we've done to the
furniture is making it so NPCs can't use it on their schedules". The forced path skips everything the sandbox checks
(record flags, keywords, markers, entry sides, pathing). This prints, for each pair (ours in FO4Port.esm, the vanilla
template in Starfield.esm): the record header flags, every subrecord (signature, size, first bytes), keywords by
EditorID, and the differences: flags set on one only, subrecords on one only or changed. Working pairs (the sweep,
the rail lean) are listed beside the forge and tanning rack for comparison.

    python -I scripts\\interior\\furniture_record_probe.py --plugin "<staging>\\FO4Port.esm" --starfield "<Starfield>"
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

# (ours, vanilla template): the forge and tanning rack (not chosen on schedules) and two that are (sweep, rail lean)
PAIRS = (("S2S_Furn_CraftingBlackSmithForge", "NPCWelder"),
         ("S2S_Furn_CraftingBlacksmithSharpeningWheel", "NPCRepairImpactWrench_Standing"),
         ("S2S_Furn_CraftingBlacksmithArmorWorkbench", "NPCWipeTable"),
         ("S2S_Furn_CraftingTanningRackMarker", "NPCStanding_WipeWall"),
         ("S2S_Furn_SweepIdleMarker", "NPCSweeping"),
         ("S2S_Furn_RailLeanMarker", "NPCLeaningBartopFront"),
         # a real model NPCs do use (owner: "so there's nothing different between the chair being usable and the
         # tanning rack?"): Hilde's chair outside her house
         ("S2S_Furn_CommonChair01F", "FoundCanvasChair01_Free"))


def header_flags(header: bytes) -> int:
    return struct.unpack_from("<I", header, 8)[0]


def flag_bits(v: int) -> list:
    return [f"0x{1 << i:08X}" for i in range(32) if v >> i & 1]


def differences(ours, vanilla) -> list:
    """Lines: header flags only one has, subrecords only one has, subrecords whose data differ (first of each sig)."""
    (oh, osubs), (vh, vsubs) = ours, vanilla
    out = []
    of, vf = header_flags(oh), header_flags(vh)
    only_o, only_v = set(flag_bits(of & ~vf)), set(flag_bits(vf & ~of))
    if only_o or only_v:
        out.append(f"flags: ours only {sorted(only_o) or '-'}, vanilla only {sorted(only_v) or '-'}")
    om, vm = {}, {}
    for s, d in osubs:
        om.setdefault(s, d)
    for s, d in vsubs:
        vm.setdefault(s, d)
    for s in sorted(set(om) | set(vm)):
        if s == b"EDID":
            continue
        if s not in vm:
            out.append(f"{s.decode('latin-1')}: ours only ({len(om[s])} bytes)")
        elif s not in om:
            out.append(f"{s.decode('latin-1')}: vanilla only ({len(vm[s])} bytes)")
        elif om[s] != vm[s]:
            out.append(f"{s.decode('latin-1')}: differs (ours {len(om[s])} / vanilla {len(vm[s])} bytes)")
    return out


def snam(d: bytes) -> list:
    """Starfield FURN SNAM marker parameters, 28 bytes each: offset x/y/z (m), rotation z, keyword, entry, exit."""
    out = []
    for i in range(0, len(d) - 27, 28):
        x, y, z, rz, kw, en, ex = struct.unpack_from("<4fIII", d, i)
        out.append(f"offset ({x:.3f}, {y:.3f}, {z:.3f}) m, rot {rz:.3f} rad, keyword {kw:08X}, entry 0x{en:X}, "
                   f"exit 0x{ex:X}")
    return out


def short2(d: bytes):
    return struct.unpack_from("<h", d)[0] if len(d) >= 2 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plugin", required=True, help="FO4Port.esm (the staged or installed one)")
    ap.add_argument("--starfield", required=True)
    a = ap.parse_args(argv)
    from fo4sf import sfplugin
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    ours = {sfplugin.edid(s): (h, s, fid) for _t, h, s, fid in sfplugin.records(a.plugin, [b"FURN"])}
    want = {v for _o, v in PAIRS}
    vanilla = {}
    kw_names = {}
    for t, h, s, fid in sfplugin.records(esm, [b"FURN", b"KYWD"]):
        e = sfplugin.edid(s)
        if t == b"KYWD":
            kw_names[fid & 0xFFFFFF] = e
        elif e in want:
            vanilla[e] = (h, s, fid)

    def kws(subs):
        return ", ".join(kw_names.get(k & 0xFFFFFF, f"{k:08X}") if k >> 24 == 0 else f"{k:08X}"
                         for k in sfplugin.keywords(subs))

    def dump(name, rec):
        h, subs, fid = rec
        print(f"  {name} {fid:08X}: flags 0x{header_flags(h):08X} {flag_bits(header_flags(h))}")
        print(f"    keywords: {kws(subs)}")
        for s, d in subs:
            print(f"    {s.decode('latin-1')} {len(d)}: {d[:48].hex(' ')}{' ...' if len(d) > 48 else ''}")
            if s == b"SNAM":
                for line in snam(d):
                    print(f"      marker: {line}")
            elif s in (b"JNAM", b"GNAM", b"FNAM"):
                print(f"      = {short2(d)}")
    for o, v in PAIRS:
        print(f"== {o} vs {v}")
        if o not in ours or v not in vanilla:
            print(f"  missing: {'ours ' if o not in ours else ''}{'vanilla' if v not in vanilla else ''}")
            continue
        for line in differences(ours[o][:2], vanilla[v][:2]):
            print("  * " + line)
        dump(o, ours[o])
        dump(v, vanilla[v])
    return 0


if __name__ == "__main__":
    sys.exit(main())
