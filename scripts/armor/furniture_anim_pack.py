"""Skyrim's own furniture animations for our furniture (docs/npc/furniture.md "Animations"): converts each set's Skyrim
clips with hkx_to_af (decode, retarget onto Starfield's human rig, .af + .afx through CALUMI) into the set's own folder,
under the file names and tags of the vanilla Starfield furniture clips (their descriptors as templates). The folder is
put first, for furniture carrying the set's keyword, by S2SStances.esm (stance_plugin.FURNITURE_SETS) - tags it lacks
fall back to Starfield's.

Sets (mapping from the owner's furniture_anim_survey, 2026-11-13 / 14: the tags the templates' folders have; the
Skyrim clips are the ones Skyrim's mt_behavior plays for that furniture), each in actors\\human\\animations\\furniture\\:
  Sit (chairs, benches) s2s_sit; RailLean, WallLean, Counter, LeanTable, Sweep, Alchemy, Enchant, Cook, Tanning
  (s2s_<name>); make_furniture.ANIM_SET_RULES says which Skyrim furniture gets which.

One offset per set: the Idle is converted first with --align-com (its mean COM moved onto the vanilla template Idle's),
and that shift is then applied to every clip of the set, so entering, idling and leaving line up; measured offsets are
kept in COM_SHIFT.
No root motion: Starfield's own furniture clips carry the body's way into the seat themselves (supported hypothesis).

    python -I scripts\\armor\\furniture_anim_pack.py --calumi "<CALUMI.Animation.dll>" --skyrim-data "$sky"
        --starfield $sf --out "$mods\\S2S Furniture Anims" --work C:\\Modding\\work\\furniture_anim_pack

Writes <out>\\meshes\\actors\\human\\animations\\furniture\\<set folder>\\*.af / .afx (a loose-file mod for MO2) and
<work>\\furniture_anim_pack.json. New folder: run the Creation Kit's -GenerateAnimInfo afterwards, as for the stances.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

SKY_ANIM = "meshes\\actors\\character\\animations\\"
SF_ANIM = "meshes\\actors\\human\\animations\\"

# set -> (folder under meshes\, vanilla template folder under meshes\, [(vanilla .afx file, Skyrim clip, new tag/None)])
# new tag: a tag the template folder lacks (written under its own name, the given template's descriptor reused).
def standing_set(folder, template, idle, flavors=(), enter=None, exit_=None, n_flavors=0, instant=False):
    """Rows for a set built on one idle loop: Idle, every Idle_FlavorNN slot the template folder has (n_flavors) filled
    from `flavors` in turn (the idle itself when there are none: a vanilla flavor would play Starfield's own pose in
    the middle of ours), EnterFromStand, ExitToStand and QuickExitToStand, EnterInstant (spawning in place) when the
    template has it. Flavors must start and end on the idle's pose (Skyrim's transitions into another loop do not)."""
    rows = [("idle.afx", idle, None)]
    pool = list(flavors) or [idle]
    rows += [(f"idle_flavor{i:02d}.afx", pool[(i - 1) % len(pool)], None) for i in range(1, n_flavors + 1)]
    if enter:
        rows.append(("enterfromstand.afx", enter, None))
    if exit_:
        rows += [("exittostand.afx", exit_, None), ("quickexittostand.afx", exit_, None)]
    if instant:
        rows.append(("enterinstant.afx", idle, None))
    return (SF_ANIM + "furniture\\" + folder, SF_ANIM + "furniture\\" + template, rows)


SETS = {
    "Sit": (SF_ANIM + "furniture\\s2s_sit", SF_ANIM + "furniture\\chair", [
        ("idle.afx", "male\\chair_idlebasevar1.hkx", None),
        ("idle_flavor01.afx", "male\\chair_idlebasevar2.hkx", None),
        ("idle_flavor02.afx", "male\\chair_idlebasevar1shoulders.hkx", None),
        ("idle_flavor03.afx", "male\\chair_idlebasevar2.hkx", None),
        ("idle_flavor03.afx", "male\\chair_idlebasevar1shoulders.hkx", "Idle_Flavor04"),     # benches have a fourth
        ("enterfromstand.afx", "male\\chair_frontentervar1.hkx", None),
        ("frontenterfromstand.afx", "male\\chair_frontentervar1.hkx", None),
        ("exittostand.afx", "male\\chair_frontexit.hkx", None),
        ("frontexittostand.afx", "male\\chair_frontexit.hkx", None),
        ("quickexittostand.afx", "male\\chair_frontexit.hkx", None),
        ("leftenterfromstand.afx", "male\\chair_leftenter.hkx", None),
        ("leftexittostand.afx", "male\\chair_leftexit.hkx", None),
        ("leftquickexittostand.afx", "male\\chair_leftexit.hkx", None),
        ("rightenterfromstand.afx", "male\\chair_rightenter.hkx", None),
        ("rightexittostand.afx", "male\\chair_rightexit.hkx", None),
        ("rightquickexittostand.afx", "male\\chair_rightexit.hkx", None),
        # Skyrim has no entry from behind: Rear* stay Starfield's; EnterInstant, LookDirections, Talk_*, Camera too
    ]),
    # 2026-11-14 (owner's survey of the templates' folders: every one has Idle, Idle_FlavorNN, EnterFromStand,
    # ExitToStand, QuickExitToStand; sweep and wipe-wall also EnterInstant). Skyrim clips: mt_behavior's furniture clips.
    "RailLean": standing_set("s2s_raillean", "leaningbartopfront", "railleanidle.hkx", (), "railleanenter.hkx",
                             "railleanexit.hkx", 6),
    "WallLean": standing_set("s2s_walllean", "leaningbartopfront", "wall_idlebackloop.hkx", (),
                             "wall_idlebackenter.hkx", "wall_idlebackexit.hkx", 6),
    # the counter's arms-on-counter / wiping loops are other poses (reached by transition clips): idle only for now
    "Counter": standing_set("s2s_counter", "bartender", "animobjectcounteridleloopright.hkx", (),
                            "animobjectcounterenter.hkx", "animobjectcounterexit.hkx", 5),
    "LeanTable": standing_set("s2s_leantable", "desklean", "idleleantable.hkx", ("idleleantable_point.hkx",),
                              "idleleantable_enter.hkx", "idleleantable_exit.hkx", 4),
    # Skyrim's sweeping has no exit clip: ExitToStand stays Starfield's. The broom: Starfield's descriptor events.
    "Sweep": standing_set("s2s_sweep", "standing_sweep", "animobjectsweepingidlebase.hkx",
                          ("animobjectsweepingidlevar1.hkx",), "animobjectsweepingidlestart.hkx", None, 5, instant=True),
    "Alchemy": standing_set("s2s_alchemy", "workbench\\pharmaworkbench", "craftingalchemybenchstirboth.hkx",
                            ("craftingalchemybenchpoundboth.hkx", "craftingalchemybenchtap.hkx"),
                            "craftingalchemybenchenter.hkx", "craftingalchemybenchexit.hkx", 5),
    "Enchant": standing_set("s2s_enchant", "workbench\\industrialworkbench", "craftingenchantingbenchidle.hkx",
                            ("craftingenchantingbenchidlecircle.hkx",), "craftingenchantingbenchenter.hkx",
                            "craftingenchantingbenchexit.hkx", 6),
    "Cook": standing_set("s2s_cook", "workbench\\galleyworkbench", "craftingcookingpotstir.hkx", (),
                         "craftingcookingpotenter.hkx", "craftingcookingpotexit.hkx", 0),
    "Tanning": standing_set("s2s_tanning", "standing_wipewall", "craftingtanningidleb.hkx",
                            ("craftingtanningidlea.hkx",), "craftingtanningenterb.hkx", "craftingtanningexitb.hkx", 5,
                            instant=True),
    # 2026-11-16 (owner: "the character takes a sword, puts them in water trough, and also puts them in the forge ...
    # there's hammering"; smithing_probe, verified: mt_behavior's forge machine Pull -> Hammer (loop) -> RandomTrough
    # (Temper: quench and back to Hammer | Discard: drop it and Pull a new iron) -> Hammer ...; exit). Starfield's
    # furniture graph plays one idle with flavors: Enter = Pull (out of the fire), Idle = Hammer, flavors = Temper (it
    # ends back on the hammering pose; Discard ends before a new Pull, so it would jump), Exit. No root motion in any of
    # them (furniture_motion --clips, verified): the walk to the trough is in the body's own track. The industrial
    # workbench template (the forge's Starfield furniture) has 6 flavor slots (the Enchant set's).
    # The furniture is NPC work furniture on the wall-wipe template (make_furniture.TEMPLATES "forge", 2026-11-16:
    # Alvor never used it as Starfield's industrial workbench): its folder's slots, 5 flavors and EnterInstant.
    # 2026-11-16 (owner, in game: "going back and forth between hammering and then putting the sword in the trough ...
    # in skyrim they usually also pull the ropes on the forge"): an NPC placed at the forge enters instantly (the
    # Hammer), so the Pull, the only clip at the fire, never played. Discard + Pull (hkx_to_af CLIP A+B, retarget.concat)
    # is Skyrim's other trough branch played through to the hammering pose: flavors alternate Temper / Discard + Pull.
    # 2026-11-16 (owner's A/B): on the welder's folder (furniture\welder: Enter / EnterInstant / Exit / QuickExit,
    # Idle and 4 flavors; owner's furniture_anim_survey --template), not the tanning rack's wall-wipe one.
    "Forge": standing_set("s2s_forge", "welder", "blacksmithforgehammer.hkx",
                          ("blacksmithforgetemper.hkx", "blacksmithforgediscard.hkx+blacksmithforgepull.hkx"),
                          "blacksmithforgepull.hkx", "blacksmithforgeexit.hkx", 4, instant=True),
    # The Grindstone set (Skyrim's sharpening wheel: Enter / Spin / Exit on the wall-wipe template) was removed
    # 2026-11-16 (owner: "Can we remove the grindstone stuff for now"); docs/npc/furniture.md keeps its clips.
}

# Seat / stand offset per set (metres, X,Y): measured once by the Idle's --align-com and kept, so reruns skip that pass.
# Sets not listed are aligned to their template's Idle on each run; (0, 0) keeps Skyrim's own placement (WallLean:
# Skyrim leans back on the wall, the template's actor faces a counter, so its COM is no guide).
# 2026-11-14 owner's pack run (--align-com of each Idle): RailLean .. Tanning. Tanning (0, 0): 2026-11-15 in game the
# tanner worked 0.65 m away from the rack with the wipe-wall template's offset (-0.029, -0.648); Skyrim's own spot.
# 2026-11-15: the lean, counter, table and sweep spots now take Skyrim's own markers (make_furniture.skyrim_markers;
# in game they stood at the bartop-lean template's spot, off the rail / post), so their clips keep Skyrim's own
# placement too: (0, 0). The offsets measured against the templates were RailLean (-0.155, -0.181), Counter
# (-0.146, -0.276), LeanTable (0.026, -0.26), Sweep (-0.002, -0.045).
COM_SHIFT = {"Sit": (0.027, -0.091), "WallLean": (0.0, 0.0), "RailLean": (0.0, 0.0), "Counter": (0.0, 0.0),
             "LeanTable": (0.0, 0.0), "Sweep": (0.0, 0.0), "Alchemy": (0.014, -0.037),
             "Enchant": (0.015, -0.035), "Cook": (0.015, -0.027), "Tanning": (0.0, 0.0),
             "Forge": (0.0, 0.0)}           # Skyrim's forge marker (make_furniture SKYRIM_SPOT_SETS): Skyrim's placement


# Descriptor variables left out of our copies (2026-11-14, owner, in game: seated on our bench the arms were pulled back
# and twisted inward, hands by the hips; af_pose showed the clip itself has them forward on the thighs, as in Skyrim).
# Starfield's chair and bench descriptors keep bEnableHandIK on over the whole Idle (and its enters / exits): the graph
# then pulls the hands to IK targets of Starfield's furniture models, which our converted Skyrim models do not have.
# Skyrim's clips place the hands themselves.
DROP_VARIABLES = ("bEnableHandIK",)

# Hands resting on the thighs: at least this far above the hip-knee line and to the outside of it (metres), by arm IK
# (hkx_to_af --hand-clearance). 2026-11-14 (owner, in game: the seated hands sink into the thighs). af_pose
# hands_on_thighs: our Idle 0.047 / 0.063 above, 0.004 / 0.034 inside; Starfield's chair Idle 0.129 / 0.136 above,
# 0.026 / 0.030 outside.
HAND_CLEARANCE = {"Sit": (0.13, 0.03)}


def strip_variables(afx_text: str, names=DROP_VARIABLES) -> str:
    """An .afx descriptor without the <variable> entries named `names` (any case)."""
    import re
    want = {n.lower() for n in names}

    def keep(m):
        nm = re.search(r"<name>\s*([^<]*?)\s*</name>", m.group(0))
        return "" if nm and nm.group(1).lower() in want else m.group(0)
    out = re.sub(r"[ \t]*<variable>.*?</variable>[ \t]*\r?\n?", keep, afx_text, flags=re.S)
    return re.sub(r"[ \t]*<variables>\s*</variables>[ \t]*\r?\n?", "", out)


# Props: the template descriptors' AnimObj* events load and draw Starfield's prop (2026-11-15, owner, in game: the tanner
# held a white cloth; standing_wipewall\enterfromstand.afx: AnimObjLoad / AnimObjDraw AnimObjectDishRag). Left out
# of every set but these, whose Skyrim clip holds the same kind of thing (the broom).
KEEP_PROPS = ("Sweep",)
# Skyrim's props on our sets (2026-11-15, owner: Embry sweeps with no broom; owner: convert Skyrim's broom). The set's
# clips key the prop bone where Skyrim holds it (hkx_to_af --prop), and its descriptors load our animation object
# (S2SStances.esm's ANIO, a copy of Starfield's AnimObjectBroom with the converted Skyrim broom, attached to the same
# bone: scripts/armor/anim_object_convert.py) instead of Starfield's.
# 2026-11-16 (owner's anim_object_probe on the forge clips, verified): Skyrim's forge holds the hammer on AnimObjectR
# (fixed in the right hand) and the hot iron on AnimObjectL (in the fire at the Pull's start, carried to the left hand,
# then fixed ~0.47 m from it through the hammering and the trough).
SET_PROPS = {"Sweep": ("AnimObjectR=R_AnimObject1",),
             "Forge": ("AnimObjectR=R_AnimObject1", "AnimObjectL=L_AnimObject1")}
PROP_SWAP = {"Sweep": {"AnimObjectBroom": "S2S_AnimObjectBroomSkyrim"}}
# Props a set loads itself (its template loads its own, or none, where Skyrim's are wanted): every enter descriptor
# (EnterFromStand, EnterInstant) gets AnimObjLoad + AnimObjDraw of each at frame 0, every exit AnimObjUnequipAll at
# frame 0. The forge's Starfield template (industrial workbench) loads AnimObjectIndustrialWorkbench01 in one flavor
# only (left out with its other prop events). S2S ANIO records: stance_plugin.PROP_OBJECTS.
SET_PROP_OBJECTS = {"Forge": ("S2S_AnimObjectForgeHammerSkyrim", "S2S_AnimObjectForgeIronSkyrim")}
# 2026-11-16 (owner's clip_join run, verified): the forge's clips chain Pull > Hammer 0.0 deg, Hammer > Temper 0.0,
# Temper > Hammer 2.7, Hammer > Discard 4.0, but the Discard ends on no clip's first pose (Discard > Pull 62.7 deg in
# the left arm and head, the closest; Pull starts from standing: Exit > Pull differs in the fingers only). Skyrim
# goes Discard -> BlacksmithForgeRestart -> Pull through a blending transition, so the joined flavor crossfades too.
# The length is an assumption (Skyrim's transition duration not read): 0.8 s.
JOIN_BLEND = {"Forge": 0.8}
# Events at times inside a joined clip's parts: {set: {clip: [(part, seconds into it, event, payload)]}}. The forge's
# Discard drops the iron and Skyrim's Pull draws a new one at 2 s (smithing_probe: AnimObjDraw at 2.0 s); without
# this the iron would fly from the drop to the fire. AnimObjUnequip with a payload removes one prop (vanilla: the
# industrial workbench's Idle_Flavor02, afx_events). Frames: the report's part_starts + seconds * 30.
_IRON = "S2S_AnimObjectForgeIronSkyrim"
CLIP_EVENTS = {"Forge": {"blacksmithforgediscard.hkx+blacksmithforgepull.hkx": [
    (1, 0.0, "AnimObjUnequip", _IRON), (1, 2.0, "AnimObjLoad", _IRON), (1, 2.0, "AnimObjDraw", _IRON)]}}
ENTER_TAGS = ("enterfromstand", "enterinstant")
EXIT_TAGS = ("exittostand", "quickexittostand")


def clip_event_rows(rows, set_events) -> dict:
    """{descriptor stem (lower): [(frame, event, payload)]} for the report rows whose clip has CLIP_EVENTS: frame =
    the part's first frame in the joined clip + seconds * 30."""
    out = {}
    for r in rows:
        clip = (r.get("clip") or "").replace("/", "\\").split("\\")[-1].lower()
        evs = set_events.get(clip)
        target = r.get("template") or r.get("replaces")
        if not evs or not target or "error" in r:
            continue
        starts = r.get("part_starts") or [0]
        stem = os.path.splitext(target.replace("\\", "/").split("/")[-1])[0].lower()
        out[stem] = [(int(starts[p] + round(sec * 30)), name, pay) for p, sec, name, pay in evs if p < len(starts)]
    return out


