import struct
import unittest
from test_door_motion import fixture
from test_doors import shape,names
from fo4sf import door_rig,door_model,nif

class MultiBoneDoorModelTests(unittest.TestCase):
    def plan(self):return door_rig.plan(fixture())
    def shapes(self):return {3:shape(b'A'),4:shape(b'B')}
    def test_matching_rig_hierarchy_and_preserved_pivots(self):
        plan=self.plan();f=nif.parse(nif.serialize(door_model.build(plan,self.shapes(),1/70)))
        nodes=names(f)
        self.assertIn(nodes[b'LeafA'],nif.node_children(f,nodes[b'Root']))
        self.assertIn(nodes[b'LeafB'],nif.node_children(f,nodes[b'Root']))
        self.assertEqual(nif._av_transform(f.blocks[nodes[b'LeafB']])[0],(2,0,0))
        self.assertEqual(nif.world_transforms(f)(nodes[b'LeafB'])[0],(3,0,0))
        for bone in plan['bones']:self.assertIn(bone['name'].encode(),nodes)
        self.assertEqual(sum(f.type_of(i)=='BSGeometry' for i in range(len(f.blocks))),2)

    def test_collision_attaches_to_each_correct_branch(self):
        f=door_model.build(self.plan(),self.shapes(),1/70,{1:b'left-native-test',2:b'right-native-test',0:b'frame-native-test'})
        nodes=names(f);targets=[]
        for i in range(len(f.blocks)):
            if f.type_of(i)=='bhkNPCollisionObject':targets.append(struct.unpack_from('<i',f.blocks[i])[0])
        self.assertEqual(set(targets),{nodes[b'Root'],nodes[b'LeafA'],nodes[b'LeafB']})
        self.assertEqual(len(targets),3)

    def test_incomplete_shapes_unknown_collision_and_name_collision_rejected(self):
        for shapes,collision,name in [({3:shape(b'A')},{},b'Model'),(self.shapes(),{99:b'x'},b'Model'),
                                     (self.shapes(),{},b'LeafA')]:
            with self.assertRaises(ValueError):door_model.build(self.plan(),shapes,1/70,collision,name)
