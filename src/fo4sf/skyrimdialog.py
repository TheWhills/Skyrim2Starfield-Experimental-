"""Skyrim dialogue: topics (DIAL), their responses (INFO, in each topic's child group), the response text (localized
string tables) and the voice files (.fuz) that hold each spoken line. For converting Skyrim voice lines to Starfield
(owner 2026-11-05; Starfield's side is docs/npc/voice-pipeline.md, from UNITY).

Formats (UESP's Skyrim Mod File Format pages; checked here on synthetic files only):
* DIAL: EDID, FULL topic text, QNAM quest, DATA (u8 flags, u8 category, u16 subtype), SNAM subtype code ('HELO').
  Its INFOs follow it in a GRUP of type 7 (topic children) labelled with the topic's FormID.
* INFO: TRDT per response (u32 emotion type, u32 emotion value, 4 unused, u8 response number, 3 unused, u32 sound,
  u8 flags ...), NAM1 the response text after its TRDT (a string id in a localized plugin), CTDA conditions (32 bytes:
  u8 type, 3 unused, f32 comparison value, u16 function, 2 unused, u32 param 1, u32 param 2, u32 run on, u32 reference,
  i32 param 3).
* .DLSTRINGS / .ILSTRINGS: like .STRINGS, but each string is a u32 length then the bytes.
* .fuz: 'FUZE', u32 version, u32 lip size, the .lip, then the .xwm audio.
* Voice files: sound\\voice\\<plugin>\\<voice type EditorID>\\<...>_<INFO FormID 8 hex>_<response number>.fuz.
"""
import re
import struct
from typing import Dict, Iterable, List, Optional, Tuple

from . import fo4land

GET_IS_ID = 72               # CTDA function indices (Skyrim)
GET_IS_VOICE_TYPE = 426
GET_IS_RACE = 69
GET_IS_SEX = 70
GET_PC_IS_CLASS, GET_PC_IS_RACE, GET_PC_IS_SEX = 129, 130, 131
# 2026-11-05 owner's run: 'What do you want, little elf / cat / lizard / Imperial?' carried function 130 run on the
# subject, which this table had called GetIsSex: it is GetPCIsRace (the player's race), so those lines are about the
# player too
PLAYER_FUNCTIONS = (GET_PC_IS_CLASS, GET_PC_IS_RACE, GET_PC_IS_SEX)
FUNCTION_NAMES = {GET_IS_ID: "GetIsID", GET_IS_VOICE_TYPE: "GetIsVoiceType", GET_IS_RACE: "GetIsRace",
                  GET_IS_SEX: "GetIsSex", GET_PC_IS_CLASS: "GetPCIsClass", GET_PC_IS_RACE: "GetPCIsRace",
                  GET_PC_IS_SEX: "GetPCIsSex"}


def _z(d) -> str:
    return fo4land.zstring(d)


def parse_condition(d: bytes) -> Dict:
    d = bytes(d)
    if len(d) < 24:
        return {}
    typ = d[0]
    use_global = bool(typ & 0x04)
    comp = struct.unpack_from("<I" if use_global else "<f", d, 4)[0]
    func, = struct.unpack_from("<H", d, 8)
    p1, p2 = struct.unpack_from("<II", d, 12)
    run_on = struct.unpack_from("<I", d, 20)[0] if len(d) >= 24 else 0
    ref = struct.unpack_from("<I", d, 24)[0] if len(d) >= 28 else 0
    return {"op": typ >> 5, "or": bool(typ & 1), "use_global": use_global, "value": comp, "function": func,
            "name": FUNCTION_NAMES.get(func, str(func)), "param1": p1, "param2": p2, "run_on": run_on,
            "reference": ref}


PLAYER_FORMS = (0x7, 0x14)       # Player (NPC_), PlayerRef
RUN_ON_TARGET = 1               # CTDA run on: 0 subject, 1 target (the player, in greetings), 2 reference ...


def about_player(c: Dict) -> bool:
    """A condition on the player (run on the target, or naming the player as a parameter or the reference): the
    player's race ('little elf'), their relationship with the speaker, their quests ... none of which exist the same
    way in Starfield."""
    return (c.get("function") in PLAYER_FUNCTIONS or c.get("run_on") == RUN_ON_TARGET
            or c.get("param1") in PLAYER_FORMS or c.get("param2") in PLAYER_FORMS
            or (c.get("run_on") == 2 and c.get("reference") in PLAYER_FORMS))


