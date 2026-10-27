"""Skyrim weapon models -> Starfield weapon models: the geometry moved into the Starfield WEAPON bone's frame.

A Skyrim weapon .nif is drawn in the Skyrim Weapon node's frame (the blade along +Y). Converted clips place Starfield's
WEAPON bone so that it points as Skyrim's Weapon node does, turned by skeletonmap.WEAPON_AXES (Starfield weapon
models run along +Z), and hold it at the vanilla Starfield grip (skeletonmap.GRIP, relative to R_Wrist). So a model
converted for those clips is: rotated by WEAPON_AXES^-1 (Skyrim +Y -> +Z) and shifted so that the point where
Skyrim's hand sits on the weapon lands where Starfield's wrist sits on its WEAPON bone. Then the handle is in the fist
and the blade points as in Skyrim, with the clips this repo converts.

Where Skyrim's hand sits on the weapon (verified 2026-10-20): the skeleton's rest Weapon node puts the hand (wrist
joint) at (7.16, 0, -2.43) units in the Weapon frame; Nordic Combat Animations' clips at (7.01, -0.85, -3.26) and
vanilla 1hm clips within about 1 cm of these; the rest value is used. The scabbard of one-handed weapons is part of
the same .nif under a node named "Scb" (shown only when sheathed): it is left out here (supported hypothesis on the
node name, from Skyrim modding practice; the converter reports which shapes it dropped).
"""
import dataclasses
import math
import re
from typing import Dict, List, Optional, Tuple

from . import nif as nifmod, skeletonmap as M, skyrimnif

UNIT = 1.0 / 70.0                          # metres per Skyrim unit, as skyrimconvert
SCABBARD = re.compile(rb"^scb", re.I)

# The iron set: one of each Skyrim melee weapon type (owner request 2026-10-20), with the Skyrim.esm EditorIDs read for
# the model path and stats, the vanilla model paths as fallback, and the Nordic Combat Animations pack to test it with.
IRON_SET: List[Dict] = [
    {"key": "dagger", "edid": "IronDagger", "model": r"weapons\iron\dagger.nif", "name": "Iron Dagger", "pack": "dagger"},
    {"key": "sword", "edid": "IronSword", "model": r"weapons\iron\longsword.nif", "name": "Iron Sword", "pack": "1h_sword"},
    {"key": "waraxe", "edid": "IronWarAxe", "model": r"weapons\iron\waraxe.nif", "name": "Iron War Axe", "pack": "waraxe"},
    {"key": "mace", "edid": "IronMace", "model": r"weapons\iron\mace.nif", "name": "Iron Mace", "pack": "mace"},
    {"key": "greatsword", "edid": "IronGreatsword", "model": r"weapons\iron\greatsword.nif", "name": "Iron Greatsword",
     "pack": "greatsword"},
    {"key": "battleaxe", "edid": "IronBattleaxe", "model": r"weapons\iron\battleaxe.nif", "name": "Iron Battleaxe",
     "pack": "battleaxe"},
    {"key": "warhammer", "edid": "IronWarhammer", "model": r"weapons\iron\warhammer.nif", "name": "Iron Warhammer",
     "pack": "battleaxe"},
]


def _qrot(q, v):
    x, y, z, w = q
    ux, uy, uz = x, y, z
    cx = uy * v[2] - uz * v[1] + w * v[0]
    cy = uz * v[0] - ux * v[2] + w * v[1]
    cz = ux * v[1] - uy * v[0] + w * v[2]
    return (v[0] + 2 * (uy * cz - uz * cy), v[1] + 2 * (uz * cx - ux * cz), v[2] + 2 * (ux * cy - uy * cx))


