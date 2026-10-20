"""Skyrim (SE / LE human, 99 animated bones of skeleton.hkx) -> Starfield human skeleton (116 nodes of
characterassets\\skeleton.nif) bone correspondence, for retargeting animations and re-rigging armor.

Built 2026-10-19 from BodySlide 6.0's reference skeletons (res\\skeleton_male_sse.nif, res\\skeleton_male_sf.nif; read
from the owner's upload, not committed) and Skyrim's skeleton.hkx bone list (PyNifly's test copy). Both rest poses are
A-poses of nearly the same size (head: Skyrim 1.72 m, Starfield 1.63 m; hands about 1.03 m high, 0.41 / 0.47 m out).
scripts/armor/bone_map_report.py prints each pair's rest positions and segment lengths: the check of this table.

Kinds of entry:
  MAP        one Skyrim bone drives one Starfield bone
  SPLIT      one Skyrim bone's rotation is shared by a chain of Starfield bones (Skyrim has 3 spine bones, Starfield 4)
  DERIVED    a Starfield bone with no Skyrim source follows a mapped neighbour (twist bones, knees, mass helpers)
  WORLD      a Starfield bone whose WORLD transform must equal a Skyrim bone's (Starfield's WEAPON / WeaponLeft hang
             off C_Chest and the hands reach them through R_HandIk / L_HandIk; in Skyrim, Weapon / Shield hang off the
             hands), so it is solved per frame, not copied
Skyrim bones with no Starfield counterpart are listed in UNMAPPED with the reason (skirt chains, sheath / quiver
nodes, magic nodes: those become attachment / effect points, not animated bones).
Supported hypothesis until a retargeted clip plays in game: the SPLIT weights, the twist assignments.
"""
from typing import Dict, List, Tuple

SIDES = (("L", "L"), ("R", "R"))

MAP: Dict[str, str] = {
    "NPC Root [Root]": "Root",
    "NPC COM [COM ]": "COM",
    "NPC Pelvis [Pelv]": "C_Hips",
    "NPC Spine [Spn0]": "C_Spine",
    "NPC Spine2 [Spn2]": "C_Chest",
    "NPC Neck [Neck]": "C_Neck",
    "NPC Head [Head]": "C_Head",
    "AnimObjectA": "AnimObjectA",
    "AnimObjectB": "AnimObjectB",
    "Camera Control": "Camera Control",
}
_LIMBS = [  # Skyrim name pattern (side letter as {s}), Starfield name pattern
    ("NPC {s} Thigh [{s}Thg]", "{s}_Thigh"),
    ("NPC {s} Calf [{s}Clf]", "{s}_Calf"),
    ("NPC {s} Foot [{s}ft ]", "{s}_Foot"),
    ("NPC {s} Toe0 [{s}Toe]", "{s}_Toe"),
    ("NPC {s} Clavicle [{s}Clv]", "{s}_Clavicle"),
    ("NPC {s} UpperArm [{s}Uar]", "{s}_Biceps"),
    ("NPC {s} UpperarmTwist1 [{s}Ut1]", "{s}_Biceps_Twist"),
    ("NPC {s} UpperarmTwist2 [{s}Ut2]", "{s}_Biceps_Twist1"),
    ("NPC {s} Forearm [{s}Lar]", "{s}_Forearm"),
    ("NPC {s} ForearmTwist2 [{s}Lt2]", "{s}_Wrist_Twist"),
    ("NPC {s} ForearmTwist1 [{s}Lt1]", "{s}_Wrist_Twist1"),
    ("NPC {s} Hand [{s}Hnd]", "{s}_Wrist"),
    ("AnimObject{s}", "{s}_AnimObject1"),
]
_FINGERS = [("0", "Thumb"), ("1", "Index"), ("2", "Middle"), ("3", "Ring"), ("4", "Pinky")]
for s, _ in SIDES:
    for a, b in _LIMBS:
        MAP[a.format(s=s)] = b.format(s=s)
    for digit, finger in _FINGERS:
        for j, suffix in enumerate(("", "1", "2")):
            MAP[f"NPC {s} Finger{digit}{j} [{s}F{digit}{j}]"] = f"{s}_{finger}{suffix}"

