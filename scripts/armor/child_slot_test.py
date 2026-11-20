"""Which half of our children's clothes hides a child's head in game: the slots or the meshes (a test plugin).

2026-11-20 (owner, in game, verified): Dorthe and Frodnar lose head, hair and neck in our clothes (unequipall brings
it back) - the shoes alone too, whose two parts sit on slot 7; still so with the addons copied from Starfield's own
child outfit (Clothes_Child_CoraCoe_NOTPLAYABLE, slot 3: no morphs, no additional races). What is left: our slots
(7, 5, 13, 10-15; ChildRace names none of them but 5) and our meshes. This writes S2SChildTest.esm, four armors
copied from the Cora Coe outfit, each a single addon:
  S2S_ChildTest_Vanilla       its own mesh, slot 3            (control: the head must stay)
  S2S_ChildTest_VanillaSlot7  its own mesh on slot 7          (head gone: the slot)
  S2S_ChildTest_OursSlot3     our shoes mesh on slot 3        (head gone: the mesh)
  S2S_ChildTest_DressSlot3    our dress mesh on slot 3
Our meshes are read from S2SClothes' archive at run time (keep S2S Clothes enabled). In game: select a child,
`unequipall`, `help S2S_ChildTest 4`, then for each: `additem <id> 1`, `equipitem <id>`, head or not, `unequipall`.

    python -I scripts\\armor\\child_slot_test.py --starfield "<Starfield>" --out "<MO2 mods>\\S2S Child Test"
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import sfplugin  # noqa: E402

PLUGIN = "S2SChildTest.esm"
OURS_SHOES = "S2S\\Items\\ClothesChildrenShoes_F\\shoes.nif"
OURS_DRESS = "S2S\\Items\\ClothesChild01_F\\clothes03.nif"
TESTS = (("Vanilla", None, 3), ("VanillaSlot7", None, 7), ("OursSlot3", OURS_SHOES, 3), ("DressSlot3", OURS_DRESS, 3))


def test_records(recs, tests=TESTS, masters: int = 1):
    """[(type, header, subs, FormID)]: per test an ARMA and an ARMO copied from the Cora Coe child outfit (recs:
    sfplugin.records' shape holding its ARMO and ARMA), the addon on that one slot with that model (None: its own)."""
    import os_export
    by = {sfplugin.edid(s).lower(): (t, h, s, f) for t, h, s, f in recs}
    armo = by.get(os_export.CHILD_TEMPLATE_ARMOR.lower())
    if armo is None:
        raise SystemExit(f"no {os_export.CHILD_TEMPLATE_ARMOR} in Starfield.esm")
    a_fid = next(struct.unpack_from("<I", d)[0] for s, d in armo[2] if s == b"MODL" and len(d) >= 4)
    arma = next(r for r in recs if r[3] == a_fid)
    out, i = [], 0
    for name, model, slot in tests:
        edid = f"S2S_ChildTest_{name}"
        aa_fid, ar_fid = sfplugin.new_form_id(i, masters), sfplugin.new_form_id(i + 1, masters)
        i += 2
        edits = {b"EDID": sfplugin.zs(edid + "_AA"), b"BO64": (1 << slot).to_bytes(8, "little")}
        if model:
            edits[b"MOD2"] = sfplugin.zs(model)
        out.append((b"ARMA", arma[1], sfplugin.edit(list(arma[2]), edits, drop=[b"MOD3"]), aa_fid))
        osubs = []
        for s, d in armo[2]:
            if s == b"MODL" and len(d) >= 4 and struct.unpack_from("<I", d)[0] == a_fid:
                d = struct.pack("<I", aa_fid) + bytes(d)[4:]
            osubs.append((s, d))
        out.append((b"ARMO", armo[1], sfplugin.edit(osubs, {b"EDID": sfplugin.zs(edid),
                                                             b"FULL": sfplugin.zs(f"Child test {name}"),
                                                             b"BO64": (1 << slot).to_bytes(8, "little")}), ar_fid))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sf_esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    recs = test_records(sfplugin.records(sf_esm, [b"ARMO", b"ARMA"]))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, sfplugin.header_info(sf_esm), author="Skyrim2Starfield child test"))
    for t, _h, s, fid in recs:
        if t == b"ARMO":
            print(f"{sfplugin.edid(s)}: xx{fid & 0xFFFFFF:06X}")
    print(f"-> {os.path.join(a.out, PLUGIN)} (enable 'S2S Child Test' in MO2, below S2S Clothes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
