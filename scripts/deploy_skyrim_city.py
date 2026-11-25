"""Install / uninstall Skyrim's walled cities next to the installed Tamriel exterior, reversibly (2026-11-25, Whiterun
first; docs/terrain/skyrim-cities.md).

install : per staged city (make_skyrim_objects.py stage --out, built make_skyrim_overlay.py --terrain-from the installed
          exterior): packs its Data into "<city plugin> - Main.ba2" (Archive2, stored) leaving out every file the installed
          exterior's archives already hold with the same contents (a file of the same path that differs, from a newer
          converter, is packed: the city's archive loads after the exterior's, so a model shared by both still looks the
          same in both; supported hypothesis, Bethesda's later-archive-wins rule), copies the archive, the city plugin
          and the registration / gates plugin
          (register_worlds.py --skyrim) into Starfield\\Data and adds them to Plugins.txt after the exterior's plugins.
          Then hides each gate's static in place (register_worlds.json "hide": the static's own record gets Initially
          Disabled and is sunk 1000 m, as apply_ref_overrides.py does), in the installed exterior plugin and the city
          plugin. Records it all in Data\\SkyrimCities.deploy.json (the exterior statics' original bytes too).
uninstall: puts the exterior's gate statics back as they were, removes exactly the files the manifest lists (unchanged
          since install) and their Plugins.txt lines.
hide    : the hiding again (after the exterior was reinstalled: its fresh plugin shows the gate static again).

    python -I scripts\\deploy_skyrim_city.py install --city C:\\Modding\\staging\\sky_whiterunworld ^
        --register C:\\Modding\\staging\\sky_worlds_register --exterior C:\\Modding\\staging\\skyrim_all --starfield "<Starfield>"
    python -I scripts\\deploy_skyrim_city.py uninstall --starfield "<Starfield>"

Starfield must be closed. MO2 (the owner's launcher) keeps its own plugin list: tick the new plugins there, after
SkyrimTerrainTamriel_Mars.esm, SkyrimWorlds_Register.esm last.
"""
import argparse
import json
import os
import shutil
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "terrain"))
sys.path.insert(0, os.path.join(HERE, "tools"))

import deploy_skyrim_exterior as dse  # noqa: E402
import apply_ref_overrides as aro  # noqa: E402
import ref_overrides  # noqa: E402
from fo4sf import ba2, fo4land  # noqa: E402

MANIFEST = "SkyrimCities.deploy.json"
EXTERIOR_MANIFEST = dse.MANIFEST


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def installed_names(data, exterior_files) -> dict:
    """{file path (lower case, backslashes): (Ba2, entry index)} of the installed exterior's archives."""
    out = {}
    for f in exterior_files:
        if f.lower().endswith(".ba2") and os.path.isfile(os.path.join(data, f)):
            arc = ba2.Ba2(os.path.join(data, f))
            for i, n in enumerate(arc.names):
                out.setdefault(ba2.Ba2._norm(n), (arc, i))
    return out


def _same(path, entry) -> bool:
    """True when the exterior's archived file (Ba2, index) holds exactly the staged file's bytes. Textures (DX10
    entries) are not compared: the converter names them by their source, and a city converts them as the exterior did."""
    arc, i = entry
    e = arc.entries[i]
    if e.kind != "GNRL":
        return True
    if e.unpacked != os.path.getsize(path):
        return False
    with open(path, "rb") as fh:
        return fh.read() == arc.read(i)


def pack_plan(staging, have) -> tuple:
    """([(relative path under Data, size)] to pack, {"skipped": n, "skipped_bytes": b, "replaced": n}) of a staged city:
    its DATA_DIRS files minus those the exterior already holds. `have`: installed_names (a file of the same path but
    other contents is packed: the city's converter is newer, e.g. 2026-11-25 vertex-alpha cutouts in Whiterun's walls,
    and the city's archive loads after the exterior's, so both worlds then show the newer file) or a set of paths."""
    root = os.path.join(staging, "Data")
    keep, skipped, sk_bytes, replaced = [], 0, 0, 0
    for d in dse.DATA_DIRS:
        for r, _ds, fs in os.walk(os.path.join(root, d)):
            for f in fs:
                path = os.path.join(r, f)
                rel = os.path.relpath(path, root)
                size = os.path.getsize(path)
                name = ba2.Ba2._norm(rel)
                if name in have and (not isinstance(have, dict) or _same(path, have[name])):
                    skipped, sk_bytes = skipped + 1, sk_bytes + size
                else:
                    replaced += name in have
                    keep.append((rel, size))
    return keep, {"skipped": skipped, "skipped_bytes": sk_bytes, "replaced": replaced}


