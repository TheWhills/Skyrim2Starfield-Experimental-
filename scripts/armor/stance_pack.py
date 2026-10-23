"""A stance moveset pack: several MCO / BFCO movesets of one weapon (LoreRim's Novice / Apprentice / Adept / Expert =
neutral / low / mid / high stance), switched in game by the stance keyword (stance_plugin.py, S2SCombat key bindings).

The neutral moveset goes where a normal pack puts it (the vanilla player folders); every other stance goes into its
own folder (stance_plugin.stance_folder: actors\\human\\animations\\melee\\s2s_stances\\<stance>), under the same file
names and tags, so the stance's HumanRace entry finds its clips first and anything it lacks in the vanilla folders.

One combo graph serves every stance, so the stances share its shape: N attack slots in a ring (slot 1 -> 2 -> ...
-> N -> 1, N = the longest stance chain that fits the slots). Each stance fills the ring with its own chain followed
from attack 1 (LoreRim sword high: 1 2 3 4 5 2 3 ...), so its order is kept except where the ring closes (reported as
"wrap": the slot after N is attack 1 instead of the chain's next). Power attacks (BFCO / MCO: which power attack
follows depends on the normal attack before it, e.g. LoreRim sword high: after attack 1 power 2, after 2 power 3):
ring slot j gets its own power state (a host + pool tag, like the extra normal slots) that each stance fills with the
power attack its routing gives after the attack it plays in slot j; slots without a free host fall back to the vanilla
power attack (each stance's power attack 1, also the power attack from standing). After power slot j a normal press
goes on to ring slot j + 1, another power press to power slot j + 1.

    python -I scripts\\armor\\stance_pack.py --stance Neutral=<folder> --stance Low=<folder> --stance Mid=<folder>
        --stance High=<folder> --anims <vanilla extract> --folder melee/onehanded/player/sword
        --folder melee/onehanded/player --graph <meleeattacks.agx> --out <pack> [hkx_to_af options ...]
"""
import argparse
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import animslots, bfco  # noqa: E402
import bfco_combo  # noqa: E402
import bfco_pack  # noqa: E402
import hkx_to_af  # noqa: E402
import stance_plugin  # noqa: E402

NEUTRAL = "Neutral"


def unroll(routing: dict, n: int, start: int = 1) -> list:
    """The first n attacks of a chain {k: next k} followed from start (repeats where the chain loops)."""
    out, k = [], start if start in routing else min(routing)
    for _ in range(n):
        out.append(k)
        k = routing.get(k, start)
    return out


def ring_slots(chains: dict, folders, anims: str, starfield_data=None, limit=None):
    """(N, {folder: {slot: (stem, tag, rekey)}}): N = the longest chain (distinct attacks) that every folder can hold."""
    want = max(len(c) for c in chains.values())
    if limit:
        want = min(want, limit)
    stems_of = {f: [s for s in animslots.HOSTS + [c for c, _t in animslots.COMBO]
                    if bfco_pack.exists(bfco_pack.anim_path(anims, f, s), starfield_data)] for f in folders}
    for n in range(want, 0, -1):
        try:
            slots = {f: animslots.allocate(n, stems_of[f]) for f in folders}
        except animslots.SlotError:
            continue
        tags = {f: {j: v[1] for j, v in s.items()} for f, s in slots.items()}
        if len({tuple(sorted(t.items())) for t in tags.values()}) != 1:
            raise SystemExit(f"the folders give the slots different tags: {tags}")
        return n, slots
    raise SystemExit("no attack slots in the folders")


def power_slots(n: int, folders, anims: str, starfield_data=None):
    """{j: (host stem, tag, folder)} for power slots 1..m (m <= n): hosts the n normal slots left free, from the first
    folder that has each (the player's sword folder has only the sneak variants, its parent folder also the zero-g
    ones; a tag missing from the sword folder is found in the parent, as the vanilla folders are listed in order),
    power descriptors first, tags from the pool after the ones the normal slots use."""
    free, used_tags = [], 0
    for f in folders:
        have = [s for s in animslots.HOSTS if bfco_pack.exists(bfco_pack.anim_path(anims, f, s), starfield_data)]
        used = {stem for stem, _t, rekey in animslots.allocate(n, have + [c for c, _t in animslots.COMBO]).values()
                if rekey}
        used_tags = max(used_tags, len(used))
        for h in have:
            if h not in used and all(h != x for x, _f in free):
                free.append((h, f))
    free.sort(key=lambda hf: "power" not in hf[0])
    tags = animslots.TAG_POOL[used_tags:]
    m = min(n, len(free), len(tags))
    return {j: (free[j - 1][0], tags[j - 1], free[j - 1][1]) for j in range(1, m + 1)}


