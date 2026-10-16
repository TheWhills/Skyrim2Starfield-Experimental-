"""Batch conversion of Fallout 4 statics read straight from the game's BA2 archives.

    src = Fo4Archives("<FO4 Data dir>")
    conv = Converter(src, staging, texconv, content_resources_zip, collision_template_nif_bytes)
    result = conv.convert_nif("meshes/setdressing/patiofurniture/chairpatio01.nif")

Each shape uses its own material; materials/textures are converted once and cached. Anything that cannot be converted falls
back to a placeholder material (tier T1) instead of failing the asset. Needs numpy and texconv.
"""
import hashlib
import os
import re
import shutil
import struct
import tempfile
from typing import Dict, List, Optional

from . import ba2 as ba2mod
from . import convert_material as cm
from . import convert_static, nif, sfcollision, sfnif, textures

DOOR_RE = re.compile(r"[\\/]doors?[\\/]|door[^\\/]*\.nif$", re.I)
NOT_HINGED_RE = re.compile(r"vault|elevator|garage|gate|hatch|slid", re.I)   # sliding / lifting doors animate differently
# FO4 load doors never swing open into the next space: activating one teleports. Destinations are not ported yet, so a
# rigged swing opened onto the void behind the wall (Parsons: walked through the entrance door, fell to z -72). Keep
# them shut and solid with their native collision; the missing teleport is reported per asset as "load_door".
LOAD_DOOR_RE = re.compile(r"door[^\\/]*load[^\\/]*\.nif$|load[^\\/]*door[^\\/]*\.nif$", re.I)


class Fo4Archives:
    def __init__(self, data_dir: str):
        self.meshes, self.materials, self.textures = [], [], []
        for fn in sorted(os.listdir(data_dir)):
            low = fn.lower()
            if not (low.endswith(".ba2") and low.startswith("fallout4 - ")):
                continue
            if "meshes" in low:
                self.meshes.append(ba2mod.Ba2(os.path.join(data_dir, fn)))
            elif "materials" in low:
                self.materials.append(ba2mod.Ba2(os.path.join(data_dir, fn)))
            elif "textures" in low:
                self.textures.append(ba2mod.Ba2(os.path.join(data_dir, fn)))

    @staticmethod
    def _read(archives, name):
        for a in archives:
            i = a.find(name)
            if i is not None:
                return a.read(i)
        return None

    def mesh(self, name):
        return self._read(self.meshes, name)

    def material(self, name):
        return self._read(self.materials, name)

    def texture(self, name):
        n = name.replace("\\", "/").lstrip("/")
        return self._read(self.textures, n if n.lower().startswith("textures/") else "textures/" + n)

    def mesh_names(self, pattern: str):
        rx = re.compile(pattern, re.I)
        out = []
        for a in self.meshes:
            out += [n for n in a.names if n.lower().endswith(".nif") and rx.search(n.replace("\\", "/"))]
        return sorted(set(out), key=str.lower)


def _plane_pair(dds: bytes, tmp: str, texconv_exe: str):
    """(R, G) uint8 planes of a DDS: native BC5, otherwise decoded through texconv."""
    h = textures.read_dds_header(dds)
    if h["dxgi"] in (83, 84) or h["fourcc"] in (b"BC5U", b"ATI2"):
        return textures.decode_bc5(dds[h["data_offset"]:], h["width"], h["height"])
    import numpy as np
    src = os.path.join(tmp, "dec_in.dds")
    open(src, "wb").write(dds)
    textures.texconv(texconv_exe, src, tmp, "R8G8B8A8_UNORM", ("-m", "1"))
    out = open(os.path.join(tmp, "dec_in.dds"), "rb").read()
    hh = textures.read_dds_header(out)
    px = np.frombuffer(out[hh["data_offset"]:hh["data_offset"] + hh["width"] * hh["height"] * 4], dtype=np.uint8)
    px = px.reshape(hh["height"], hh["width"], 4)
    return px[:, :, 0].copy(), px[:, :, 1].copy()