# Skyrim's Spine1 rotation shared by Starfield's C_Spine1 and C_Spine2 (Skyrim Spine1 at 1.16 m sits between them:
# Starfield 1.11 / 1.17 m); weights sum to 1 (applied as slerp fractions of the rotation).
SPLIT: Dict[str, List[Tuple[str, float]]] = {
    "NPC Spine1 [Spn1]": [("C_Spine1", 0.5), ("C_Spine2", 0.5)],
}

# Starfield bone -> (source Starfield bone it copies, what it copies). Twist bones copy a fraction of the twist.
DERIVED: Dict[str, Tuple[str, str]] = {"C_Neck1": ("C_Neck", "rest"), "C_Neck_Twist": ("C_Neck", "rest"),
                                       "DirectAt": ("C_Chest", "rest")}
for s, _ in SIDES:
    DERIVED.update({
        f"{s}_Knee": (f"{s}_Calf", "follow"), f"{s}_CalfMass": (f"{s}_Calf", "rest"),
        f"{s}_Thigh_Twist": (f"{s}_Thigh", "rest"), f"{s}_Thigh_Twist1": (f"{s}_Thigh", "rest"),
        f"{s}_Elbow": (f"{s}_Forearm", "follow"),
        f"{s}_Wrist_Twist2": (f"{s}_Wrist_Twist1", "twist"), f"{s}_Arm": (f"{s}_Wrist", "follow"),
        f"{s}_Cup": (f"{s}_Wrist", "rest"), f"{s}_Butt": ("C_Hips", "rest"),
        f"{s}_ArmMass": (f"{s}_Biceps_Twist", "rest"), f"{s}_Deltoid": (f"{s}_Biceps_Twist", "rest"),
    })

# Starfield nodes no Skyrim clip drives: left at their rest pose (cameras, eyes, backpack, controller, spare
# animation-object slots).
REST = ("", "HumanExportRoot", "CharacterBumper", "CharacterController", "Camera", "Camera Control FP",
        "CamTargetParent", "CameraTarget", "Eye_Target", "L_Eye", "R_Eye", "C_BackPack", "C_BackPackHose",
        "AnimObjectC", "AnimObjectD", "L_AnimObject2", "L_AnimObject3", "R_AnimObject2", "R_AnimObject3")

# Bones vanilla human clips keep at their rest rotation in character space, letting the bones below carry the turn
# (verified 2026-10-19: within 0.7 deg on every frame of the vanilla one-handed ready idle, attacks and the chair idle).
# DirectAt (under C_Chest) is the "Source Bone" of the melee graph's Dual Direct At node, which turns chest and head
# toward the camera's aim by the angle between DirectAt and the aim: a DirectAt that turns with the chest (up to 100 deg
# in a Skyrim swing) makes that node fight the swing, and only while the camera aims (not in TFC). COM: the same
# convention (the body turn lives in C_Hips / C_Spine); its child C_Waist, never animated, then stays put too.
HOLD_REST_ROTATION = ("COM", "DirectAt")

# Bones vanilla melee clips set to another bone's world transform. R_AnimObject3 (under R_Wrist) equals the Weapon bone
# (within 1 mm / 0.4 deg) on every frame of every vanilla one-handed combat clip checked: attacks, ready and block idles,
# equip / unequip, jumps, casts (verified 2026-10-19; relaxed and furniture clips do not). Left at rest the weapon sat
# on the wrist bone once in combat (owner: aligned when drawn, "all weird" once attacking). Applied to clips converted
# with hkx_to_af --weapon-in-hand, which then also give R_AnimObject3 a track.
WEAPON_FOLLOWERS: Dict[str, str] = {"R_AnimObject3": "Weapon"}

# Bones vanilla human clips never animate (verified 2026-10-19 on the vanilla chair Idle and sword attacks: their tracks
# are absent): the game drives the cameras, prop slots, eye target and helpers itself. A converted clip must leave them
# out too: a track on Camera / Camera Control tilts the third-person camera into the floor (owner, in game). Root is
# only animated for root motion (vanilla attacks move it forward each frame).
NOT_ANIMATED = ("Camera", "Camera Control", "Camera Control FP", "CamTargetParent", "CameraTarget", "Eye_Target",
                "AnimObjectA", "AnimObjectB", "AnimObjectC", "AnimObjectD", "L_AnimObject1", "L_AnimObject2",
                "L_AnimObject3", "R_AnimObject1", "R_AnimObject2", "R_AnimObject3", "L_Arm", "R_Arm", "C_Waist", "Root")

