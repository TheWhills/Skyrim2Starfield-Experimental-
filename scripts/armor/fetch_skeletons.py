"""Collect the skeleton and naked-body files the armor work needs from the owner's own Skyrim SE and Starfield
installs, into ONE zip to upload (nothing is written into either game folder or into this repository).

What it gathers (read-only):
  Skyrim SE   meshes\\actors\\character\\character assets*\\  skeleton*.nif and the naked body / hands / feet / head
              NIFs (malebody_0/_1, femalebody_0/_1, ...), from the BSAs in load order or loose files.
  Starfield   every NIF in the Starfield - Meshes*.ba2 archives whose path looks like a human skeleton, a naked human
              body part (body / hands / feet / head under actors\\human), or the vanilla Nightwear outfit (the outfit
              Robes of Oblivion's records copy, for comparing a working worn NIF against vanilla), plus the external
              geometries\\*.mesh files those NIFs reference.

Plus a few animation samples for the animation work: Skyrim's Havok skeleton(s) and a handful of .hkx clips (an idle,
a walk, attacks), and Starfield's human skeleton.rig file(s) and a few idle / walk .af clips.

It always writes candidates.txt (every matching path, archive and size, also the ones not extracted) so a wrong
guess about Starfield's folder layout is visible and fixable with --starfield-pattern.

    python -I scripts\\armor\\fetch_skeletons.py --skyrim-data "<Skyrim Special Edition>\\Data" ^
        --starfield-data "<Starfield>\\Data" --out C:\\Modding\\work\\skeletons

Then upload <out>\\skeletons_for_claude.zip. --list-only writes candidates.txt without extracting.
"""
import argparse
import os
import re
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, bsa, nif, sfnif  # noqa: E402

SKYRIM_FOLDER = r"actors/character/character assets"            # also matches "character assets female"
SKYRIM_KEEP = re.compile(r"(skeleton|body|hands|feet|head)[^/]*\.nif$", re.I)
STARFIELD_PATTERNS = [
    r"actors/human/.*skeleton[^/]*\.nif$",                      # the human skeleton(s)
    r"actors/human/.*(naked|nude|body|hands|feet|head)[^/]*\.nif$",   # naked body parts
    r"clothes/outfit_nightwear_01/[^/]*\.nif$",                 # the vanilla outfit Robes of Oblivion copies
]
MAX_STARFIELD_NIFS = 60                                        # extract at most this many (all are listed)
EMBEDDED_GEOMETRY = 0x200                                      # BSGeometry NiAV flag: mesh data inside the NIF


def norm(name: str) -> str:
    return name.replace("\\", "/").lower()


def skyrim_files(data_dir):
    """{archive path: bytes} of Skyrim skeleton / naked body NIFs, archives in load order, loose files winning."""
    src = bsa.SkyrimArchives(data_dir)
    names = set(src.mesh_names(SKYRIM_FOLDER))
    loose_root = os.path.join(data_dir, "meshes", "actors", "character")
    if os.path.isdir(loose_root):
        for root, _dirs, files in os.walk(loose_root):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), data_dir).replace("/", "\\").lower()
                if SKYRIM_FOLDER in norm(rel) and fn.lower().endswith(".nif"):
                    names.add(rel)
    out = {}
    for n in sorted(names):
        if SKYRIM_KEEP.search(norm(n)):
            data = src.mesh(n)
            if data is not None:
                out[n] = data
    return out


def starfield_archives(data_dir):
    return [ba2.Ba2(os.path.join(data_dir, fn)) for fn in sorted(os.listdir(data_dir))
            if fn.lower().startswith(("starfield - meshes", "starfield - animations")) and fn.lower().endswith(".ba2")]


# animation samples for the .hkx reader and the .af work: (regex on the normalised path, how many to take)
SKYRIM_ANIM_SAMPLES = [
    (r"actors/character/character assets[^/]*/skeleton[^/]*\.hkx$", 4),      # the Havok skeletons (male, female)
    (r"actors/character/animations/mt_idle\.hkx$", 1),
    (r"actors/character/animations/mt_walkforward\.hkx$", 1),
    (r"actors/character/animations/1hm_attack[^/]*\.hkx$", 2),
    (r"actors/character/animations/idle[^/]*\.hkx$", 3),
]
STARFIELD_ANIM_SAMPLES = [
    (r"actors/human/.*characterassets/[^/]*\.rig$", 4),
    (r"actors/human/.*idle[^/]*\.af$", 4),
    (r"actors/human/.*walk[^/]*\.af$", 2),
]


def pick(names, samples):
    """[name] chosen by (regex, count) pairs over sorted normalised names, each name once."""
    out = []
    for rx, k in samples:
        r = re.compile(rx, re.I)
        out += [n for n in sorted(names, key=norm) if r.search(norm(n)) and n not in out][:k]
    return out


def skyrim_animations(data_dir, samples=SKYRIM_ANIM_SAMPLES):
    src = bsa.SkyrimArchives(data_dir)
    names = {n for arc in src.archives for n in arc.names if n.lower().endswith(".hkx")}
    return {n: d for n in pick(names, samples) for d in [src._read(norm(n).replace("/", "\\"))] if d is not None}