def add_clip_events(afx_text: str, events) -> str:
    from fo4sf import af_writer
    data = afx_text.encode("utf-8")
    for f, name, pay in events:
        data = af_writer.add_event(data, f, name, pay)
    return data.decode("utf-8")


def add_set_props(afx_text: str, objects) -> str:
    """The descriptor with the set's own props loaded and drawn at the start of an enter, all unequipped at the start
    of an exit (SET_PROP_OBJECTS); other descriptors unchanged."""
    from fo4sf import af_writer
    tag = (_tag(afx_text) or "").lower()
    data = afx_text.encode("utf-8")
    if tag in ENTER_TAGS:
        for o in objects:                                # add_event keeps insertion order among equal frames
            data = af_writer.add_event(data, 0, "AnimObjLoad", o)
            data = af_writer.add_event(data, 0, "AnimObjDraw", o)
    elif tag in EXIT_TAGS:
        data = af_writer.add_event(data, 0, "AnimObjUnequipAll", "")
    else:
        return afx_text
    return data.decode("utf-8")


PROP_LOAD_EVENTS = ("AnimObjLoad", "AnimObjDraw")


def props_at_start(afx_text: str, names=PROP_LOAD_EVENTS) -> str:
    """The descriptor with its `names` events moved to frame 0 (2026-11-15, owner: Embry's hands were on the broom
    handle for seconds before the broom appeared: the events kept the frames of Starfield's own enter, whose hands
    reach the broom later than Skyrim's)."""
    import re
    from fo4sf import af_writer
    data = afx_text.encode("utf-8")
    for n in names:
        if re.search(rf"<name>\s*{n}\s*</name>", afx_text):
            data = af_writer.set_event_frame(data, n, 0)
    return data.decode("utf-8")