# Weapon grip, copied from vanilla Starfield clips (verified 2026-10-19: in the player's sword and generic one-handed
# MeleeAttack_A the Weapon bone sits rigidly in R_Wrist's frame at this offset (metres) / rotation (x, y, z, w) on every
# frame; R_HandIk coincides with R_Wrist). Converted clips place Weapon the same way, so a Starfield weapon sits in the
# hand as in vanilla (Skyrim's WEAPON offset put the blade ~16 degrees off and 1.7 cm out of the fist).
GRIP: Dict[str, Tuple[str, Tuple[float, float, float], Tuple[float, float, float, float]]] = {
    "weapon": ("R_Wrist", (0.068, 0.011, -0.038), (0.499, 0.375, 0.519, -0.583)),
}
# Weapon orientation taken from Skyrim's weapon node instead of the grip: Starfield weapon models run along the
# Weapon bone's +Z, Skyrim's along +Y (supported: the vanilla sword hit frame swings the bone's +Z forward-left, the
# Skyrim ready idle holds +Y forward-up; measured on our retarget the other axes map x_sf = -z_sk, y_sf = -x_sk, within
# 20 deg of the vanilla grip). With retarget(weapon_in_hand=True) the gripping hand is turned so that hand * GRIP =
# Skyrim Weapon world * WEAPON_AXES: the blade points and faces exactly as in Skyrim and stays in the fist. (Setting the
# weapon itself to that orientation, 2026-10-19, turned the hilt ~22 deg out of the fist in game.)
WEAPON_AXES: Dict[str, Tuple[str, Tuple[float, float, float, float]]] = {"weapon": ("Weapon", (0.5, -0.5, -0.5, -0.5))}
# Dual wield (retarget(left_weapon=True)): Skyrim hangs the left weapon rigidly off the Shield node (verified 2026-10-20
# on Nordic Combat Animations' dual-sword clips: Shield is fixed in the left hand on every frame, as Weapon is in the
# right). LEFT_GRIP is the right grip mirrored onto L_Wrist (retarget.mirror_grip against the Starfield skeleton NIF's
# rest wrists; the two wrists' local axes are not mirror images, the fixed turn is taken out): at rest the left weapon
# is the exact mirror of the right. LEFT_WEAPON_AXES makes the left weapon Skyrim's Shield frame turned about the blade
# so that, at rest, it is the mirror of the right weapon (Shield's +Y, the blade, already is the mirrored Weapon +Y;
# its other axes are rolled about 150 deg, which would twist the left wrist that far if followed).
LEFT_GRIP: Dict[str, Tuple[str, Tuple[float, float, float], Tuple[float, float, float, float]]] = {
    "weaponleft": ("L_Wrist", (0.068, -0.011, -0.038), (-0.3752, -0.4993, 0.5833, -0.5193)),
}
LEFT_WEAPON_AXES: Dict[str, Tuple[str, Tuple[float, float, float, float]]] = {
    "weaponleft": ("Shield", (0.5792, 0.4057, 0.4055, -0.5793)),
}
# Hand-over (retarget): a Skyrim weapon node more than the first value (game units) away from where it sits in its hand
# starts to follow Skyrim's weapon node instead of the grip, fully past the second (Nordic battleaxe power attacks).
HANDOVER_UNITS = (3.0, 8.0)
# Two-handed grip (retarget(two_hand_grip=True)): the support hand's Skyrim bone and the Starfield arm the IK turns
SUPPORT_HAND_SKYRIM = "NPC L Hand [LHnd]"
# the support hand counts as on the haft up to the first distance (game units, from the weapon's +Y axis) and as let go
# from the second (Nordic: 2-9 units on the grip; the greatsword's power attack 3 lets go, up to 74)
SUPPORT_ON_GRIP_UNITS = (10.0, 16.0)
SUPPORT_ARM = ("L_Biceps", "L_Forearm", "L_Wrist")
# IK targets kept on the hands they belong to (the IK pass then changes nothing)
HAND_TARGETS: Dict[str, str] = {"r_handik": "R_Wrist", "l_handik": "L_Wrist"}
# Skyrim bones with several mapped children: the child whose direction aligns the bone (see retarget)
DIRECTION_CHILD: Dict[str, str] = {}
for _s in "LR":
    DIRECTION_CHILD.update({f"NPC {_s} Hand [{_s}Hnd]": f"NPC {_s} Finger20 [{_s}F20]",
                            f"NPC {_s} UpperArm [{_s}Uar]": f"NPC {_s} Forearm [{_s}Lar]",
                            f"NPC {_s} Forearm [{_s}Lar]": f"NPC {_s} Hand [{_s}Hnd]"})
