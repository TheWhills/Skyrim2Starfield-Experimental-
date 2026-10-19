"""Survey Starfield's animation system (read-only) for the Skyrim animation port (docs/armor/animation-port.md).

What it reads from the owner's Starfield archives (Starfield - Animations*.ba2 and Starfield - Meshes*.ba2):
  * every .af / .afx / .agx / .rig / .ffxanim path: counts per archive, per extension and per folder (3 levels)
  * the graphs (.agx): which exist, whether each is text or binary, and the readable strings of the graphs whose path
    matches --graph-filter (events, variables, state / tag names, referenced base graphs)
  * the clip descriptors (.afx, XML): every element name, and the <tag> values per folder (how clips are discovered)
  * keyword hits for what Skyrim needs and Starfield may not have (casting / powers, bows, melee, blocking, mounts,
    swimming, furniture, killmoves ...), so we know which behaviours exist natively

Writes <out>\\report.txt and <out>\\sf_anim_samples.zip (a few human graphs, descriptors and the human rig, to upload;
the zip stays on the PC and is never committed: game files).

    python -I scripts\\armor\\sf_anim_survey.py --starfield-data "<Starfield>\\Data" --out C:\\Modding\\work\\sf_anim

Mods instead of (or as well as) the game: --mod takes a mod folder (loose files and every .ba2 in it), a single .ba2 or
a .zip, and is repeatable; each file is labelled with its source:

    python -I scripts\\armor\\sf_anim_survey.py --mod "D:\\Downloads\\SomeAnimMod" --mod other.zip --out C:\\Modding\\work\\sf_anim_mods

Known before this survey (docs/spikes/WP-doors-research.md, docs/handoff-archive): a DOOR binds a graph (ANAM, e.g.
AnimTextData\\Tables\\Graphs\\SimpleOpenClose01.agx, which references SimpleOpenClose_Base01 with event / tag selectors
Open, Close and variables AnimSpeed, OpenCloseFormState), a skeleton (BNAM, skeleton.rig) and an animation folder
(CNAM); each clip .af has an .afx XML descriptor beside it (<tag>Open</tag><filename>Open.af</filename>, is_state).
"""
import argparse
import collections
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import agx, ba2  # noqa: E402

EXTS = (".af", ".afx", ".agx", ".rig", ".ffxanim", ".gltf", ".glb")      # glTF: Native Animation Framework mods
KEYWORDS = {
    "cast / powers": r"cast|spell|power|starborn|magic|telekin|gravwave|antigrav",
    "bow / draw": r"\bbow|_bow|bowdraw|archery|crossbow",
    "melee": r"melee|1hm|2hm|onehand|twohand|sword|axe|blade|knife|bash|swing",
    "block / shield": r"block|shield|parry",
    "mount / ride / vehicle": r"mount|ride|riding|horse|saddle|vehicle|rover|rev8|rev-8|drive|driver|seat",
    "swim": r"swim|underwater|tread",
    "sneak / crouch": r"sneak|crouch|stealth",
    "furniture / idle markers": r"furniture|chair|bed|sit|sleep|lean|workbench|crafting|cook|eat|drink",
    "killmove / sync": r"killmove|kill_move|paired|sync|takedown|execution",
    "jump / fall / land": r"jump|fall|land",
    "dialogue / gesture": r"dialog|dialogue|talk|gesture|emote|convers",
    "creature": r"creature|quadruped|biped|terrormorph|ashta|lizard|insect",
}
TEXT_LIMIT = 4000


def norm(n: str) -> str:
    return n.replace("\\", "/").lower()


def archives(data_dir):
    out = []
    for fn in sorted(os.listdir(data_dir)):
        low = fn.lower()
        if low.endswith(".ba2") and low.startswith(("starfield - animations", "starfield - meshes",
                                                     "starfield - misc", "starfield - interface")):
            try:
                out.append((fn, ba2.Ba2(os.path.join(data_dir, fn))))
            except Exception as e:                       # texture / odd archives: listed, not fatal
                print(f"  skipped {fn}: {e}")
    return out


class _Loose:
    """A folder or a .zip read like a Ba2: .names and .read(index)."""

    def __init__(self, path):
        self.path, self.names, self._src = path, [], []
        if path.lower().endswith(".zip"):
            self._zip = zipfile.ZipFile(path)
            for n in self._zip.namelist():
                if not n.endswith("/"):
                    self.names.append(n)
                    self._src.append(n)
        else:
            self._zip = None
            for root, _dirs, files in os.walk(path):
                for fn in files:
                    full = os.path.join(root, fn)
                    self.names.append(os.path.relpath(full, path))
                    self._src.append(full)

    def read(self, i):
        if self._zip is not None:
            return self._zip.read(self._src[i])
        with open(self._src[i], "rb") as fh:
            return fh.read()