def parse_info(subs, fid: int) -> Dict:
    out = {"form_id": fid, "edid": "", "responses": [], "conditions": []}
    cur = None
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = _z(d)
        elif sig == b"TRDT" and len(d) >= 13:
            cur = {"emotion": struct.unpack_from("<I", d, 0)[0], "number": d[12], "text": None, "text_id": None}
            out["responses"].append(cur)
        elif sig == b"NAM1" and cur is not None:
            if len(d) == 4:
                cur["text_id"] = struct.unpack_from("<I", d, 0)[0]
            else:
                cur["text"] = _z(d)
        elif sig == b"CTDA":
            c = parse_condition(d)
            if c:
                out["conditions"].append(c)
    return out


def parse_topic(subs, fid: int) -> Dict:
    out = {"form_id": fid, "edid": "", "text": None, "text_id": None, "quest": None, "subtype": None,
           "subtype_code": ""}
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = _z(d)
        elif sig == b"FULL":
            if len(d) == 4:
                out["text_id"] = struct.unpack_from("<I", d, 0)[0]
            else:
                out["text"] = _z(d)
        elif sig == b"QNAM" and len(d) >= 4:
            out["quest"] = struct.unpack_from("<I", d, 0)[0]
        elif sig == b"DATA" and len(d) >= 4:
            out["subtype"] = struct.unpack_from("<H", d, 2)[0]
        elif sig == b"SNAM" and len(d) >= 4:
            out["subtype_code"] = d[:4].decode("latin-1")
    return out


def topics(esm_path: str) -> List[Dict]:
    """Every DIAL of the plugin with its INFOs (parse_topic + "infos": [parse_info])."""
    out, by_fid = [], {}
    with fo4land.Plugin(esm_path) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP" or item[3] != b"DIAL":
                continue
            for it in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if it[0] == "GRUP":
                    owner = struct.unpack_from("<I", it[3], 0)[0] if len(it[3]) == 4 else None
                    topic = by_fid.get(owner)
                    if topic is None or it[4] != 7:
                        continue
                    for r in fo4land.iter_items(p.buf, it[1] + 24, it[2]):
                        if r[0] == "GRUP" or r[0] != b"INFO":
                            continue
                        subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, r[1])))
                        topic["infos"].append(parse_info(subs, r[3]))
                    continue
                typ, off, _fl, fid = it
                if typ != b"DIAL":
                    continue
                t = parse_topic(list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off))), fid)
                t["infos"] = []
                by_fid[fid] = t
                out.append(t)
    return out


def read_lstrings(raw: bytes, length_prefixed: bool) -> Dict[int, str]:
    """A Skyrim string table: u32 count, u32 data size, count x (id, offset), then the strings (zero-terminated; in
    .DLSTRINGS / .ILSTRINGS each after a u32 length)."""
    if not raw or len(raw) < 8:
        return {}
    count, _size = struct.unpack_from("<II", raw, 0)
    base = 8 + 8 * count
    out = {}
    for i in range(count):
        sid, off = struct.unpack_from("<II", raw, 8 + 8 * i)
        p = base + off
        if p >= len(raw):
            continue
        if length_prefixed:
            n, = struct.unpack_from("<I", raw, p)
            s = raw[p + 4:p + 4 + n]
            s = s[:-1] if s.endswith(b"\0") else s
        else:
            end = raw.find(b"\0", p)
            s = raw[p:end if end >= 0 else len(raw)]
        out[sid] = s.decode("utf-8", "replace")
    return out


def response_texts(sky, language: str = "english") -> Dict[int, str]:
    """Skyrim.esm's dialogue response strings (strings\\skyrim_<language>.ilstrings: INFO texts; .dlstrings holds
    descriptions and book text: the owner's first run found 2,686 of those and no response text)."""
    raw = sky._read(f"strings\\skyrim_{language}.ilstrings") if hasattr(sky, "_read") else None
    return read_lstrings(raw, True) if raw else {}


def speaks(info: Dict, npc_fid: int, voice_fid: Optional[int]) -> Optional[str]:
    """How this NPC says the INFO: 'own' (a GetIsID condition on it), 'voice' (GetIsVoiceType its voice type, no
    GetIsID of anyone else), 'anyone' (no GetIsID / voice type condition), None (someone else's line)."""
    ids = [c["param1"] for c in info["conditions"] if c["function"] == GET_IS_ID and c["value"] == 1.0]
    vts = [c["param1"] for c in info["conditions"] if c["function"] == GET_IS_VOICE_TYPE and c["value"] == 1.0]
    if ids:
        return "own" if npc_fid in ids else None
    if vts:
        return "voice" if voice_fid in vts else None
    return "anyone"


