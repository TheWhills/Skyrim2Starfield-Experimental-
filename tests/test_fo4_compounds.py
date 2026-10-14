import unittest
from unittest.mock import patch
from fo4sf import fo4_compounds as decoder,hkpackfile

class CompoundFixture:
    def array(self,offset):return 1000,2
    def pointer(self,offset):return 2000
    def unpack(self,fmt,offset):
        if fmt=='<I':return (0,)
        at=1000 if offset<1128 else 1128;relative=offset-at
        if relative==64:return (1,1,1,1)
        if relative==48:return (10 if at==1000 else -10,0,0)
        return {0:(0,1,0),16:(-1,0,0),32:(0,0,1)}[relative]

class CompoundShapeTests(unittest.TestCase):
    def test_shared_child_instances_preserve_rotation_translation_and_hole(self):
        pack=CompoundFixture();classes={0:'hknpDynamicCompoundShape',2000:'hknpCompressedMeshShape'}
        original=[(1,0,0),(2,0,0),(1,1,0)]
        with patch.object(decoder.fc,'_compressed_mesh',return_value=(original,[(0,1,2)])):
            leaves=decoder._shape_leaves(pack,0,classes)
        self.assertEqual(len(leaves),2)
        self.assertEqual(leaves[0]['points'][0],(10,1,0))
        self.assertEqual(leaves[1]['points'][0],(-10,1,0))
        self.assertEqual([leaf['instance_path'] for leaf in leaves],[[0],[1]])
        self.assertEqual(original[0],(1,0,0))
    def test_unsupported_child_and_cycle_fail(self):
        with self.assertRaises(hkpackfile.PackfileError):decoder._shape_leaves(CompoundFixture(),0,{0:'hknpDynamicCompoundShape',2000:'unknown'})
        pack=CompoundFixture();pack.pointer=lambda offset:0
        with self.assertRaisesRegex(hkpackfile.PackfileError,'cycle'):decoder._shape_leaves(pack,0,{0:'hknpDynamicCompoundShape'})
    def test_nonunit_instance_scale_rejected(self):
        pack=CompoundFixture();original=pack.unpack
        pack.unpack=lambda fmt,off:(2,1,1,1) if fmt=='<4f' else original(fmt,off)
        with self.assertRaisesRegex(hkpackfile.PackfileError,'scale'):decoder._shape_leaves(pack,0,{0:'hknpDynamicCompoundShape'})
