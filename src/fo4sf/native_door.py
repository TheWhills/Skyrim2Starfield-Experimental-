"""Experimental external CALUMI native door writer; no game graph/deployment.

Explicit scale factor and source-local basis required. Outputs are source-derived
assets and must remain outside the repository. Event data is retained in a
sidecar for future graph integration, not encoded as working runtime events.
"""
import ctypes as c
import math
import pathlib
import json
import xml.etree.ElementTree as ET
from .nif import NifError


def prepare(plan, unit_scale, fps=30):
    if not math.isfinite(unit_scale) or unit_scale <= 0 or fps != 30:
        raise NifError('native prototype requires positive unit scale and 30 fps')
    bones=plan['bones']
    if not bones or plan['space']!='source_local':raise NifError('native writer requires a source-local rig')
    for i,bone in enumerate(bones):
        if bone['parent'] < -1 or bone['parent'] >= i or abs(bone['bind']['scale']-1)>1e-5:
            raise NifError('native prototype requires ordered bones with unit bind scale')
    clips=[]
    for clip in plan['clips']:
        last=round(clip['duration']*fps)
        if not 0<=last<=65535 or abs(last-clip['duration']*fps)>1e-4:
            raise NifError('native door duration is not on the 30 fps grid')
        by_node={t['node']:t for t in clip['tracks']}
        tracks=[]
        for bone in bones:
            source=by_node.get(bone['node'])
            samples=source['samples'] if source else [{'elapsed':t,**bone['bind']} for t in sorted({0,clip['duration']})]
            frames={}
            for sample in samples:
                frame=round(sample['elapsed']*fps)
                if not 0<=frame<=last or abs(frame-sample['elapsed']*fps)>1e-4:
                    raise NifError('native door sample is not on the 30 fps grid')
                frames[frame]={'frame':frame,'translation':[x*unit_scale for x in sample['translation_source_units']],
                               'quaternion_wxyz':sample['quaternion_wxyz'],'scale':sample['scale']}
            tracks.append({'name':bone['name'],'keys':[frames[f] for f in sorted(frames)]})
        clips.append({'name':clip['name'],'tracks':tracks,'events':clip['events'],'duration':clip['duration']})
    return {'bones':bones,'clips':clips,'unit_scale':unit_scale,'fps':fps}


def clip_descriptor(name):
    """New .afx discovery descriptor matching native Open/Close tag metadata.

    No game graph is copied or altered. Relative filename resolves beside .afx.
    This does not provide source sound/quest events or graph activation itself.
    """
    if name not in ('Open', 'Close'):
        raise ValueError('unsupported door clip name')
    root = ET.Element('root')
    ET.SubElement(root, 'is_state').text = '0'
    ET.SubElement(root, 'tag').text = name
    ET.SubElement(root, 'filename').text = name + '.af'
    return ET.tostring(root, encoding='utf-8')


def export(plan, dll, output, unit_scale):
    prepared=prepare(plan,unit_scale)
    output=pathlib.Path(output).resolve()
    repo=pathlib.Path(__file__).resolve().parents[2]
    if output==repo or repo in output.parents:raise ValueError('native assets must stay outside repository')
    output.mkdir(parents=True,exist_ok=True)
    lib=c.CDLL(str(pathlib.Path(dll).resolve()))
    p=c.c_void_p;b=c.c_bool
    def bind(name,args,result):
        fn=getattr(lib,name);fn.argtypes=args;fn.restype=result;return fn
    error=bind('CreateStringContainerC',[],p)()
    message=bind('GetStringFromContainerC',[p],c.c_char_p)
    def require(result):
        if not result:raise RuntimeError((message(error) or b'CALUMI operation failed').decode(errors='replace'))
        return result
    rig=bind('CreateSkeletonRigC',[c.c_char_p],p)(b'FO4Port_DoorPrototype')
    try:
        require(rig)
        require(bind('SFBGSRigPackage_AddPackageToSkeletonRigC',[p,p,b],b)(rig,error,True))
        add=bind('AddBoneToSkeletonRigC',[p]+[c.c_float]*7+[c.c_char_p,c.c_int,b,p],b)
        for bone in prepared['bones']:
            pose=bone['bind'];w,x,y,z=pose['quaternion_wxyz'];t=[v*unit_scale for v in pose['translation_source_units']]
            require(add(rig,x,y,z,w,*t,bone['name'].encode('utf-8'),bone['parent'],True,error))
        rigpath=output/'door.rig'
        require(bind('SaveSkeletonRigToSFBGSFormatDirectC',[p,c.c_wchar_p,p],b)(rig,str(rigpath),error))
        for clip in prepared['clips']:
            if clip['name'] not in ('Open','Close'):raise ValueError('unsupported door clip name')
            anim=bind('CreateAnimationC',[c.c_char_p,c.c_uint],p)(clip['name'].encode(),len(prepared['bones']))
            try:
                require(anim)
                for index,track in enumerate(clip['tracks']):
                    block=bind('CreateAnimBlockC',[c.c_char_p,c.c_int,p],p)(track['name'].encode('utf-8'),index,error)
                    require(block)
                    try:
                        for key in track['keys']:
                            w,x,y,z=key['quaternion_wxyz']
                            for kind,args,values in [('Rotation',[c.c_uint16]+[c.c_float]*4,[key['frame'],x,y,z,w]),
                                    ('Translation',[c.c_uint16]+[c.c_double]*3,[key['frame'],*key['translation']]),
                                    ('Scalar',[c.c_uint16,c.c_float],[key['frame'],key['scale']])]:
                                entry=bind('Create'+kind+'EntryC',args,p)(*values)
                                require(entry)
                                try:require(bind('Add'+kind+'SqToAnimBlockC',[p,p,c.c_uint,b],b)(block,entry,1,True))
                                finally:bind('Delete'+kind+'EntryC',[p],b)(entry)
                        require(bind('AddAnimBlockToAnimationC',[p,p,b,p],b)(anim,block,True,error))
                        block=None # ownership transferred/deleted by successful native call
                    finally:
                        if block:bind('DeleteAnimationBlockC',[p],b)(block)
                require(bind('SaveAnimationToSFBGSFormatDirectC',[p,c.c_wchar_p,p,p],b)(anim,str(output/(clip['name']+'.af')),rig,error))
                (output/(clip['name']+'.afx')).write_bytes(clip_descriptor(clip['name']))
            finally:
                if anim:bind('DeleteAnimationC',[p],b)(anim)
        (output/'events.json').write_text(json.dumps({'runtime_events_encoded':False,'clips':[
            {'name':clip['name'],'duration':clip['duration'],'events':clip['events']} for clip in prepared['clips']]},indent=2))
        return prepared
    finally:
        if rig:bind('DeleteSkeletonRigC',[p],b)(rig)
        bind('DeleteStringContainerC',[p],None)(error)
