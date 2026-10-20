"""BFCO / MCO attack annotations -> Starfield attack descriptor windows and combo routing.

Read 2026-10-19 from the clips BFCO ships (nexusmods.com/skyrimspecialedition/mods/117052; format only, nothing
copied), all inside each attack clip's annotations (times in seconds):
  BFCO_NextIsAttackN / BFCO_NextIsPowerAttackN (at 0)   which normal / power attack a press leads to next
                                                        (1hm-sword-base: 1 -> 2 -> 3 -> 4 -> 5 -> 2, an endless chain)
  BFCO_NextWinStart, BFCO_NextPowerWinStart             the next normal / power attack may start from here
    (MCO-era packs, e.g. its 2hm set: MCO_WinOpen / MCO_PowerWinOpen with MCO_WinClose / MCO_PowerWinClose)
  BFCO_DIY_EndLoop                                      the window closes (with MCO_WinClose where both exist)
  BFCO_DIY_recovery (also spelled BFCO_DIY_Rcovery), MCO_Recovery
                                                        recovery: moving now cancels the attack
  HitFrame / preHitFrame / weaponSwing (+ weaponLeftSwing) as in vanilla Skyrim.
MCO / DAR movesets route through Payload Interpreter instructions instead (verified 2026-10-20 on the owner's Nordic
Combat Animations and LoreRim MCO packs, read for the format only): `PIE.@SGVI|MCO_nextattack|N` and
`PIE.@SGVI|MCO_nextpowerattack|N` at 0.06 s (the next normal / power attack; a graph, not an order: Nordic's 1H set
goes 1 -> 2 -> 3 -> 4 -> 5 -> 1 and never plays its attack 6) and `PIE.@SGVF|MCO_AttackSpeed|S` (the attack's playback
speed, 0.7 - 1.5 seen). Payload Interpreter instructions are case sensitive and unknown ones do nothing, so the
misspelt `@SVGF|MCO_AttackSpeed|...` in 1,270 LoreRim clips is taken as not setting the speed (supported hypothesis).

Starfield equivalents (verified on the vanilla player one-handed descriptors, see combo_loop.py): bCanComboAttack is
the next-attack window, bDontAllowAttack / bDontAllowPowerAttack lock attacks before it, AttackStateNextAttack marks
where the queued attack starts, and bFreeMovement (with DisableAllowRotation) opens the late window in which moving
leaves the attack (MeleeAttacks: "None" on Speed > 1.0 and bFreeMovement). The mapping below is a supported
hypothesis until checked in game.
"""
import re
from typing import Dict, List

from . import af_writer

NEXT_ATTACK = re.compile(r"^BFCO_NextIsAttack(\d+)$", re.I)
NEXT_POWER = re.compile(r"^BFCO_NextIsPowerAttack(\d+)$", re.I)
PAYLOAD = re.compile(r"^[^@]*?\.@(\w+)((?:\|[^|]*)*)$")
SPEED_VARIABLES = ("MCO_AttackSpeed", "BFCO_AttackSpeed")
WIN_OPEN = ("bfco_nextwinstart", "mco_winopen")
POWER_WIN_OPEN = ("bfco_nextpowerwinstart", "mco_powerwinopen")
WIN_CLOSE = ("bfco_diy_endloop", "mco_winclose")
POWER_WIN_CLOSE = ("bfco_diy_endloop", "mco_powerwinclose")
RECOVERY = ("bfco_diy_recovery", "bfco_diy_rcovery", "mco_recovery")


def payload(text: str):
    """(instruction, [args]) of a Payload Interpreter annotation such as `PIE.@SGVI|MCO_nextattack|2`, else None."""
    m = PAYLOAD.match((text or "").strip())
    if not m:
        return None
    return m.group(1), [x.strip() for x in m.group(2).split("|")[1:]]