def dense_keys(keys, frames: int, quat: bool):
    """(frames, 3 or 4) values from [(frame, value)] keys: linear between keys (normalised for quaternions, the
    shorter way), held before the first and after the last."""
    import numpy as np
    fr = [k for k, _v in keys]
    vals = [np.asarray(v, float) for _k, v in keys]
    out = np.empty((frames, len(vals[0])))
    for f in range(frames):
        j = int(np.searchsorted(fr, f))
        if j < len(fr) and fr[j] == f:
            out[f] = vals[j]
        elif j == 0:
            out[f] = vals[0]
        elif j >= len(fr):
            out[f] = vals[-1]
        else:
            a, b = vals[j - 1], vals[j]
            u = (f - fr[j - 1]) / (fr[j] - fr[j - 1])
            if quat and float(np.dot(a, b)) < 0:
                b = -b
            v = a * (1 - u) + b * u
            out[f] = v / (np.linalg.norm(v) or 1.0) if quat else v
    return out


def pin_bone(calumi, rig_path, af_path, bone, t, q, work):
    """Rewrite a clip with `bone` held at local (t, q) on every frame, every other keyed bone as it was (header root
    motion kept). 2026-11-15, owner: at the end of sweeping the broom flew off: our Sweep set uses Starfield's own exit
    clips (Skyrim has none), which key R_AnimObject1 for Starfield's setup (its broom hangs on AnimObjectA; the
    vanilla sweep idle holds R_AnimObject1 1.16 m from the wrist), and our broom hangs on R_AnimObject1."""
    import numpy as np
    from fo4sf import af_writer, rootmotion
    rig = af_writer.load_rig(calumi, rig_path)
    rb = af_writer.read_back(calumi, af_path, rig_path)
    F = max(int(rb["frames"]), 1)
    names = rig["names"]
    ct = np.repeat(np.asarray(rig["t"], float)[None], F, axis=0)
    cq = np.repeat(np.asarray(rig["q"], float)[None], F, axis=0)
    keyed = set(rb["bones"]) | {bone}
    for i, n in enumerate(names):
        if rb["translations"].get(n):
            ct[:, i] = dense_keys(rb["translations"][n], F, False)
        if rb["rotations"].get(n):
            cq[:, i] = dense_keys(rb["rotations"][n], F, True)
    bi = names.index(bone)
    ct[:, bi], cq[:, bi] = np.asarray(t, float), np.asarray(q, float)
    with open(af_path, "rb") as fh:
        head_q, head_t = rootmotion.read_header(fh.read())
    os.makedirs(work, exist_ok=True)
    stem = os.path.splitext(os.path.basename(af_path))[0]
    w = af_writer.write(calumi, work, stem, names, rig["parents"], rig["t"], rig["q"], ct, cq, rig_path=rig_path,
                        omit=tuple(n for n in names if n not in keyed))
    rootmotion.patch_header(w["af"], head_t, head_q)
    shutil.copy2(w["af"], af_path)
    return {"frames": F, "bones": len(keyed)}


