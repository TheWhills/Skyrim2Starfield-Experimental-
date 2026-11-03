"""Build a test mod of Skyrim HDT-SMP wigs (KS Hairdos SMP's wigs) for Starfield, with their hair physics as Starfield's
own cloth (docs/armor/animation-port.md "SMP hair -> Starfield cloth").

On the owner's PC, in one run:
  1. finds each wig NIF of the mod (default: its "01 Wigs" folder, female wigs) and the SMP config it names;
  2. re-rigs the hair onto Starfield's head / chest bones and the hair's own simulated bones (fo4sf.skyrimhair),
     builds the cloth that drives those bones from the config (fo4sf.smpcloth) on a cloth template (a Starfield
     physics hair: the vanilla game's when one fits, else --cloth-template), converts materials and textures with
     the Skyrim object converter;
  3. copies a vanilla head apparel record (keyword ArmorTypeApparelHead) once per wig into S2SHair.esm;
  4. packs "S2SHair - Main.ba2" / "S2SHair - Textures.ba2" with Archive2 (or leaves the files loose).

    python -I scripts\\armor\\hair_pack.py --ks "<KS Hairdos SMP folder>" --starfield "<Starfield folder>"
        --texconv "<texconv.exe>" --out "<MO2 mods>\\S2S Hair" --only Anna

--cloth-template takes a Starfield NIF with cloth (or "<archive.ba2>:<path in archive>", or a .hkx tagfile); it must be
a bone-driving hair with bone-space skinning and capsule colliders (e.g. Eris Hairstyles' long curls). Read-only on
both games' files.
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fo4sf import ba2 as ba2mod  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import sfcloth, sfnif, sfplugin, skyrimconvert, skyrimhair, skyrimnif, smpcloth  # noqa: E402
from fo4sf import smpconfig as smp  # noqa: E402

PLUGIN = "S2SHair.esm"
MAIN_BA2 = "S2SHair - Main.ba2"
TEX_BA2 = "S2SHair - Textures.ba2"
PREFIX = "s2s"
HEAD_KEYWORD = "ArmorTypeApparelHead"
WIG_GLOB = re.compile(r"(^|/)meshes/armor/kswigshdt/f/[^/]+\.nif$", re.I)


class LooseRoots:
    """Loose files of one or more mod folders (installer folders such as "00 Core" / "01 Wigs" included), with the
    interface pipeline.Converter uses (mesh, texture, material, mesh_names). Later roots win; names case-blind."""

    def __init__(self, roots):
        self.index = {}
        for root in roots:
            for d, _ds, fs in os.walk(root):
                for f in fs:
                    p = os.path.join(d, f)
                    rel = os.path.relpath(p, root).replace("\\", "/").lower()
                    self.index[rel] = p
                    # an installer subfolder ("00 Core/Meshes/..."): also index from its data root
                    m = re.match(r"^[^/]+/((?:meshes|textures|skse|interface)/.*)$", rel)
                    if m:
                        self.index[m.group(1)] = p

    def _read(self, rel):
        p = self.index.get(rel.replace("\\", "/").lower().lstrip("/"))
        if p is None:
            return None
        with open(p, "rb") as fh:
            return fh.read()

    def mesh(self, name):
        n = name.replace("\\", "/").lower()
        return self._read(n if n.startswith("meshes/") else "meshes/" + n)

    def texture(self, name):
        n = name.replace("\\", "/").lower()
        return self._read(n if n.startswith("textures/") else "textures/" + n)

    def material(self, name):
        return None

    def data(self, rel):
        return self._read(smp.data_relative(rel).replace("\\", "/"))

    def mesh_names(self, pattern):
        rx = re.compile(pattern, re.I)
        return sorted(k for k in self.index if k.endswith(".nif") and rx.search(k))


def read_template(spec: str) -> bytes:
    """Cloth tagfile from a NIF / .hkx file, or "<archive.ba2>:<path>"."""
    m = re.match(r"^(.*\.ba2):(.+)$", spec, re.I)
    if m:
        a = ba2mod.Ba2(m.group(1))
        want = m.group(2).replace("\\", "/").lower()
        hit = next((i for i, n in enumerate(a.names) if n.replace("\\", "/").lower().endswith(want)), None)
        if hit is None:
            raise SystemExit(f"{m.group(2)} not in {m.group(1)}")
        data = a.read(hit)
    else:
        with open(spec, "rb") as fh:
            data = fh.read()
    if data[4:8] == b"TAG0":
        return data
    n = nifmod.parse(data)
    blobs = [sfcloth.payload(b) for i, b in enumerate(n.blocks) if n.type_of(i) == "BSClothExtraData"]
    if not blobs:
        raise SystemExit(f"{spec}: no BSClothExtraData")
    return blobs[0]


def find_template(starfield: str, report: dict) -> bytes:
    """The best vanilla hair cloth smpcloth can build on (scans the game's mesh archives): one with a local range and
    stretch links (SMP's swing limits) wins; the first such ends the scan."""
    data = os.path.join(starfield, "Data")
    tried, best = 0, None
    for f in sorted(os.listdir(data)):
        if not (f.lower().startswith("starfield - meshes") and f.lower().endswith(".ba2")):
            continue
        try:
            a = ba2mod.Ba2(os.path.join(data, f))
        except ba2mod.Ba2Error:
            continue
        for i, name in enumerate(a.names):
            nl = name.lower()
            if "hair" not in nl or not nl.endswith(".nif"):
                continue
            raw = a.read(i)
            if b"BSClothExtraData" not in raw:
                continue
            tried += 1
            try:
                n = nifmod.parse(raw)
                blob = next(sfcloth.payload(b) for k, b in enumerate(n.blocks) if n.type_of(k) == "BSClothExtraData")
                root = smpcloth.check_template(blob)
            except Exception:                                    # noqa: BLE001 (not a usable template: next)
                continue
            score = smpcloth.template_score(root)
            if best is None or score > best[0]:
                best = (score, blob, f"{f}:{name}", root["$kind"])
            if score >= 3:
                break
        if best is not None and best[0] >= 3:
            break
    report["cloth_templates_looked_at"] = tried
    if best is None:
        raise SystemExit(f"no vanilla hair cloth fits ({tried} cloth hairs looked at): pass --cloth-template, e.g. "
                         "\"<Eris Hairstyles>\\ErisHair - Main.ba2:meshes/actors/human/mesh/hairs/eh_longcurls/"
                         "longcurls_f.nif\"")
    report["cloth_template"], report["cloth_template_kind"] = best[2], best[3]
    return best[1]


def head_apparel(armo, arma, kw_names):
    """(ARMO, ARMA) of the first vanilla ARMO with the head-apparel keyword that names an ARMA."""
    head = {k for k, n in kw_names.items() if n == HEAD_KEYWORD}
    by_fid = {r[3]: r for r in arma}
    for r in sorted(armo, key=lambda r: sfplugin.edid(r[2])):
        if head & set(sfplugin.keywords(r[2])):
            for s, d in r[2]:
                if s == b"MODL" and len(d) == 4 and struct.unpack("<I", d)[0] in by_fid:
                    return r, by_fid[struct.unpack("<I", d)[0]]
    raise SystemExit(f"no vanilla ARMO with {HEAD_KEYWORD} and an addon")


def read_game_file(starfield: str, rel: str):
    """A file of the game's own archives (Starfield - Meshes*.ba2 ...) by its path in the archive, or None."""
    want = rel.replace("\\", "/").lower()
    data = os.path.join(starfield, "Data")
    for f in sorted(os.listdir(data)):
        if not (f.lower().startswith("starfield - ") and f.lower().endswith(".ba2")):
            continue
        try:
            a = ba2mod.Ba2(os.path.join(data, f))
        except ba2mod.Ba2Error:
            continue
        for i, name in enumerate(a.names):
            if name.replace("\\", "/").lower() == want:
                return a.read(i)
    return None


def game_files_named(starfield: str, stem: str, limit: int = 200):
    """Paths in the game's archives whose file or folder name contains `stem` (case-blind): what else the game keeps
    for a model (morphs, face bones ...), found by name only."""
    stem = stem.lower()
    data = os.path.join(starfield, "Data")
    out = []
    for f in sorted(os.listdir(data)):
        if not (f.lower().startswith("starfield - ") and f.lower().endswith(".ba2")):
            continue
        try:
            a = ba2mod.Ba2(os.path.join(data, f))
        except ba2mod.Ba2Error:
            continue
        out += [f"{f}:{n}" for n in a.names if stem in n.replace("\\", "/").lower()]
        if len(out) >= limit:
            break
    return out[:limit]


def subrecord_dump(rec):
    """[signature, size, first 48 bytes as hex] of a record's subrecords (for comparing a template with its copy)."""
    return [[s.decode("latin-1"), len(d), bytes(d[:48]).hex()] for s, d in rec[2]]


def nif_materials(raw: bytes):
    """The material names of a Starfield NIF's shapes (BSLightingShaderProperty names), in block order."""
    n = nifmod.parse(raw)
    out = []
    for i in range(len(n.blocks)):
        if n.type_of(i) == "BSLightingShaderProperty":
            si, = struct.unpack_from("<i", n.blocks[i], 0)
            if 0 <= si < len(n.strings) and n.strings[si]:
                out.append(n.strings[si].decode("latin-1"))
    return out


def arma_model(arma) -> str:
    """The worn model of an ARMA (female, else male), as written in the record."""
    d = dict((k, bytes(v)) for k, v in arma[2])
    for k in (b"MOD3", b"MOD2"):
        if d.get(k, b"\0")[:1] != b"\0":
            return d[k].split(b"\0")[0].decode("latin-1")
    return ""


def write_files(staging: str, files: dict):
    for rel, data in files.items():
        p = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)


def facebones_worlds_of(raw: bytes) -> dict:
    """({face bone: rest world}, the shape node transform as a 4x4) of a vanilla *_facebones.nif."""
    from fo4sf import sfweaponleft
    n = nifmod.parse(raw)
    shapes = sfweaponleft.shapes_in_model(n)
    node = skyrimhair.xf_matrix(shapes[0][1]) if shapes else None
    return skyrimhair.face_bone_worlds(sfnif.parse_skin(n), node), node


def facebones_template(starfield: str, hat_model: str, report: dict, hair_template: str = None):
    """(face bone, its rest world, every face bone's world, the hat's facebones NIF bytes) or None. Head items are
    drawn from <model>_facebones.nif on actors with face bones (the player, named NPCs): vanilla hats and hairs ship
    both files (verified in game 2026-11-02: our wigs show once that file exists). The face bones' rest worlds come
    from a vanilla hair's facebones file (the cloth template's, e.g. bob_f_facebones.nif) when found, else the hat's;
    both are reported to compare."""
    if not hat_model:
        return None
    rel = "meshes/" + os.path.splitext(hat_model.replace("\\", "/"))[0] + "_facebones.nif"
    raw = read_game_file(starfield, rel)
    info = report.setdefault("facebones", {})
    info["hat_file"] = rel if raw is not None else f"not found: {rel}"
    if raw is None:
        return None
    sources = []
    if hair_template and ":" in hair_template:
        hrel = os.path.splitext(hair_template.split(":", 1)[1].replace("\\", "/"))[0] + "_facebones.nif"
        hraw = read_game_file(starfield, hrel)
        info["hair_file"] = hrel if hraw is not None else f"not found: {hrel}"
        if hraw is not None:
            sources.append(("hair", hraw))
    sources.append(("hat", raw))
    picked = None
    for kind, data in sources:
        worlds, node = facebones_worlds_of(data)
        face = skyrimhair.pick_face_bone(worlds)
        info[kind] = {"node": None if node is None else np.round(node, 4).tolist(), "face_bones": len(worlds),
                      "face_bone": face, "face_bone_world": np.round(worlds[face], 4).tolist()}
        if picked is None:
            picked = (kind, face, worlds)
    kind, face, worlds = picked
    info["used"] = kind
    report["face_bone"] = face
    return face, worlds[face], worlds, raw


def facebones_files(row: dict, fb, sf_world: dict, rigid_copies: bool) -> dict:
    """<model>_facebones.nif for a wig and its no-physics / head-bone copies: C_Head's weights on the face bone."""
    hair, mats, blob, out_name, backs = row["_fb"]
    face, fw = fb[0], fb[1]
    world = dict(sf_world, **{face: fw})
    files = skyrimhair.nif_files(skyrimhair.on_face_bone(hair, face), mats, blob, world, out_name + "_facebones", backs)
    if rigid_copies:
        rg = skyrimhair.rigid(hair)
        files.update(skyrimhair.nif_files(skyrimhair.on_face_bone(rg, face), mats, None, world,
                                          out_name + "_rigid_facebones", backs))
        hl, hw = skyrimhair.head_local(rg, world, bone=face)
        files.update(skyrimhair.nif_files(hl, mats, None, hw, out_name + "_head_facebones", backs))
    return files


def control_files(row: dict, conv, hat_raw, hat_model: str, fb=None, sf_world=None) -> dict:
    """In-game controls for one wig, to find why a wig is not drawn (each {relative path: bytes} plus its model):
    "opaque": the head-bone copy with its material made solid (no alpha test), "hatmat": the head-bone copy with the
    vanilla hat's own material, "hatcopy": the vanilla hat NIF itself put in this mod's archive."""
    hl, hw, n, out_name, backs = row["_control"]
    out = {}
    mats = []
    for sh in hl.shapes:
        paths = skyrimnif.texture_set(n, sh.shader_ref) if sh.shader_ref >= 0 else []
        if paths and paths[0]:
            mats.append(conv.skyrim_material(paths[0], paths[1] if len(paths) > 1 else "", False, False, 0) or
                        conv.neutral)
        else:
            mats.append(conv.neutral)
    fhl = fhw = None
    if fb is not None:                        # the same controls on the face bone (the file the game draws)
        fhl, fhw = skyrimhair.head_local(skyrimhair.rigid(row["_fb"][0]), dict(sf_world, **{fb[0]: fb[1]}),
                                         bone=fb[0])

    def both(materials, name):
        files = skyrimhair.nif_files(hl, materials, None, hw, name, backs)
        if fhl is not None:
            files.update(skyrimhair.nif_files(fhl, materials, None, fhw, name + "_facebones", backs))
        return files, name
    out["opaque"] = both(mats, out_name + "_opaque")
    hat_mats = nif_materials(hat_raw) if hat_raw else []
    if hat_mats:
        out["hatmat"] = both([hat_mats[0]] * len(hl.shapes), out_name + "_hatmat")
    if hat_raw:
        files = {f"meshes/{PREFIX}/hair/control_hat_copy.nif": hat_raw}
        if fb is not None:
            files[f"meshes/{PREFIX}/hair/control_hat_copy_facebones.nif"] = fb[3]
        out["hatcopy"] = (files, f"{PREFIX}/hair/control_hat_copy")
    if hat_model:            # the addon copied exactly as for a wig, but still naming the vanilla model path
        out["armacopy"] = ({}, os.path.splitext(hat_model.replace("\\", "/"))[0])
    return out


def pack(staging: str, out: str, starfield: str, archive2: str = None, main_ba2: str = MAIN_BA2,
         tex_ba2: str = TEX_BA2) -> dict:
    """BA2 archives named after the plugin (Starfield loads "<plugin> - *.ba2"), or the files loose."""
    tool = archive2 or os.path.join(starfield, "Tools", "Archive2", "Archive2.exe")
    main = [d for d in ("meshes", "geometries", "materials") if os.path.isdir(os.path.join(staging, d))]
    tex = [d for d in ("textures",) if os.path.isdir(os.path.join(staging, d))]
    if os.path.isfile(tool):
        import deploy_starfield
        a = types.SimpleNamespace(starfield=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(tool)))),
                                  staging=staging)
        if main:
            deploy_starfield.build_archive(a, os.path.join(out, main_ba2), main, "General")
        if tex:
            deploy_starfield.build_archive(a, os.path.join(out, tex_ba2), tex, "DDS")
        return {"archives": [main_ba2] * bool(main) + [tex_ba2] * bool(tex)}
    for d in main + tex:
        shutil.copytree(os.path.join(staging, d), os.path.join(out, d), dirs_exist_ok=True)
    return {"loose": main + tex, "note": "Archive2 not found: files left loose"}


