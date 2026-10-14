"""Build isolated native door prototype artifacts; no deployment/activation claim."""
import dataclasses
import pathlib
import re
import json
from . import nif,door_rig,door_model,native_door,convert_static,sfnif,sfmesh,door_collision


def build(source, materials_by_shape, asset, unit_scale, collision_by_node=None, exclude_editor_markers=False):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',asset):
        raise ValueError('prototype asset requires a simple lowercase name')
    plan=door_rig.plan(source)
    source_shapes={s.block:s for s in nif.fo4_trishapes(source) if s.positions and s.triangles}
    exclusions=[]
    if exclude_editor_markers:
        for block,shape in list(source_shapes.items()):
            if shape.name.startswith(b'EditorMarker') and source.type_of(shape.shader_ref)=='BSEffectShaderProperty':
                exclusions.append({'shape':block,'reason':'explicit_editor_marker_omission'})
                del source_shapes[block]
        plan['attachments']=[a for a in plan['attachments'] if a['shape'] in source_shapes]
    if set(materials_by_shape)!=set(source_shapes) or any(not v for v in materials_by_shape.values()):
        raise ValueError('explicit material identity required for every source shape')
    if any(s.skinned for s in source_shapes.values()):
        raise ValueError('native rigid door prototype cannot silently freeze skinned shapes')
    native_door.prepare(plan,unit_scale)
    files={};shapes={}
    for block,shape in source_shapes.items():
        local=dataclasses.replace(shape,translation=(0,0,0),rotation=(1,0,0,0,1,0,0,0,1),scale=1)
        mesh=convert_static.shape_to_mesh(local,unit_scale);payload=sfmesh.serialize(mesh)
        directory,stem=convert_static.mesh_file_path(payload)
        files[f'geometries/{directory}/{stem}.mesh']=payload
        points=[sfmesh.decode_position(p,mesh.scale) for p in mesh.positions]
        sphere,box=sfnif.bounds_from_points(points)
        shapes[block]=sfnif.StaticShape(shape.name,f'{directory}\\{stem}'.encode(),len(mesh.triangles)*3,
                                      len(mesh.positions),materials_by_shape[block],sphere,box)
    path=f'fo4port/native_doors/{asset}'
    model=door_model.build(plan,shapes,unit_scale,collision_by_node,name=('FO4Port_'+asset).encode())
    files[f'meshes/{path}/door.nif']=nif.serialize(model)
    metadata={'experimental':True,'ready_for_gameplay':False,'collision_status':'unverified' if collision_by_node else 'missing',
              'runtime_source_events_encoded':False,'material_assets_bundled':False,'excluded_shapes':exclusions,'coordinate_basis':'source_local_unverified_in_game',
              'unit_scale':unit_scale,'origin_offset':[0,0,0],
              'door':{'model':path+'/door.nif','anim_graph':sfnif.DOOR_TEMPLATE['anim_graph'],
                      'skeleton':path+'/characterassets/skeleton.rig','animations':path+'/animations'},
              'shape_materials':materials_by_shape,'source_collision':door_collision.plan(source,plan)}
    return files,plan,metadata


def stage(source, materials_by_shape, asset, unit_scale, dll, output, collision_by_node=None, exclude_editor_markers=False):
    files,plan,metadata=build(source,materials_by_shape,asset,unit_scale,collision_by_node,exclude_editor_markers)
    output=pathlib.Path(output).resolve();repo=pathlib.Path(__file__).resolve().parents[2]
    if output==repo or repo in output.parents:raise ValueError('prototype assets must stay outside repository')
    if output.exists() and any(output.iterdir()):raise ValueError('prototype output must be empty; never overwrite a prior build')
    output.mkdir(parents=True,exist_ok=True)
    # Mark incomplete before any native output: interrupted prototype is not a deployable installation.
    (output/'prototype.json').write_text(json.dumps({**metadata,'build_complete':False},indent=2))
    animations=output/'meshes'/metadata['door']['animations']
    native_door.export(plan,dll,animations,unit_scale)
    rig=output/'meshes'/metadata['door']['skeleton'];rig.parent.mkdir(parents=True,exist_ok=True)
    (animations/'door.rig').rename(rig)
    for name,payload in files.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
    (output/'prototype.json').write_text(json.dumps({**metadata,'build_complete':True},indent=2))
    return metadata
