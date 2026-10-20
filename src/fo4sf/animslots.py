"""Where extra attack clips can live in Starfield: existing descriptor paths re-keyed under tags the game knows.

Owner, in game, 2026-10-19/20 (BFCO diagnostics, docs/armor/animation-port.md):
  * a copied combo state plays whatever clip its tag resolves to (diagnostic 4);
  * clips are found by (<prefix>, <tag>) read from the descriptor (verified on vanilla: sneak variants are
    <tag>MeleeAttack_B</tag> <prefix>Sneak</prefix>), not by file name;
  * a NEW loose file is not found (BFCO_Attack1, the first state, played nothing);
  * an EXISTING path re-keyed (prefix removed) under the tag MeleeAttack_D plays (diagnostic 6), but the same under a
    brand-new tag string (BFCO_Attack5) does not.
So an extra attack needs an existing descriptor path in the weapon's folder (a host) and a tag string the game
already uses somewhere (supported hypothesis: any tag of a vanilla descriptor; MeleeAttack_D is the one verified).
The hosts given up are the player's sneak (and zero-g) attack variants: with their prefix gone, a sneak attack
falls back to the unprefixed clip (supported hypothesis), i.e. plays the same moveset.
"""
from typing import Dict, Iterable, List, Tuple

# the vanilla combo states' own files and tags (attacks 1-3)
COMBO = [("meleeattack_a", "MeleeAttack_A"), ("meleeattack_b", "MeleeAttack_B"), ("meleeattack_c", "MeleeAttack_C")]
# tags found in vanilla human descriptors (owner's listing) and not used by the player's melee graphs
TAG_POOL = ["MeleeAttack_D", "MeleeAttack_E", "MeleeAttack01", "MeleeAttack02", "MeleeAttack03", "MeleeAttack04",
            "MeleeAttackPower01", "MeleeAttackPower02"]
# existing player descriptor paths that can host them (the attack variants for sneaking / zero gravity)
HOSTS = ["sneak_meleeattack_a", "sneak_meleeattack_b", "sneak_meleeattack_c", "sneak_meleeattackpower_a",
         "zerog_meleeattack_a", "zerog_meleeattack_b", "zerog_meleeattack_c", "zerog_meleeattackpower_a"]


class SlotError(ValueError):
    pass


def allocate(n: int, existing: Iterable[str], hosts: List[str] = None, tags: List[str] = None
             ) -> Dict[int, Tuple[str, str, bool]]:
    """{k: (file stem to write, tag, re-key)} for attacks 1..n: 1-3 on the vanilla combo files under their own tags,
    4.. on hosts present in `existing` (stems, lower case) under pool tags, re-keyed (prefix removed)."""
    have = {e.lower() for e in existing}
    hosts = [h for h in (hosts or HOSTS) if h in have]
    tags = list(tags or TAG_POOL)
    out = {}
    for k in range(1, n + 1):
        if k <= len(COMBO):
            stem, tag = COMBO[k - 1]
            if stem not in have:
                raise SlotError(f"vanilla combo file {stem} missing from the folder")
            out[k] = (stem, tag, False)
        else:
            j = k - len(COMBO) - 1
            if j >= len(hosts) or j >= len(tags):
                raise SlotError(f"attack {k}: only {min(len(hosts), len(tags))} extra slots in this folder")
            out[k] = (hosts[j], tags[j], True)
    return out
