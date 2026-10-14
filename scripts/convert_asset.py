"""Convert one Fallout 4 static (mesh + material + textures) into a Starfield staging folder.

usage: python convert_asset.py --fo4-nif <extracted .nif> --fo4-root <dir holding Materials/ and Textures/ extracted from FO4>
                               --staging <out dir> --name fo4port/setdressing/chairpatio01
                               --content-resources <Starfield\\Tools\\ContentResources.zip> --texconv <Texconvx64.exe>
Needs numpy (pip install numpy). Nothing is written inside the game folders.
"""
import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import convert_material as cm  # noqa: E402
from fo4sf import convert_static, nif, textures  # noqa: E402


def find(root, rel):
    rel = rel.replace("\\", "/").lstrip("/")
    for dp, _, fns in os.walk(root):
        for fn in fns:
            full = os.path.join(dp, fn)
            if os.path.relpath(full, root).replace("\\", "/").lower().endswith(rel.lower()):
                return full
    raise FileNotFoundError(rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fo4-nif", required=True)
    ap.add_argument("--fo4-root", required=True)
    ap.add_argument("--staging", required=True)
    ap.add_argument("--name", required=True, help="output path without extension, e.g. fo4port/setdressing/chair")
    ap.add_argument("--content-resources", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--metalness", type=float, default=0.0)
    ap.add_argument("--flip-green", action="store_true")
    ap.add_argument("--collision-template", default="", help="a vanilla Starfield NIF with plain box collision; enables box collision")
    a = ap.parse_args()

    raw = open(a.fo4_nif, "rb").read()
    src = nif.parse(raw)
    bgsm_path = next(s.decode("latin-1") for s in src.strings if s.lower().endswith(b".bgsm"))
    bgsm = cm.parse_bgsm(open(find(a.fo4_root, bgsm_path), "rb").read())
    print("material:", bgsm_path, "->", bgsm.diffuse, bgsm.normal, bgsm.smooth_spec)

    base = a.name.rsplit("/", 1)
    folder, stem = (base[0], base[1]) if len(base) == 2 else ("", base[0])
    tex_rel = f"textures/{folder}/{stem}".strip("/")
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        # colour: DXT5/BC1 sRGB -> BC1_SRGB
        diff = find(a.fo4_root, "textures/" + bgsm.diffuse)
        textures.texconv(a.texconv, diff, tmp, "BC1_UNORM_SRGB", ("-srgbi",))
        shutil.move(os.path.join(tmp, os.path.basename(diff)), os.path.join(tmp, "color.dds"))
        # normal: BC5 unorm RG -> BC5_SNORM
        nr, ng = textures.load_fo4_bc5(find(a.fo4_root, "textures/" + bgsm.normal))
        if a.flip_green:
            ng = textures.flip_green(ng)
        textures.write_rg8_snorm(os.path.join(tmp, "normal_in.dds"), nr, ng)
        textures.texconv(a.texconv, os.path.join(tmp, "normal_in.dds"), tmp, "BC5_SNORM")
        os.replace(os.path.join(tmp, "normal_in.dds"), os.path.join(tmp, "normal.dds"))
        # roughness: 255 - gloss (spec map G) -> BC4_UNORM
        _sr, sg = textures.load_fo4_bc5(find(a.fo4_root, "textures/" + bgsm.smooth_spec))
        textures.write_r8(os.path.join(tmp, "rough_in.dds"), textures.roughness_from_smoothness(sg))
        textures.texconv(a.texconv, os.path.join(tmp, "rough_in.dds"), tmp, "BC4_UNORM")
        os.replace(os.path.join(tmp, "rough_in.dds"), os.path.join(tmp, "rough.dds"))
        for kind in ("color", "normal", "rough"):
            dst = os.path.join(a.staging, *f"{tex_rel}_{kind}.dds".split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(tmp, f"{kind}.dds"), dst)
            out[kind] = cm.game_path(f"{tex_rel}_{kind}.dds")
            print("wrote", os.path.relpath(dst, a.staging))

    mat_name = f"FO4Port_{stem}"
    mat = cm.build_mat(cm.read_template(a.content_resources), mat_name, out["color"], out["normal"], out["rough"],
                       metalness=a.metalness)
    mat_rel = f"materials/{folder}/{stem}.mat".replace("//", "/")
    mat_path = os.path.join(a.staging, *mat_rel.split("/"))
    os.makedirs(os.path.dirname(mat_path), exist_ok=True)
    open(mat_path, "w", encoding="utf-8", newline="\n").write(cm.dump_mat(mat))
    print("wrote", mat_rel)

    template = None
    if a.collision_template:
        template = convert_static.collision_template_from_nif(open(a.collision_template, "rb").read())
        print("collision: box from template", os.path.basename(a.collision_template))
    files = convert_static.convert_static(raw, a.name, material_path=mat_rel.replace("/", "\\"), collision_template=template)
    for rel, data in files.items():
        p = os.path.join(a.staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(data)
        print("wrote", rel)


if __name__ == "__main__":
    main()
