"""Skyrim editor-only geometry left out of converted models (2026-11-16, owner: untextured grey shapes at Riverwood's
forge and anvil: the helper geometry of Skyrim's furniture marker models, which Skyrim does not draw in game)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import nif as nifmod, skyrimconvert, skyrimnif  # noqa: E402


class FakeNif:
    """blocks: (type, name); node children given separately."""

    def __init__(self, blocks, children):
        self.strings = [nm for _t, nm in blocks]
        self.blocks = [struct.pack("<iI", i, 0) + bytes(80) for i in range(len(blocks))]
        self.types = [t for t, _nm in blocks]
        self.children = children

    def type_of(self, i):
        return self.types[i]


class EditorMarkerTest(unittest.TestCase):
    def test_blocks_under_or_named_editormarker(self):
        n = FakeNif([("NiNode", b"Scene Root"), ("NiNode", b"EditorMarker"), ("BSTriShape", b"Arrow"),
                     ("BSTriShape", b"Anvil:0"), ("BSTriShape", b"EditorMarkerCone")],
                    {0: [1, 3, 4], 1: [2]})
        orig = nifmod.node_children
        nifmod.node_children = lambda nn, i: nn.children.get(i, [])
        try:
            got = skyrimnif.editor_marker_blocks(n)
        finally:
            nifmod.node_children = orig
        self.assertEqual(got, {1, 2, 4})

    def test_marker_models_by_file_name(self):
        rx = skyrimnif.MARKER_MODEL_RE
        for m in ("meshes\\furniture\\BlacksmithForgeMarker.nif", "Furniture\\SmelterMarker.nif",
                  "furniture\\hammertablemarker.nif"):
            self.assertTrue(rx.search(m), m)
        for m in ("Furniture\\Clutter\\BlacksmithAnvil.nif", "meshes\\markers\\chair.nif",
                  "furniture\\BlacksmithSharpeningWheelAnimating.nif"):
            self.assertFalse(rx.search(m), m)

    def test_marker_models_keep_their_textured_geometry(self):
        """11:36, owner: with the whole *Marker.nif dropped the forge pit and anvil went too: only untextured shapes
        (and EditorMarker ones) are editor-only."""
        from types import SimpleNamespace as S
        n = FakeNif([("BSTriShape", b"Forge"), ("BSLightingShaderProperty", b""), ("BSTriShape", b"Blade"),
                     ("BSLightingShaderProperty", b""), ("BSEffectShaderProperty", b"")], {})
        tex = {1: ["textures\\forge.dds", "n.dds"], 3: ["", ""]}
        orig = skyrimnif.texture_set
        skyrimnif.texture_set = lambda nn, ref: tex.get(ref)
        try:
            forge, blade = S(block=0, shader_ref=1), S(block=2, shader_ref=3)
            self.assertIsNone(skyrimnif.editor_only(n, forge, True, set()))
            self.assertEqual(skyrimnif.editor_only(n, blade, True, set()), "untextured")
            self.assertEqual(skyrimnif.editor_only(n, S(block=5, shader_ref=-1), True, set()), "untextured")
            self.assertIsNone(skyrimnif.editor_only(n, S(block=6, shader_ref=4), True, set()))      # flames
            self.assertIsNone(skyrimnif.editor_only(n, blade, False, set()))                     # not a marker model
            self.assertEqual(skyrimnif.editor_only(n, forge, False, {0}), "EditorMarker")
        finally:
            skyrimnif.texture_set = orig

    def test_an_editor_marker_model_converts_to_an_empty_model(self):
        report = {}
        files = skyrimconvert.convert_static_sse(None, [], "skyrim/furniture/blacksmithforgemarker", [], None, report,
                                                 allow_empty=True)
        nif = nifmod.parse(files["meshes/skyrim/furniture/blacksmithforgemarker.nif"])
        self.assertFalse(any(nif.type_of(i) == "BSGeometry" for i in range(len(nif.blocks))))
        self.assertIsNone(report["render_bounds_m"])
        with self.assertRaises(nifmod.NifError):
            skyrimconvert.convert_static_sse(None, [], "x/y", [], None, {})


if __name__ == "__main__":
    unittest.main()
