"""Source-local door rig plan; source-derived output must remain local.

Preserves static ancestors and shape attachments so independently animated
nodes can become native rig bones without losing their parent transforms.
"""
import math
import struct
from . import nif, door_motion, door_clips


def quaternion_from_matrix(matrix):
    if len(matrix) != 9 or not all(math.isfinite(x) for x in matrix):
        raise nif.NifError('invalid door bind rotation matrix')
    for row in range(3):
        for other in range(3):
            dot = sum(matrix[3*row+k]*matrix[3*other+k] for k in range(3))
            if abs(dot - (1 if row == other else 0)) > 1e-4:
                raise nif.NifError('door bind rotation is not orthonormal')
    m = matrix
    determinant = m[0]*(m[4]*m[8]-m[5]*m[7])-m[1]*(m[3]*m[8]-m[5]*m[6])+m[2]*(m[3]*m[7]-m[4]*m[6])
    if abs(determinant-1)>1e-4:
        raise nif.NifError('door bind rotation is reflected')
    trace=m[0]+m[4]+m[8]
    if trace>0:
        s=math.sqrt(1+trace)*2
        result=[s/4,(m[7]-m[5])/s,(m[2]-m[6])/s,(m[3]-m[1])/s]
    else:
        i=max(range(3),key=lambda j:m[4*j]);j=(i+1)%3;k=(i+2)%3
        s=math.sqrt(1+m[4*i]-m[4*j]-m[4*k])*2
        result=[0]*4
        result[0]=(m[3*k+j]-m[3*j+k])/s
        result[i+1]=s/4
        result[j+1]=(m[3*j+i]+m[3*i+j])/s
        result[k+1]=(m[3*k+i]+m[3*i+k])/s
    length=math.hypot(*result)
    return [x/length for x in result]


def plan(source, samples_per_second=30):
    report=door_motion.inspect(source)
    if report['issues']:
        raise nif.NifError('door has absent or ambiguous animation bindings')
    nodes={i for i in range(len(source.blocks)) if source.type_of(i).endswith('Node')}
    parents={}
    for node in sorted(nodes):
        for child in nif.node_children(source,node):
            if child in parents and parents[child]!=node:
                raise nif.NifError('door node or shape has multiple parents')
            parents[child]=node
    shapes={s.block for s in nif.fo4_trishapes(source) if s.positions and s.triangles}
    required={t['node'] for sequence in report['sequences'] for t in sequence['targets']}
    required.update(parents[s] for s in shapes if s in parents)
    ordered=[];visited=set();active=set()
    def visit(node):
        if node in active:
            raise nif.NifError('cycle in door rig hierarchy')
        if node in visited:return
        active.add(node)
        if node in parents:visit(parents[node])
        active.remove(node);visited.add(node);ordered.append(node)
    for node in sorted(required):visit(node)
    indices={node:i for i,node in enumerate(ordered)}
    bones=[];binds={};names=set()
    for node in ordered:
        name_index,=struct.unpack_from('<i',source.blocks[node])
        name=source.strings[name_index].decode('latin-1') if 0<=name_index<len(source.strings) else ''
        if not name or name in names:
            raise nif.NifError('door rig bone name is empty or duplicate')
        names.add(name)
        translation,rotation,scale=nif._av_transform(source.blocks[node])
        bind={'translation_source_units':list(translation),'quaternion_wxyz':quaternion_from_matrix(rotation),'scale':scale}
        # Validate unanimated bind channels too.
        bind=door_clips.sample_track(None,0,bind)
        binds[node]=bind
        bones.append({'node':node,'name':name,'parent':indices[parents[node]] if node in parents else -1,'bind':bind})
    attachments=[]
    for shape in sorted(shapes):
        if shape not in parents:
            raise nif.NifError('door shape lacks a rig attachment parent')
        t,r,s=nif._av_transform(source.blocks[shape])
        attachments.append({'shape':shape,'bone':indices[parents[shape]],
                            'local_transform':{'translation_source_units':list(t),'rotation_row_major':list(r),'scale':s}})
    clips=[door_clips.sample_sequence(sequence,binds,samples_per_second) for sequence in report['sequences']]
    return {'space':'source_local','bones':bones,'attachments':attachments,'clips':clips}