def unpack_fuz(raw: bytes) -> Tuple[bytes, bytes]:
    """(lip, xwm) of a .fuz."""
    if raw[:4] != b"FUZE":
        raise ValueError("not a .fuz (no FUZE magic)")
    _ver, lip_size = struct.unpack_from("<II", raw, 4)
    return raw[12:12 + lip_size], raw[12 + lip_size:]


def voice_index(names: Iterable[str], plugin: str = "skyrim.esm") -> Dict[Tuple[str, int, int], str]:
    """{(voice type EditorID lower, INFO FormID, response number): archive path} of the .fuz / .xwm / .wav voice files
    of `plugin` among archive names."""
    out = {}
    rx = re.compile(r"sound[\\/]voice[\\/]" + re.escape(plugin.lower()) +
                    r"[\\/]([^\\/]+)[\\/][^\\/]*_([0-9a-f]{8})_(\d+)\.(fuz|xwm|wav)$")
    for n in names:
        m = rx.search(n.lower())
        if m:
            key = (m.group(1), int(m.group(2), 16), int(m.group(3)))
            if key not in out or m.group(4) == "fuz":
                out[key] = n
    return out


# ---------------------------------------------------------------------------------------- the world at game start
# 2026-11-10 (owner: converted NPCs say lines whose conditions were never met: Delphine about the dragon mounds before
# the main quest, Embry as if the player had romanced him). Starfield has none of Skyrim's quests, globals or
# relationships, so a line keeps its Skyrim conditions only as a decision made here: would it pass at the start of a
# new Skyrim game? Function indices from xEdit's wbDefinitionsTES5 condition table.
F = {"GetDistance": 1, "GetCurrentTime": 18, "GetDead": 46, "GetItemCount": 47, "GetQuestRunning": 56,
     "GetStage": 58, "GetStageDone": 59, "IsRaining": 62, "GetInCell": 67, "GetIsRace": 69, "GetIsSex": 70,
     "GetInFaction": 71, "GetIsID": 72, "GetFactionRank": 73, "GetGlobalValue": 74, "IsSnowing": 75,
     "GetRandomPercent": 77, "GetQuestVariable": 79, "GetLevel": 80, "GetDeadCount": 84, "GetCurrentAIPackage": 110,
     "IsGuard": 125, "GetPCIsClass": 129, "GetPCIsRace": 130, "GetPCIsSex": 131, "GetPCInFaction": 132,
     "IsTalking": 141, "GetCurrentAIProcedure": 143, "IsTrespassing": 145, "GetIsCurrentWeather": 149,
     "GetDayOfWeek": 170, "IsPCSleeping": 175, "IsPCAMurderer": 176, "GetEquipped": 182, "HasMagicEffect": 214,
     "IsInDialogueWithPlayer": 249, "GetLocationCleared": 250, "IsWeaponOut": 263, "IsHorseStolen": 282,
     "IsSneaking": 286, "IsInCombat": 289, "IsInInterior": 300, "GetInWorldspace": 310, "GetPCMiscStat": 312,
     "GetWithinPackageLocation": 325, "IsActor": 353, "GetInCurrentLoc": 359, "GetInCurrentLocAlias": 360,
     "IsChild": 365, "IsInList": 372, "GetCrimeGoldViolent": 375, "GetCrimeGoldNonviolent": 376,
     "IsBribedbyPlayer": 402, "GetRelationshipRank": 403, "GetIsVoiceType": 426, "GetHealthPercentage": 430,
     "HasPerk": 448, "GetPlayerTeammate": 453, "GetPlayerTeammateCount": 454, "GetCrimeGold": 459,
     "GetKeywordItemCount": 465, "GetQuestCompleted": 543, "HasKeyword": 560, "LocationHasKeyword": 562,
     "GetIsEditorLocation": 565, "GetIsAliasRef": 566, "IsInSameCurrentLocAsRef": 603,
     "IsInSameCurrentLocAsRefAlias": 604, "LocAliasHasKeyword": 610, "GetVMQuestVariable": 629,
     "WornHasKeyword": 682, "GetActorValue": 14}