def plan(stances: dict, folders, anims: str, starfield_data=None, limit=None):
    """({stance: {"sequence", "wrap", "replace": [hkx_to_af --replace specs], "folders", "powers"}}, N, tags {slot: tag},
    power {j: (host, tag, folder)}); "folders": the vanilla folders whose converted clips a stance moves into its
    stance folder."""
    chains = {s: bfco_combo.routing_of(f) for s, f in stances.items()}
    after = {s: bfco_combo.routes_of(f).get("attack_power", {}) for s, f in stances.items()}
    empty = [s for s, c in chains.items() if not c]
    if empty:
        raise SystemExit(f"no BFCO_AttackN / mco_attackN clips for {', '.join(empty)}")
    n, slots = ring_slots(chains, folders, anims, starfield_data, limit)
    pslots = power_slots(n, folders, anims, starfield_data)
    out = {}
    for stance, folder in stances.items():
        names = sorted(os.listdir(folder))
        grouped = bfco.attack_files(names)
        seq = unroll(chains[stance], n)
        nxt = chains[stance].get(seq[-1])
        wrap = None if nxt == seq[0] else {"after": seq[-1], "chain_next": nxt, "ring_next": seq[0]}
        use = folders if stance == NEUTRAL else folders[:1]       # stances: one folder's worth, moved later
        replace = []
        for f in use:
            for j, (stem, tag, rekey) in slots[f].items():
                clip = os.path.join(folder, grouped["attack"][seq[j - 1]])
                replace.append(f"{clip}::{bfco_pack.anim_path(anims, f, stem)}" + (f"::tag:{tag}" if rekey else ""))
            p = grouped["power"].get(1)
            if p and bfco_pack.exists(bfco_pack.anim_path(anims, f, "meleeattackpower_a"), starfield_data):
                replace.append(f"{os.path.join(folder, p)}::{bfco_pack.anim_path(anims, f, 'meleeattackpower_a')}")
            s = bfco_pack.pick(names, "BFCO_SprintAttack") or bfco_pack.pick(names, "mco_sprintattack")
            if s and bfco_pack.exists(bfco_pack.anim_path(anims, f, "meleeattacksprint"), starfield_data):
                replace.append(f"{os.path.join(folder, s)}::{bfco_pack.anim_path(anims, f, 'meleeattacksprint')}")
        powers, move = {}, list(use)
        for j, (host, ptag, hf) in pslots.items():                  # the power attack after slot j's attack
            q = after[stance].get(seq[j - 1], 1)
            clip = grouped["power"].get(q) or grouped["power"].get(1)
            if clip:
                powers[j] = q
                replace.append(f"{os.path.join(folder, clip)}::{bfco_pack.anim_path(anims, hf, host)}::tag:{ptag}")
                if hf not in move:
                    move.append(hf)
        out[stance] = {"sequence": seq, "wrap": wrap, "replace": replace, "folders": move,
                       "chain": chains[stance], "powers": powers}
    tags = {j: v[1] for j, v in slots[folders[0]].items()}
    return out, n, tags, pslots


