"""The flame part of SkyrimConverter (a mixin it inherits): Skyrim's hearth / candle flames as Starfield effect
materials and cards (skyrimfire holds the data and rules; this the conversion steps that write files).

Its own module since 2026-11-21 (owner: "does it need to do all of this every time we test"): make_skyrim_objects'
checkpoint signature hashes the converter's modules, so the candle code living in skyrimconvert.py reconverted all 250
Riverwood models for a candle change (145 s build, "reused": 0). This module is in make_skyrim_objects.FLAME_MODULES:
a change here reconverts the flame models only (their per-model flame_key), like a change to skyrimfire.
"""
import hashlib
import os
import re
from typing import Optional

from . import nif as nifmod, skyrimfire, skyrimnif

UNIT = 1.0 / 70.0          # metres per Skyrim unit (as skyrimconvert.UNIT; not imported: skyrimconvert imports this module)


class FlameMixin:
    # -- flames (skyrimfire) ---------------------------------------------------------------------
    def skyrim_flame_material(self, src, shader_ref) -> Optional[str]:
        """Effect material for a Skyrim flame shape (BSEffectShaderProperty with a fire texture), None otherwise."""
        try:
            info = skyrimfire.effect_shader(src, shader_ref)
        except Exception:                                           # noqa: BLE001
            return None
        if not skyrimfire.is_fire_effect(info, self.fire_pattern):
            return None
        if getattr(self, "flame_style", "skyrim") == "particles" and \
                re.search(skyrimfire.PARTICLE_REPLACES, info["source"], re.I):
            return None                               # Starfield's particle fire burns here instead
        if getattr(self, "flame_style", "skyrim") == "layered" and \
                re.search(skyrimfire.PARTICLE_REPLACES, info["source"], re.I):
            return self.layered_fire_material()       # Skyrim's flame mesh, Starfield's geometry fire material
        bake = skyrimfire.bake_params(info)
        return self.flame_material(info["source"], **bake,
                                   scroll=skyrimfire.uv_scroll(info["controllers"]), kind="hearth",
                                   vertex_color=info["vertex_alpha"])

    def flame_material(self, source: str, greyscale: str = "", palette_color: bool = False,
                       palette_alpha: bool = False, color_row: float = 1.0, alpha_row: float = 1.0,
                       tint=(1.0, 1.0, 1.0), scroll=None, kind: str = "hearth", flicker: Optional[float] = None,
                       vertex_color: bool = False, flipbook=None, multiple: float = 1.0,
                       crossfade=None) -> Optional[str]:
        """Convert (once) a Skyrim effect texture into a Starfield emissive effect material: palette baked in
        (skyrimfire.palette_bake), colour + emissive BC1 sRGB, opacity BC4; skyrimfire.effect_material with the
        scroll / flicker / flipbook controllers."""
        tint = tuple(float(t) for t in tint)
        ident = "|".join(str(x) for x in (source.lower(), greyscale.lower(), palette_color, palette_alpha,
                                          round(color_row, 3), round(alpha_row, 3), [round(v, 3) for v in tint],
                                          scroll, kind, flicker, vertex_color, flipbook, round(multiple, 3),
                                          crossfade))
        stem = os.path.splitext(os.path.basename(source.replace("\\", "/")))[0].lower() + "_" + \
            hashlib.sha1(ident.encode()).hexdigest()[:8]
        key = "fire:" + stem
        if key in self._materials:
            return self._materials[key]
        try:
            self._materials[key] = self._write_flame_material(stem, source, greyscale, palette_color, palette_alpha,
                                                              color_row, alpha_row, tint, scroll, kind, flicker,
                                                              vertex_color, flipbook, multiple, crossfade)
            self.stats["flame_materials"] = self.stats.get("flame_materials", 0) + 1
        except Exception as e:                                      # noqa: BLE001  (recorded; the shape is skipped)
            self._materials[key] = None
            self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def _rgba(self, data: bytes, tmp: str, tag: str):
        import numpy as np
        from . import textures
        p = os.path.join(tmp, f"{tag}.dds")
        with open(p, "wb") as f:
            f.write(data)
        textures.texconv(self.texconv, p, tmp, "R8G8B8A8_UNORM", ("-m", "1"))
        raw = open(p, "rb").read()
        h = textures.read_dds_header(raw)
        px = np.frombuffer(raw[h["data_offset"]:h["data_offset"] + h["width"] * h["height"] * 4], np.uint8)
        return px.reshape(h["height"], h["width"], 4)

    def _write_flame_material(self, stem, source, greyscale, palette_color, palette_alpha, color_row, alpha_row,
                              tint, scroll, kind, flicker, vertex_color, flipbook, multiple=1.0, crossfade=None) -> str:
        import tempfile
        import numpy as np
        from . import convert_material as cm, textures
        src = self.src.texture(source)
        if src is None:
            raise FileNotFoundError(f"{source} not in the Skyrim archives")
        pal = self.src.texture(greyscale) if greyscale and (palette_color or palette_alpha) else None
        tex_rel = f"textures/{self.prefix}/effects/{stem}"
        files = {}
        with tempfile.TemporaryDirectory() as tmp:
            rgba = self._rgba(src, tmp, "src")
            if pal is not None:
                rgba = skyrimfire.palette_bake(rgba, self._rgba(pal, tmp, "pal"), palette_color, palette_alpha,
                                               row=color_row, alpha_row=alpha_row, tint=tint)
            else:
                rgba = skyrimfire.palette_bake(rgba, rgba[:1], False, False, tint=tint)
            h, w = rgba.shape[:2]
            colour = np.ascontiguousarray(np.concatenate([rgba[:, :, :3], np.full((h, w, 1), 255, np.uint8)], 2))
            textures.write_dds_dx10(os.path.join(tmp, "c_in.dds"), w, h, textures.DXGI_R8G8B8A8_UNORM,
                                    colour.tobytes(), 4)
            # BC7: soft flame gradients went blocky in BC1 (owner, flames v2)
            textures.texconv(self.texconv, os.path.join(tmp, "c_in.dds"), tmp, "BC7_UNORM_SRGB")
            textures.write_r8(os.path.join(tmp, "o_in.dds"), np.ascontiguousarray(rgba[:, :, 3]))
            textures.texconv(self.texconv, os.path.join(tmp, "o_in.dds"), tmp, "BC4_UNORM")
            for kind_, fn in (("color", "c_in.dds"), ("opacity", "o_in.dds")):
                dst = os.path.join(self.staging, *f"{tex_rel}_{kind_}.dds".split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                self._publish_texture(os.path.join(tmp, fn), dst, kind_)
                files[kind_] = cm.game_path(f"{tex_rel}_{kind_}.dds")
        if self._effect_template is None:
            self._effect_template = cm.read_template_path(self.content_resources, skyrimfire.EFFECT_TEMPLATE_MAT)
        mat = skyrimfire.effect_material(self._effect_template, "S2S_Flame_" + re.sub(r"[^a-z0-9]+", "_", stem),
                                         {"Albedo": files["color"], "Emissive": files["color"],
                                          "Opacity": files["opacity"]},
                                         kind=kind, scroll=scroll, flicker=flicker, vertex_color=vertex_color,
                                         flipbook=flipbook, multiple=multiple, crossfade=crossfade)
        mat_rel = f"materials/{self.prefix}/effects/{stem}.mat"
        p = os.path.join(self.staging, *mat_rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(skyrimfire.dumps(mat))
        return mat_rel.replace("/", "\\")

    def particle_flame_cards(self, flames, offset=(0.0, 0.0, 0.0), kind="candle", tag="Flame") -> tuple:
        """(shapes, materials): crossed cards for particle flames (skyrimfire.particle_flame results), moved by
        `offset` (an AddOnNode's position). An atlas with several frames plays as a flipbook on two layers per spot
        (skyrimfire.LAYER2: turned, smaller, higher, mirrored, its own frame rate) that cross-fade."""
        shapes, mats = [], []
        L2 = skyrimfire.LAYER2
        for f in flames:
            if kind == "candle" and getattr(self, "candle_style", "skyrim") == "soft":
                mat = self.soft_candle_material(max(0.6, 3 * f["life"]))
                if mat is None:
                    continue
                cw, ch = skyrimfire.SOFT_CARD
                for c in skyrimfire.flame_card_centres(f):
                    # same centre as Skyrim's card: the flame is drawn centred in the larger card at Skyrim's size
                    # (x SOFT_FLAME_SCALE), so its foot and tip land where Skyrim's card had them
                    centre = (c[0] + offset[0], c[1] + offset[1], c[2] + offset[2])
                    shapes.append(skyrimfire.crossed_cards(centre, f["half_w"] * cw, f["half_h"] * ch,
                                                           name=f"{tag}_{len(shapes)}".encode()))
                    mats.append(mat)
                continue
            if kind == "candle" and getattr(self, "candle_style", "skyrim") == "starfield":
                mat = self.starfield_flame_material("candle", keep_emittance=True)   # Starfield's candle, as it is
                if mat is None:
                    continue
                sf_mesh = getattr(self, "sf_candle_mesh", None)
                for c in skyrimfire.flame_card_centres(f):
                    centre = (c[0] + offset[0], c[1] + offset[1], c[2] + offset[2])
                    w = f["half_w"] * skyrimfire.SF_CANDLE_WIDTH
                    h = f["half_h"] * skyrimfire.SF_CANDLE_HEIGHT
                    nm = f"{tag}_{len(shapes)}".encode()
                    shapes.append(skyrimfire.sf_flame_shape(sf_mesh, centre, w, h, nm) if sf_mesh is not None
                                  else skyrimfire.crossed_cards(centre, w, h, name=nm))
                    mats.append(mat)
                continue
            if kind == "hearth" and getattr(self, "flame_style", "skyrim") == "layered":
                mat = self.layered_fire_material()
                if mat is None:
                    continue
                for c in skyrimfire.flame_card_centres(f):
                    centre = (c[0] + offset[0], c[1] + offset[1], c[2] + offset[2])
                    shapes.append(skyrimfire.crossed_cards(centre, f["half_w"], f["half_h"],
                                                           name=f"{tag}_{len(shapes)}".encode()))
                    mats.append(mat)
                continue
            if getattr(self, "flame_style", "skyrim") == "starfield":   # Starfield's flipbook, one layer (it has frames enough)
                mat = self.starfield_flame_material(kind)
                if mat is None:
                    continue
                for c in skyrimfire.flame_card_centres(f):
                    centre = (c[0] + offset[0], c[1] + offset[1], c[2] + offset[2])
                    shapes.append(skyrimfire.crossed_cards(centre, f["half_w"], f["half_h"],
                                                           name=f"{tag}_{len(shapes)}".encode()))
                    mats.append(mat)
                continue
            cols, rows = f["grid"]
            frames = cols * rows
            fps = skyrimfire.FLIPBOOK_FPS[kind]
            period = max(0.6, 3 * f["life"])
            layers = [(None, 1.0, 0.0, 0.0, False, 0)]
            if frames > 1:
                layers = [((cols, rows, fps), 1.0, 0.0, 0.0, False, 0),
                          ((cols, rows, round(fps * L2["fps"], 2)), L2["size"], L2["lift"], L2["turn_deg"], True, 1)]
            for fb, size, lift, turn, mirror, phase in layers:
                mat = self.flame_material(f["texture"], f["greyscale"], f["palette_color"], f["palette_alpha"],
                                          f["color_row"], f["alpha_row"], tint=f["color"], kind=kind,
                                          flicker=period, flipbook=fb, multiple=f.get("multiple", 1.0),
                                          crossfade=(period, phase) if frames > 1 else None)
                if mat is None:
                    continue
                for c in skyrimfire.flame_card_centres(f):
                    centre = (c[0] + offset[0], c[1] + offset[1], c[2] + offset[2] + lift * f["half_h"])
                    shapes.append(skyrimfire.crossed_cards(centre, f["half_w"] * size, f["half_h"] * size,
                                                           name=f"{tag}_{len(shapes)}".encode(), turn_deg=turn,
                                                           mirror=mirror))
                    mats.append(mat)
        return shapes, mats

    def soft_candle_material(self, flicker_period: float) -> Optional[str]:
        """candle_style "soft": our own flame flipbook (skyrimfire.procedural_flame_atlas, drawn here, colour BC7 sRGB +
        opacity BC4) on the effect template, played at SOFT_FPS with a flicker; written once per flicker period."""
        key = f"softcandle:{flicker_period:.3f}"
        if key in self._materials:
            return self._materials[key]
        try:
            import tempfile
            import numpy as np
            from . import convert_material as cm, textures
            stem = "s2s_candleflame_soft"
            tex_rel = f"textures/{self.prefix}/effects/{stem}"
            files = {}
            if "softcandle_tex" not in self._materials:
                rgba = skyrimfire.procedural_flame_atlas()
                h, w = rgba.shape[:2]
                with tempfile.TemporaryDirectory() as tmp:
                    colour = np.ascontiguousarray(np.concatenate([rgba[:, :, :3], np.full((h, w, 1), 255, np.uint8)], 2))
                    textures.write_dds_dx10(os.path.join(tmp, "c_in.dds"), w, h, textures.DXGI_R8G8B8A8_UNORM,
                                            colour.tobytes(), 4)
                    textures.texconv(self.texconv, os.path.join(tmp, "c_in.dds"), tmp, "BC7_UNORM_SRGB")
                    textures.write_r8(os.path.join(tmp, "o_in.dds"), np.ascontiguousarray(rgba[:, :, 3]))
                    textures.texconv(self.texconv, os.path.join(tmp, "o_in.dds"), tmp, "BC4_UNORM")
                    for kind_, fn in (("color", "c_in.dds"), ("opacity", "o_in.dds")):
                        dst = os.path.join(self.staging, *f"{tex_rel}_{kind_}.dds".split("/"))
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        self._publish_texture(os.path.join(tmp, fn), dst, kind_)
                self._materials["softcandle_tex"] = "done"
            for kind_ in ("color", "opacity"):
                files[kind_] = cm.game_path(f"{tex_rel}_{kind_}.dds")
            if self._effect_template is None:
                self._effect_template = cm.read_template_path(self.content_resources, skyrimfire.EFFECT_TEMPLATE_MAT)
            cols, rows = skyrimfire.SOFT_GRID
            name = f"{stem}_{int(round(flicker_period * 1000))}"
            mat = skyrimfire.effect_material(self._effect_template, "S2S_Flame_" + name,
                                             {"Albedo": files["color"], "Emissive": files["color"],
                                              "Opacity": files["opacity"]},
                                             kind="candle", flicker=flicker_period,
                                             flipbook=(cols, rows, skyrimfire.SOFT_FPS))
            mat_rel = f"materials/{self.prefix}/effects/{name}.mat"
            p = os.path.join(self.staging, *mat_rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(skyrimfire.dumps(mat))
            self._materials[key] = mat_rel.replace("/", "\\")
            self.stats["flame_materials"] = self.stats.get("flame_materials", 0) + 1
        except Exception as e:                                      # noqa: BLE001  (recorded; the candle gets no flame)
            self._materials[key] = None
            self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def layered_fire_material(self) -> Optional[str]:
        """flame_style "layered": a clone of skyrimfire.LAYERED_FIRE_MAT as it is (its textures, controllers) but with
        skyrimfire.LAYERED_EMITTANCE, written once; what it is goes to stats["layered_fire"]. If it cannot be read, the vanilla path itself
        (the game resolves it from its own material database) and the reason in material_errors."""
        key = "layeredfire"
        if key in self._materials:
            return self._materials[key]
        from . import convert_material as cm
        path = skyrimfire.LAYERED_FIRE_MAT
        try:
            template = cm.read_template_path(self.content_resources, path)
            stem = "sf_" + os.path.splitext(os.path.basename(path))[0].lower()
            mat = cm.build_from_template(template, "S2S_Flame_" + stem, {})
            changed = skyrimfire.set_emittance(mat, skyrimfire.LAYERED_EMITTANCE)
            mat_rel = f"materials/{self.prefix}/effects/{stem}.mat"
            p = os.path.join(self.staging, *mat_rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(skyrimfire.dumps(mat))
            self.stats["layered_fire"] = dict(skyrimfire.material_summary(template), template=path,
                                              emittance_set=changed)
            self._materials[key] = mat_rel.replace("/", "\\")
        except Exception as e:                                      # noqa: BLE001
            self.material_errors[key] = f"{type(e).__name__}: {e}"
            self._materials[key] = path.replace("/", "\\")
        if not hasattr(self, "_layered"):
            self._layered = set()
        self._layered.add(self._materials[key])
        return self._materials[key]

    def starfield_flame_material(self, kind: str, keep_emittance: bool = False) -> Optional[str]:
        """flame_style "starfield" / candle_style "starfield": a clone of Starfield's own fire material for `kind`
        (skyrimfire.STARFIELD_FLAMES: its textures and flipbook, played on a timer; our emittance and a flicker, or
        with keep_emittance its own emittance and no flicker), written once."""
        from . import convert_material as cm
        key = "sffire:" + kind + (":own" if keep_emittance else "")
        if key in self._materials:
            return self._materials[key]
        try:
            path, flipbook = skyrimfire.STARFIELD_FLAMES[kind]
            template = cm.read_template_path(self.content_resources, path)
            stem = "sf_" + os.path.splitext(os.path.basename(path))[0].lower() + ("_own" if keep_emittance else "")
            mat = skyrimfire.effect_material(template, "S2S_Flame_" + stem, {}, kind=kind, flipbook=flipbook,
                                             flicker=None if keep_emittance else 1.0, keep_emittance=keep_emittance)
            mat_rel = f"materials/{self.prefix}/effects/{stem}.mat"
            p = os.path.join(self.staging, *mat_rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(skyrimfire.dumps(mat))
            self._materials[key] = mat_rel.replace("/", "\\")
        except Exception as e:                                      # noqa: BLE001
            self._materials[key] = None
            self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def addon_flames(self, src) -> tuple:
        """(shapes, materials) of flame cards at the model's AddOnNodes whose add-on is a flame particle system
        (Skyrim's candles: AddOnNode49 -> MPSCandleFlame01)."""
        shapes, mats = [], []
        for idx, pos in skyrimfire.addon_nodes(src):
            model = self.addon_models.get(idx)
            if not model:
                continue
            if idx not in self._addon_flames:
                flames = []
                raw = self.src.mesh(model)
                if raw is not None:
                    try:
                        flames = [f for f in (skyrimfire.particle_flame(ps)
                                              for ps in skyrimfire.particle_systems(nifmod.parse(raw))) if f]
                    except Exception as e:                          # noqa: BLE001
                        self.material_errors["addon:" + model] = f"{type(e).__name__}: {e}"
                self._addon_flames[idx] = flames
            sh, ma = self.particle_flame_cards(self._addon_flames[idx], pos, "candle",
                                               f"AddOnFlame{idx}_{len(shapes)}")
            shapes += sh
            mats += ma
        return shapes, mats

    def model_flames(self, src) -> tuple:
        """(shapes, materials): the model's own flame particle systems as cards (FireplaceWood01Burning's
        FlamesSmall01: most of what a Skyrim hearth shows). Smoke and halos stay out (skyrimfire.particle_flame).
        flame_style "particles": no cards; see model_fire_effects."""
        if getattr(self, "flame_style", "skyrim") == "particles":
            return [], []
        try:
            flames = [f for f in (skyrimfire.particle_flame(ps) for ps in skyrimfire.particle_systems(src)) if f]
        except Exception:                                           # noqa: BLE001
            return [], []
        return self.particle_flame_cards(flames, kind="hearth", tag="ParticleFlame")

    def model_fire_effects(self, src) -> list:
        """flame_style "particles": [{"base", "scale", "offset_m"}] Starfield particle fires (skyrimfire.
        PARTICLE_FIRE_BASE) for a model with flame particles: spread along its fire shapes (skyrimfire.fire_spots: the
        flame meshes and log glow), at the emitter's height; in metres, model space (PluginSpike places them with each
        reference). A model without fire shapes gets one fire at each emitter."""
        if getattr(self, "flame_style", "skyrim") != "particles":
            return []
        try:
            flames = [f for f in (skyrimfire.particle_flame(ps) for ps in skyrimfire.particle_systems(src)) if f]
        except Exception:                                           # noqa: BLE001
            return []
        if not flames:
            return []
        choices = getattr(self, "particle_fire", None) or [(skyrimfire.PARTICLE_FIRE_BASE,
                                                             skyrimfire.PARTICLE_FIRE_SCALE)]
        if isinstance(choices, tuple):                 # one (base, scale)
            choices = [choices]
        spots = skyrimfire.fire_spots(self._fire_shape_points(src), origin_z=min(f["origin"][2] for f in flames))
        if not spots:
            spots = [tuple(f["origin"]) for f in flames]
        k = skyrimfire.SPREAD_SCALE if len(spots) > 1 else 1.0
        out = []
        for p in spots:
            e = {"base": choices[0][0], "scale": round(choices[0][1] * k, 3),
                 "offset_m": [round(c * UNIT, 4) for c in p]}
            if len(choices) > 1:                       # A/B: the plugin rotates through these
                e["choices"] = [{"base": b, "scale": round(sc * k, 3)} for b, sc in choices]
            out.append(e)
        return out

    def _fire_shape_points(self, src) -> list:
        """Model-space vertices (Skyrim units) of the model's fire effect shapes (skyrimfire.is_fire_effect)."""
        pts = []
        try:
            shapes = skyrimnif.trishapes(src)
        except Exception:                                           # noqa: BLE001
            return pts
        for sh in shapes:
            if not (0 <= sh.shader_ref < len(src.blocks)) or src.type_of(sh.shader_ref) != "BSEffectShaderProperty":
                continue
            try:
                if not skyrimfire.is_fire_effect(skyrimfire.effect_shader(src, sh.shader_ref), self.fire_pattern):
                    continue
            except Exception:                                       # noqa: BLE001
                continue
            r, t, sc = sh.rotation, sh.translation, sh.scale
            for x, y, z in sh.positions:
                pts.append((sc * (r[0] * x + r[1] * y + r[2] * z) + t[0], sc * (r[3] * x + r[4] * y + r[5] * z) + t[1],
                            sc * (r[6] * x + r[7] * y + r[8] * z) + t[2]))
        return pts