NAME_OF = {v: k for k, v in F.items()}
# what changes during play without the story moving: time, weather, chance, where the NPC stands, combat, what it is
# doing. A line under these plays when they happen to hold; kept by default (verdict 'ambient')
AMBIENT = {F[n] for n in ("GetDistance", "GetCurrentTime", "IsRaining", "IsSnowing", "GetRandomPercent", "GetInCell",
                          "GetCurrentAIPackage", "IsTalking", "GetCurrentAIProcedure", "GetIsCurrentWeather",
                          "GetDayOfWeek", "IsWeaponOut", "IsSneaking", "IsInCombat", "IsInInterior",
                          "GetInWorldspace", "GetWithinPackageLocation", "GetInCurrentLoc", "LocationHasKeyword",
                          "IsInDialogueWithPlayer", "GetHealthPercentage", "IsPCSleeping", "IsInSameCurrentLocAsRef",
                          "HasMagicEffect", "GetIsEditorLocation")}
# what is 0 / false at the start of a new game: quests not begun, nobody dead, no crime, no followers, no misc stats
START_ZERO = {F[n] for n in ("GetStage", "GetStageDone", "GetQuestCompleted", "GetDead", "GetDeadCount",
                             "GetLocationCleared", "GetCrimeGold", "GetCrimeGoldViolent", "GetCrimeGoldNonviolent",
                             "IsPCAMurderer", "IsBribedbyPlayer", "GetPCMiscStat", "GetPlayerTeammate",
                             "GetPlayerTeammateCount", "IsHorseStolen", "IsTrespassing", "GetQuestVariable",
                             "GetVMQuestVariable")}
STORY_ALIAS = {F[n] for n in ("GetIsAliasRef", "GetInCurrentLocAlias", "IsInSameCurrentLocAsRefAlias",
                              "LocAliasHasKeyword")}
OPS = {0: lambda a, b: a == b, 1: lambda a, b: a != b, 2: lambda a, b: a > b, 3: lambda a, b: a >= b,
       4: lambda a, b: a < b, 5: lambda a, b: a <= b}
QUEST_START_ENABLED = 0x0001


class World:
    """Skyrim at the start of a new game: quests that run from the start (QUST DNAM flag 0x1), global values (GLOB
    FLTV), each NPC's factions / race / sex / voice (skyrimnpc.parse_npc rows by FormID), form lists (FLST LNAM),
    quest dialogue conditions (QUST CTDA before NEXT)."""

    def __init__(self, quests=None, globals_=None, npcs=None, lists=None, quest_conditions=None):
        self.quests = quests or {}                  # {fid: flags}
        self.globals = globals_ or {}               # {fid: value}
        self.npcs = npcs or {}                      # {fid: parse_npc row}
        self.lists = lists or {}                    # {fid: [fids]}
        self.quest_conditions = quest_conditions or {}

    def running(self, quest_fid) -> bool:
        return bool(self.quests.get(quest_fid, 0) & QUEST_START_ENABLED)


def world_from(esm_path: str, npcs: Optional[Dict[int, Dict]] = None) -> World:
    from . import sfplugin
    quests, qconds, globs, lists = {}, {}, {}, {}
    for t, _h, subs, fid in sfplugin.records(esm_path, [b"QUST", b"GLOB", b"FLST"]):
        if t == b"QUST":
            conds = []
            for s, d in subs:
                d = bytes(d)
                if s == b"DNAM" and len(d) >= 2:
                    quests[fid] = struct.unpack_from("<H", d, 0)[0]
                elif s == b"CTDA":
                    c = parse_condition(d)
                    if c:
                        conds.append(c)
                elif s == b"NEXT":
                    break                         # the story manager's conditions follow
            quests.setdefault(fid, 0)
            if conds:
                qconds[fid] = conds
        elif t == b"GLOB":
            v = next((bytes(d) for s, d in subs if s == b"FLTV" and len(d) >= 4), None)
            if v is not None:
                globs[fid] = struct.unpack_from("<f", v, 0)[0]
        else:
            lists[fid] = [struct.unpack_from("<I", bytes(d), 0)[0] for s, d in subs if s == b"LNAM" and len(d) >= 4]
    return World(quests, globs, npcs or {}, lists, qconds)


def _actor(c, speaker, world):
    """The NPC row a condition is run on: the speaker (subject), the player (target, in greetings) or a named
    reference to the player; None otherwise."""
    run_on = c.get("run_on", 0)
    if run_on == 0:
        return speaker
    if run_on == RUN_ON_TARGET or (run_on == 2 and c.get("reference") in PLAYER_FORMS):
        return world.npcs.get(0x7, {"form_id": 0x7, "factions": [], "player": True})
    return None


