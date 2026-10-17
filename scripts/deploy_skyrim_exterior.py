"""Install / uninstall a staged Skyrim exterior build (terrain overlay, with or without objects) into Starfield, reversibly.

The staging folder is make_skyrim_overlay.py build --out (terrain only) or make_skyrim_objects.py stage --out (terrain +
objects), after dotnet/TerrainOverlays wrote its plugins there. Its overlays_params.json names them.

install  : packs <staging>\\Data (Terrain, meshes, geometries, materials, textures, lodsettings) into "<plugin stem> - Main.ba2" with
           the official Archive2 (Starfield Creation Kit) and -compression=None: the terrain BTD must be stored
           uncompressed (experiment 2b read a packed BTD as flat ground). Copies the archive, the plugin and the Mars
           registration plugin into Starfield\\Data, activates both in Plugins.txt (plugin first), and records everything
           in Data\\SkyrimExterior.deploy.json. Refuses to overwrite files, or to install a second terrain experiment.
uninstall: removes exactly what the manifest lists, and its Plugins.txt lines.

    python -I scripts\\deploy_skyrim_exterior.py install --staging C:\\Modding\\staging\\skyrim_objects --starfield "<Starfield>"
    python -I scripts\\deploy_skyrim_exterior.py uninstall --starfield "<Starfield>"
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

MANIFEST = "SkyrimExterior.deploy.json"
# lodsettings: distant-object LOD's <world>.lod (make_skyrim_objects.py lod); it was missing from the first LOD
# installs, so the engine never had our world's LOD settings
DATA_DIRS = ("Terrain", "meshes", "geometries", "materials", "textures", "lodsettings", "planetdata")
ARCHIVE_LIMIT = 4 * 1024 ** 3                      # one stored General archive


def plugins_txt_path():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Starfield", "Plugins.txt")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_plugins(path):
    if not os.path.exists(path):
        return None, []
    with open(path, "rb") as f:
        raw = f.read()
    return raw, raw.decode("utf-8-sig").splitlines()


def write_plugins(path, lines, original):
    bom = b"\xef\xbb\xbf" if original and original.startswith(b"\xef\xbb\xbf") else b""
    nl = "\n" if original and b"\r\n" not in original and b"\n" in original else "\r\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".skyext-plugins-", dir=os.path.dirname(path))
    with os.fdopen(fd, "wb") as f:
        f.write(bom + (nl.join(lines) + (nl if lines else "")).encode("utf-8"))
    os.replace(tmp, path)


def staged(staging):
    prm_path = os.path.join(staging, "overlays_params.json")
    if not os.path.exists(prm_path):
        sys.exit(f"{prm_path} missing: not a staged terrain / objects build")
    with open(prm_path, encoding="utf-8") as f:
        prm = json.load(f)
    plugins = [prm["plugin"]] + ([prm["mars"]["plugin"]] if prm.get("mars") else [])
    for p in plugins:
        if not os.path.exists(os.path.join(staging, p)):
            sys.exit(f"{p} not in {staging}: run dotnet/TerrainOverlays (or stage --sf-esm) first")
        # a failed plugin build leaves the previous run's plugin behind (owner's run: the stage step's dotnet build
        # failed and the old plugin was installed): refuse plugins older than the params they were built from
        if os.path.getmtime(os.path.join(staging, p)) < os.path.getmtime(prm_path):
            sys.exit(f"{p} is older than overlays_params.json: the plugin build did not finish (stage / "
                     "dotnet/TerrainOverlays failed?); rebuild before installing")
    dirs = [d for d in DATA_DIRS if os.path.isdir(os.path.join(staging, "Data", d))]
    if "Terrain" not in dirs:
        sys.exit(f"{staging}\\Data\\Terrain missing")
    size = sum(os.path.getsize(os.path.join(r, f)) for d in dirs
               for r, _ds, fs in os.walk(os.path.join(staging, "Data", d)) for f in fs)
    coc = prm["overlays"][0].get("coc")
    return prm, plugins, dirs, size, coc


def other_terrain_plugins(data):
    """Terrain experiments already in Data (every Mars plugin overrides MarsPlanetData: never two at once)."""
    return sorted(f for f in os.listdir(data) if f.lower().endswith("_mars.esm"))


def build_archive(starfield, staging, dirs, out):
    tool = os.path.join(starfield, "Tools", "Archive2", "Archive2.exe")
    if not os.path.exists(tool):
        sys.exit(f"Archive2 not found at {tool} (install the Starfield Creation Kit)")
    root = os.path.join(staging, "Data")
    if os.path.exists(out):
        os.remove(out)                                   # a stale build must not pass as this one
    r = subprocess.run([tool, ",".join(dirs), f"-create={out}", f"-root={root}", "-format=General",
                        "-compression=None"], cwd=root, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(out):
        sys.exit("Archive2 failed:\n" + (r.stdout or "") + (r.stderr or ""))
    with open(out, "rb") as f:
        if f.read(4) != b"BTDX":
            sys.exit(f"Archive2 wrote something that is not a BA2: {out}")


def install(a):
    staging = os.path.abspath(a.staging)
    prm, plugins, dirs, size, coc = staged(staging)
    if size > ARCHIVE_LIMIT:
        sys.exit(f"staged Data is {size / 1024 ** 3:.2f} GiB: over one archive's 4 GiB; use a smaller area or "
                 "--max-texture 1024 in the convert step")
    data = os.path.join(a.starfield, "Data")
    man_path = os.path.join(data, MANIFEST)
    if os.path.exists(man_path):
        sys.exit("a Skyrim exterior is already installed (manifest exists): uninstall first")
    others = [p for p in other_terrain_plugins(data) if p not in plugins]
    if others:
        sys.exit(f"another terrain experiment is installed ({others}); every Mars plugin overrides MarsPlanetData, "
                 "so only one at a time: uninstall it first")
    archive = os.path.splitext(plugins[0])[0] + " - Main.ba2"
    targets = plugins + [archive]
    clash = [t for t in targets if os.path.exists(os.path.join(data, t))]
    if clash:
        sys.exit("refusing to overwrite existing files in Data: " + ", ".join(clash))
    pt = plugins_txt_path()
    original, lines = read_plugins(pt)
    names = {ln.strip().lstrip("*").lower() for ln in lines}
    add = [f"*{p}" for p in plugins if p.lower() not in names]
    print(f"install {targets} -> {data} ({', '.join(dirs)}, {size / 1e6:,.0f} MB stored)\n"
          f"Plugins.txt ({pt}): add {add or 'nothing'}")
    if a.dry_run:
        return 0
    built = os.path.join(staging, archive)
    print("packing with Archive2 (stored, no compression)...")
    build_archive(a.starfield, staging, dirs, built)
    sources = [os.path.join(staging, p) for p in plugins] + [built]
    state = {"files": [], "artifacts": {}, "plugins_txt": pt, "plugins_added": add, "coc": coc}
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    try:
        for src, rel in zip(sources, targets):
            dst = os.path.join(data, rel)
            with open(src, "rb") as fi, open(dst, "xb") as fo:     # "x": never overwrite
                shutil.copyfileobj(fi, fo, 1 << 20)
            state["files"].append(rel)
            state["artifacts"][rel] = sha256(dst)
            with open(man_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=1)
        if add:
            now, _ = read_plugins(pt)
            if now != original:
                raise OSError("Plugins.txt changed during install")
            write_plugins(pt, lines + add, original)
    except Exception as e:                                  # noqa: BLE001  (roll back what was copied)
        for rel in state["files"]:
            try:
                os.remove(os.path.join(data, rel))
            except OSError:
                pass
        os.remove(man_path)
        sys.exit(f"install failed and was rolled back: {type(e).__name__}: {e}")
    print(f"installed. In game: tgm, then coc {coc}\n"
          f"Undo: python -I scripts\\deploy_skyrim_exterior.py uninstall --starfield \"{a.starfield}\"")
    return 0


def uninstall(a):
    data = os.path.join(a.starfield, "Data")
    man_path = os.path.join(data, MANIFEST)
    if not os.path.exists(man_path):
        sys.exit("nothing to uninstall (no manifest)")
    with open(man_path, encoding="utf-8") as f:
        m = json.load(f)
    print(f"removing {m['files']} and Plugins.txt lines {m['plugins_added']}")
    if a.dry_run:
        return 0
    left = []
    for rel in m["files"]:
        if os.path.basename(rel) != rel:
            left.append(rel)
            continue
        p = os.path.join(data, rel)
        if os.path.exists(p):
            if sha256(p) != m["artifacts"].get(rel):
                print(f"  {rel} changed since install: kept")
                left.append(rel)
                continue
            os.remove(p)
    pt = m["plugins_txt"]
    original, lines = read_plugins(pt)
    drop = {x.lower() for x in m["plugins_added"]}
    if original is not None and drop:
        write_plugins(pt, [ln for ln in lines if ln.strip().lower() not in drop], original)
    if left:
        m["files"], m["plugins_added"] = left, []
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1)
        sys.exit(f"uninstalled except {left} (changed since install; manifest kept)")
    os.remove(man_path)
    print("uninstalled")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("install", "uninstall"))
    ap.add_argument("--staging", default="", help="install: the staged build (objects stage --out, or overlay build --out)")
    ap.add_argument("--starfield", required=True, help="the Starfield game folder")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.action == "install" and not a.staging:
        sys.exit("install needs --staging")
    return (install if a.action == "install" else uninstall)(a)


if __name__ == "__main__":
    sys.exit(main())