def build_pack_root(staging, files, root):
    """A folder holding only `files` (hard links where possible) for Archive2."""
    for rel, _size in files:
        src, dst = os.path.join(staging, "Data", rel), os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)


def find_ref(path, lid):
    """(record offset, flags) of the plugin's own reference lid, or None."""
    with fo4land.Plugin(path) as p:
        n = len(ref_overrides.masters(p))
        for typ, off, flags, fid, _chain in ref_overrides.walk(p, p.body, len(p.buf)):
            if typ in ref_overrides.REF_TYPES and fid >> 24 == n and fid & 0xFFFFFF == lid:
                return off, flags
    return None


def set_ref(path, lid, flags, data: bytes):
    """Write a reference's record flags and DATA (24 bytes) in place (same size)."""
    found = find_ref(path, lid)
    if found is None:
        raise OSError(f"{path}: reference {lid:06X} not found")
    off, _f = found
    with open(path, "rb") as fh:
        buf = bytearray(fh.read())
    doff = aro.field_offset(buf, off, b"DATA")
    if doff is None:
        raise OSError(f"{path}: reference {lid:06X} has no plain DATA")
    struct.pack_into("<I", buf, off + 8, flags)
    buf[doff:doff + 24] = data
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(buf)
    os.replace(tmp, path)


def ref_state(path, lid):
    """(flags, DATA 24 bytes) of the plugin's own reference lid, or None."""
    found = find_ref(path, lid)
    if found is None:
        return None
    off, flags = found
    with open(path, "rb") as fh:
        buf = fh.read()
    doff = aro.field_offset(buf, off, b"DATA")
    return flags, (bytes(buf[doff:doff + 24]) if doff is not None else None)


def hide(data, entries, state, quiet=False):
    """Hide the listed gate statics in the installed plugins (Initially Disabled + sunk). The exterior's first: its
    original flags and DATA go into state["restore"] so uninstall can put them back."""
    restore = state.setdefault("restore", {})
    for h in entries:
        path = os.path.join(data, h["plugin"])
        lid = int(h["local_id"], 16)
        cur = ref_state(path, lid)
        if cur is None:
            raise OSError(f"{h['plugin']}: gate static {h['local_id']} not found (rebuilt since register_worlds?)")
        flags, d = cur
        sunk = bytes.fromhex(h["data"])
        key = f"{h['plugin']}:{h['local_id']}"
        if flags & aro.DISABLED and d == sunk:
            if not quiet:
                print(f"  {key}: already hidden")
            continue
        if d != bytes.fromhex(h["original"]):
            raise OSError(f"{key}: the static is not where register_worlds read it ({d.hex()}); rebuild the gates")
        if h["plugin"] not in state["files"]:          # the exterior's plugin: remember how it was
            restore[key] = {"flags": flags, "data": d.hex()}
            if not os.path.exists(path + aro.BACKUP):
                # as apply_ref_overrides.py: the file as installed, so deploy_skyrim_exterior.py uninstall knows the
                # change is ours (known_change) and still removes the plugin
                shutil.copy2(path, path + aro.BACKUP)
        set_ref(path, lid, flags | aro.DISABLED, sunk)
        print(f"  {key}: gate static hidden")