def markers(annotations) -> Dict:
    """The BFCO / MCO markers of one clip: {"next_attack", "next_power" (int or None), "win", "power_win",
    "win_close", "power_win_close", "recovery", "hits" (times), "speed" (float or None)}."""
    out = {"next_attack": None, "next_power": None, "win": None, "power_win": None, "win_close": None,
           "power_win_close": None, "recovery": None, "hits": [], "speed": None}

    def first(key, t):
        if out[key] is None or t < out[key]:
            out[key] = t
    for a in annotations or []:
        text, t = (a.get("text") or "").strip(), float(a.get("time", 0.0))
        low = text.lower()
        pl = payload(text)
        if pl and len(pl[1]) >= 2:
            instr, (var, val) = pl[0], pl[1][:2]
            try:
                if instr == "SGVI" and var.lower() in ("mco_nextattack", "mco_nextpowerattack"):
                    out["next_attack" if var.lower() == "mco_nextattack" else "next_power"] = int(float(val))
                elif instr == "SGVF" and var in SPEED_VARIABLES:
                    out["speed"] = float(val)
            except ValueError:
                pass
            continue
        m = NEXT_ATTACK.match(text)
        if m:
            out["next_attack"] = int(m.group(1))
            continue
        m = NEXT_POWER.match(text)
        if m:
            out["next_power"] = int(m.group(1))
            continue
        if low in WIN_OPEN:
            first("win", t)
        if low in POWER_WIN_OPEN:
            first("power_win", t)
        if low in RECOVERY:
            first("recovery", t)
        if low == "hitframe":
            out["hits"].append(t)
    for a in annotations or []:                      # closes count only after their window opened
        low, t = (a.get("text") or "").strip().lower(), float(a.get("time", 0.0))
        if low in WIN_CLOSE and out["win"] is not None and t > out["win"]:
            out["win_close"] = t if out["win_close"] is None else min(out["win_close"], t)
        if low in POWER_WIN_CLOSE and out["power_win"] is not None and t > out["power_win"]:
            out["power_win_close"] = t if out["power_win_close"] is None else min(out["power_win_close"], t)
    out["hits"].sort()
    return out


def is_attack(m: Dict) -> bool:
    return any(m[k] is not None for k in ("next_attack", "next_power", "win", "power_win", "recovery"))


def windows(m: Dict, last: int, fps: float = 30.0) -> Dict[str, tuple]:
    """Starfield variable windows (frame start, end) for a clip of `last` + 1 frames."""
    f = lambda t: max(0, min(last, int(round(t * fps))))        # noqa: E731
    out = {}
    if m["win"] is not None:
        # Vanilla (sword A): bCanComboAttack 6-22 and AttackStateNextAttack at 22 - presses inside the window queue,
        # and the queued attack starts where the window ENDS. Owner, in game, 2026-10-19: a window left open to the
        # clip's end replayed attack 1 on every press (the queue fired only after the clip, as a fresh attack). So
        # the window ends at BFCO's NextWinStart. Presses queue from 0.2 s in (vanilla: frame 6) or 0.6 s before
        # the window, whichever is later - a window from the hit was only 3 frames wide. A press after
        # NextWinStart starts the chain again, unlike BFCO's late window (to EndLoop).
        buffer = min(m["win"], max(0.2, m["win"] - 0.6))
        out["bDontAllowAttack"] = (0, f(buffer))
        out["bCanComboAttack"] = (f(buffer), f(m["win"]))
    else:                                                       # no follow-up: attacks stay locked to the end
        out["bDontAllowAttack"] = (0, last)
    out["bDontAllowPowerAttack"] = (0, f(m["power_win"]) if m["power_win"] is not None else last)
    if m["recovery"] is not None:
        out["bFreeMovement"] = (f(m["recovery"]), last)
        out["DisableAllowRotation"] = (f(m["recovery"]), last)
    return out


def apply(afx: bytes, m: Dict, last: int, fps: float = 30.0) -> bytes:
    """The descriptor with the BFCO windows and AttackStateNextAttack at the window's start (when there is one)."""
    for name, (a, b) in windows(m, last, fps).items():
        afx = af_writer.set_variable_window(afx, name, a, b)
    # BFCO has no finisher; a vanilla B template's bAllowFinisher makes the game send MeleeAttackFinisherStart and
    # end the combo after C (owner, in game: the chain stopped after three swings until this was dropped)
    afx, _gone = af_writer.drop_variables(afx, {"bAllowFinisher"})
    if m["win"] is not None:
        afx = af_writer.set_event_frame(afx, "AttackStateNextAttack", max(0, min(last, int(round(m["win"] * fps)))))
    return afx