# Bones whose roll (twist about their direction) is aligned too, by a second pair of Skyrim joints: the hands, by the
# line across the knuckles (index -> pinky base), 13.5 degrees apart in the two rest poses
ROLL_REF: Dict[str, Tuple[str, str]] = {f"NPC {_s} Hand [{_s}Hnd]": (f"NPC {_s} Finger10 [{_s}F10]",
                                                                    f"NPC {_s} Finger40 [{_s}F40]") for _s in "LR"}
NO_ALIGN = ("NPC Root [Root]", "NPC COM [COM ]", "NPC Pelvis [Pelv]", "NPC Spine [Spn0]", "NPC Spine1 [Spn1]",
            "NPC Spine2 [Spn2]", "NPC Neck [Neck]", "NPC Head [Head]")

WORLD: Dict[str, str] = {"WEAPON": "Weapon", "WeaponLeft": "Shield",
                         "R_HandIk": "NPC R Hand [RHnd]", "L_HandIk": "NPC L Hand [LHnd]"}

UNMAPPED: Dict[str, str] = {
    "x_NPC LookNode [Look]": "Skyrim look-at helper; Starfield uses Eye_Target / DirectAt",
    "x_NPC Translate [Pos ]": "Skyrim root-motion helper; becomes Starfield root motion",
    "x_NPC Rotate [Rot ]": "Skyrim root-motion helper; becomes Starfield root motion",
    "NPCEyeBone": "eye; Starfield eyes are driven by face animation",
    "NPC L Pauldron": "armor helper (shoulder plates follow the clavicle)",
    "NPC R Pauldron": "armor helper (shoulder plates follow the clavicle)",
    "MagicEffectsNode": "effect attachment point",
    "NPC L MagicNode [LMag]": "spell effect attachment (casting): attach to L_Wrist",
    "NPC R MagicNode [RMag]": "spell effect attachment (casting): attach to R_Wrist",
    "NPC Head MagicNode [Hmag]": "shout effect attachment: attach to C_Head",
    "Quiver": "sheathed-gear point", "WeaponAxe": "sheathed-gear point", "WeaponBack": "sheathed-gear point",
    "WeaponBow": "sheathed-gear point", "WeaponDagger": "sheathed-gear point", "WeaponMace": "sheathed-gear point",
    "WeaponSword": "sheathed-gear point", "Camera3rd [Cam3]": "Skyrim camera",
}
for _p in ("R", "L", "B", "F"):
    for _k in ("01", "02", "03"):
        UNMAPPED[f"Skirt{_p}Bone{_k}"] = "skirt / robe chain: no Starfield bones; cloth-like parts are skinned to thighs"

def starfield_of(skyrim_bone: str):
    """The Starfield bone(s) a Skyrim bone drives: [(name, weight)], [] if unmapped."""
    if skyrim_bone in MAP:
        return [(MAP[skyrim_bone], 1.0)]
    return list(SPLIT.get(skyrim_bone, []))


def coverage(skyrim_bones, starfield_bones) -> dict:
    """Which bones of two skeletons the table covers: the check that names in the table exist in the real files."""
    sk, sf = set(skyrim_bones), set(starfield_bones)
    driven = {b for v in MAP.values() for b in [v]} | {b for v in SPLIT.values() for b, _w in v}
    return {
        "skyrim_missing_from_table": sorted(b for b in sk if b not in MAP and b not in SPLIT and b not in UNMAPPED
                                            and b not in WORLD.values()),
        "table_skyrim_not_in_skeleton": sorted(b for b in list(MAP) + list(SPLIT) if b not in sk),
        "table_starfield_not_in_skeleton": sorted(b for b in driven | set(DERIVED) | set(WORLD) if b not in sf),
        "starfield_not_driven": sorted(b for b in sf if b not in driven and b not in DERIVED and b not in WORLD
                                       and b not in REST),
    }
