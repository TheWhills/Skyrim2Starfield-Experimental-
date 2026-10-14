"""Experimental multi-bone Starfield door NIF, matching native_door rig names.

Meshes/bounds must be shape-local target-unit geometry, not world/pivot-baked
convert_door outputs. Collision blobs must be native body-local target units;
caller is responsible for motion/body types and complete collision coverage.
"""
import struct
from . import nif,sfnif,native_door,door_rig


def build(plan, shapes, unit_scale, collision_by_node=None, name=b'FO4Port_DoorModel'):
    native_door.prepare(plan,unit_scale)
    collision_by_node=dict(collision_by_node or {})
    expected={a['shape'] for a in plan['attachments']}
    if set(shapes)!=expected:
        raise ValueError('shape-local geometry must cover every rig attachment exactly')
    node_ids={b['node'] for b in plan['bones']}
    if not set(collision_by_node)<=node_ids:
        raise ValueError('collision attachment references absent rig bone')
    if any(not isinstance(blob,bytes) or not blob for blob in collision_by_node.values()):
        raise ValueError('collision attachment requires a nonempty native blob')
    if name.decode('utf-8') in {b['name'] for b in plan['bones']}:
        raise ValueError('model wrapper name collides with rig bone')
    f=nif.NifFile(endian=1,user_version=12,bs_version=173,author=b'\0',unknown_int=0,export_script=b'\0',sf_data=b'\x7a\0')
    keep=f.string_index(b'sgoKeep');matid=f.string_index(b'MaterialID')
    pending={}
    identity=(1,0,0,0,1,0,0,0,1)
    def node(node_name,t,r,scale=1,blob=None,retained=True):
        index=f.add_block('NiNode',b'')
        extras=[f.add_block('NiStringExtraData',struct.pack('<ii',keep,keep))] if retained else []
        collision=-1
        if blob is not None:
            collision=f.add_block('bhkNPCollisionObject',struct.pack('<iHiI',index,0x80,len(f.blocks)+1,0))
            f.add_block('bhkPhysicsSystem',struct.pack('<I',len(blob))+blob)
        pending[index]=[f.string_index(node_name),extras,t,r,scale,collision,[]]
        return index
    root=node(name,(0,0,0),identity,retained=False)
    flags=f.add_block('BSXFlags',struct.pack('<iI',f.string_index(b'BSX'),0x0A if collision_by_node else 0))
    pending[root][1].append(flags)
    target_nodes=[]
    for bone in plan['bones']:
        bind=bone['bind'];w,x,y,z=bind['quaternion_wxyz']
        r=(1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y),2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x),2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y))
        index=node(bone['name'].encode('utf-8'),[v*unit_scale for v in bind['translation_source_units']],r,
                   blob=collision_by_node.get(bone['node']))
        parent=root if bone['parent']==-1 else target_nodes[bone['parent']]
        pending[parent][-1].append(index);target_nodes.append(index)
    for attachment in plan['attachments']:
        local=attachment['local_transform'];door_rig.quaternion_from_matrix(local['rotation_row_major'])
        wrapper=node(('GeometryAttachment_'+str(attachment['shape'])).encode(),
                     [v*unit_scale for v in local['translation_source_units']],local['rotation_row_major'],local['scale'])
        pending[target_nodes[attachment['bone']]][-1].append(wrapper)
        shape=shapes[attachment['shape']];base=len(f.blocks)
        geometry=sfnif.BSGeometry(name_idx=f.string_index(shape.name),extra_refs=[base+1],sphere=shape.sphere,
                    box=shape.box,shader=base+2,meshes=[sfnif.MeshRef(shape.indices_size,shape.num_verts,0x40,shape.mesh_path),None,None,None])
        f.add_block('BSGeometry',sfnif.build_bsgeometry(geometry))
        f.add_block('NiIntegerExtraData',struct.pack('<iI',matid,sfnif.material_id(shape.material_path)))
        f.add_block('BSLightingShaderProperty',struct.pack('<iIi',f.string_index(shape.material_path.encode('latin-1')),0,-1))
        pending[wrapper][-1].append(base)
    for index,(node_name,extras,t,r,scale,collision,children) in pending.items():
        f.blocks[index]=(struct.pack('<iI',node_name,len(extras))+struct.pack(f'<{len(extras)}i',*extras)+
            struct.pack('<iI3f9ffiI',-1,0xE,*t,*r,scale,collision,len(children))+struct.pack(f'<{len(children)}i',*children))
    f.footer=struct.pack('<II',1,root)
    return f