def evaluate(c: Dict, speaker: Dict, world: World) -> Tuple[Optional[bool], str]:
    """(True / False / None, kind) of one condition at the start of a new game; kind 'start' (decided), 'ambient'
    (varies in play, AMBIENT), 'player' (the player's race / sex / class: chosen later), 'story' (quest aliases,
    relationships with others: unknown), 'unknown' (a function not modelled)."""
    f = c.get("function")
    op = OPS.get(c.get("op", 0), OPS[0])
    want = c.get("value")
    if c.get("use_global"):
        want = world.globals.get(int(want))
        if want is None:
            return None, "unknown"
    p1 = c.get("param1")
    if f in AMBIENT:
        return None, "ambient"
    if f in (F["GetPCIsRace"], F["GetPCIsSex"], F["GetPCIsClass"]):
        return None, "player"
    if f in START_ZERO:
        return op(0.0, want), "start"
    if f in STORY_ALIAS:
        return None, "story"
    who = _actor(c, speaker, world)
    if f == F["GetQuestRunning"]:
        return op(1.0 if world.running(p1) else 0.0, want), "start"
    if f == F["GetGlobalValue"]:
        if p1 not in world.globals:
            return None, "unknown"
        return op(world.globals[p1], want), "start"
    if f == F["IsActor"]:
        return op(1.0 if who is not None else 0.0, want), "start"
    if who is None:
        return None, "story"
    player = bool(who.get("player")) or who.get("form_id") == 0x7
    if f == F["GetIsID"]:
        return op(1.0 if who.get("form_id") == p1 else 0.0, want), "start"
    if f == F["GetIsVoiceType"]:
        if player:
            return None, "player"
        vts = world.lists.get(p1, [p1])
        return op(1.0 if who.get("voice") in vts else 0.0, want), "start"
    if f in (F["GetIsRace"], F["GetIsSex"]):
        if player:
            return None, "player"
        have = who.get("race") == p1 if f == F["GetIsRace"] else int(bool(who.get("female"))) == p1
        return op(1.0 if have else 0.0, want), "start"
    if f in (F["GetInFaction"], F["GetFactionRank"], F["GetPCInFaction"]):
        if f == F["GetPCInFaction"]:
            who = world.npcs.get(0x7, {"factions": []})
        ranks = dict(who.get("factions", []))
        if f == F["GetFactionRank"]:
            return op(float(ranks.get(p1, -1)), want), "start"
        return op(1.0 if p1 in ranks else 0.0, want), "start"
    if f == F["GetRelationshipRank"]:
        if player or p1 in PLAYER_FORMS:
            return op(0.0, want), "start"           # strangers: acquaintance (0) with everyone at the start
        return None, "story"
    if f == F["IsInList"]:
        if p1 not in world.lists:
            return None, "unknown"
        return op(1.0 if who.get("form_id") in world.lists[p1] else 0.0, want), "start"
    if f == F["HasPerk"] and player:
        return op(0.0, want), "start"
    if f == F["GetLevel"] and player:
        return op(1.0, want), "start"
    return None, "unknown"


def verdict(info: Dict, speaker: Dict, world: World, quest: Optional[int] = None,
            lenient=frozenset({"ambient"})) -> Tuple[str, List[str]]:
    """('keep' | 'ambient' | 'drop', reasons) of an INFO said by speaker at the start of a new game: its topic's quest
    must run from the start, and the quest's dialogue conditions with the INFO's own (AND of OR groups, as the
    engine reads them: a condition with the OR flag joins the next one) must pass. Undecided groups: 'ambient' when
    only ambient conditions are undecided (kept: they hold some of the time), else 'drop'."""
    reasons = []
    if quest is not None and not world.running(quest):
        return "drop", [f"quest {quest:08X} not running at the start"]
    conds = list(world.quest_conditions.get(quest, [])) + list(info.get("conditions", []))
    groups, cur = [], []
    for c in conds:
        cur.append(c)
        if not c.get("or"):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    undecided = set()
    for g in groups:
        vals = [(evaluate(c, speaker, world), c) for c in g]
        if any(v is True for (v, _k), _c in vals):
            continue
        open_ = [(k, c) for (v, k), c in vals if v is None]
        if not open_:
            c = g[0]
            reasons.append(f"{NAME_OF.get(c['function'], c['function'])}({c.get('param1', 0):08X}) fails at start")
            return "drop", reasons
        undecided |= {k for k, _c in open_}
        reasons += [f"{NAME_OF.get(c['function'], c['function'])} {k}" for k, c in open_]
    if not undecided:
        return "keep", reasons
    return ("ambient", reasons) if undecided <= set(lenient) else ("drop", reasons)
