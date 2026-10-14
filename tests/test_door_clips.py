import unittest
from fo4sf import door_clips, nif


class DoorClipTests(unittest.TestCase):
    def bind(self, x=0):
        return {'translation_source_units': [x, 0, 0], 'quaternion_wxyz': [1,0,0,0], 'scale': 1}

    def sequence(self):
        return {'name': 'Open', 'timing': {'start': .1, 'stop': .9, 'frequency': 2,
            'text_events': [{'time': .5, 'text': 'Sound:Open'}, {'time': 1, 'text': 'End'}]},
            'targets': [{'node': i, 'name': str(i), 'shape_blocks': [i+10], 'transform_track': None} for i in [1,2]]}

    def test_timing_and_independent_local_binds(self):
        result = door_clips.sample_sequence(self.sequence(), {1:self.bind(0), 2:self.bind(140)}, 7)
        self.assertEqual(result['duration'], .4)
        self.assertEqual(len(result['tracks'][0]['samples']), 4)
        self.assertEqual(result['tracks'][1]['samples'][-1]['translation_source_units'], [140,0,0])
        self.assertEqual(result['tracks'][0]['samples'][-1]['source_time'], .9)
        self.assertEqual(result['events'][0]['elapsed'], .2)
        self.assertFalse(result['events'][1]['in_playback_range'])

    def test_invalid_interpolator_channels_use_local_bind(self):
        track={'type':'NiTransformInterpolator', 'translation':[-3.4e38]*3,
               'quaternion_wxyz':[-3.4e38]*4, 'scale':-3.4e38}
        self.assertEqual(door_clips.sample_track(track, 0, self.bind(7)), self.bind(7))
        track.update(translation=[1,2,3], quaternion_wxyz=[2,0,0,0], scale=2)
        self.assertEqual(door_clips.sample_track(track, 0, self.bind(7)),
                         {'translation_source_units':[1,2,3], 'quaternion_wxyz':[1,0,0,0], 'scale':2})

    def test_animated_channels_replace_bind(self):
        empty={'interpolation':None,'keys':[]}
        track={'type':'NiTransformInterpolator', 'translation':[-3.4e38]*3,
               'quaternion_wxyz':[-3.4e38]*4, 'scale':-3.4e38,
               'decoded_keys':{'translation_source_units':{'interpolation':1,'keys':[
                   {'time':0,'value':[0,0,0]}, {'time':1,'value':[10,0,0]}]},
                   'rotation':{'representation':'quaternion_wxyz',**empty},'scale':empty}}
        self.assertEqual(door_clips.sample_track(track,.5,self.bind(140))['translation_source_units'], [5,0,0])

    def test_bad_timing_duplicate_and_missing_bind_rejected(self):
        for freq in [0,-1,float('nan')]:
            sequence=self.sequence();sequence['timing']['frequency']=freq
            with self.assertRaises(nif.NifError):door_clips.sample_sequence(sequence,{1:self.bind(),2:self.bind()})
        sequence=self.sequence();sequence['targets'][1]['node']=1
        with self.assertRaises(nif.NifError):door_clips.sample_sequence(sequence,{1:self.bind()})
        with self.assertRaises(nif.NifError):door_clips.sample_sequence(self.sequence(),{})