def power_routing(n: int, pslots: dict) -> dict:
    """bfco_combo.build's power argument for the shared graph: ring slot j -> power slot j; slots without a power slot
    of their own -> a power state on the vanilla tag (MeleeAttackPower_A: each stance's power attack 1), so every
    slot has its own power transition and the vanilla combo -> power transition can be switched off (inner_only).
    After power slot j a normal press goes to ring slot j + 1 and a power press to power slot j + 1 (wrapping)."""
    m = len(pslots)
    if not m:
        return None
    tags = {j: v[1] for j, v in pslots.items()}
    attack_power = {j: j for j in range(1, m + 1)}
    if m < n:
        tags[m + 1] = bfco_combo.POWER_TOP
        attack_power.update({j: m + 1 for j in range(m + 1, n + 1)})
    k = len(tags)
    return {"tags": tags, "attack_power": attack_power,
            "power_attack": {p: (p if p <= m else n) % n + 1 for p in tags},
            "power_power": {p: p % k + 1 for p in tags}, "inner_only": True}


def _move_into_stance(tmp: str, folder: str, out: str, stance: str) -> int:
    """Move the converted clips of `folder` (Data-relative under meshes/actors/human/animations) into the stance's
    folder of the pack (flat: the stance entries list that folder first, owner's run 2026-10-23 showed a subfolder is
    not searched); returns how many files."""
    src = os.path.join(tmp, *bfco_pack.ANIMS.split("/"), *folder.split("/"))
    dst = os.path.join(out, "meshes", *stance_plugin.stance_folder(stance).split("\\"))
    os.makedirs(dst, exist_ok=True)
    n = 0
    for fn in os.listdir(src) if os.path.isdir(src) else []:
        if fn.lower().endswith((".af", ".afx")):
            shutil.move(os.path.join(src, fn), os.path.join(dst, fn))
            n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stance", action="append", required=True, metavar="NAME=FOLDER",
                    help=f"a moveset per stance: {NEUTRAL} (vanilla folders) and any of {', '.join(stance_plugin.STANCES)}")
    ap.add_argument("--anims", required=True)
    ap.add_argument("--folder", action="append", required=True, help="vanilla player folders, most specific first")
    ap.add_argument("--graph", required=True, help="the vanilla MeleeAttacks.agx")
    ap.add_argument("--out", required=True)
    ap.add_argument("--slots", type=int, help="at most this many attack slots in the ring")
    ap.add_argument("--starfield-data")
    a, rest = ap.parse_known_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    stances = {}
    for spec in a.stance:
        name, _, folder = spec.partition("=")
        name = name.strip().capitalize()
        if name != NEUTRAL and name not in stance_plugin.STANCES or not os.path.isdir(folder):
            sys.exit(f"--stance wants NAME=FOLDER with NAME {NEUTRAL} or one of {stance_plugin.STANCES}; got {spec}")
        stances[name] = folder
    p, n, tags, pslots = plan(stances, a.folder, a.anims, a.starfield_data, a.slots)
    print(f"ring of {n} slots: " + ", ".join(f"{j}:{t}" for j, t in sorted(tags.items())))
    print(f"power slots: " + (", ".join(f"after {j}: {t} (on {h})" for j, (h, t, _f) in sorted(pslots.items()))
                              or "none (no free hosts): the vanilla power attack after every slot"))
    rc = 0
    for stance, st in p.items():
        print(f"{stance}: powers after slots {st['powers']}")
        print(f"{stance}: chain {st['chain']} -> slots {st['sequence']}"
              + (f" (wrap: after {st['wrap']['after']} the chain goes to {st['wrap']['chain_next']}, the ring to "
                 f"{st['wrap']['ring_next']})" if st["wrap"] else ""))
        base = ["--weapon-in-hand", "--bfco"] + (["--starfield-data", a.starfield_data] if a.starfield_data else [])
        specs = [x for r in st["replace"] for x in ("--replace", r)]
        if stance == NEUTRAL:
            rc |= hkx_to_af.main(rest + ["--out", out] + base + specs)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                rc |= hkx_to_af.main(rest + ["--out", tmp] + base + specs)
                moved = sum(_move_into_stance(tmp, f, out, stance) for f in st["folders"])
            print(f"{stance}: {moved} files in {stance_plugin.stance_folder(stance)}")
    with open(a.graph, "rb") as fh:
        data, added = bfco_combo.build(fh.read(), {j: j % n + 1 for j in range(1, n + 1)}, tags,
                                       power_routing(n, pslots))
    dst = os.path.join(out, *bfco_combo.GRAPH_REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)
    print(f"graph {dst}: {added}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