def pin_props(a, st, dst, idle_af, bones, left) -> list:
    """Hold each prop bone in Starfield's clips copied into our folder (`left`, non-additive ones) at our Idle's pose
    of it (pin_bone). Returns the clips rewritten."""
    import hkx_to_af
    from fo4sf import af_writer
    work = os.path.join(a.work, st, "pin")
    os.makedirs(work, exist_ok=True)
    rig_path = os.path.join(work, "skeleton.rig")
    if not os.path.isfile(rig_path):
        _n, data = hkx_to_af.starfield_find(os.path.join(a.starfield, "Data"), hkx_to_af.SF_RIG_RX,
                                            ("starfield - animations",))
        if data is None:
            print(f"{st}: Starfield's skeleton.rig not found: the prop bones in its clips are left as they are")
            return []
        with open(rig_path, "wb") as fh:
            fh.write(data)
    ours = af_writer.read_back(a.calumi, os.path.join(dst, idle_af), rig_path)
    done = []
    for name, (text, clip) in left.items():
        if not clip or clip[1] is None or "<flag>additive</flag>" in text.lower().replace(" ", ""):
            continue
        for b in bones:
            if not (ours["translations"].get(b) and ours["rotations"].get(b)):
                continue
            pin_bone(a.calumi, rig_path, os.path.join(dst, clip[0]), b, ours["translations"][b][0][1],
                     ours["rotations"][b][0][1], os.path.join(work, "out"))
            done.append(_tag(text))
    return sorted(set(done))


def swap_anim_objects(afx_text: str, swaps: dict) -> str:
    """The descriptor with each AnimObj* event payload named in `swaps` (any case) replaced by its value."""
    import re
    low = {k.lower(): v for k, v in swaps.items()}

    def one(m):
        body = m.group(0)
        nm = re.search(r"<name>\s*([^<]*?)\s*</name>", body)
        if not nm or not nm.group(1).lower().startswith("animobj"):
            return body
        return re.sub(r"(<payload>\s*)([^<]*?)(\s*</payload>)",
                      lambda p: p.group(1) + low.get(p.group(2).lower(), p.group(2)) + p.group(3), body)
    return re.sub(r"<event>.*?</event>", one, afx_text, flags=re.S)


# Talking while on our furniture (2026-11-15, owner, in game: seated Hilde, talking, crossed her arms fine but "puts them
# down and they briefly go inside her body"): those are Starfield's own seated talk clips (furniture\common: the owner's
# survey lists these tags), blended with our sitting pose, the forearms passing through the body. Each set gets them
# as copies of its own Idle (Skyrim's seated NPCs do not gesture either), so the game finds ours first. Copies, not
# conversions: the same clip 38 times over would only cost time.
# 2026-11-15, owner, in game after those: seated Hilde still put a hand to her chin / crossed her arms, and at rest her
# shoulders dropped with the hands sunk into her lap. Verified on the owner's PC: the 38 copies are on disk and in the
# Creation Kit cache, and no subgraph row but the Furniture ones matches chairs (subgraph_rows.py). The furniture graph
# links NPC_IdlePartialBody (an upper-body idle layer; its variables iSyncPartialBodyBlend / iSyncInDialogueScene), and
# common\female (in the female rows' folder chain) holds IdlePartialBody, its flavors 01-04, Start and Stop
# (common\pirate 01-02; plain common none, so men are unaffected): a woman's standing upper body over our seat. Same
# answer: each set's Idle under those tags too, in our folder before common\female.
PARTIAL_BODY_SLOTS = ("IdlePartialBody", "IdlePartialBody_Flavor01", "IdlePartialBody_Flavor02",
                      "IdlePartialBody_Flavor03", "IdlePartialBody_Flavor04", "IdlePartialBody_Start",
                      "IdlePartialBody_Stop")
