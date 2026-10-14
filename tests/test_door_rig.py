import math
import struct
import unittest
from test_door_motion import fixture
from fo4sf import door_rig,nif


class DoorRigTests(unittest.TestCase):
    def test_parent_before_children_and_separate_attachments(self):
        result=door_rig.plan(fixture())
        self.assertEqual([(b['name'],b['parent']) for b in result['bones']], [('Root',-1),('LeafA',0),('LeafB',0)])
        self.assertEqual(result['bones'][0]['bind']['translation_source_units'],[70,0,0])
        self.assertEqual(result['bones'][2]['bind']['translation_source_units'],[140,0,0])
        self.assertEqual([a['bone'] for a in result['attachments']],[1,2])
        self.assertEqual(result['clips'][0]['tracks'][1]['samples'][-1]['translation_source_units'],[140,0,0])

    def test_cycle_and_multiple_parent_rejected(self):
        source=fixture();source.blocks[1]=source.blocks[1][:-8]+struct.pack('<Ii',1,0)
        with self.assertRaisesRegex(nif.NifError,'cycle'):door_rig.plan(source)
        source=fixture();source.blocks[2]=source.blocks[2][:-8]+struct.pack('<Ii',1,3)
        with self.assertRaisesRegex(nif.NifError,'multiple parents'):door_rig.plan(source)

    def test_half_turn_matrix_conversion_and_reflection_rejection(self):
        q=door_rig.quaternion_from_matrix((1,0,0,0,-1,0,0,0,-1))
        self.assertAlmostEqual(abs(q[1]),1)
        self.assertAlmostEqual(q[0],0)
        for matrix in [(1,0,0,0,1,0,0,0,-1),(2,0,0,0,1,0,0,0,1)]:
            with self.assertRaises(nif.NifError):door_rig.quaternion_from_matrix(matrix)

    def test_ambiguous_bone_name_rejected(self):
        source=fixture();data=bytearray(source.blocks[2]);struct.pack_into('<i',data,0,0);source.blocks[2]=bytes(data)
        with self.assertRaises(nif.NifError):door_rig.plan(source)
