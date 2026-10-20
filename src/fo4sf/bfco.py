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
WIN_OPEN = ("bfco_nextwinstart", "mco_winopen")
POWER_WIN_OPEN = ("bfco_nextpowerwinstart", "mco_powerwinopen")
WIN_CLOSE = ("bfco_diy_endloop", "mco_winclose")
POWER_WIN_CLOSE = ("bfco_diy_endloop", "mco_powerwinclose")
RECOVERY = ("bfco_diy_recovery", "bfco_diy_rcovery", "mco_recovery")


def markers(annotations) -> Dict:
    """The BFCO / MCO markers of one clip: {"next_attack", "next_power" (int or None), "win", "power_win",
    "win_close", "power_win_close", "recovery", "hits" (times)}."""
    out = {"next_attack": None, "next_power": None, "win": None, "power_win": None, "win_close": None,
           "power_win_close": None, "recovery": None, "hits": []}

    def first(key, t):
        if out[key] is None or t < out[key]:
            out[key] = t
    for a in annotations or []:
        text, t = (a.get("text") or "").strip(), float(a.get("time", 0.0))
        low = text.lower()
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


def chain(attacks: Dict[int, Dict]) -> Dict[int, int]:
    """Normal-attack routing {k: next k} from the markers of attacks 1..N; a missing or unknown target goes back to 1."""
    out = {}
    for k, m in attacks.items():
        n = m.get("next_attack")
        out[k] = n if n in attacks else (1 if 1 in attacks else min(attacks))
    return out


def attack_files(names: List[str]) -> Dict[str, Dict[int, str]]:
    """Group a moveset folder's clips: {"attack": {N: file}, "power": {N: file}, "other": {stem: file}}."""
    out = {"attack": {}, "power": {}, "other": {}}
    for n in names:
        stem = n.rsplit(".", 1)[0]
        m = re.match(r"^BFCO_Attack(\d+)$", stem, re.I)
        p = re.match(r"^BFCO_PowerAttack(\d+)$", stem, re.I)
        if m:
            out["attack"][int(m.group(1))] = n
        elif p:
            out["power"][int(p.group(1))] = n
        elif n.lower().endswith(".hkx"):
            out["other"][stem] = n
    return out