def _qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def _norm(q):
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def weapon_frame() -> Tuple[tuple, tuple]:
    """(row-major 3x3 rotation, translation in Skyrim units) taking a point in Skyrim's Weapon frame (units) to
    Starfield's WEAPON frame (still in units; skyrimconvert scales by UNIT afterwards)."""
    a = _norm(M.WEAPON_AXES["weapon"][1])
    ai = _qinv(a)
    cols = [_qrot(ai, e) for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    rot = tuple(cols[c][r] for r in range(3) for c in range(3))           # row-major
    _h, gt, gq = M.GRIP["weapon"]
    wrist_sf = _qrot(_qinv(_norm(gq)), gt)
    wrist_sf = tuple(-c / UNIT for c in wrist_sf)                         # Starfield wrist in WEAPON frame, units
    hand_sk = M.SKYRIM_HAND_IN_WEAPON
    moved = tuple(sum(rot[3 * r + c] * hand_sk[c] for c in range(3)) for r in range(3))
    return rot, tuple(wrist_sf[i] - moved[i] for i in range(3))


def left_weapon_frame() -> Tuple[tuple, tuple]:
    """As weapon_frame, for a weapon in the left hand, into the frame of Starfield's WeaponLeft bone and in metres
    there (worn models are skinned to WeaponLeft with an identity bind, so their vertices are bone-local): Skyrim draws
    left-hand weapons in its Shield node's frame; WeaponLeft = Shield * LEFT_WEAPON_AXES (the clips converted with
    --left-weapon), held at LEFT_GRIP (the mirrored right grip). Returns (rotation row-major, translation in Skyrim
    units: skyrimconvert scales by UNIT afterwards)."""
    a = _norm(M.LEFT_WEAPON_AXES["weaponleft"][1])
    ai = _qinv(a)
    cols = [_qrot(ai, e) for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    rot = tuple(cols[c][r] for r in range(3) for c in range(3))
    _h, gt, gq = M.LEFT_GRIP["weaponleft"]
    wrist_sf = _qrot(_qinv(_norm(gq)), gt)
    wrist_sf = tuple(-c / UNIT for c in wrist_sf)
    hand_sk = M.SKYRIM_HAND_IN_SHIELD
    moved = tuple(sum(rot[3 * r + c] * hand_sk[c] for c in range(3)) for r in range(3))
    return rot, tuple(wrist_sf[i] - moved[i] for i in range(3))


def left_wrist_frame() -> Tuple[tuple, tuple]:
    """As left_weapon_frame, into L_Wrist's frame instead (WeaponLeft held at its rest grip LEFT_GRIP on the wrist): a
    blade skinned to L_Wrist stays in the left hand in every clip, also the vanilla idles / walks / blocks where
    WeaponLeft is not in the hand (owner's run 2026-10-26: the left blade hung at the hip outside the dual attacks).
    In the clips converted with --left-weapon WeaponLeft sits at this grip, so the attacks look the same."""
    rot, trans = left_weapon_frame()
    _h, gt, gq = M.LEFT_GRIP["weaponleft"]
    q = _norm(gq)
    cols = [_qrot(q, e) for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    g = tuple(cols[c][r] for r in range(3) for c in range(3))
    rot2 = _matmul(g, rot)
    moved = tuple(sum(g[3 * r + c] * trans[c] for c in range(3)) for r in range(3))
    return rot2, tuple(moved[i] + gt[i] / UNIT for i in range(3))


def left_wrist_shapes(n: nifmod.NifFile, shapes: List[nifmod.Fo4Shape], report: Optional[dict] = None):
    """The drawn-weapon shapes in L_Wrist's frame (see left_wrist_frame)."""
    scb = scabbard_blocks(n)
    kept = [s for s in shapes if s.block not in scb and not SCABBARD.match(s.name or b"")]
    if report is not None:
        report["scabbard_shapes_dropped"] = len(shapes) - len(kept)
    rot, trans = left_wrist_frame()
    return [to_weapon_frame(s, rot, trans) for s in kept]


def left_weapon_shapes(n: nifmod.NifFile, shapes: List[nifmod.Fo4Shape], report: Optional[dict] = None):
    """The drawn-weapon shapes (scabbard left out) in WeaponLeft's frame: the left blade of a dual-wield pair."""
    scb = scabbard_blocks(n)
    kept = [s for s in shapes if s.block not in scb and not SCABBARD.match(s.name or b"")]
    if report is not None:
        report["scabbard_shapes_dropped"] = len(shapes) - len(kept)
    rot, trans = left_weapon_frame()
    return [to_weapon_frame(s, rot, trans) for s in kept]


def _matmul(a, b):
    return tuple(sum(a[3 * r + k] * b[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))


def to_weapon_frame(shape: nifmod.Fo4Shape, rot=None, trans=None) -> nifmod.Fo4Shape:
    """The shape with its world transform composed with weapon_frame() (geometry and normals move together)."""
    if rot is None:
        rot, trans = weapon_frame()
    t = shape.translation
    new_t = tuple(sum(rot[3 * r + c] * t[c] for c in range(3)) + trans[r] for r in range(3))
    return dataclasses.replace(shape, rotation=_matmul(rot, shape.rotation), translation=new_t)


def scabbard_blocks(n: nifmod.NifFile) -> set:
    """Blocks under a node whose name starts with "Scb" (the sheath of one-handed Skyrim weapons)."""
    out = set()
    for i, blk in enumerate(n.blocks):
        if n.type_of(i).endswith("Node") and SCABBARD.match(skyrimnif._name(n, blk) or b""):
            out |= nifmod.descendants(n, i)
    return out


def weapon_shapes(n: nifmod.NifFile, shapes: List[nifmod.Fo4Shape], report: Optional[dict] = None):
    """The drawn-weapon shapes (scabbard left out), moved into Starfield's WEAPON frame."""
    scb = scabbard_blocks(n)
    kept = [s for s in shapes if s.block not in scb and not SCABBARD.match(s.name or b"")]
    if report is not None:
        report["scabbard_shapes_dropped"] = len(shapes) - len(kept)
    rot, trans = weapon_frame()
    return [to_weapon_frame(s, rot, trans) for s in kept]


def skyrim_weapon_stats(subs) -> Dict:
    """Model path and the stats worth carrying over from a Skyrim WEAP record's subrecords (wbDefinitionsTES5:
    DATA = value u32, weight f32, damage u16; DNAM = animation type u8, ..., speed f32 @4, reach f32 @8)."""
    import struct
    out = {}
    for s, d in subs:
        d = bytes(d)
        if s == b"MODL":
            out["model"] = d.rstrip(b"\0").decode("latin-1")
        elif s == b"EDID":
            out["edid"] = d.rstrip(b"\0").decode("latin-1")
        elif s == b"DATA" and len(d) >= 10:
            out["value"], out["weight"], out["damage"] = struct.unpack_from("<IfH", d, 0)
        elif s == b"DNAM" and len(d) >= 12:
            out["anim_type"] = d[0]
            out["speed"], out["reach"] = struct.unpack_from("<ff", d, 4)
    return out