def chain(attacks: Dict[int, Dict], key: str = "next_attack") -> Dict[int, int]:
    """Routing {k: next k} from the markers of clips 1..N (key "next_attack" for the next normal attack, "next_power"
    for the next power attack). With routing on any clip (BFCO_NextIsAttackN, MCO_nextattack payloads), a missing or
    unknown target goes back to 1; without any (older MCO sets), k -> k + 1 and the last back to 1."""
    routed = any(m.get(key) is not None for m in attacks.values())
    first = 1 if 1 in attacks else min(attacks)
    out = {}
    for k, m in attacks.items():
        n = m.get(key)
        if not routed:
            n = k + 1
        out[k] = n if n in attacks else first
    return out


def cross(marks: Dict[int, Dict], key: str, targets) -> Dict[int, int]:
    """{k: target} for routing from one group into another (normal attack -> next power attack, power -> next normal):
    marks[k][key] when it names one of `targets`, else the first target. Empty when no clip routes this way."""
    targets = sorted(targets)
    if not targets or not any(m.get(key) is not None for m in marks.values()):
        return {}
    return {k: (m.get(key) if m.get(key) in targets else targets[0]) for k, m in marks.items()}


def routes(attacks: Dict[int, Dict], powers: Dict[int, Dict]) -> Dict[str, Dict[int, int]]:
    """The whole MCO / BFCO routing over normal attacks and power attacks, restricted to what the player can reach
    from a first normal attack and a first power attack (attack 1 and power attack 1 when present):
    {"attack": k -> next normal, "attack_power": k -> next power, "power_attack": p -> next normal,
     "power_power": p -> next power}."""
    a = chain(attacks, "next_attack") if attacks else {}
    pp = chain(powers, "next_power") if powers and any(m.get("next_power") is not None for m in powers.values()) else {}
    ap = cross(attacks, "next_power", powers) if powers else {}
    pa = cross(powers, "next_attack", attacks) if attacks and powers else {}
    seen_a, seen_p = set(), set()
    todo = []
    if a:
        todo.append(("a", 1 if 1 in a else min(a)))
    if powers:
        todo.append(("p", 1 if 1 in powers else min(powers)))
    while todo:
        kind, k = todo.pop()
        seen = seen_a if kind == "a" else seen_p
        if k in seen:
            continue
        seen.add(k)
        if kind == "a":
            if k in a:
                todo.append(("a", a[k]))
            if k in ap:
                todo.append(("p", ap[k]))
        else:
            if k in pa:
                todo.append(("a", pa[k]))
            if k in pp:
                todo.append(("p", pp[k]))
    return {"attack": {k: v for k, v in a.items() if k in seen_a},
            "attack_power": {k: v for k, v in ap.items() if k in seen_a},
            "power_attack": {k: v for k, v in pa.items() if k in seen_p},
            "power_power": {k: v for k, v in pp.items() if k in seen_p},
            "powers": sorted(seen_p)}


def reachable(routing: Dict[int, int], start: int = 1) -> List[int]:
    """The attacks a chain actually plays from `start`, in order of first visit."""
    seen, k = [], start
    while k in routing and k not in seen:
        seen.append(k)
        k = routing[k]
    return seen


def attack_files(names: List[str]) -> Dict[str, Dict[int, str]]:
    """Group a moveset folder's clips: {"attack": {N: file}, "power": {N: file}, "other": {stem: file}}; BFCO
    (BFCO_AttackN / BFCO_PowerAttackN) and MCO / DAR (mco_attackN / mco_powerattackN) names."""
    out = {"attack": {}, "power": {}, "other": {}}
    for n in names:
        stem = n.rsplit(".", 1)[0]
        m = re.match(r"^(?:BFCO|MCO)_Attack(\d+)$", stem, re.I)
        p = re.match(r"^(?:BFCO|MCO)_PowerAttack(\d+)$", stem, re.I)
        if m:
            out["attack"][int(m.group(1))] = n
        elif p:
            out["power"][int(p.group(1))] = n
        elif n.lower().endswith(".hkx"):
            out["other"][stem] = n
    return out