TALK_SLOTS = tuple([f"Idle_Dialogue{i:02d}" for i in range(1, 8)] + [f"Talk_L{i:02d}" for i in range(1, 11)]
                   + [f"Talk_M{i:02d}" for i in range(1, 17)] + [f"Talk_S{i:02d}" for i in range(1, 6)]) \
    + PARTIAL_BODY_SLOTS


def talk_copies(idle_afx: str, slots=TALK_SLOTS):
    """{file name: descriptor text} for each slot: the set's Idle descriptor with its tag and file name changed, the
    clip being a copy of Idle.af under <slot>.af."""
    import re
    out = {}
    for slot in slots:
        t = re.sub(r"<tag>\s*[^<]*</tag>", f"<tag>{slot}</tag>", idle_afx, count=1)
        t = re.sub(r"<filename>\s*[^<]*</filename>", f"<filename>{slot}.af</filename>", t, count=1)
        out[slot.lower() + ".afx"] = t
    return out


def strip_events(afx_text: str, prefixes=("AnimObj",)) -> str:
    """An .afx descriptor without the <event> entries whose name starts with one of `prefixes` (any case)."""
    import re
    low = tuple(x.lower() for x in prefixes)

    def keep(m):
        nm = re.search(r"<name>\s*([^<]*?)\s*</name>", m.group(0))
        return "" if nm and nm.group(1).lower().startswith(low) else m.group(0)
    out = re.sub(r"[ \t]*<event>.*?</event>[ \t]*\r?\n?", keep, afx_text, flags=re.S)
    return re.sub(r"[ \t]*<events>\s*</events>[ \t]*\r?\n?", "", out)


# Starfield's own states we do not convert (chair: Rear* enters / exits, EnterInstant, LookDirections ...; the
# templates' and furniture\common's descriptors) still play with bEnableHandIK and their prop events. 2026-11-15
# (owner, male player): the hands go into the body for a moment as he sits; af_pose --gaps on every one of our sit
# enters and the Idle: never inside (closest +0.035 m; Starfield's chair EnterFromStand -0.001 m), so the game adds it.
# Each such descriptor is copied into our folder (found first) with those left out, its clip with it: Starfield's
# motion, without the pull to IK targets our models do not have. Descriptors with nothing to leave out are not copied.
COMMON_FOLDER = SF_ANIM + "furniture\\common"
# Other template folders a set's keyword rows read after ours (the owner's subgraph_rows.py, 2026-11-15: benches read
# furniture\bench, women chair\female / bench\female first): scanned too, each with its female subfolder.
EXTRA_TEMPLATES = {"Sit": (SF_ANIM + "furniture\\bench",)}


def leftover_folders(anim_set: str) -> list:
    """The Starfield folders vanilla_leftovers scans for a set: its template and EXTRA_TEMPLATES, each with its
    animflavor and female subfolders, then furniture\\common."""
    out = []
    for f in (SETS[anim_set][1],) + EXTRA_TEMPLATES.get(anim_set, ()):
        # animflavor first (2026-11-15, owner's furniture_graph_probe: HumanRace's chair / bench entries read
        # chair\animflavor (32 tags) and chair\female\animflavor before chair; the graph renames tags with a
        # "Relaxed" prefix and PoseA / B / C suffixes, played from there: Starfield's armrest pose on our seat)
        out += [f + "\\animflavor", f + "\\female\\animflavor", f, f + "\\female"]
    return out + [COMMON_FOLDER]


def _tag(afx_text: str):
    import re
    m = re.search(r"<tag>\s*([^<]*?)\s*</tag>", afx_text)
    return m.group(1) if m else None


def _clip_name(afx_text: str):
    import re
    m = re.search(r"<filename>\s*([^<]*?)\s*</filename>", afx_text)
    return m.group(1) if m else None


def vanilla_leftovers(names, read, folders, have_tags, keep_props=False, graph_swaps=None, force=False) -> dict:
    """{file name: (descriptor text, clip bytes or None)} for the descriptors directly in `folders` (archive folders,
    first wins per tag) whose tag is not in `have_tags` (lower case) and that change when bEnableHandIK / prop events
    are left out. names: normalised archive names; read(name) -> bytes."""
    out, seen = {}, {t.lower() for t in have_tags}
    for folder in folders:
        f = folder.replace("/", "\\").lower().rstrip("\\") + "\\"
        for n in sorted(x for x in names if x.startswith(f) and x.endswith(".afx") and "\\" not in x[len(f):]):
            raw = read(n)
            if raw is None:
                continue
            text = raw.decode("utf-8", "replace")
            tag = _tag(text)
            if not tag or tag.lower() in seen:
                continue
            seen.add(tag.lower())
            new = strip_variables(text)
            if not keep_props:
                new = strip_events(new)
            if graph_swaps:
                new = swap_graph(new, graph_swaps)
            if new == text and not (force and "<flag>additive</flag>" not in text.lower().replace(" ", "")):
                continue
            clip = _clip_name(text)
            out[n[len(f):]] = (new, (clip, read(f + clip.lower())) if clip else None)
    return out


# 2026-11-15 (owner, in game, seated male player): with every flavor replaced by the Idle the body still slumps now and
# then, the arms straight and the hands down at the seat's edge: Starfield's own chair pose (made for armrests) on a
# chair without them. So a state of the template folders that ours do not answer still plays Starfield's clip. Every
# such tag that is not an enter / exit / look / camera / flinch state (those keep Starfield's motion, cleaned above)
# gets the set's Idle, as the talk slots do.
NOT_IDLE = ("enter", "exit", "look", "camera", "flinch")


# The furniture graph renames tags (owner's furniture_graph_probe, 2026-11-15: FurnitureHeadTracking_Wrapping's
# switches add the prefix "Relaxed" and the suffixes PoseA / PoseB / PoseC): a renamed tag whose base ours answers
# plays our clip for the base (an enter stays an enter).
TAG_PREFIXES = ("Relaxed",)
TAG_SUFFIXES = ("PoseA", "PoseB", "PoseC")


