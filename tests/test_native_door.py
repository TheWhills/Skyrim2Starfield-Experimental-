import unittest
from test_door_motion import fixture
from fo4sf import door_rig,native_door,nif

class NativeDoorPreparationTests(unittest.TestCase):
    def test_explicit_units_static_ancestors_and_frame_keys(self):
        result=native_door.prepare(door_rig.plan(fixture()),1/70)
        tracks=result['clips'][0]['tracks']
        self.assertEqual(tracks[0]['keys'][0]['translation'],[1,0,0])
        self.assertEqual(tracks[2]['keys'][-1]['translation'],[2,0,0])
        self.assertEqual([k['frame'] for k in tracks[1]['keys']],list(range(31)))
    def test_off_grid_duration_and_nonunit_bind_fail(self):
        plan=door_rig.plan(fixture());plan['clips'][0]['duration']=.101
        with self.assertRaises(nif.NifError):native_door.prepare(plan,1/70)
        plan=door_rig.plan(fixture());plan['bones'][0]['bind']['scale']=2
        with self.assertRaises(nif.NifError):native_door.prepare(plan,1/70)
    def test_float_endpoint_rounding_does_not_add_frame(self):
        plan=door_rig.plan(fixture());clip=plan['clips'][0];clip['duration']=1.00000001
        for track in clip['tracks']:
            track['samples'].append({**track['samples'][-1],'elapsed':clip['duration']})
        result=native_door.prepare(plan,1/70)
        self.assertEqual(len(result['clips'][0]['tracks'][1]['keys']),31)


class NativeDoorDescriptorTests(unittest.TestCase):
    def test_native_tags_and_adjacent_relative_filenames(self):
        import xml.etree.ElementTree as ET
        for name in ['Open', 'Close']:
            root=ET.fromstring(native_door.clip_descriptor(name))
            self.assertEqual(root.tag,'root')
            self.assertEqual(root.findtext('tag'),name)
            self.assertEqual(root.findtext('filename'),name+'.af')
            self.assertEqual(root.findtext('is_state'),'0')
            self.assertEqual([child.tag for child in root],['is_state','tag','filename'])
    def test_unknown_and_path_clip_names_rejected(self):
        for name in ['../Open','Open.af','Closed','open']:
            with self.assertRaises(ValueError):native_door.clip_descriptor(name)
