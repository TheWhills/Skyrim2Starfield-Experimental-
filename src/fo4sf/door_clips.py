"""Sample local source door poses; outputs contain game data and stay local.

This bridge deliberately retains source units/basis and exact endpoint times.
A native emitter must separately convert coordinates and encode graph events.
"""
import math
from . import animation_curves as curves
from .nif import NifError


# NiTransformInterpolator uses -FLT_MAX for absent components.
def _usable(values):
    return all(math.isfinite(x) and abs(x) < 1e30 for x in values)


def sample_track(track, time, bind):
    """Evaluate each channel, falling back to caller's LOCAL node bind pose.

    bind contains translation_source_units, quaternion_wxyz and scale.
    Animated values replace local channels; they are not added to world pivots.
    """
    if track is not None and track.get('type') != 'NiTransformInterpolator':
        raise NifError('unsupported sampled door interpolator')
    defaults = dict(bind)
    if track:
        for source, dest in [('translation', 'translation_source_units'),
                             ('quaternion_wxyz', 'quaternion_wxyz')]:
            if _usable(track[source]):
                defaults[dest] = track[source]
        if _usable([track['scale']]):
            defaults['scale'] = track['scale']
    data = track.get('decoded_keys') if track else None
    empty = {'interpolation': None, 'keys': []}
    translation = curves.evaluate_group(data['translation_source_units'] if data else empty,
                                       time, defaults['translation_source_units'])
    rotation = curves.evaluate_rotation(data['rotation'] if data else
              {'representation': 'quaternion_wxyz', **empty}, time, defaults['quaternion_wxyz'])
    scale = curves.evaluate_group(data['scale'] if data else empty, time, [defaults['scale']])[0]
    if len(translation) != 3 or not _usable(translation) or not _usable([scale]) or scale <= 0:
        raise NifError('invalid sampled local door pose')
    return {'translation_source_units': translation, 'quaternion_wxyz': rotation, 'scale': scale}


def sample_sequence(sequence, binds, samples_per_second=30):
    """Return independent per-node local samples and timing/event metadata.

    binds maps source node indices to local bind poses. Sampling includes exact
    source start/stop; final interval may be shorter. These are time-stamped
    samples, not fixed-frame native clips. Positive sequence frequency changes
    elapsed playback duration. Reverse/zero frequencies explicitly unsupported.
    """
    timing = sequence['timing']
    start, stop, frequency = timing['start'], timing['stop'], timing['frequency']
    if not all(math.isfinite(x) for x in [start, stop, frequency, samples_per_second]):
        raise NifError('nonfinite sequence timing')
    if frequency <= 0 or stop < start or samples_per_second <= 0:
        raise NifError('unsupported sequence timing')
    duration = (stop - start) / frequency
    count = math.ceil(duration * samples_per_second)
    if count > 65535:
        raise NifError('door sequence sample limit exceeded')
    times = [i / samples_per_second for i in range(count)] + [duration]
    tracks = []
    seen = set()
    for target in sequence['targets']:
        node = target['node']
        if node in seen or node not in binds:
            raise NifError('duplicate door target or missing local bind pose')
        seen.add(node)
        samples = []
        for elapsed in times:
            source_time = stop if elapsed == duration else start + elapsed * frequency
            samples.append({'elapsed': elapsed, 'source_time': source_time,
                            **sample_track(target['transform_track'], source_time, binds[node])})
        tracks.append({'node': node, 'name': target['name'],
                       'shape_blocks': list(target['shape_blocks']), 'samples': samples})
    events = []
    for event in timing['text_events']:
        if not math.isfinite(event['time']):
            raise NifError('nonfinite door event time')
        events.append({**event, 'elapsed': (event['time'] - start) / frequency,
                       'in_playback_range': start <= event['time'] <= stop})
    return {'name': sequence['name'], 'duration': duration, 'timing': dict(timing),
            'events': events, 'tracks': tracks, 'space': 'source_local'}