def base_tag(tag: str, have_lower) -> str:
    """The tag ours answer that `tag` renames (a TAG_PREFIXES prefix and / or a TAG_SUFFIXES suffix, with or without
    an underscore), or None."""
    cands = {tag}
    for p in TAG_PREFIXES:
        for c in list(cands):
            if c.lower().startswith(p.lower()):
                cands.add(c[len(p):].lstrip("_"))
    for x in TAG_SUFFIXES:
        for c in list(cands):
            if c.lower().endswith(x.lower()):
                cands.add(c[:-len(x)].rstrip("_"))
    hits = [c for c in cands if c != tag and c.lower() in have_lower]
    return min(hits, key=len) if hits else None


def unanswered_tags(names, read, folders, have_tags) -> list:
    """[(tag, idle-like)] of the descriptors directly in `folders` (first wins per tag) whose tag is not in have_tags."""
    out, seen = [], {t.lower() for t in have_tags}
    for folder in folders:
        f = folder.replace("/", "\\").lower().rstrip("\\") + "\\"
        for n in sorted(x for x in names if x.startswith(f) and x.endswith(".afx") and "\\" not in x[len(f):]):
            raw = read(n)
            tag = _tag(raw.decode("utf-8", "replace")) if raw else None
            if not tag or tag.lower() in seen:
                continue
            seen.add(tag.lower())
            out.append((tag, not any(w in tag.lower() for w in NOT_IDLE)))
    return out


# Mood variants (2026-11-15, owner's anim_cache_clips on the Creation Kit cache: our Sit set still resolved 862 Starfield
# clips, 738 of them in chair / bench (female) \\animflavor: analyze_idle, confident_idle_flavor02, crosslegs_talk_l01
# ... and the upper-body layer's relaxed_idlepartialbody_handsbehind ... in common): a seated character's animation
# flavor (thinking, confident, crosslegs, executive, relaxed, tablet, bored, slouched, analyze ...) plays
# <flavor>_<clip>.af, found by file name along the folder chain (no descriptor of its own), so Starfield's played
# over our pose. Each such variant whose base is a clip of ours gets a copy of ours under its name, in our folder.
VARIANT_FOLDERS = (SF_ANIM + "common", SF_ANIM + "common\\female", SF_ANIM + "common\\pirate")


def mood_variants(names, folders, our_clips) -> dict:
    """{variant file name: our clip file name} for the .af files directly in `folders` named <prefix>_<base> where
    <base> is one of ours (our_clips: {stem lower case: file name}; the longest base wins), and any with
    'idlepartialbody' in the name (the upper-body layer) -> our Idle. Our own names are skipped."""
    out = {}
    stems = sorted(our_clips, key=len, reverse=True)
    for folder in folders:
        f = folder.replace("/", "\\").lower().rstrip("\\") + "\\"
        for n in names:
            if not (n.startswith(f) and n.endswith(".af") and "\\" not in n[len(f):]):
                continue
            stem = n[len(f):-3]
            if stem in our_clips or stem + ".af" in out:
                continue
            base = next((o for o in stems if stem.endswith("_" + o)), None)
            if base is None and "idlepartialbody" in stem and "idle" in our_clips:
                base = "idle"
            if base is not None:
                out[stem + ".af"] = our_clips[base]
    return out


# The graph our sit-down loads (2026-11-15, owner's S2SCombat log: our chair enter sends LoadFurnitureGraph
# FurnitureRandomSitChair.agx, copied with Starfield's chair descriptor, which then runs IdleFlavor / FlavorEnd of its own:
# the brief arms-back slump that survived every tag we answered). Starfield's descriptors load 4 furniture graphs
# (owner's listing): FurnitureRandomSitChair (41: bar stools, benches, chairs), FurnitureGenericSit (45: executive
# chairs, character creation, console seats), FurnitureFireWeapon, FurnitureSyncIdle. Ours load the plain sitting one.
GRAPH_SWAP = {"Sit": {"furniturerandomsitchair.agx": "FurnitureGenericSit.agx"}}


def swap_graph(afx_text: str, swaps: dict) -> str:
    """The descriptor with each LoadFurnitureGraph payload whose file name is a key of `swaps` (lower case) replaced
    by the value, keeping the folder."""
    import re

    def one(m):
        path = m.group(2)
        head, _, name = path.replace("/", "\\").rpartition("\\")
        new = swaps.get(name.lower())
        return m.group(1) + ((head + "\\" if head else "") + new if new else path) + m.group(3)
    return re.sub(r"(<name>\s*LoadFurnitureGraph\s*</name>.*?<payload>\s*)([^<]*?)(\s*</payload>)", one, afx_text,
                  flags=re.S)


def parse_pair(value):
    """'0.027,-0.091' or ['0.027', '-0.091'] or ['0.027,-0.091'] (PowerShell splits an unquoted pair) -> floats."""
    text = ",".join(value) if isinstance(value, (list, tuple)) else str(value)
    return [float(x) for x in text.replace(" ", ",").split(",") if x]


def replace_args(anim_set: str):
    """hkx_to_af --replace values for a set: (Idle first, the rest)."""
    folder, tpl, rows = SETS[anim_set]
    args = []
    for afx, clip, tag in rows:
        a = f"{SKY_ANIM}{clip}::{tpl}\\{afx}" + (f"::{tag}" if tag else "")
        args.append(a)
    idle = [x for x in args if x.endswith("\\idle.afx")]
    return idle, [x for x in args if x not in idle]


def without_enter(entry):
    """A set (folder, template, rows) without its EnterFromStand row: Starfield's template plays its own walk-in."""
    folder, tpl, rows = entry
    return folder, tpl, [r for r in rows if r[0] != "enterfromstand.afx"]


