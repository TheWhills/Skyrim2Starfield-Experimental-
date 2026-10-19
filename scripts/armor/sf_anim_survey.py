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

Known before this survey (docs/spikes/WP-doors-research.md, docs/handoff-archive): a DOOR binds a graph (ANAM, e.g.
AnimTextData\\Tables\\Graphs\\SimpleOpenClose01.agx, which references SimpleOpenClose_Base01 with event / tag selectors
Open, Close and variables AnimSpeed, OpenCloseFormState), a skeleton (BNAM, skeleton.rig) and an animation folder
(CNAM); each clip .af has an .afx XML descriptor beside it (<tag>Open</tag><filename>Open.af</filename>, is_state).
"""
import argparse
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2  # noqa: E402

EXTS = (".af", ".afx", ".agx", ".rig", ".ffxanim")
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
    ap.add_argument("--starfield-data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--graph-filter", default=r"human|character|player|npc|base",
                    help="regex on .agx paths whose strings are printed in full")
    ap.add_argument("--max-graphs", type=int, default=40, help="most graphs printed / zipped")
    ap.add_argument("--max-samples", type=int, default=60, help="most .afx descriptors zipped")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    gx = re.compile(a.graph_filter, re.I)
    where = {}                                              # normalised path -> (archive name, Ba2, index, name)
    per_arc = defaultdict(Counter)
    for fn, arc in archives(a.starfield_data):
        for i, n in enumerate(arc.names):
            p = norm(n)
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
