import struct
import unittest
from unittest.mock import patch
from fo4sf import meshcollision, hkpackfile, fo4collision as fc, nif, convert_static


class BodyFixture:
    def __init__(self, count=1, rotation=(0,0,0,1), position=(0,0,0), kind='hknpCompressedMeshShape'):
        self.count,self.rotation,self.position,self.kind=count,rotation,position,kind
    def objects(self):return [(0,'hknpPhysicsSystemData'),(1000,self.kind)]
    def array(self, offset):return 100,self.count
    def pointer(self, offset):return 1000 if offset==100 else 2000
    def unpack(self, fmt, offset):return self.rotation if offset==100+fc.BODY_ROT else self.position


class MeshBodyCoverageTests(unittest.TestCase):
    def test_supported_single_body_and_convex_dispatch(self):
        self.assertEqual(meshcollision._fo4_mesh_body(BodyFixture()), (2000,(0,0,0)))
        self.assertEqual(meshcollision._fo4_mesh_body(BodyFixture(rotation=(0,0,0,-1))), (2000,(0,0,0)))
        self.assertIsNone(meshcollision._fo4_mesh_body(BodyFixture(kind='hknpConvexPolytopeShape')))

    def test_multiple_bodies_never_choose_first(self):
        with self.assertRaisesRegex(hkpackfile.PackfileError, 'all 3 source collision bodies'):
            meshcollision._fo4_mesh_body(BodyFixture(count=3))

    def test_transforms_and_invalid_data_explicitly_rejected(self):
        for body in [BodyFixture(position=(1,0,0)), BodyFixture(rotation=(0,0,.5,.5)),
                     BodyFixture(rotation=(0,0,0,0)), BodyFixture(position=(float('nan'),0,0)),
                     BodyFixture(count=-1)]:
            with self.assertRaises(hkpackfile.PackfileError):meshcollision._fo4_mesh_body(body)

    def test_production_caller_records_fallback_reason(self):
        source=nif.NifFile(bs_version=130)
        source.add_block('NiNode',b'')
        data=source.add_block('bhkPhysicsSystem',struct.pack('<I',4)+b'test')
        source.add_block('bhkNPCollisionObject',struct.pack('<iHi',0,0,data))
        report={}
        with patch.object(meshcollision,'transplant',side_effect=hkpackfile.PackfileError('cannot preserve all 3 source collision bodies')):
            self.assertIsNone(convert_static.fo4_mesh_collision(source,b'template',report))
        self.assertIn('all 3 source collision bodies',report['fo4_collision_error'])
        self.assertNotIn('source',report)
