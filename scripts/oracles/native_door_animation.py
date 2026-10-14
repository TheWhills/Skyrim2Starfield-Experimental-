"""External CALUMI DLL oracle: synthetic opposing door leaves, no game assets.

Run with --dll /path/to/CALUMI.Animation.dll --output /outside/repo/output.
Creates a three-bone rig and Open/Close clips; reads all rotation frames back.
Native output is experimental and does not prove graph/gameplay compatibility.
Use a trusted, pinned upstream DLL; the repository does not distribute it.
"""
import argparse
import ctypes as c
import pathlib
import math
import json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dll', type=pathlib.Path, required=True)
parser.add_argument('--output', type=pathlib.Path, required=True)
args = parser.parse_args()
repo = pathlib.Path(__file__).resolve().parents[2]
out = args.output.resolve()
if out == repo or repo in out.parents:
    parser.error('native outputs must stay outside the source repository')
if not args.dll.is_file():
    parser.error('DLL does not exist')
out.mkdir(parents=True, exist_ok=True)
lib = c.CDLL(str(args.dll.resolve()))

if not __debug__:
    parser.error("run without Python optimization so all oracle checks execute")
def bind(name,args,result):
 f=getattr(lib,name);f.argtypes=args;f.restype=result;return f
p=c.c_void_p;b=c.c_bool
create=bind('CreateSkeletonRigC',[c.c_char_p],p);destroy=bind('DeleteSkeletonRigC',[p],b)
error=bind('CreateStringContainerC',[],p);message=bind('GetStringFromContainerC',[p],c.c_char_p);free=bind('DeleteStringContainerC',[p],None)
package=bind('SFBGSRigPackage_AddPackageToSkeletonRigC',[p,p,b],b)
add=bind('AddBoneToSkeletonRigC',[p]+[c.c_float]*7+[c.c_char_p,c.c_int,b,p],b)
save=bind('SaveSkeletonRigToSFBGSFormatDirectC',[p,c.c_wchar_p,p],b)
ac=bind('CreateAnimationC',[c.c_char_p,c.c_uint],p);ad=bind('DeleteAnimationC',[p],b)
bc=bind('CreateAnimBlockC',[c.c_char_p,c.c_int,p],p)
ba=bind('AddAnimBlockToAnimationC',[p,p,b,p],b)
rc=bind('CreateRotationEntryC',[c.c_uint16]+[c.c_float]*4,p);rd=bind('DeleteRotationEntryC',[p],b)
ra=bind('AddRotationSqToAnimBlockC',[p,p,c.c_uint,b],b)
saveanim=bind('SaveAnimationToSFBGSFormatWithExistingRigDirectC',[p,c.c_wchar_p,c.c_wchar_p,p],b)
load=bind('LoadAnimationSceneFromSFBGSFormatC',[c.POINTER(c.c_wchar_p),c.c_int,p],p)
getrig=bind('GetSkeletonRigC',[p],p)
bonecount=bind('GetSkeletonRigBoneCountC',[p],c.c_size_t)
getbone=bind('GetSkeletonBoneC',[p,c.c_int,p],p)
bonename=bind('GetSkeletonBoneNameC',[p],c.c_char_p)
parentindex=bind('GetSkeletonBoneParentIndexC',[p],c.c_int)
scenedel=bind('DeleteAnimationSceneC',[p],b)
count=bind('GetAnimationCountC',[p],c.c_size_t);getanim=bind('GetAnimationC',[p,c.c_int,p],p)
blockcount=bind('GetAnimationBlockCountC',[p],c.c_size_t);getblock=bind('GetAnimationBlockC',[p,c.c_int,p],p)
name=bind('GetAnimBlockBoneNameC',[p],c.c_char_p);rotcount=bind('GetRotationSqSizeC',[p],c.c_size_t)
rotget=bind('GetRotationFromSqC',[p,c.c_int,p],p);frame=bind('GetFrameFromRotationEntryC',[p],c.c_uint16)
value=bind('GetValueFromRotationEntryC',[p],p)
components=[bind('GetQuaternion'+axis,[p],c.c_float) for axis in 'XYZW']
err=error();reports=[]
try:
 rig=create(b'FO4Port_SyntheticDoubleDoor')
 try:
  assert package(rig,err,True),message(err)
  for bone_name,parent,x in [(b'Root',-1,0),(b'LeafLeft',0,-1),(b'LeafRight',0,1)]:
   assert add(rig,0,0,0,1,x,0,0,bone_name,parent,True,err),message(err)
  assert save(rig,str(out/'synthetic-double-door.rig'),err),message(err)
 finally:
  destroy(rig)
 for title,reverse in [('Open',False),('Close',True)]:
  anim=ac(title.encode(),3)
  try:
   for i,bone in enumerate(['Root','LeafLeft','LeafRight']):
    block=bc(bone.encode(),i,err)
    for f in range(31):
     progress=(30-f if reverse else f)/30
     angle=0 if i==0 else progress*math.pi/2*(1 if i==1 else -1)
     entry=rc(f,0,0,math.sin(angle/2),math.cos(angle/2))
     try: assert ra(block,entry,1,True),message(err)
     finally: rd(entry)
    assert ba(anim,block,True,err),message(err)
   path=out/(title+'.af')
   assert saveanim(anim,str(path),str(out/'synthetic-double-door.rig'),err),message(err)
  finally:ad(anim)
  paths=(c.c_wchar_p*2)(str(out/'synthetic-double-door.rig'),str(path))
  scene=load(paths,2,err);assert scene,message(err)
  try:
   loadedrig=getrig(scene);assert loadedrig
   assert bonecount(loadedrig)==3
   for index,expectedname in enumerate(['Root','LeafLeft','LeafRight']):
    bone=getbone(loadedrig,index,err);assert bone
    assert bonename(bone).decode()==expectedname
    assert parentindex(bone)==(-1 if index==0 else 0)
   assert count(scene)==1,count(scene)
   loaded=getanim(scene,0,err);assert blockcount(loaded)==3
   blocks=[]
   for i in range(3):
    block=getblock(loaded,i,err);n=name(block).decode();keys=[]
    for j in range(rotcount(block)):
     entry=rotget(block,j,err);q=value(entry);keys.append({'frame':frame(entry),'xyzw':[component(q) for component in components]})
    assert len(keys)==31,(n,len(keys));assert [k['frame'] for k in keys]==list(range(31))
    boneindex=['Root','LeafLeft','LeafRight'].index(n)
    for k in keys:
     progress=(30-k['frame'] if reverse else k['frame'])/30
     angle=0 if boneindex==0 else progress*math.pi/2*(1 if boneindex==1 else -1)
     expected=[0,0,math.sin(angle/2),math.cos(angle/2)]
     assert min(max(abs(a-sign*z) for a,z in zip(k['xyzw'],expected)) for sign in [-1,1])<1e-4,(n,k,expected)
    blocks.append({'bone':n,'keys':len(keys),'first':keys[0],'last':keys[-1]})
   reports.append({'animation':title,'bytes':path.stat().st_size,'blocks':blocks,'readback':'passed'})
  finally:scenedel(scene)
 print(json.dumps(reports,indent=2));(out/'readback.json').write_text(json.dumps(reports,indent=2))
finally:free(err)




