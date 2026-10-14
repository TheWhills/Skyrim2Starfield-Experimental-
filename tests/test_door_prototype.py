import unittest
from test_door_motion import fixture
from fo4sf import door_prototype,nif,sfnif

class DoorPrototypeTests(unittest.TestCase):
    def test_local_mesh_paths_materials_and_record_binding(self):
        files,plan,metadata=door_prototype.build(fixture(),{3:'Materials/A.mat',4:'Materials/B.mat'},'double',1/70)
        f=nif.parse(files['meshes/fo4port/native_doors/double/door.nif'])
        meshes=[sfnif.parse_bsgeometry(f.blocks[i]) for i in range(len(f.blocks)) if f.type_of(i)=='BSGeometry']
        for g in meshes:
            relative='geometries/'+g.meshes[0].path.decode().replace('\\','/')+'.mesh'
            self.assertIn(relative,files)
        materials=[]
        for i in range(len(f.blocks)):
            if f.type_of(i)=='BSLightingShaderProperty':
                index=int.from_bytes(f.blocks[i][:4],'little',signed=True);materials.append(f.strings[index].decode())
        self.assertEqual(materials,['Materials/A.mat','Materials/B.mat'])
        self.assertFalse(metadata['ready_for_gameplay'])
        self.assertEqual(metadata['origin_offset'],[0,0,0])
        self.assertEqual(metadata['collision_status'],'missing')
        self.assertTrue(metadata['door']['skeleton'].endswith('/characterassets/skeleton.rig'))
    def test_material_coverage_and_path_escape_rejected(self):
        for materials,asset in [({3:'Materials/A.mat'},'test'),({3:'a',4:None},'test'),({3:'a',4:'b'},'../test')]:
            with self.assertRaises(ValueError):door_prototype.build(fixture(),materials,asset,1/70)

    def test_editor_marker_omission_is_opt_in_and_recorded(self):
        import dataclasses
        from unittest.mock import patch
        source=fixture();effect=source.add_block('BSEffectShaderProperty',b'')
        shapes=nif.fo4_trishapes(source)
        shapes[0]=dataclasses.replace(shapes[0],name=b'EditorMarker:0',shader_ref=effect)
        with patch.object(nif,'fo4_trishapes',return_value=shapes):
            with self.assertRaises(ValueError):door_prototype.build(source,{4:'b'},'marker',1/70)
            files,plan,metadata=door_prototype.build(source,{4:'b'},'marker',1/70,exclude_editor_markers=True)
        self.assertEqual(metadata['excluded_shapes'],[{'shape':3,'reason':'explicit_editor_marker_omission'}])
        self.assertEqual([a['shape'] for a in plan['attachments']],[4])

    def test_existing_prototype_is_not_overwritten(self):
        import pathlib,tempfile
        with tempfile.TemporaryDirectory() as directory:
            marker=pathlib.Path(directory)/'keep.txt';marker.write_text('keep')
            with self.assertRaisesRegex(ValueError,'output must be empty'):
                door_prototype.stage(fixture(),{3:'a',4:'b'},'test',1/70,'unused.dll',directory)
            self.assertEqual(marker.read_text(),'keep')
