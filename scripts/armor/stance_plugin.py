"""Stances for Starfield melee (LoreRim / Stances - Dynamic Weapon Movesets style): S2SStances.esm with one actor keyword
per stance and HumanRace animation entries that put that stance's clip folder first (docs/armor/animation-port.md,
"Stances").

How Starfield picks an actor's animation folders (verified on RACE subgraph data, src/fo4sf/subgraph.py): entries of
actor keywords (SAKD), target / weapon keywords (STKD), a graph (SGNM) and animation folders most specific first
(SAPT). The player's weapon sets are NOT among Starfield.esm's HumanRace entries: they are the "Weapon" rows of the
game's generated table meshes\\animtextdata\\generatedsubgraphdata\\humanrace.txt (verified, owner's archives
2026-10-23: e.g. AnimArchetypePlayer + AnimOneHanded, AnimSword -> Player_Melee.agx, melee\\onehanded\\player\\sword >
...\\player > ...\\sword > onehanded > melee\\common > common). The first version copied the esm's generic melee
entries instead, which the sword rows always beat (keywords set, caches rebuilt, same swings). Now, per stance, every
third-person player one-handed Weapon row of that table becomes an esm entry with the stance keyword added to its actor
keywords, the same weapon keywords and graph, and the stance folder in front of its folders (SRAF role Weapon, third
person). Without the table (--no-table) it falls back to the esm's melee entries. The combat plugin adds / removes the
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


GENERATED_TABLE = "meshes\\animtextdata\\generatedsubgraphdata\\humanrace.txt"
WEAPON_THIRD_PERSON = "01 00 00 00"            # SRAF: role u16 1 = Weapon, perspective u16 0 = third person


def parse_table(text: str) -> list:
    """Rows of a GeneratedSubgraphData table (tab separated: Role, Perspective, Actor Keyword(s), Target Keyword(s),
    Behavior Path, Animation Path(s); lists comma separated): [{role, perspective, actor, target, graph, paths}]."""
    rows = []
    for line in text.splitlines():
        cols = line.rstrip("\r").split("\t")
        if len(cols) < 6 or cols[0].strip().lower() == "role":
            continue
        split = lambda c: [x.strip() for x in c.split(",") if x.strip()]      # noqa: E731
        rows.append({"role": cols[0].strip(), "perspective": cols[1].strip(), "actor": split(cols[2]),
                     "target": split(cols[3]), "graph": cols[4].strip(), "paths": split(cols[5])})
    return rows


def player_weapon_rows(rows, target="AnimOneHanded") -> list:
    """The third-person player Weapon rows for one weapon class (zero-g and female variants included)."""
    low = lambda xs: [x.lower() for x in xs]                                  # noqa: E731
    return [r for r in rows if r["role"].lower() == "weapon" and r["perspective"].lower() == "3rd"
            and "animarchetypeplayer" in low(r["actor"]) and target.lower() in low(r["target"])]


def race_with_stances(subs, keywords: dict, first_person: bool = False, table_rows=None, keyword_ids=None):
    """(new subrecords, report): the race's subrecords with, before its first animation entry, the stance entries.
    table_rows (player_weapon_rows of the generated table) + keyword_ids {EditorID lower: FormID}: one entry per row
    and stance (stance keyword added, stance folder first, role Weapon / third person). Otherwise one copy of every
    melee esm entry per stance (the first version)."""
    entries = subgraph.parse(subs)
    if table_rows:
        ids = keyword_ids or {}
        added, unresolved, used = [], set(), 0
        for r in table_rows:
            names = r["actor"] + r["target"]
            missing = [n for n in names if n.lower() not in ids]
            if missing:
                unresolved.update(missing)
                continue
            used += 1
            for stance, kw in keywords.items():
                added += subgraph.build({"actor_keywords": [ids[n.lower()] for n in r["actor"]] + [kw],
                                         "target_keywords": [ids[n.lower()] for n in r["target"]],
                                         "graph": r["graph"], "paths": [stance_folder(stance)] + r["paths"],
                                         "flags": WEAPON_THIRD_PERSON})
        if not used:
            raise SystemExit(f"no table row with known keywords (unresolved: {sorted(unresolved)})")
        at = next(i for i, (s_, _d) in enumerate(subs) if s_ in subgraph.FIELDS)
        return list(subs[:at]) + added + list(subs[at:]), {
            "source": "generated table weapon rows", "entries": len(entries), "melee_entries": used,
            "added_entries": used * len(keywords), "unresolved_keywords": sorted(unresolved),
            "melee_graphs": sorted({r["graph"] for r in table_rows}),
            "melee_first_folders": sorted({r["paths"][0] for r in table_rows if r["paths"]})}
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
    return out, {"source": "esm melee entries", "entries": len(entries), "melee_entries": len(melee),
                 "added_entries": len(melee) * len(keywords),
                 "melee_graphs": sorted({e["graph"] for e in melee}),
                 "melee_first_folders": sorted({e["paths"][0] for e in melee if e["paths"]})}


def build(esm_path: str, stances=STANCES, first_person: bool = False, table_text=None):
    """(plugin bytes, report) from Starfield.esm (+ the generated HumanRace table text, read from the archives)."""
    info = sfplugin.header_info(esm_path)
    recs = sfplugin.records(esm_path, [b"KYWD", b"RACE"])
    kywd = next((r for r in recs if r[0] == b"KYWD"), None)
    keyword_ids = {sfplugin.edid(r[2]).lower(): r[3] for r in recs if r[0] == b"KYWD" and sfplugin.edid(r[2])}
    rows = player_weapon_rows(parse_table(table_text)) if table_text else None
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
    race_subs, rep = race_with_stances(race[2], keywords, first_person, table_rows=rows, keyword_ids=keyword_ids)
    out.append((b"RACE", race[1], race_subs, race[3]))
    rep["keywords"] = {keyword_edid(s): f"{fid:08X}" for s, fid in keywords.items()}
    rep["folders"] = {s: stance_folder(s) for s in stances}
    rep["race"] = f"{race[3]:08X}"
    return sfplugin.build(out, info, author="Skyrim2Starfield stances"), rep


def read_table(data_dir: str):
    """The game's generated HumanRace table from the Data folder's archives (last archive wins), or None."""
    from fo4sf import ba2
    found = None
    for fn in sorted(os.listdir(data_dir), key=str.lower):
        if not fn.lower().endswith(".ba2") or "texture" in fn.lower():
            continue
        try:
            arc = ba2.Ba2(os.path.join(data_dir, fn))
        except Exception:                               # noqa: BLE001
            continue
        i = arc.find(GENERATED_TABLE)
        if i is not None:
            found = arc.read(i).decode("utf-8", "replace")
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True, help="Starfield install folder (reads Data\\Starfield.esm)")
    ap.add_argument("--out", required=True, help="mod folder (MO2): gets S2SStances.esm and stance_plugin.json")
    ap.add_argument("--first-person", action="store_true", help="first-person melee entries too (esm fallback only)")
    ap.add_argument("--table", help="a GeneratedSubgraphData humanrace.txt to use instead of the one in the archives")
    ap.add_argument("--no-table", action="store_true", help="copy the esm's melee entries (the first version)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    if not os.path.isfile(esm):
        esm = os.path.join(a.starfield, "Starfield.esm")
    table = None
    if not a.no_table:
        if a.table:
            with open(a.table, "rb") as fh:
                table = fh.read().decode("utf-8", "replace")
        else:
            table = read_table(os.path.dirname(esm))
            if table is None:
                print(f"{GENERATED_TABLE} not found in the archives: falling back to the esm's melee entries")
    data, rep = build(esm, first_person=a.first_person, table_text=table)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(data)
    with open(os.path.join(out, "stance_plugin.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{PLUGIN}: {len(rep['keywords'])} keywords, {rep['added_entries']} animation entries added to HumanRace "
          f"({rep['melee_entries']} {rep['source']} x {len(rep['keywords'])} stances)")
    if rep.get("unresolved_keywords"):
        print(f"  rows skipped, keywords not in Starfield.esm: {', '.join(rep['unresolved_keywords'])}")
    for f in rep["melee_first_folders"]:
        print(f"  melee entry folder: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
