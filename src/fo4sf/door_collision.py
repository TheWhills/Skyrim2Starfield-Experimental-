"""Source door collision ownership, preserving bhkNPCollisionObject Body ID.

Inventory only: no compound geometry conversion or target physics generation.
One source physics system can be shared by distinct animated node attachments.
"""
import struct
import math
from . import nif,hkpackfile,fo4collision as fc


def plan(source, rig):
    bone_indices={bone['node']:i for i,bone in enumerate(rig['bones'])}
    animated={track['node'] for clip in rig['clips'] for track in clip['tracks']}
    systems={};attachments=[];assigned={}
    for index in range(len(source.blocks)):
        if source.type_of(index)!='bhkNPCollisionObject':continue
        block=source.blocks[index]
        if len(block)!=14:raise nif.NifError('invalid door collision attachment layout')
        node,flags,data,body=struct.unpack('<iHiI',block)
        if node not in bone_indices:raise nif.NifError('door collision target absent from rig')
        if not 0<=data<len(source.blocks) or source.type_of(data)!='bhkPhysicsSystem':
            raise nif.NifError('invalid door physics system link')
        if data not in systems:
            raw=source.blocks[data]
            if len(raw)<4:raise nif.NifError('truncated door physics system')
            length,=struct.unpack_from('<I',raw)
            if len(raw)!=length+4:raise nif.NifError('door physics system length mismatch')
            pack=hkpackfile.Packfile(raw[4:]);classes=dict(pack.objects())
            roots=[o for o,c in classes.items() if c=='hknpPhysicsSystemData']
            if len(roots)!=1:raise nif.NifError('door requires one physics system root per blob')
            at,count=pack.array(roots[0]+fc.SYS_BODIES)
            if count<0 or (count and at is None):raise nif.NifError('invalid door body array')
            bodies=[]
            for i in range(count):
                offset=at+fc.BODY_SIZE*i
                position=list(pack.unpack('<3f',offset+fc.BODY_POS));rotation=list(pack.unpack('<4f',offset+fc.BODY_ROT))
                if not all(math.isfinite(x) for x in position+rotation):raise nif.NifError('nonfinite door body transform')
                bodies.append({'body_id':i,'shape_class':classes.get(pack.pointer(offset),'unknown'),
                               'position_havok_units':position,'quaternion_xyzw':rotation})
            systems[data]=bodies
        if body>=len(systems[data]):raise nif.NifError('door collision body ID out of range')
        identity=(data,body)
        if identity in assigned:raise nif.NifError('source door body attached to multiple nodes')
        assigned[identity]=node
        ancestor=bone_indices[node];moving=False
        while ancestor!=-1:
            bone=rig['bones'][ancestor];moving=moving or bone['node'] in animated;ancestor=bone['parent']
        attachments.append({'collision_block':index,'node':node,'bone':bone_indices[node],'flags':flags,
                            'system_block':data,'body_id':body,'follows_animated_ancestor':moving,
                            **systems[data][body]})
    unassigned=[{'system_block':system,'body_id':body['body_id']} for system,bodies in systems.items()
                for body in bodies if (system,body['body_id']) not in assigned]
    return {'attachments':attachments,'systems':[{'system_block':s,'bodies':b} for s,b in systems.items()],
            'unassigned_bodies':unassigned,'geometry_converted':False}