def install(a):
    data = os.path.join(a.starfield, "Data")
    man_path = os.path.join(data, MANIFEST)
    if os.path.exists(man_path):
        sys.exit("cities are already installed (manifest exists): uninstall first")
    if not os.path.exists(os.path.join(data, EXTERIOR_MANIFEST)):
        sys.exit("the Skyrim exterior is not installed (deploy_skyrim_exterior.py install first)")
    ext = load(os.path.join(data, EXTERIOR_MANIFEST))
    reg = load(os.path.join(a.register, "register_worlds.json"))
    ext_ids = load(os.path.join(a.exterior, "formids.json"))
    if ext_ids["plugin"] not in ext["files"]:
        sys.exit(f"{ext_ids['plugin']} is not the installed exterior's plugin ({ext['files']})")
    have = installed_names(data, ext["files"])
    plan = []
    for c in a.city:
        prm, plugins, _dirs, _size, coc = dse.staged(c)
        if prm.get("mars"):
            sys.exit(f"{c}: has its own planet plugin; build the city --no-mars (register_worlds.py registers it)")
        files, skip = pack_plan(c, have)
        size = sum(s for _r, s in files)
        if size > dse.ARCHIVE_LIMIT:
            sys.exit(f"{c}: {size / 1024 ** 3:.2f} GiB to pack, over one archive's 4 GiB")
        arc = os.path.splitext(plugins[0])[0] + " - Main.ba2"
        plan.append((c, plugins[0], arc, files, skip, coc))
        print(f"{plugins[0]}: {len(files):,} files ({size / 1e6:,.0f} MB) into {arc}; {skip['skipped']:,} "
              f"({skip['skipped_bytes'] / 1e6:,.0f} MB) already in the exterior's archives; {skip['replaced']:,} "
              "packed although the exterior has an older version")
    reg_plugin = reg["plugin"]
    targets = [t for _c, p, arc, _f, _s, _coc in plan for t in (p, arc)] + [reg_plugin]
    clash = [t for t in targets if os.path.exists(os.path.join(data, t))]
    if clash:
        sys.exit("refusing to overwrite existing files in Data: " + ", ".join(clash))
    missing = [m for m in reg["masters"][1:] if not os.path.exists(os.path.join(data, m)) and m not in targets]
    if missing:
        sys.exit(f"{reg_plugin} needs {missing} in Data")
    pt = dse.plugins_txt_path()
    original, lines = dse.read_plugins(pt)
    names = [ln.strip().lstrip("*").lower() for ln in lines]
    add = [f"*{p}" for _c, p, _a, _f, _s, _coc in plan] + [f"*{reg_plugin}"]
    add = [x for x in add if x[1:].lower() not in names]
    after = max([i for i, n in enumerate(names) if n in {f.lower() for f in ext["files"] if f.endswith(".esm")}],
                default=len(lines) - 1)
    print(f"Plugins.txt ({pt}): add {add} after line {after + 1}")
    if a.dry_run:
        return 0
    sources = []
    for c, p, arc, files, _skip, _coc in plan:
        out = os.path.join(c, arc)
        with tempfile.TemporaryDirectory(prefix="citypack-", dir=c) as root:
            build_pack_root(c, files, root)
            dirs = [d for d in dse.DATA_DIRS if os.path.isdir(os.path.join(root, d))]
            print(f"packing {arc} with Archive2 (stored, no compression)...")
            r = dse.subprocess.run([os.path.join(a.starfield, "Tools", "Archive2", "Archive2.exe"), ",".join(dirs),
                                    f"-create={out}", f"-root={root}", "-format=General", "-compression=None"],
                                   cwd=root, capture_output=True, text=True)
            if r.returncode != 0 or not os.path.isfile(out):
                sys.exit("Archive2 failed:\n" + (r.stdout or "") + (r.stderr or ""))
        sources += [(os.path.join(c, p), p), (out, arc)]
    sources.append((os.path.join(a.register, reg_plugin), reg_plugin))
    state = {"files": [], "artifacts": {}, "plugins_txt": pt, "plugins_added": add,
             "coc": [coc for *_x, coc in plan], "cities": [c for c, *_x in plan], "hide": reg.get("hide", [])}

    def save():
        with open(man_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
    save()
    try:
        for src, rel in sources:
            with open(src, "rb") as fi, open(os.path.join(data, rel), "xb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
            state["files"].append(rel)
            save()
        hide(data, state["hide"], state)
        for rel in state["files"]:
            state["artifacts"][rel] = dse.sha256(os.path.join(data, rel))
        save()
        if add:
            now, _ = dse.read_plugins(pt)
            if now != original:
                raise OSError("Plugins.txt changed during install")
            dse.write_plugins(pt, lines[:after + 1] + add + lines[after + 1:], original)
    except Exception as e:                                   # noqa: BLE001  (roll back)
        restore_exterior(data, state)
        for rel in state["files"]:
            try:
                os.remove(os.path.join(data, rel))
            except OSError:
                pass
        os.remove(man_path)
        sys.exit(f"install failed and was rolled back: {type(e).__name__}: {e}")
    print("installed. MO2: refresh (F5) and tick " + ", ".join(x[1:] for x in add) + " after "
          "SkyrimTerrainTamriel_Mars.esm (the registration plugin last).\n"
          f"In game: coc {ext.get('coc') or 'SKY_TamrielRiverwoodSpawn'}, walk to the city's gate and use it; or coc "
          + ", ".join(state["coc"]) + ".\nUndo: python -I scripts\\deploy_skyrim_city.py uninstall --starfield "
          f"\"{a.starfield}\"")
    return 0


def restore_exterior(data, state) -> list:
    """Put the exterior's gate statics back (flags, DATA as before install) where they are still as we left them.
    Returns the ones left alone."""
    left = []
    for key, v in list(state.get("restore", {}).items()):
        plugin, lid = key.rsplit(":", 1)
        path = os.path.join(data, plugin)
        h = next((x for x in state["hide"] if f"{x['plugin']}:{x['local_id']}" == key), None)
        cur = ref_state(path, int(lid, 16)) if os.path.exists(path) else None
        if cur is None:
            continue                                         # the exterior is gone: nothing to restore
        if h and cur[1] == bytes.fromhex(h["data"]):
            set_ref(path, int(lid, 16), v["flags"], bytes.fromhex(v["data"]))
            print(f"  {key}: gate static back")
        elif cur[1] != bytes.fromhex(v["data"]):
            left.append(key)
        state["restore"].pop(key)
    return left


def uninstall(a):
    data = os.path.join(a.starfield, "Data")
    man_path = os.path.join(data, MANIFEST)
    if not os.path.exists(man_path):
        sys.exit("nothing to uninstall (no manifest)")
    m = load(man_path)
    print(f"removing {m['files']} and Plugins.txt lines {m['plugins_added']}")
    if a.dry_run:
        return 0
    odd = restore_exterior(data, m)
    if odd:
        print(f"  left as they are (changed by something else since install): {odd}")
    left = []
    for rel in m["files"]:
        p = os.path.join(data, rel)
        if os.path.basename(rel) != rel:
            left.append(rel)
            continue
        if os.path.exists(p):
            if dse.sha256(p) != m["artifacts"].get(rel):
                print(f"  {rel} changed since install: kept")
                left.append(rel)
                continue
            os.remove(p)
    pt = m["plugins_txt"]
    original, lines = dse.read_plugins(pt)
    drop = {x.lower() for x in m["plugins_added"]}
    if original is not None and drop:
        dse.write_plugins(pt, [ln for ln in lines if ln.strip().lower() not in drop], original)
    if left:
        m["files"], m["plugins_added"] = left, []
        with open(man_path, "w", encoding="utf-8") as fh:
            json.dump(m, fh, indent=1)
        sys.exit(f"uninstalled except {left} (changed since install; manifest kept)")
    os.remove(man_path)
    print("uninstalled")
    return 0


def rehide(a):
    data = os.path.join(a.starfield, "Data")
    man_path = os.path.join(data, MANIFEST)
    if not os.path.exists(man_path):
        sys.exit("no cities installed (no manifest)")
    m = load(man_path)
    hide(data, m["hide"], m)
    for rel in m["files"]:                                    # our own plugins may have been re-hidden too
        if os.path.exists(os.path.join(data, rel)):
            m["artifacts"][rel] = dse.sha256(os.path.join(data, rel))
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("install", "uninstall", "hide"))
    ap.add_argument("--city", action="append", default=[], help="install: a staged city (repeatable)")
    ap.add_argument("--register", default="", help="install: register_worlds.py --out (with --skyrim: the gates)")
    ap.add_argument("--exterior", default="", help="install: the installed exterior's staging (skyrim_all)")
    ap.add_argument("--starfield", required=True, help="the Starfield game folder")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.action == "install" and not (a.city and a.register and a.exterior):
        sys.exit("install needs --city, --register and --exterior")
    return {"install": install, "uninstall": uninstall, "hide": rehide}[a.action](a)


if __name__ == "__main__":
    sys.exit(main())
