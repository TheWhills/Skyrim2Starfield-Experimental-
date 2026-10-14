"""Decode selected FO4 body shape trees, preserving compound instances.

Source extraction only. No native shape/BVH generation and no physics claims.
Compound layout cross-checked against PyNifly and actual FO4 packfiles.
"""
import math
from . import hkpackfile,fo4collision as fc,door_rig


def _shape_leaves(pack, shape, classes, active=(), path=(), transforms=()):
    if shape in active or len(active)>=64:raise hkpackfile.PackfileError('cycle/depth limit in compound collision')
    kind=classes.get(shape)
    if kind=='hknpCompressedMeshShape':
        data=pack.pointer(shape+fc.CMS_DATA)
        if data is None:raise hkpackfile.PackfileError('collision mesh data missing')
        points,triangles=fc._compressed_mesh(pack,data);radius=0.0
    elif kind=='hknpConvexPolytopeShape':
        points,triangles=fc._convex(pack,shape);radius=pack.unpack('<f',shape+20)[0]
    elif kind=='hknpDynamicCompoundShape':
        array,count=pack.array(shape+96)
        if count<=0 or count>65535 or (count and array is None):raise hkpackfile.PackfileError('invalid compound instance array')
        leaves=[]
        for index in range(count):
            at=array+128*index
            child=pack.pointer(at+80)
            if child is None:raise hkpackfile.PackfileError('compound child shape missing')
            columns=[pack.unpack('<3f',at+16*i) for i in range(3)]
            rotation=[columns[c][r] for r in range(3) for c in range(3)]
            door_rig.quaternion_from_matrix(rotation)
            translation=list(pack.unpack('<3f',at+48));scale=pack.unpack('<4f',at+64)
            if not all(math.isfinite(x) for x in translation+list(scale)) or any(abs(x-1)>1e-5 for x in scale):
                raise hkpackfile.PackfileError('unsupported/nonfinite compound instance scale or translation')
            transform={'rotation_row_major':rotation,'translation_havok_units':translation,
                       'packed_rotation_w_words':[pack.unpack('<I',at+12+16*i)[0] for i in range(3)],
                       'packed_translation_w_word':pack.unpack('<I',at+60)[0]}
            children=_shape_leaves(pack,child,classes,active+(shape,),path+(index,),transforms+(transform,))
            for leaf in children:
                leaf['points']=[tuple(translation[r]+sum(rotation[3*r+c]*v[c] for c in range(3)) for r in range(3)) for v in leaf['points']]
            leaves.extend(children)
        return leaves
    else:raise hkpackfile.PackfileError('unsupported compound child/body shape: '+str(kind))
    if not points or not triangles or not math.isfinite(radius) or radius<0:
        raise hkpackfile.PackfileError('empty/invalid collision leaf geometry')
    if any(not all(math.isfinite(v) for v in point) for point in points):raise hkpackfile.PackfileError('nonfinite collision leaf vertex')
    if any(any(i<0 or i>=len(points) for i in tri) for tri in triangles):raise hkpackfile.PackfileError('collision leaf index out of range')
    return [{'shape_class':kind,'shape_offset':shape,'instance_path':list(path),'instance_transforms':list(transforms),
             'points':points,'triangles':triangles,'convex_radius_havok_units':radius}]


def decode_body(blob, body_id):
    pack=hkpackfile.Packfile(blob);classes=dict(pack.objects())
    roots=[o for o,c in classes.items() if c=='hknpPhysicsSystemData']
    if len(roots)!=1:raise hkpackfile.PackfileError('selected body requires one physics root')
    array,count=pack.array(roots[0]+fc.SYS_BODIES)
    if not isinstance(body_id,int) or not 0<=body_id<count or array is None:
        raise hkpackfile.PackfileError('selected collision body ID out of range')
    at=array+body_id*fc.BODY_SIZE;shape=pack.pointer(at)
    position=list(pack.unpack('<3f',at+fc.BODY_POS));rotation=list(pack.unpack('<4f',at+fc.BODY_ROT))
    if not all(math.isfinite(v) for v in position+rotation):raise hkpackfile.PackfileError('nonfinite selected body transform')
    return {'body_id':body_id,'position_havok_units':position,'quaternion_xyzw':rotation,
            'space':'body_shape_local_havok_units','body_transform_applied':False,
            'leaves':_shape_leaves(pack,shape,classes)}
