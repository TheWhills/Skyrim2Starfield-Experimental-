"""Stances for Starfield melee (LoreRim / Stances - Dynamic Weapon Movesets style): S2SStances.esm with one actor keyword
per stance and HumanRace animation entries that put that stance's clip folder first (docs/armor/animation-port.md,
"Stances").

How Starfield picks an actor's animation folders (verified on RACE subgraph data, src/fo4sf/subgraph.py): entries of
actor keywords (SAKD), target / weapon keywords (STKD), a graph (SGNM) and animation folders most specific first
(SAPT). For every third-person melee entry of HumanRace this plugin adds, per stance, a copy with the stance keyword
added to its actor keywords and the stance folder in front of its folders. The combat plugin adds / removes the
keyword when an arrow key is pressed ([Keys] keyword bindings in S2SCombat.ini).

Supported hypotheses, tested by the pack: an entry with more matching actor keywords wins over the plain one (the
copies are also placed first); a clip tag missing from the stance folder falls back to the vanilla folders after it.
Unresolved: whether the folder switch takes effect while the weapon is drawn (Skyrim's Stances pokes the graph with
blockStart / blockStop for this; S2SCombat.ini sStanceRefreshEvents does the same), and whether a new folder needs the
Creation Kit's animation-cache rebuild.

    python -I scripts\\armor\\stance_plugin.py --starfield "<Starfield folder>" --out "<mod folder>"
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import sfplugin, subgraph  # noqa: E402

# Stances - Dynamic Weapon Movesets: up = high, left = mid, down = low, right = neutral (no keyword); LoreRim's tiers
# Expert / Adept / Apprentice / Novice are these stances (verified on its DAR conditions).
STANCES = ("High", "Mid", "Low")
STANCE_ROOT = "actors\\human\\animations\\melee\\s2s_stances"
PLUGIN = "S2SStances.esm"
RACE_EDID = "HumanRace"


def keyword_edid(stance: str) -> str:
    return f"S2S_Stance{stance}"


def stance_folder(stance: str) -> str:
    return f"{STANCE_ROOT}\\{stance.lower()}"


def is_melee_entry(entry, first_person: bool = False) -> bool:
    paths = [p.lower().replace("/", "\\") for p in entry["paths"]]
    if any("_1stperson" in p for p in paths) and not first_person:
        return False
    return any("\\melee" in p for p in paths)


def race_with_stances(subs, keywords: dict, first_person: bool = False):
    """(new subrecords, report): the race's subrecords with, before its first animation entry, one copy of every melee
    entry per stance (stance keyword added to SAKD, stance folder first in SAPT)."""
    entries = subgraph.parse(subs)
    melee = [e for e in entries if is_melee_entry(e, first_person)]
    if not melee:
        raise SystemExit("no melee animation entries in the race (are these Starfield.esm's records?)")
    added = []
    for stance, kw in keywords.items():
        for e in melee:
            copy = dict(e, actor_keywords=list(e["actor_keywords"]) + [kw], paths=[stance_folder(stance)] + e["paths"])
            added += subgraph.build(copy)
    at = next(i for i, (s, _d) in enumerate(subs) if s in subgraph.FIELDS)
    out = list(subs[:at]) + added + list(subs[at:])
    return out, {"entries": len(entries), "melee_entries": len(melee), "added_entries": len(melee) * len(keywords),
                 "melee_graphs": sorted({e["graph"] for e in melee}),
                 "melee_first_folders": sorted({e["paths"][0] for e in melee if e["paths"]})}


def build(esm_path: str, stances=STANCES, first_person: bool = False):
    """(plugin bytes, report) from Starfield.esm."""
    info = sfplugin.header_info(esm_path)
    recs = sfplugin.records(esm_path, [b"KYWD", b"RACE"])
    kywd = next((r for r in recs if r[0] == b"KYWD"), None)
    race = next((r for r in recs if r[0] == b"RACE" and sfplugin.edid(r[2]) == RACE_EDID), None)
    if kywd is None or race is None:
        raise SystemExit(f"{esm_path}: no KYWD / no RACE {RACE_EDID}")
    out, keywords = [], {}
    for i, stance in enumerate(stances):
        fid = sfplugin.new_form_id(i)
        keywords[stance] = fid
        # a keyword copied from the game's first one: EditorID replaced, display name dropped (it is localized)
        subs = sfplugin.edit(kywd[2], {b"EDID": sfplugin.zs(keyword_edid(stance))}, drop=(b"FULL", b"DESC"))
        out.append((b"KYWD", kywd[1], subs, fid))
    race_subs, rep = race_with_stances(race[2], keywords, first_person)
    out.append((b"RACE", race[1], race_subs, race[3]))
    rep["keywords"] = {keyword_edid(s): f"{fid:08X}" for s, fid in keywords.items()}
    rep["folders"] = {s: stance_folder(s) for s in stances}
    rep["race"] = f"{race[3]:08X}"
    return sfplugin.build(out, info, author="Skyrim2Starfield stances"), rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True, help="Starfield install folder (reads Data\\Starfield.esm)")
    ap.add_argument("--out", required=True, help="mod folder (MO2): gets S2SStances.esm and stance_plugin.json")
    ap.add_argument("--first-person", action="store_true", help="first-person melee entries too")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    if not os.path.isfile(esm):
        esm = os.path.join(a.starfield, "Starfield.esm")
    data, rep = build(esm, first_person=a.first_person)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(data)
    with open(os.path.join(out, "stance_plugin.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{PLUGIN}: {len(rep['keywords'])} keywords, {rep['added_entries']} animation entries added to HumanRace "
          f"({rep['melee_entries']} melee entries x {len(rep['keywords'])} stances)")
    for f in rep["melee_first_folders"]:
        print(f"  melee entry folder: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