def starfield_animations(archives, samples=STARFIELD_ANIM_SAMPLES):
    where = {}
    for arc in archives:
        for i, n in enumerate(arc.names):
            if norm(n).endswith((".af", ".rig")):
                where.setdefault(n, (arc, i))
    return {n: where[n][0].read(where[n][1]) for n in pick(list(where), samples)}


def external_meshes(nif_bytes):
    """geometries\\... .mesh paths a Starfield NIF references (embedded meshes need nothing extra)."""
    out = []
    try:
        n = nif.parse(nif_bytes)
    except Exception:                                          # noqa: BLE001  (listed, just not followed)
        return out
    for i in range(len(n.blocks)):
        if n.type_of(i) != "BSGeometry":
            continue
        blk = n.blocks[i]
        nextra, = struct.unpack_from("<I", blk, 4)
        flags, = struct.unpack_from("<I", blk, 8 + 4 * nextra + 4)
        if flags & EMBEDDED_GEOMETRY:
            continue
        try:
            g = sfnif.parse_bsgeometry(blk)
        except Exception:                                      # noqa: BLE001
            continue
        for m in g.meshes:
            if m is not None and m.path:
                out.append("geometries\\" + m.path.decode("latin-1") + ".mesh")
    return out


def starfield_files(archives, patterns, limit=MAX_STARFIELD_NIFS):
    """(candidates [(name, archive file, bytes size)], extracted {name: bytes})."""
    rx = [re.compile(p, re.I) for p in patterns]
    cands, seen = [], set()
    for arc in archives:
        for i, name in enumerate(arc.names):
            key = norm(name)
            if key in seen or not any(r.search(key) for r in rx):
                continue
            seen.add(key)
            e = arc.entries[i]
            cands.append((name, os.path.basename(arc.path), e.unpacked or e.packed or 0, arc, i))
    cands.sort(key=lambda c: (0 if "skeleton" in norm(c[0]) else 1, norm(c[0])))
    files = {}
    for name, _a, _s, arc, i in cands[:limit]:
        files[name] = arc.read(i)
    want = {m for data in list(files.values()) for m in external_meshes(data)}
    for m in sorted(want):
        for arc in archives:
            j = arc.find(m)
            if j is not None:
                files[m] = arc.read(j)
                break
    missing = sorted(m for m in want if m not in files)
    return [(c[0], c[1], c[2]) for c in cands], files, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("--skyrim-data", required=True, help="Skyrim Special Edition\\Data (read-only)")
    ap.add_argument("--starfield-data", required=True, help="Starfield\\Data (read-only)")
    ap.add_argument("--out", required=True, help="output folder OUTSIDE the repository")
    ap.add_argument("--starfield-pattern", action="append", default=[],
                    help="extra regex on Starfield archive paths (forward slashes, lower case) to include")
    ap.add_argument("--list-only", action="store_true", help="write candidates.txt only, extract nothing")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository (game files never go into Git)")
    os.makedirs(out, exist_ok=True)

    sky = skyrim_files(a.skyrim_data)
    sky.update(skyrim_animations(a.skyrim_data))
    archives = starfield_archives(a.starfield_data)
    if not archives:
        sys.exit(f"no 'Starfield - Meshes*.ba2' in {a.starfield_data}")
    sf_anims = {} if a.list_only else starfield_animations(archives)
    cands, sf, missing = starfield_files(archives, STARFIELD_PATTERNS + a.starfield_pattern,
                                         0 if a.list_only else MAX_STARFIELD_NIFS)
    sf.update(sf_anims)

    lines = [f"Skyrim files ({len(sky)}):"] + [f"  {n}  {len(d):,} B" for n, d in sky.items()]
    lines += [f"", f"Starfield candidates ({len(cands)}; first {min(len(cands), MAX_STARFIELD_NIFS)} extracted):"]
    lines += [f"  {n}  [{arc}]  {size:,} B" for n, arc, size in cands]
    if missing:
        lines += ["", "Referenced geometry not found in any Starfield - Meshes*.ba2:"] + [f"  {m}" for m in missing]
    with open(os.path.join(out, "candidates.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(sky)} Skyrim files, {len(cands)} Starfield candidates (see candidates.txt)")
    if not sky:
        print("WARNING: no Skyrim skeleton / body NIFs found: is --skyrim-data the Skyrim Special Edition Data folder?")
    if not any("skeleton" in norm(c[0]) for c in cands):
        print("WARNING: no Starfield skeleton found; send candidates.txt and I will adjust the patterns")
    if a.list_only:
        print(f"listed only: {os.path.join(out, 'candidates.txt')}")
        return 0

    zpath = os.path.join(out, "skeletons_for_claude.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(out, "candidates.txt"), "candidates.txt")
        for n, d in sky.items():
            z.writestr("skyrim/" + n.replace("\\", "/"), d)
        for n, d in sf.items():
            z.writestr("starfield/" + n.replace("\\", "/"), d)
    print(f"{len(sky)} Skyrim + {len(sf)} Starfield files -> {zpath} ({os.path.getsize(zpath) / 1e6:.1f} MB). "
          f"Upload that zip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