def fresh_dir(path):
    """`path` empty (made if missing)."""
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def hkx_args(a, work, folder, replace, com=None, hands=None, profiles=None, shoulders=None, props=(), blend=0.0):
    out = ["--calumi", a.calumi, "--skyrim-data", a.skyrim_data, "--starfield-data", os.path.join(a.starfield, "Data"),
           "--out", work, "--into", folder, "--no-root-motion"]
    if blend:
        out += ["--join-blend", str(blend)]
    out += ["--com-shift", f"{com[0]},{com[1]}"] if com is not None else ["--align-com"]
    for p in props or ():
        out += ["--prop", p]
    if hands:
        out += ["--hand-clearance", ",".join(str(x) for x in hands)]
    if profiles:
        out += ["--body-profiles", profiles]
    if shoulders:
        out += ["--shoulder-calibration", shoulders]
    for r in replace:
        out += ["--replace", r]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--calumi", required=True, help="CALUMI.Animation.dll (as for hkx_to_af)")
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield's game folder")
    ap.add_argument("--out", required=True, help="the mod folder (MO2): gets meshes\\actors\\human\\animations\\...")
    ap.add_argument("--work", required=True, help="a scratch folder outside the repository")
    ap.add_argument("--set", action="append", choices=sorted(SETS), help="only these sets (default: all)")
    ap.add_argument("--vanilla-enter", action="append", default=[], choices=sorted(SETS),
                    help="A/B: leave this set's EnterFromStand to Starfield's template (2026-11-16: does the forge's "
                         "13.9 s Pull as the walk-in stop NPCs entering?)")
    ap.add_argument("--com-shift", metavar="X,Y", nargs="+",
                    help="with one --set: use this offset instead of COM_SHIFT / the Idle's --align-com result "
                         "(PowerShell splits an unquoted X,Y in two: both forms are taken)")
    ap.add_argument("--hand-clearance", metavar="UP,OUT", help="override HAND_CLEARANCE for the sets run")
    ap.add_argument("--copy-only", action="store_true",
                    help="no conversion: copy the earlier one in --work again (descriptor clean-up, talk slots); for "
                         "changes to the copy step only")
    ap.add_argument("--shoulder-calibration", metavar="JSON",
                    help="af_pose.py --calibrate-shoulders' output (all sets): shoulders where Starfield's clips have them")
    ap.add_argument("--body-profiles", metavar="JSON",
                    help="body_profiles.py's output: hands keep their place relative to the body (all sets); replaces "
                         "HAND_CLEARANCE unless --hand-clearance is given")
    a = ap.parse_args(argv)
    for st in a.vanilla_enter:
        SETS[st] = without_enter(SETS[st])
    for p in (a.out, a.work):
        if os.path.abspath(p).lower().startswith(os.path.abspath(REPO).lower()):
            sys.exit(f"{p}: must be outside the repository")
    if a.com_shift and len(a.set or SETS) != 1:
        sys.exit("--com-shift is one set's offset: give it with exactly one --set")
    import hkx_to_af
    report = {}
    sf_arcs = None                       # Starfield's archives, for its own states we do not convert (vanilla_leftovers)
    if os.path.isdir(os.path.join(a.starfield, "Data")):
        import furniture_anim_survey
        sf_arcs = furniture_anim_survey.SfArchives(os.path.join(a.starfield, "Data"))
    for st in a.set or list(SETS):
        folder = SETS[st][0]
        work = os.path.join(a.work, st)
        idle, rest = replace_args(st)
        com = parse_pair(a.com_shift) if a.com_shift else (list(COM_SHIFT[st]) if st in COM_SHIFT else None)
        hands = parse_pair(a.hand_clearance) if a.hand_clearance else (
            None if a.body_profiles else HAND_CLEARANCE.get(st))
        done_rep = os.path.join(work, "all", "report.json")
        if a.copy_only and not os.path.exists(done_rep):
            print(f"{st}: --copy-only but no earlier conversion in {os.path.join(work, 'all')}; converting")
        if a.copy_only and os.path.exists(done_rep):
            print(f"== {st}: the earlier conversion, copied again (--copy-only)")
        elif com is None:
            print(f"== {st}: Idle with --align-com (the set's seat offset)")
            rc = hkx_to_af.main(hkx_args(a, os.path.join(work, "idle"), folder, idle))
            with open(os.path.join(work, "idle", "report.json"), encoding="utf-8") as fh:
                row = json.load(fh)[0]
            if rc != 0 or "com_shift_m" not in row:
                print(f"{st}: the Idle did not convert ({row.get('error') or row}); set skipped")
                report[st] = {"folder": folder, "failed": [row.get("clip")], "error": row.get("error"), "files": []}
                continue
            com = row["com_shift_m"]
            print(f"{st}: offset {com[0]},{com[1]} (add to COM_SHIFT to keep it)")
        if not (a.copy_only and os.path.exists(done_rep)):
            # a fresh conversion folder: the copy step takes every file in it (2026-11-16: the Forge's Idle_Flavor06 of
            # the industrial-workbench template, 11:59, was still copied after the move to the wall-wipe one's 5)
            fresh_dir(os.path.join(work, "all"))
            print(f"== {st}: every clip with --com-shift {com[0]},{com[1]}")
            hkx_to_af.main(hkx_args(a, os.path.join(work, "all"), folder, idle + rest, com, hands, a.body_profiles,
                                    a.shoulder_calibration, SET_PROPS.get(st, ()), JOIN_BLEND.get(st, 0.0)))
        with open(os.path.join(work, "all", "report.json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        src = os.path.join(work, "all", *folder.split("\\"))
        dst = os.path.join(a.out, *folder.split("\\"))
        # the set's folder is ours alone and every file in it is made here: start empty, so no copy from an earlier
        # run survives (2026-11-15: the Sweep reconversion with the broom bone kept 119 mood variants copied from the
        # old clips, which mood_variants then skipped as already present)
        if os.path.isdir(dst) and os.path.isdir(src):
            shutil.rmtree(dst)
        os.makedirs(dst, exist_ok=True)
        files = sorted(f for f in os.listdir(src) if f.lower().endswith((".af", ".afx"))) if os.path.isdir(src) else []
        stripped = props = graphs_swapped = clip_events_added = 0
        clip_events = clip_event_rows(rows, CLIP_EVENTS.get(st, {}))
        for f in files:
            if f.lower().endswith(".afx"):
                with open(os.path.join(src, f), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                new = strip_variables(text)
                stripped += new != text
                if st not in KEEP_PROPS:
                    plain = strip_events(new)
                    props += plain != new
                    new = plain
                if PROP_SWAP.get(st):
                    new = props_at_start(swap_anim_objects(new, PROP_SWAP[st]))
                if SET_PROP_OBJECTS.get(st):
                    new = add_set_props(new, SET_PROP_OBJECTS[st])
                timed = clip_events.get(os.path.splitext(f)[0].lower())
                if timed:
                    new = add_clip_events(new, timed)
                    clip_events_added += len(timed)
                if GRAPH_SWAP.get(st):
                    swapped = swap_graph(new, GRAPH_SWAP[st])
                    graphs_swapped += swapped != new
                    new = swapped
                with open(os.path.join(dst, f), "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
            else:
                shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
        idle_af = next((f for f in files if f.lower() == "idle.af"), None)
        idle_afx = next((f for f in files if f.lower() == "idle.afx"), None)
        talk = 0
        if idle_af and idle_afx:
            with open(os.path.join(dst, idle_afx), encoding="utf-8", errors="replace") as fh:
                base = fh.read()
            for name, text in talk_copies(base).items():
                with open(os.path.join(dst, name), "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                shutil.copy2(os.path.join(dst, idle_af), os.path.join(dst, name[:-1]))
                talk += 1
        left = {}
        filled = []
        if sf_arcs is not None:
            have = {t for t in (_tag(open(os.path.join(dst, x), encoding="utf-8", errors="replace").read())
                                for x in os.listdir(dst) if x.lower().endswith(".afx")) if t}
            if idle_af and idle_afx:
                gaps = unanswered_tags(sf_arcs.names, sf_arcs.read, leftover_folders(st), have)
                ours = {}
                for x in os.listdir(dst):
                    if x.lower().endswith(".afx"):
                        with open(os.path.join(dst, x), encoding="utf-8", errors="replace") as fh:
                            text = fh.read()
                        if _tag(text):
                            ours.setdefault(_tag(text).lower(), text)
                renamed = []
                for t, _idle_like in gaps:
                    b = base_tag(t, ours)
                    clip = _clip_name(ours[b.lower()]) if b else None
                    if not clip or not os.path.isfile(os.path.join(dst, clip)):
                        continue
                    for name, text in talk_copies(ours[b.lower()], [t]).items():
                        with open(os.path.join(dst, name), "w", encoding="utf-8", newline="") as fh:
                            fh.write(text)
                        shutil.copy2(os.path.join(dst, clip), os.path.join(dst, name[:-1]))
                    renamed.append(f"{t}={b}")
                have |= {r.split("=")[0] for r in renamed}
                gaps = [(t, i) for t, i in gaps if t not in have]
                if renamed:
                    print(f"{st}: renamed states answered with our clip of the base: {', '.join(renamed)}")
                filled = [t for t, idle_like in gaps if idle_like]
                for name, text in talk_copies(base, filled).items():
                    with open(os.path.join(dst, name), "w", encoding="utf-8", newline="") as fh:
                        fh.write(text)
                    shutil.copy2(os.path.join(dst, idle_af), os.path.join(dst, name[:-1]))
                have |= set(filled)
                rest = [t for t, idle_like in gaps if not idle_like]
                print(f"{st}: Starfield's own states answered with our Idle: {', '.join(filled) or 'none'}; "
                      f"left to Starfield: {', '.join(rest) or 'none'}")
            prop_bones = [p.split("=", 1)[1] for p in SET_PROPS.get(st, ())]
            left = vanilla_leftovers(sf_arcs.names, sf_arcs.read, leftover_folders(st), have,
                                     st in KEEP_PROPS, GRAPH_SWAP.get(st), force=bool(prop_bones))
            for name, (text, clip) in left.items():
                with open(os.path.join(dst, name), "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                if clip and clip[1] is not None:
                    with open(os.path.join(dst, clip[0]), "wb") as fh:
                        fh.write(clip[1])
            if left:
                print(f"{st}: Starfield's own {', '.join(sorted(_tag(t) for t, _c in left.values()))} "
                      f"copied with {', '.join(DROP_VARIABLES)} / prop events left out, our graph")
            pinned = pin_props(a, st, dst, idle_af, prop_bones, left) if prop_bones and idle_af else []
            if pinned:
                print(f"{st}: {', '.join(prop_bones)} held in the hand in Starfield's {', '.join(pinned)}")
            our_clips = {x[:-3].lower(): x for x in os.listdir(dst) if x.lower().endswith(".af")}
            variants = mood_variants(sf_arcs.names, leftover_folders(st) + list(VARIANT_FOLDERS), our_clips)
            for name, clip in variants.items():
                shutil.copy2(os.path.join(dst, clip), os.path.join(dst, name))
            if variants:
                print(f"{st}: {len(variants)} mood / upper-body variants answered with our clips "
                      f"({len({n.split('_')[0] for n in variants})} prefixes)")
        if clip_events_added:
            print(f"{st}: {clip_events_added} timed events in joined clips (CLIP_EVENTS)")
        if graphs_swapped:
            print(f"{st}: {graphs_swapped} descriptors load {', '.join(GRAPH_SWAP[st].values())} instead of "
                  f"{', '.join(GRAPH_SWAP[st])}")
        print(f"{st}: {', '.join(DROP_VARIABLES)} left out of {stripped} descriptors"
              + (f", Starfield's prop events of {props}" if props else "")
              + (f"; Idle copied into {talk} talk / upper-body slots" if talk else ""))
        lifted = {r["name"]: r["hands_lifted"] for r in rows if r.get("hands_lifted")}
        contacts = {r["name"]: r["contacts"] for r in rows if r.get("contacts")}
        if a.body_profiles:
            moved = [v["max_move_m"] for d in contacts.values() for v in d.values() if v.get("frames")]
            near = sorted({k for d in contacts.values() for v in d.values() for k in v.get("segments", {})})
            print(f"{st}: hands kept on the body in {sum(1 for d in contacts.values() if any(v.get('frames') for v in d.values()))}"
                  f" clips, moved up to {max(moved, default=0.0)} m, against {', '.join(near) or 'nothing'}")
        if hands:
            top = max((v["max_lift_m"] for d in lifted.values() for v in d.values()), default=0.0)
            print(f"{st}: hands kept {hands[0]} m above the thighs, {len(lifted)} clips, lifted up to {top} m")
        report[st] = {"folder": folder, "com_shift_m": com, "hand_clearance": hands, "hands_lifted": lifted, "contacts": contacts, "clips": len(rows), "hand_ik_stripped": stripped,
                      "failed": [r.get("clip") for r in rows if "error" in r], "files": files,
                      "starfield_states_cleaned": sorted(left), "starfield_states_idle": filled}
        print(f"{st}: {len(files)} files -> {dst}" + (f"; failed: {report[st]['failed']}" if report[st]["failed"] else ""))
    with open(os.path.join(a.work, "furniture_anim_pack.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return 0 if all(not r["failed"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