def mod_sources(path):
    """[(label, reader)] for a mod folder (loose files + each .ba2 inside), a .ba2 or a .zip."""
    out = []
    low = path.lower()
    if low.endswith(".ba2"):
        return [(os.path.basename(path), ba2.Ba2(path))]
    if low.endswith(".zip"):
        return [(os.path.basename(path), _Loose(path))]
    out.append((os.path.basename(os.path.normpath(path)) + " (loose)", _Loose(path)))
    for root, _dirs, files in os.walk(path):
        for fn in files:
            if fn.lower().endswith(".ba2"):
                try:
                    out.append((fn, ba2.Ba2(os.path.join(root, fn))))
                except Exception as e:
                    print(f"  skipped {fn}: {e}")
    return out


def is_text(d: bytes) -> bool:
    if not d:
        return True
    head = d[:2048]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return all(c in (9, 10, 13) or 32 <= c < 127 or c >= 0xC0 for c in head)


def strings_of(d: bytes, n: int = 4):
    return [m.decode("latin-1") for m in re.findall(rb"[\x20-\x7e]{%d,}" % n, d)]


def afx_fields(d: bytes):
    """(element names, tag values, filename values) of an .afx descriptor (tolerant regex, not a full XML parse)."""
    t = d.decode("utf-8", "replace")
    elems = re.findall(r"<([A-Za-z_][\w\-.]*)[\s>/]", t)
    tags = [v.strip() for v in re.findall(r"<tag>(.*?)</tag>", t, re.S)]
    files = [v.strip() for v in re.findall(r"<filename>(.*?)</filename>", t, re.S)]
    return elems, tags, files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield-data", help="the game's Data folder (its Starfield - *.ba2 archives)")
    ap.add_argument("--mod", action="append", default=[],
                    help="a mod folder, .ba2 or .zip to survey (repeatable); with --starfield-data, game files win")
    ap.add_argument("--out", required=True)
    ap.add_argument("--graph-filter", default=r"human|character|player|npc|base",
                    help="regex on .agx paths whose strings are printed in full")
    ap.add_argument("--max-graphs", type=int, default=40, help="most graphs printed / zipped")
    ap.add_argument("--max-samples", type=int, default=60, help="most .afx descriptors zipped")
    a = ap.parse_args(argv)
    if not a.starfield_data and not a.mod:
        ap.error("give --starfield-data and / or --mod")
    os.makedirs(a.out, exist_ok=True)
    gx = re.compile(a.graph_filter, re.I)
    where = {}                                              # normalised path -> (archive name, Ba2, index, name)
    per_arc = defaultdict(Counter)
    sources = archives(a.starfield_data) if a.starfield_data else []
    for m in a.mod:
        sources += mod_sources(m)
    for fn, arc in sources:
        for i, n in enumerate(arc.names):
            p = norm(n)
            if p.startswith("data/"):                       # mod zips often wrap everything in Data\
                p = p[5:]
            ext = os.path.splitext(p)[1]
            if ext in EXTS:
                per_arc[fn][ext] += 1
                where.setdefault(p, (fn, arc, i, n))
    lines = []
    w = lines.append
    w(f"Starfield animation survey: {len(where):,} animation-system files")
    for fn, c in per_arc.items():
        w(f"  {fn}: " + ", ".join(f"{e} {k:,}" for e, k in c.most_common()))
    by_ext = Counter(os.path.splitext(p)[1] for p in where)
    w("by extension: " + ", ".join(f"{e} {k:,}" for e, k in by_ext.most_common()))
    # folders
    folders = defaultdict(Counter)
    for p in where:
        parts = p.split("/")
        folders["/".join(parts[:min(4, len(parts) - 1)])][os.path.splitext(p)[1]] += 1
    w(f"\nfolders (first 4 levels), {len(folders):,}; largest 120:")
    for f, c in sorted(folders.items(), key=lambda kv: -sum(kv[1].values()))[:120]:
        w(f"  {sum(c.values()):6,}  {f}  " + " ".join(f"{e}:{k}" for e, k in c.most_common()))
    # graphs
    graphs = sorted(p for p in where if p.endswith(".agx"))
    w(f"\n.agx graphs: {len(graphs):,}")
    for p in graphs:
        w(f"  {p}")
    picked = [p for p in graphs if gx.search(p)][:a.max_graphs]
    w(f"\ngraphs matching /{a.graph_filter}/ printed: {len(picked)}")
    zipped = {}
    for p in picked:
        fn, arc, i, n = where[p]
        d = arc.read(i)
        zipped[p] = d
        txt = is_text(d)
        w(f"\n=== {p} ({fn}, {len(d):,} bytes, {'text' if txt else 'binary'}) ===")
        if txt:
            t = d.decode("utf-8", "replace")
            w(t[:TEXT_LIMIT] + ("\n  ... (truncated)" if len(t) > TEXT_LIMIT else ""))
        else:
            s = strings_of(d)
            w(f"  first 32 bytes: {d[:32].hex(' ')}")
            w(f"  {len(s)} strings: " + " | ".join(s[:400]) + (" ..." if len(s) > 400 else ""))
    # the engine <-> graph interface, from every text graph (TES4 AutoConvert's first step for creatures: enumerate the
    # events the engine sends, the variables it drives, the events graphs emit, before generating any graph)
    all_events, all_vars, all_tags, refs_by, alters = (collections.Counter() for _ in range(5))
    per_graph, bad_graphs = [], 0
    for p in graphs:
        fn, arc, i, n = where[p]
        try:
            g = agx.read_graph(arc.read(i))
        except Exception:                                    # noqa: BLE001 - binary or malformed: counted
            bad_graphs += 1
            continue
        sm = agx.summary(g)
        all_events.update(sm["events"])
        all_vars.update(sm["variables"])
        all_tags.update(sm["tags"])
        refs_by.update(sm["graph_refs"])
        alters.update(f"{a['mode']}:{a['variable'] or a['switch']}:{'/'.join(a['cases'])}" for a in sm["tag_alterations"])
        per_graph.append((p, sm))
    w(f"\ngraph interface over {len(per_graph):,} text graphs ({bad_graphs} unreadable):")
    w(f"  link events ({len(all_events):,}, graphs using each): " + ", ".join(f"{e} {k}" for e, k in all_events.most_common(400)))
    w(f"  variables ({len(all_vars):,}): " + ", ".join(f"{v} {k}" for v, k in all_vars.most_common(400)))
    w(f"  most referenced graphs: " + ", ".join(f"{r} {k}" for r, k in refs_by.most_common(80)))
    w(f"  tag alterations: " + ", ".join(f"{t} x{k}" for t, k in alters.most_common(60)))
    w(f"  clip tags ({len(all_tags):,}): " + ", ".join(f"{t}" for t, _k in all_tags.most_common(600)))
    w("  per graph (nodes, tags, refs, events), creature / non-human graphs first:")
    order = sorted(per_graph, key=lambda x: ("human" in x[0] or "player" in x[0], x[0]))
    for p, sm in order[:400]:
        w(f"    {os.path.basename(p)}: {sm['nodes']} nodes; tags {sm['tags'][:12]}; refs {sm['graph_refs'][:10]}; "
          f"events {sm['events'][:16]}")
    # descriptors
    afx = [p for p in where if p.endswith(".afx")]
    elem_count, tag_by_folder, tag_count = Counter(), defaultdict(Counter), Counter()
    bad = 0
    for p in afx:
        fn, arc, i, n = where[p]
        try:
            d = arc.read(i)
        except Exception:
            bad += 1
            continue
        elems, tags, _files = afx_fields(d)
        elem_count.update(set(elems))
        tag_count.update(tags)
        tag_by_folder[os.path.dirname(p)].update(tags)
    w(f"\n.afx descriptors: {len(afx):,} ({bad} unreadable); element names (files containing each):")
    w("  " + ", ".join(f"{e} {k:,}" for e, k in elem_count.most_common(60)))
    w(f"distinct <tag> values: {len(tag_count):,}; most common 300:")
    w("  " + ", ".join(f"{t} {k:,}" for t, k in tag_count.most_common(300)))
    human = sorted(f for f in tag_by_folder if "human" in f)
    w(f"\nhuman folders with descriptors: {len(human):,}; their tags (first 200 folders):")
    for f in human[:200]:
        c = tag_by_folder[f]
        w(f"  {f}: " + ", ".join(f"{t}" + (f" x{k}" if k > 1 else "") for t, k in c.most_common(40)))
    samples = [p for p in sorted(afx) if "human" in p][:a.max_samples]
    for p in samples:
        zipped[p] = where[p][1].read(where[p][2])
    w(f"\nfull text of 8 human descriptors:")
    for p in samples[:8]:
        w(f"--- {p}\n{zipped[p].decode('utf-8', 'replace')[:1500]}")
    # rigs
    rigs = sorted(p for p in where if p.endswith(".rig"))
    w(f"\n.rig skeletons: {len(rigs):,}")
    for p in rigs[:300]:
        w(f"  {p}")
    for p in [r for r in rigs if "human" in r][:4]:
        zipped[p] = where[p][1].read(where[p][2])
    # keywords
    w("\nkeyword hits in animation-system paths (count, then up to 25 samples):")
    for label, rx in KEYWORDS.items():
        r = re.compile(rx, re.I)
        hits = sorted(p for p in where if r.search(p))
        w(f"\n[{label}] {len(hits):,}")
        for p in hits[:25]:
            w(f"  {p}")
    rep = os.path.join(a.out, "report.txt")
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    zp = os.path.join(a.out, "sf_anim_samples.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.txt", "\n".join(lines) + "\n")
        for p, d in zipped.items():
            z.writestr("starfield/" + p, d)
    print(f"{len(where):,} animation-system files; {len(graphs):,} graphs, {len(afx):,} descriptors, {len(rigs):,} rigs")
    print(f"wrote {rep} and {zp} ({len(zipped)} sample files); upload the zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