def build_one(src: LooseRoots, conv, nif_rel: str, template_blob: bytes, template_root: dict, sf_world: dict,
              settings: smpcloth.Settings, a, staging: str) -> dict:
    """Convert one wig: files written into staging; returns its report row (ok, model, ...)."""
    stem = os.path.splitext(os.path.basename(src.index.get(nif_rel, nif_rel)))[0]     # the file's own spelling
    row = {"wig": stem, "nif": nif_rel, "ok": False}
    raw = src._read(nif_rel)
    n = nifmod.parse(raw)
    paths = smp.nif_physics_paths(n)
    if not paths:
        row["reason"] = "no SMP config named in the NIF"
        return row
    xml = src.data(paths[0])
    if xml is None:
        row["reason"] = f"config not found: {paths[0]}"
        return row
    row["config"] = paths[0]
    hair = skyrimhair.convert(raw, xml, sf_world, a.head_scale, tuple(a.head_offset))
    row.update({k: hair.report[k] for k in ("chain_bones", "hosts", "shapes", "vertices") if k in hair.report})
    if not hair.bones:
        row["reason"] = "the config simulates no bone of this mesh"
        return row
    cap = skyrimhair.head_capsule(sf_world, hair)
    root, rig = smpcloth.build_cloth(template_root, hair.bones, hair.host_of_root, [cap], settings)
    blob = smpcloth.write(template_blob, root)
    row["cloth"] = {**rig.report, "check": smpcloth.verify(blob), "head_capsule_radius": round(cap.radius, 4)}
    mats, backs = [], []
    for sh in hair.shapes:
        mats.append(conv._shape_material(n, sh))
        backs.append(bool(sh.shader_ref >= 0 and skyrimnif.double_sided(n, sh.shader_ref)))
    row["materials"] = mats
    out_name = f"{PREFIX}/hair/{stem.lower()}"
    files = skyrimhair.nif_files(hair, mats, blob, sf_world, out_name, backs)
    for rel, data in files.items():
        p = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    row.update(ok=True, model=out_name.replace("/", "\\") + ".nif")
    row["_fb"] = (hair, mats, blob, out_name, backs)
    if getattr(a, "rigid_copies", False):          # the control: the same wig without physics
        files = skyrimhair.nif_files(skyrimhair.rigid(hair), mats, None, sf_world, out_name + "_rigid", backs)
        for rel, data in files.items():
            p = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(data)
        row["model_rigid"] = out_name.replace("/", "\\") + "_rigid.nif"
        hl, hw = skyrimhair.head_local(skyrimhair.rigid(hair), sf_world)   # second control: the left blade's skin
        files = skyrimhair.nif_files(hl, mats, None, hw, out_name + "_head", backs)
        for rel, data in files.items():
            p = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(data)
        row["model_head"] = out_name.replace("/", "\\") + "_head.nif"
        row["_control"] = (hl, hw, n, out_name, backs)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ks", required=True, nargs="+", help="the KS Hairdos SMP folder(s) (installer or installed)")
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True, help="the mod folder to create (outside the repository)")
    ap.add_argument("--only", help="comma list of wig names (file stems, e.g. Anna,Kikyo); default all")
    ap.add_argument("--cloth-template", help="Starfield NIF / .hkx / '<ba2>:<path>' with a physics hair's cloth")
    ap.add_argument("--content-resources", help="default: <Starfield>/Tools/ContentResources.zip")
    ap.add_argument("--archive2")
    ap.add_argument("--head-scale", type=float, default=skyrimhair.HEAD_SCALE,
                    help="Skyrim -> Starfield skull size ratio (measured on the male heads: 0.93)")
    ap.add_argument("--head-offset", type=float, nargs=3, default=skyrimhair.HEAD_OFFSET, metavar=("X", "Y", "Z"),
                    help="metres added after scaling, model axes (+Y forward, +Z up)")
    ap.add_argument("--damping", type=float, default=smpcloth.Settings.damping, help="cloth damping per second")
    ap.add_argument("--range-scale", type=float, default=1.0, help="how far the hair may swing (x the SMP limits)")
    ap.add_argument("--no-rigid-copies", dest="rigid_copies", action="store_false",
                    help="leave out the in-game controls: each wig's no-physics and head-bone copies and the vanilla control hat")
    ap.add_argument("--slot", type=int, help="biped slot bit for the wigs (default: the template hat's)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    staging = os.path.join(out, "_staging")
    shutil.rmtree(staging, ignore_errors=True)
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    for p, what in ((cr, "ContentResources.zip (Creation Kit)"), (esm, "Starfield.esm")):
        if not os.path.isfile(p):
            sys.exit(f"{what} not found: {p}")
    report = {"plugin": PLUGIN, "wigs": []}
    template_blob = read_template(a.cloth_template) if a.cloth_template else find_template(a.starfield, report)
    report.setdefault("cloth_template", a.cloth_template)
    template_root = smpcloth.check_template(template_blob)
    sk = smpcloth.human_skeleton(template_root)
    world = smpcloth.skeleton_world(sk)
    sf_world = {b["name"]: world[i] for i, b in enumerate(sk["bones"])}
    settings = smpcloth.Settings(damping=a.damping, range_scale=a.range_scale)
    missing = [k for k in a.ks if not os.path.isdir(k)]
    if missing:
        sys.exit(f"--ks folder not found: {', '.join(missing)} (the KS Hairdos SMP folder with '00 Core' and "
                 f"'01 Wigs', or an installed copy with Meshes\\Armor\\KSWigsHDT)")
    src = LooseRoots(a.ks)
    wigs = sorted(k for k in src.index if k.startswith("meshes/") and WIG_GLOB.search(k))
    if a.only:
        keep = {w.strip().lower() for w in a.only.split(",")}
        wigs = [w for w in wigs if os.path.splitext(os.path.basename(w))[0].lower() in keep]
    if not wigs:
        sys.exit("no wig NIF found (meshes/armor/kswigshdt/f/*.nif under --ks)")
    conv = skyrimconvert.SkyrimConverter(src, staging, a.texconv, cr, collision_template=None, prefix=PREFIX)
    for w in wigs:
        try:
            report["wigs"].append(build_one(src, conv, w, template_blob, template_root, sf_world, settings, a,
                                            staging))
        except Exception as e:                                   # noqa: BLE001 (one bad wig must not stop the rest)
            report["wigs"].append({"wig": w, "ok": False, "reason": f"{type(e).__name__}: {e}"})
    good = [r for r in report["wigs"] if r["ok"]]
    if not good:
        sys.exit("no wig converted: " + json.dumps(report["wigs"], indent=1))
    info = sfplugin.header_info(esm)
    sf = sfplugin.records(esm, [b"ARMO", b"ARMA", b"KYWD"])
    kw_names = {fid: sfplugin.edid(s) for t, _h, s, fid in sf if t == b"KYWD"}
    armo_t, arma_t = head_apparel([r for r in sf if r[0] == b"ARMO"], [r for r in sf if r[0] == b"ARMA"], kw_names)
    report["apparel_template"] = {"armo": sfplugin.edid(armo_t[2]), "arma": sfplugin.edid(arma_t[2])}
    fb = facebones_template(a.starfield, arma_model(arma_t), report, report.get("cloth_template"))
    for r in good:
        if fb is not None:
            write_files(staging, facebones_files(r, fb, sf_world, a.rigid_copies))
            r["facebones"] = True
    import weapon_test_pack as wtp
    recs = []
    for r in good:
        edid = "S2S_KSWig_" + re.sub(r"[^A-Za-z0-9]+", "_", r["wig"])
        name = f"{r['wig']} wig (Skyrim)"
        aa, ao = wtp.left_blade_records(armo_t, arma_t, len(recs), edid, name, r["model"], slot=a.slot)
        recs += [aa, ao]
        r.update(editor_id=edid, name=name, form_id_in_plugin=f"{ao[3] & 0xFFFFFF:06X}")
        if r.get("model_rigid"):
            aa2, ao2 = wtp.left_blade_records(armo_t, arma_t, len(recs), edid + "_Rigid",
                                              f"{r['wig']} wig (Skyrim, no physics)", r["model_rigid"], slot=a.slot)
            recs += [aa2, ao2]
            r["form_id_rigid"] = f"{ao2[3] & 0xFFFFFF:06X}"
        if r.get("model_head"):
            aa3, ao3 = wtp.left_blade_records(armo_t, arma_t, len(recs), edid + "_Head",
                                              f"{r['wig']} wig (Skyrim, head bone)", r["model_head"], slot=a.slot)
            recs += [aa3, ao3]
            r["form_id_head"] = f"{ao3[3] & 0xFFFFFF:06X}"
    if a.rigid_copies:                       # the record control: the template hat itself under a new name
        ta, ha, sa, _f = armo_t
        ctl = (ta, ha, sfplugin.edit(sa, {b"EDID": sfplugin.zs("S2S_KSWig_ControlHat"),
                                          b"FULL": sfplugin.zs("S2S control hat (vanilla model)")}),
               sfplugin.new_form_id(len(recs)))
        recs.append(ctl)
        report["control_hat"] = f"{ctl[3] & 0xFFFFFF:06X}"
        first = next((r for r in good if r.get("_control")), None)
        if first is not None:                # material / archive controls, on the first wig only
            hat_model = arma_model(arma_t)
            hat_raw = read_game_file(a.starfield, "meshes/" + hat_model) if hat_model else None
            report["controls"] = {"wig": first["wig"], "hat_model": hat_model, "hat_found": hat_raw is not None,
                                  "hat_materials": nif_materials(hat_raw) if hat_raw else []}
            report["controls"]["arma_template"] = subrecord_dump(arma_t)
            report["controls"]["armo_template"] = subrecord_dump(armo_t)
            if hat_model:
                stem = os.path.splitext(os.path.basename(hat_model.replace("\\", "/")))[0]
                report["controls"]["hat_model_files"] = game_files_named(a.starfield, stem)
            names = {"opaque": "solid material", "hatmat": "hat material", "hatcopy": None, "armacopy": None}
            for kind, (files, model) in control_files(first, conv, hat_raw, hat_model, fb, sf_world).items():
                for rel, data in files.items():
                    pth = os.path.join(staging, *rel.split("/"))
                    os.makedirs(os.path.dirname(pth), exist_ok=True)
                    with open(pth, "wb") as fh:
                        fh.write(data)
                label = (f"{first['wig']} wig (Skyrim, {names[kind]})" if names[kind]
                         else "S2S control hat (copied addon, vanilla path)" if kind == "armacopy"
                         else "S2S control hat (from S2SHair archive)")
                aa4, ao4 = wtp.left_blade_records(armo_t, arma_t, len(recs), f"S2S_KSWig_Control_{kind}", label,
                                                  model.replace("/", "\\") + ".nif", slot=a.slot)
                recs += [aa4, ao4]
                report["controls"][kind] = {"name": label, "form_id": f"{ao4[3] & 0xFFFFFF:06X}"}
    for r in report["wigs"]:
        r.pop("_control", None)
        r.pop("_fb", None)
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, info))
    report["packing"] = pack(staging, out, a.starfield, a.archive2)
    report["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
    with open(os.path.join(out, "hair_pack.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    lines = ["S2S Hair: KS Hairdos SMP wigs with their hair physics as Starfield cloth.", "",
             "Enable this mod in MO2. In game, open the console (~) and run:",
             '  help "wig (Skyrim)" 4     - lists the wigs with their FormIDs', "  player.additem <FormID> 1",
             "then equip it like a hat (pick a short hairstyle or bald look under it).", "",
             "Wig               FormID ending   simulated bones"]
    for r in report["wigs"]:
        if r["ok"]:
            lines.append(f"  {r['wig']:<16} ..{r['form_id_in_plugin'][-3:]}          {len(r.get('chain_bones', []))}"
                         + (f"      (no-physics copy ..{r['form_id_rigid'][-3:]})" if r.get("form_id_rigid") else "")
                         + (f" (head-bone copy ..{r['form_id_head'][-3:]})" if r.get("form_id_head") else ""))
        else:
            lines.append(f"  {r['wig']}: not converted ({r.get('reason')})")
    if report.get("control_hat"):
        lines += ["", f"Control: 'S2S control hat (vanilla model)' ..{report['control_hat'][-3:]} is the vanilla hat "
                      "record under a new name (if it does not show either, the head slot itself is hidden)."]
    for kind, c in (report.get("controls") or {}).items():
        if isinstance(c, dict) and "form_id" in c:
            lines.append(f"Control: '{c['name']}' ..{c['form_id'][-3:]}")
    lines += ["", f"Record copied from the vanilla head apparel {report['apparel_template']['armo']}.",
              f"Cloth template: {report.get('cloth_template')}"]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    shutil.rmtree(staging, ignore_errors=True)
    print("\n".join(lines))
    print(f"\nreport: {os.path.join(out, 'hair_pack.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
