"""Build a Starfield pack from a BFCO or MCO / DAR moveset folder (BFCO_AttackN or mco_attackN clips) (docs/armor/animation-port.md, "BFCO plan"): every attack with
its root motion and BFCO windows, the moveset's routing as the player's combo, its power and sprint attacks.

Attacks 1-3 replace the folder's vanilla MeleeAttack_A / B / C; attacks 4.. reuse existing descriptor paths re-keyed
under tags the game knows (fo4sf.animslots: the sneak / zero-g attack variants are given up). The combo graph is
scripts/armor/bfco_combo.py's, with those tags. Runs hkx_to_af (same options) once for all folders.

    python -I scripts\\armor\\bfco_pack.py --moveset "<BFCO>\\1hm-sword-base" --anims "<extract or archive root>"
        --folder melee/onehanded/player/sword --folder melee/onehanded/player --graph <meleeattacks.agx>
        --calumi ... --skyrim-skeleton ... --starfield-skeleton ... --starfield-rig ... [--starfield-data ...] --out <pack>
--anims is the folder holding meshes/actors/human/animations (an extract), or that Data-relative path itself
("meshes/actors/human/animations") with --starfield-data to read the archives.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import animslots, bfco  # noqa: E402
import bfco_combo  # noqa: E402
import hkx_to_af  # noqa: E402

ANIMS = "meshes/actors/human/animations"


def anim_path(anims: str, folder: str, stem: str) -> str:
    base = anims.rstrip("/\\")
    if not base.replace("\\", "/").lower().endswith(ANIMS):
        base = os.path.join(base, *ANIMS.split("/"))
    return os.path.join(base, *folder.split("/"), stem + ".afx")


def exists(path: str, starfield_data) -> bool:
    if os.path.isfile(path):
        return True
    if not starfield_data:
        return False
    try:
        hkx_to_af.vanilla_file(path, starfield_data)
        return True
    except SystemExit:
        return False


def pick(names, stem: str):
    """The moveset file whose stem is `stem` (any case), or None."""
    return next((n for n in names if n.rsplit(".", 1)[0].lower() == stem.lower()), None)


def plan(moveset: str, folders, anims: str, starfield_data=None, power=None, sprint=None):
    """(hkx_to_af --replace list, {k: tag}, report, {p: power tag}). With MCO / BFCO power routing in the moveset
    (bfco.routes), power attacks get slots too: the first on the vanilla meleeattackpower_a (tag MeleeAttackPower_A,
    also the standing power attack), the others on the spare hosts left after the normal attacks, as many as every
    folder has room for (the rest fall back to the first in the graph)."""
    names = sorted(os.listdir(moveset))
    grouped = bfco.attack_files(names)
    n = len(grouped["attack"])
    if not n or sorted(grouped["attack"]) != list(range(1, n + 1)):
        raise SystemExit(f"attacks must be BFCO_Attack1..N / mco_attack1..N without gaps, found {sorted(grouped['attack'])}")
    r = bfco_combo.routes_of(moveset)
    routed_power = bool(r["attack_power"] or r["power_attack"] or r["power_power"]) and not power
    keys = sorted(r["attack"]) if routed_power else sorted(bfco_combo.routing_of(moveset))
    powers = r["powers"] if routed_power else []
    stems_of = {f: [s for s in animslots.HOSTS + [c for c, _t in animslots.COMBO]
                    if exists(anim_path(anims, f, s), starfield_data)] for f in folders}
    chain = r["attack"] if routed_power else bfco_combo.routing_of(moveset)
    order = bfco.reachable(chain, 1 if 1 in chain else min(chain)) if chain else []
    order += [k for k in keys if k not in order]                # reachable only through power attacks
    cap = len(keys)
    while cap > 1:                                              # more attacks than slots: keep the chain's first ones
        try:
            for f in folders:
                animslots.allocate(cap, stems_of[f])
            break
        except animslots.SlotError:
            cap -= 1
    keys = sorted(order[:cap])
    base = max(len(keys), len(animslots.COMBO))
    extra = max(0, len(powers) - 1)
    while extra > 0:                                       # as many extra power slots as every folder can hold
        try:
            for f in folders:
                animslots.allocate(base + extra, stems_of[f])
            break
        except animslots.SlotError:
            extra -= 1
    replace, tags, report, ptags = [], {}, {}, {}
    for folder in folders:
        stems = stems_of[folder]
        slots = {keys[j - 1]: v for j, v in animslots.allocate(len(keys), stems).items()}
        for k, (stem, tag, rekey) in slots.items():
            clip = os.path.join(moveset, grouped["attack"][k])
            spec = f"{clip}::{anim_path(anims, folder, stem)}"
            replace.append(spec + (f"::tag:{tag}" if rekey else ""))
            if tags.setdefault(k, tag) != tag:
                raise SystemExit(f"attack {k} gets tag {tags[k]} in one folder and {tag} in {folder}")
        if routed_power:
            first = powers[0]
            p = grouped["power"][first]
        else:
            first = None
            p = pick(names, power) if power else (pick(names, "BFCO_PowerAttackA") or grouped["power"].get(1))
        if p and exists(anim_path(anims, folder, "meleeattackpower_a"), starfield_data):
            replace.append(f"{os.path.join(moveset, p)}::{anim_path(anims, folder, 'meleeattackpower_a')}")
            if first is not None:
                ptags[first] = "MeleeAttackPower_A"
        if routed_power and extra:
            more = animslots.allocate(base + extra, stems)
            for j, pk in enumerate(powers[1:1 + extra]):
                stem, tag, rekey = more[base + 1 + j]
                clip = os.path.join(moveset, grouped["power"][pk])
                replace.append(f"{clip}::{anim_path(anims, folder, stem)}" + (f"::tag:{tag}" if rekey else ""))
                if ptags.setdefault(pk, tag) != tag:
                    raise SystemExit(f"power attack {pk} gets tag {ptags[pk]} in one folder and {tag} in {folder}")
        s = pick(names, sprint or "BFCO_SprintAttack")
        if s and exists(anim_path(anims, folder, "meleeattacksprint"), starfield_data):
            replace.append(f"{os.path.join(moveset, s)}::{anim_path(anims, folder, 'meleeattacksprint')}")
        report[folder] = {k: v[:2] for k, v in slots.items()}
    return replace, tags, report, ptags


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--moveset", required=True)
    ap.add_argument("--anims", required=True)
    ap.add_argument("--folder", action="append", required=True)
    ap.add_argument("--graph", required=True, help="the vanilla MeleeAttacks.agx")
    ap.add_argument("--power", help="power attack clip stem (default BFCO_PowerAttackA, else BFCO_PowerAttack1)")
    ap.add_argument("--sprint", help="sprint attack clip stem (default BFCO_SprintAttack)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--starfield-data")
    a, rest = ap.parse_known_args(argv)
    replace, tags, report, ptags = plan(a.moveset, a.folder, a.anims, a.starfield_data, a.power, a.sprint)
    for f, slots in report.items():
        print(f"{f}: " + ", ".join(f"{k}:{t}" for k, (_s, t) in slots.items()))
    if ptags:
        print("power attacks: " + ", ".join(f"{p}:{t}" for p, t in sorted(ptags.items())))
    args = rest + ["--out", a.out, "--weapon-in-hand", "--bfco"]
    if a.starfield_data:
        args += ["--starfield-data", a.starfield_data]
    for r in replace:
        args += ["--replace", r]
    rc = hkx_to_af.main(args)
    rc2 = bfco_combo.main(["--graph", a.graph, "--moveset", a.moveset, "--out", a.out] +
                          [x for k, t in sorted(tags.items()) for x in ("--tag", f"{k}={t}")] +
                          [x for p, t in sorted(ptags.items()) for x in ("--power-tag", f"{p}={t}")])
    return rc or rc2


if __name__ == "__main__":
    sys.exit(main())