class Converter:
    def __init__(self, src: Fo4Archives, staging: str, texconv_exe: str, content_resources: str,
                 collision_template: Optional[bytes] = None, prefix: str = "fo4port",
                 no_collision_pattern: str = r"^meshes[\\/](architecture|interiors|scol)[\\/]", rig_doors: bool = False,
                 door_physics_donor: Optional[bytes] = None, sf_mesh_template: Optional[bytes] = None,
                 max_texture=None):
        self.src, self.staging, self.texconv = src, staging, texconv_exe
        # max_texture: optional size cap per texture kind (textures.parse_texture_caps: '1024' or 'color=1024,...'); the
        # converted DDS loses its top mip levels until it fits (textures.cap_dds). Off by default: FO4Port keeps full
        # resolution. When set, texture_log records every texture's full and written size.
        self.texture_caps = textures.parse_texture_caps(max_texture)
        self.texture_log: Dict[str, dict] = {}
        # rig_doors: hinged doors become DOOR NIFs that open (needs door_physics_donor: without a keyframed leaf body the leaf
        # is pinned and blocks the doorway). Off by default because the donor comes from the Starfield install.
        self.rig_doors = rig_doors
        self.door_physics_donor = door_physics_donor
        # vanilla Starfield mesh-collision blob: FO4's own collision meshes are transplanted (meshcollision.transplant)
        self.sf_mesh_template = sf_mesh_template   # body of a vanilla door leaf (sfcollision.physics_blob_from_nif)
        self.template_mat = cm.read_template(content_resources)
        self.collision_template = collision_template
        self.prefix = prefix
        # one AABB box is wrong for architecture (a corridor piece would become a solid block), so skip it there for now
        self.no_collision = re.compile(no_collision_pattern, re.I) if no_collision_pattern else None
        self._materials: Dict[str, Optional[str]] = {}
        self.stats = {"assets": 0, "failed": 0, "materials_ok": 0, "materials_fallback": 0}
        self.material_errors: Dict[str, str] = {}
        self._blend_cache: Dict[str, bool] = {}
        self._glass_template = None
        self._decal_template = None
        self.content_resources = content_resources
        self.neutral = self._make_neutral_material()

    def _make_neutral_material(self) -> str:
        """Plain mid-grey, flat, fairly rough material used when a shape's own material cannot be converted
        (instead of the vanilla template's marble look)."""
        import numpy as np
        stem = "_neutral"
        tex_rel = f"textures/{self.prefix}/{stem}"
        out = {}
        with tempfile.TemporaryDirectory() as tmp:
            grey = np.full((16, 16), 128, np.uint8)
            rgba = np.stack([grey, grey, grey, np.full((16, 16), 255, np.uint8)], axis=-1)
            textures.write_dds_dx10(os.path.join(tmp, "c_in.dds"), 16, 16, textures.DXGI_R8G8B8A8_UNORM, rgba.tobytes(), 4)
            textures.texconv(self.texconv, os.path.join(tmp, "c_in.dds"), tmp, "BC1_UNORM_SRGB")
            textures.write_rg8_snorm(os.path.join(tmp, "n_in.dds"), np.full((16, 16), 128, np.uint8), np.full((16, 16), 128, np.uint8))
            textures.texconv(self.texconv, os.path.join(tmp, "n_in.dds"), tmp, "BC5_SNORM")
            textures.write_r8(os.path.join(tmp, "r_in.dds"), np.full((16, 16), 190, np.uint8))
            textures.texconv(self.texconv, os.path.join(tmp, "r_in.dds"), tmp, "BC4_UNORM")
            for kind, fn in (("color", "c_in.dds"), ("normal", "n_in.dds"), ("rough", "r_in.dds")):
                dst = os.path.join(self.staging, *f"{tex_rel}_{kind}.dds".split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(tmp, fn), dst)
                out[kind] = cm.game_path(f"{tex_rel}_{kind}.dds")
        mat = cm.build_mat(self.template_mat, "FO4Port_Neutral", out["color"], out["normal"], out["rough"])
        mat_rel = f"materials/{self.prefix}/{stem}.mat"
        p = os.path.join(self.staging, *mat_rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8", newline="\n").write(cm.dump_mat(mat))
        return mat_rel.replace("/", "\\")

    def _publish_texture(self, src_path: str, dst: str, kind: str):
        """Copy a converted texture into the staging folder; with a cap for its kind, without the top mip levels that
        exceed it (the full size is logged either way while caps are on)."""
        cap = self.texture_caps.get(kind, 0)
        if not self.texture_caps:
            shutil.copy2(src_path, dst)
            return
        with open(src_path, "rb") as f:
            data = f.read()
        out, info = textures.cap_dds(data, cap)
        with open(dst, "wb") as f:
            f.write(out)
        rel = os.path.relpath(dst, self.staging).replace("\\", "/").lower()
        self.texture_log[rel] = {"kind": kind, "cap": cap, **info}

    # -- materials ---------------------------------------------------------------------------
    def material(self, bgsm_path: str) -> Optional[str]:
        """Convert a .bgsm (once) and return its Starfield material path, or None to use the placeholder."""
        m = re.search(r"materials[\\/].*", bgsm_path, re.I)      # some NIFs store the developer's absolute build path
        bgsm_path = m.group(0) if m else bgsm_path
        key = bgsm_path.replace("/", "\\").lower()
        if key not in self._materials:
            try:
                self._materials[key] = self._convert_material(bgsm_path)
                self.stats["materials_ok"] += 1
            except Exception as e:                        # noqa: BLE001  (fallback by design; reason is recorded)
                self._materials[key] = None
                self.stats["materials_fallback"] += 1
                self.material_errors[bgsm_path] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def _convert_material(self, bgsm_path: str) -> str:
        raw = self.src.material(bgsm_path)
        if raw is None:
            raise FileNotFoundError("bgsm not in archives")
        b = cm.parse_bgsm(raw)
        if not (b.diffuse and b.normal):
            raise ValueError("material lacks diffuse/normal textures")
        rel = re.sub(r"^materials[\\/]", "", bgsm_path.replace("\\", "/"), flags=re.I)
        return self._convert_texture_set(os.path.splitext(rel)[0].lower(), b.diffuse, b.normal, b.smooth_spec,
                                         smoothness=b.smoothness, spec_mult=b.spec_mult,
                                         alpha_test=b.alpha_test, alpha_ref=b.alpha_ref)

    def decal_material(self, bgsm_path: str) -> Optional[str]:
        """Alpha-blended FO4 material -> Starfield decal material (or None: the shape is skipped, as before decals)."""
        m = re.search(r"materials[\\/].*", bgsm_path, re.I)
        bgsm_path = m.group(0) if m else bgsm_path
        key = "decal:" + bgsm_path.replace("/", "\\").lower()
        if key not in self._materials:
            try:
                raw = self.src.material(bgsm_path)
                if raw is None:
                    raise FileNotFoundError("bgsm not in archives")
                b = cm.parse_bgsm(raw)
                if not (b.diffuse and b.normal):
                    raise ValueError("material lacks diffuse/normal textures")
                rel = re.sub(r"^materials[\\/]", "", bgsm_path.replace("\\", "/"), flags=re.I)
                self._materials[key] = self._convert_texture_set("decals/" + os.path.splitext(rel)[0].lower(), b.diffuse,
                                                                 b.normal, b.smooth_spec, smoothness=b.smoothness,
                                                                 spec_mult=b.spec_mult, decal=True)
                self.stats["materials_ok"] += 1
            except Exception as e:                        # noqa: BLE001
                self._materials[key] = None
                self.stats["materials_fallback"] += 1
                self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def effect_decal_material(self, base: str, normal: str) -> Optional[str]:
        """FO4 effect-shader grime (wall stains, oil puddles: alpha-blended overlays drawn with BSEffectShaderProperty) ->
        Starfield decal material from the effect's base texture (its alpha is the opacity). None if it cannot convert."""
        ident = "|".join(x.replace("\\", "/").lower() for x in (base, normal))
        stem = ("fxdecals/" + os.path.splitext(re.sub(r"^textures[\\/]", "", base.replace("\\", "/"), flags=re.I))[0].lower()
                + "_" + hashlib.sha1(ident.encode()).hexdigest()[:8])
        key = "fxdecal:" + stem
        if key not in self._materials:
            try:
                self._materials[key] = self._convert_texture_set(stem, base, normal, "", decal=True)
                self.stats["materials_ok"] += 1
            except Exception as e:                        # noqa: BLE001
                self._materials[key] = None
                self.stats["materials_fallback"] += 1
                self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def texture_set_material(self, diffuse: str, normal: str, spec: str) -> Optional[str]:
        """Material for a shape that names its textures directly (BSShaderTextureSet, no .bgsm). Cached by diffuse path."""
        stem = "texsets/" + re.sub(r"^textures[\\/]", "", diffuse.replace("\\", "/"), flags=re.I).lower()
        ident = "|".join(x.replace("\\", "/").lower() for x in (diffuse, normal, spec))      # every input is part of identity
        stem = os.path.splitext(stem)[0] + "_" + hashlib.sha1(ident.encode()).hexdigest()[:8]
        key = "texset:" + stem
        if key not in self._materials:
            try:
                self._materials[key] = self._convert_texture_set(stem, diffuse, normal, spec)
                self.stats["materials_ok"] += 1
            except Exception as e:                        # noqa: BLE001
                self._materials[key] = None
                self.stats["materials_fallback"] += 1
                self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def _convert_texture_set(self, stem: str, diffuse: str, normal: str, spec: str,
                             smoothness: float = 1.0, spec_mult: float = 1.0,
                             alpha_test: bool = False, alpha_ref: int = 128, decal: bool = False,
                             template: Optional[dict] = None, extra_files: Optional[dict] = None,
                             opaque_color: bool = False) -> str:
        """FO4 diffuse / normal / smooth-spec textures -> Starfield colour / normal / rough DDS + a .mat. Spec is optional.
        decal: alpha-blended overlay; the diffuse alpha always becomes the opacity map and the .mat is cloned from the
        vanilla decal template (cm.DECAL_TEMPLATE_MAT) so it blends over the surface behind it."""
        import numpy as np
        tex_rel = f"textures/{self.prefix}/{stem}"
        d, n = self.src.texture(diffuse), (self.src.texture(normal) if normal else None)
        s = self.src.texture(spec) if spec else None
        if d is None or (n is None and not decal and template is None):   # decals / ground may lack a normal: flat
            raise FileNotFoundError("diffuse or normal texture missing from archives")
        out = {}
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "d.dds"), "wb").write(d)
            opacity = None
            if alpha_test or decal:                        # cutout / blend: the diffuse alpha becomes a BC4 opacity map
                open(os.path.join(tmp, "a.dds"), "wb").write(d)
                textures.texconv(self.texconv, os.path.join(tmp, "a.dds"), tmp, "R8G8B8A8_UNORM", ("-m", "1"))
                raw_a = open(os.path.join(tmp, "a.dds"), "rb").read()
                ha = textures.read_dds_header(raw_a)
                px = np.frombuffer(raw_a[ha["data_offset"]:ha["data_offset"] + ha["width"] * ha["height"] * 4], np.uint8)
                alpha = px.reshape(ha["height"], ha["width"], 4)[:, :, 3].copy()
                if decal or alpha.min() < 250:            # only if the texture really has a cutout
                    textures.write_r8(os.path.join(tmp, "o_in.dds"), alpha)
                    textures.texconv(self.texconv, os.path.join(tmp, "o_in.dds"), tmp, "BC4_UNORM")
                    opacity = "o_in.dds"
            if opaque_color:                               # drop the source alpha (Skyrim ground: specular mask)
                textures.texconv(self.texconv, os.path.join(tmp, "d.dds"), tmp, "R8G8B8A8_UNORM", ("-m", "1"))
                raw_d = open(os.path.join(tmp, "d.dds"), "rb").read()
                hd = textures.read_dds_header(raw_d)
                pd = np.frombuffer(raw_d[hd["data_offset"]:hd["data_offset"] + hd["width"] * hd["height"] * 4],
                                   np.uint8).reshape(hd["height"], hd["width"], 4).copy()
                pd[:, :, 3] = 255
                textures.write_dds_dx10(os.path.join(tmp, "d.dds"), hd["width"], hd["height"],
                                        textures.DXGI_R8G8B8A8_UNORM, pd.tobytes(), 4)
            textures.texconv(self.texconv, os.path.join(tmp, "d.dds"), tmp, "BC1_UNORM_SRGB", ("-srgbi",))
            if n is not None:
                nr, ng = _plane_pair(n, tmp, self.texconv)
            else:                                          # flat: x = y = 0 in signed form
                nr = np.zeros((4, 4), dtype=np.int8)
                ng = np.zeros((4, 4), dtype=np.int8)
            textures.write_rg8_snorm(os.path.join(tmp, "n_in.dds"), nr, ng)
            textures.texconv(self.texconv, os.path.join(tmp, "n_in.dds"), tmp, "BC5_SNORM")
            if s is not None:
                _sr, sg = _plane_pair(s, tmp, self.texconv)
                rough = textures.roughness_from_smoothness(sg, smoothness, spec_mult)
            else:                                          # no spec map: uniformly fairly rough
                rough = np.full((max(4, nr.shape[0] // 4), max(4, nr.shape[1] // 4)), 190, dtype=np.uint8)
            textures.write_r8(os.path.join(tmp, "r_in.dds"), rough)
            textures.texconv(self.texconv, os.path.join(tmp, "r_in.dds"), tmp, "BC4_UNORM")
            kinds = [("color", "d.dds"), ("normal", "n_in.dds"), ("rough", "r_in.dds")] + ([("opacity", opacity)] if opacity else [])
            for kind, fn in kinds:
                dst = os.path.join(self.staging, *f"{tex_rel}_{kind}.dds".split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                self._publish_texture(os.path.join(tmp, fn), dst, kind)
                out[kind] = cm.game_path(f"{tex_rel}_{kind}.dds")
        if template is not None:                           # any single-layer vanilla material (terrain ground, ...)
            mat = cm.build_from_template(template, "FO4Port_" + re.sub(r"[^a-z0-9]+", "_", stem),
                                         dict({"Albedo": out["color"], "Normal": out["normal"], "Roughness": out["rough"]},
                                              **(extra_files or {})))
        elif decal:
            if self._decal_template is None:
                self._decal_template = cm.read_template_path(self.content_resources, cm.DECAL_TEMPLATE_MAT)
            mat = cm.build_from_template(self._decal_template, "FO4Port_" + re.sub(r"[^a-z0-9]+", "_", stem),
                                         {"Albedo": out["color"], "Normal": out["normal"], "Roughness": out["rough"],
                                          "Opacity": out["opacity"]})
        else:
            mat = cm.build_mat(self.template_mat, "FO4Port_" + re.sub(r"[^a-z0-9]+", "_", stem), out["color"], out["normal"],
                               out["rough"], opacity=out.get("opacity"), alpha_threshold=alpha_ref / 255.0)
        mat_rel = f"materials/{self.prefix}/{stem}.mat"
        p = os.path.join(self.staging, *mat_rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8", newline="\n").write(cm.dump_mat(mat))
        return mat_rel.replace("/", "\\")

    def glass_material(self, base: str, normal: str) -> Optional[str]:
        key = "glass:" + "|".join(x.replace("/", "\\").lower() for x in (base, normal))
        if key not in self._materials:
            try:
                self._materials[key] = self._convert_glass(base, normal)
                self.stats["materials_ok"] += 1
            except Exception as e:                        # noqa: BLE001
                self._materials[key] = None
                self.stats["materials_fallback"] += 1
                self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def _convert_glass(self, base: str, normal: str) -> str:
        import numpy as np
        d = self.src.texture(base) if base else None
        n = self.src.texture(normal) if normal else None
        if d is None:
            raise FileNotFoundError("glass base texture missing")
        rel = re.sub(r"^textures[\\/]", "", base.replace("\\", "/"), flags=re.I)
        stem = ("glass/" + os.path.splitext(rel)[0].lower() + "_"
                + hashlib.sha1((base + "|" + normal).lower().encode()).hexdigest()[:8])
        tex_rel = f"textures/{self.prefix}/{stem}"
        out = {}
        with tempfile.TemporaryDirectory() as tmp:
            if d is not None:
                open(os.path.join(tmp, "d.dds"), "wb").write(d)
                textures.texconv(self.texconv, os.path.join(tmp, "d.dds"), tmp, "BC1_UNORM_SRGB", ("-srgbi",))
                out["Albedo"] = "d.dds"
            if n is not None:
                nr, ng = _plane_pair(n, tmp, self.texconv)
                textures.write_rg8_snorm(os.path.join(tmp, "n_in.dds"), nr, ng)
                textures.texconv(self.texconv, os.path.join(tmp, "n_in.dds"), tmp, "BC5_SNORM")
                out["Normal"] = "n_in.dds"
            textures.write_r8(os.path.join(tmp, "r_in.dds"), np.full((16, 16), 25, np.uint8))   # glass: very smooth
            textures.texconv(self.texconv, os.path.join(tmp, "r_in.dds"), tmp, "BC4_UNORM")
            out["Roughness"] = "r_in.dds"
            files = {}
            for slot, fn in out.items():
                kind = {"Albedo": "color", "Normal": "normal", "Roughness": "rough"}[slot]
                dst = os.path.join(self.staging, *f"{tex_rel}_{kind}.dds".split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                self._publish_texture(os.path.join(tmp, fn), dst, kind)
                files[slot] = cm.game_path(f"{tex_rel}_{kind}.dds")
        if self._glass_template is None:
            self._glass_template = cm.read_template_path(self.content_resources, cm.GLASS_TEMPLATE_MAT)
        mat = cm.build_from_template(self._glass_template, "FO4Port_" + re.sub(r"[^a-z0-9]+", "_", stem), files,
                                     opacity_value=0.15)
        mat_rel = f"materials/{self.prefix}/{stem}.mat"
        p = os.path.join(self.staging, *mat_rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8", newline="\n").write(cm.dump_mat(mat))
        return mat_rel.replace("/", "\\")

    def _is_blended(self, bgsm_path: str) -> bool:
        m = re.search(r"materials[\\/].*", bgsm_path, re.I)
        key = (m.group(0) if m else bgsm_path).replace("/", "\\").lower()
        if key not in self._blend_cache:
            raw = self.src.material(key)
            try:
                self._blend_cache[key] = bool(raw) and cm.parse_bgsm(raw).alpha_blend
            except Exception:                         # noqa: BLE001
                self._blend_cache[key] = False
        return self._blend_cache[key]

    # -- meshes -------------------------------------------------------------------------------
    def _shape_material(self, src, s) -> Optional[str]:
        """Starfield material path for one FO4 shape; None = skip the shape (effect shaders: glass, glow, frost)."""
        if s.shader_ref < 0:
            return self.neutral
        kind = src.type_of(s.shader_ref)
        if kind == "BSEffectShaderProperty":
            idx, = struct.unpack_from("<i", src.blocks[s.shader_ref], 4)
            name = src.strings[idx].decode("latin-1") if 0 <= idx < len(src.strings) else ""
            if name.lower().endswith(".bgem"):
                raw = self.src.material(name) or b""
                try:
                    base, normal = cm.parse_bgem_textures(raw)
                except ValueError:
                    base, normal = "", ""
                cubemap = b"cubemap" in raw.lower()
            else:                                       # textures stored inline in the effect block
                dds = [x.decode("latin-1") for x in re.findall(rb"[\w\\/ .-]+\.dds", src.blocks[s.shader_ref])]
                base = dds[0] if dds else ""
                normal = next((x for x in dds if x.lower().endswith("_n.dds")), "")
                cubemap = any("cubemap" in x.lower() for x in dds)
            # glass: named glass/window, or an environment-mapped effect with its own normal map (beakers, test tubes,
            # bottles: FO4's usual glass setup); never textures from the effects folder (glow, smoke, dust)
            glassy = re.search(r"glass|window", base, re.I) or (cubemap and normal)
            if glassy and not re.search(r"[\\/]effects[\\/]", base, re.I):
                return self.glass_material(base, normal)   # windows, cryo-pod glass: vanilla glass shader model
            if base and re.search(r"stain|streak|grime|leak|blood|decal", base, re.I) \
                    and not re.search(r"[\\/]effects[\\/]", base, re.I):
                return self.effect_decal_material(base, normal)   # alpha-blended grime: decal; None = skip as before
            return None                                 # other effects (glow, frost, dust, smoke, signs): skipped
        if kind != "BSLightingShaderProperty":
            return self.neutral
        blk = src.blocks[s.shader_ref]
        idx, = struct.unpack_from("<i", blk, 4)
        name = src.strings[idx] if 0 <= idx < len(src.strings) else b""
        if name.lower().endswith(b".bgsm"):
            if self._is_blended(name.decode("latin-1")):
                return self.decal_material(name.decode("latin-1"))   # overlay shells (cracks, grime): decal; None = skip
            return self.material(name.decode("latin-1")) or self.neutral
        # no material file: shader type, name, extra data list, controller, flags1, flags2, UV offset, UV scale, texture set
        n_extra, = struct.unpack_from("<I", blk, 8)
        ts_ref, = struct.unpack_from("<i", blk, 12 + 4 * n_extra + 4 + 8 + 16)
        if not (0 <= ts_ref < len(src.blocks)) or src.type_of(ts_ref) != "BSShaderTextureSet":
            return self.neutral
        tb = src.blocks[ts_ref]
        count, = struct.unpack_from("<I", tb, 0)
        paths, p = [], 4
        for _ in range(count):
            ln, = struct.unpack_from("<I", tb, p)
            paths.append(tb[p + 4:p + 4 + ln].decode("latin-1"))
            p += 4 + ln
        diffuse = paths[0] if paths else ""
        normal = paths[1] if len(paths) > 1 else ""
        spec = paths[7] if len(paths) > 7 else ""
        if not (diffuse and normal):
            return self.neutral
        return self.texture_set_material(diffuse, normal, spec) or self.neutral

    def convert_nif(self, nif_name: str) -> dict:
        res = {"nif": nif_name, "ok": False}
        try:
            raw = self.src.mesh(nif_name)
            src = nif.parse(raw)
            # skinned props (lockers, cabinets, desks: skinned only so drawers/doors can animate) are taken in bind pose
            shapes = [s for s in nif.fo4_trishapes(src) if s.positions and s.triangles]
            if not shapes:
                raise ValueError("no static BSTriShape geometry")
            mats: List[Optional[str]] = []
            for s in shapes:
                mats.append(self._shape_material(src, s))
            if all(m is None for m in mats):
                raise ValueError("only effect-shader shapes (glass/glow), skipped")
            rel = re.sub(r"^meshes[\\/]", "", nif_name.replace("\\", "/"), flags=re.I)
            out_name = f"{self.prefix}/{os.path.splitext(rel)[0].lower()}"
            arch = bool(self.no_collision and self.no_collision.search(nif_name))
            mode = "surfaces" if arch else "box"        # architecture: thin boxes behind flat surfaces; props: one AABB
            # Vegetation, mounds and door-named models (wall plugs around doorways, vault hall pieces, signs) keep FO4's
            # own collision but never get a guessed box: a box around a tree or a doorway is an invisible wall. (These
            # used to get no collision at all, so walls beside doors and grass mounds could be walked through.)
            no_guess = bool(re.search(r"[\\/]landscape[\\/](trees|plants|grass)|roots|cobweb|vines|hanging"
                                      r"|[\\/]doors?[\\/]|door[^\\/]*\.nif$", nif_name, re.I))
            load_door = bool(LOAD_DOOR_RE.search(nif_name))
            if load_door:
                res["load_door"] = "teleport not ported: door stays shut"
            # A door leaf that animates in FO4 ("Open" sequence) but is not rigged here (sliding / vault / elevator doors,
            # or rigging failed) cannot open: keep it passable rather than a closed wall, and say so.
            seq_names = [struct.unpack_from("<i", src.blocks[i], 0)[0] for i in range(len(src.blocks))
                         if src.type_of(i) == "NiControllerSequence"]
            animated = any(0 <= s < len(src.strings) and src.strings[s] == b"Open" for s in seq_names)
            use_box = self.collision_template is not None
            coll_report = {}
            files = None
            if self.rig_doors and self.door_physics_donor is not None and DOOR_RE.search(nif_name) and not NOT_HINGED_RE.search(nif_name) and not load_door and nif.door_hinge(src):
                try:                                     # hinged door: rigged like the vanilla template door so it opens
                    files, offset, bounds = convert_static.convert_door(raw, out_name, mats,
                                                                collision_template=self.collision_template,
                                                                leaf_physics_donor=self.door_physics_donor)
                    t = sfnif.DOOR_TEMPLATE
                    res["door"] = {"origin_offset": [round(x, 5) for x in offset], "anim_graph": t["anim_graph"],
                                   "bounds": [[round(x, 4) for x in b] for b in bounds],
                                   "skeleton": t["skeleton"], "animations": t["animations"]}
                except Exception as e:                   # noqa: BLE001  (falls back to a static door)
                    res["door_error"] = f"{type(e).__name__}: {e}"
            if files is None:
                if animated and not load_door and DOOR_RE.search(nif_name):
                    use_box = False
                    res["door_not_opening"] = "open animation not ported: passable"
                files = convert_static.convert_static(raw, out_name, material_paths=mats, collision_mode=mode,
                                                      include_skinned=True, report=coll_report,
                                                      sf_mesh_template=self.sf_mesh_template if use_box else None,
                                                      collision_template=self.collision_template if use_box else None,
                                                      allow_guess=not no_guess)
                if "door_not_opening" in res:
                    coll_report["source"] = "passable-door"   # deliberately none (see above), not a failed conversion
            for relp, data in files.items():
                p = os.path.join(self.staging, *relp.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "wb").write(data)
            res.update(ok=True, out_name=out_name, shapes=len(shapes), materials=mats, collision=mode if use_box else None, collision_report=coll_report,
                       skipped_effect_shapes=sum(1 for m in mats if m is None),
                       fallback_materials=sum(1 for m in mats if m == self.neutral))
            self.stats["assets"] += 1
        except Exception as e:                           # noqa: BLE001  (recorded per asset, batch continues)
            res["reason"] = f"{type(e).__name__}: {e}"
            self.stats["failed"] += 1
        return res
