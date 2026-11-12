"""Body bug report: upgrade, pivots, mirror, toes, stretch and UI hygiene."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils import Matrix,Vector,kdtree

ROOT=Path(__file__).resolve().parents[1]
WORK=__import__('runpy').run_path(str(Path(__file__).with_name('_paths.py')))['WORK']
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon);addon.register()
from metamorphosis import body_converter,body_refine,body_remap,body_snap
bpy.ops.wm.open_mainfile(filepath='F:/AI/Training_Data/Body Rig/New_Update_Body_Rig.blend',load_ui=False,use_scripts=False)
rig=bpy.data.objects['METAHUMAN_BODY_RIG'];bpy.context.view_layer.objects.active=rig;rig.select_set(True)
old_custom=set(json.loads(rig['mm_body_custom_bones']))
native=set(rig.data.bones.keys())-old_custom
assert len(native)==342
original={n:(rig.data.bones[n].matrix_local.copy(),rig.data.bones[n].parent.name if rig.data.bones[n].parent else None) for n in native}
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
weights={o.name:[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices] for o in meshes}
def update():rig.update_tag();bpy.context.view_layer.update()
def skin():
    dg=bpy.context.evaluated_depsgraph_get()
    return np.concatenate([np.asarray([v.co[:] for v in o.evaluated_get(dg).data.vertices]) for o in meshes])
update();baseline=skin()
assert bpy.ops.metamorphosis.convert_body()=={'FINISHED'}
pb=rig.pose.bones;custom=set(json.loads(rig['mm_body_custom_bones']))
assert rig['mm_body_converter']=='NATIVE_BRIDGE_2'
assert native<=set(pb.keys()) and len(pb)==565 and len(custom)==223
assert not any(n.startswith(('DEF_','COR_','ORG_COR_')) for n in custom)
assert not any(n in pb for n in ('ROOT_02','ORG_CHEST','ORG_NECK','MCH_PIVOT'))
assert {'TORSO','HIPS','CHEST','MCH_SPINE_01','MCH_SPINE_02'}<=custom
for n,(matrix,parent) in original.items():
    assert max(abs(x-y) for ra,rb in zip(matrix,rig.data.bones[n].matrix_local) for x,y in zip(ra,rb))<1e-6
    assert (rig.data.bones[n].parent.name if rig.data.bones[n].parent else None)==parent
for o in meshes:assert weights[o.name]==[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices]
update();assert np.max(np.abs(skin()-baseline))<1e-5
def matrix_error(a,b):return max(abs(x-y) for ra,rb in zip(a,b) for x,y in zip(ra,rb))
rest=max(matrix_error(p.matrix,p.bone.matrix_local) for p in pb)
assert rest<=1e-5,rest
for owner in list(bpy.data.objects)+list(bpy.data.meshes):
    if owner.animation_data:assert all(f.driver.is_valid for f in owner.animation_data.drivers),owner.name
for p in pb:
    for c in p.constraints:
        if c.type=='ARMATURE':assert all(t.target==rig and t.subtarget in pb for t in c.targets)
        if hasattr(c,'target'):assert c.target==rig and c.subtarget in pb,(p.name,c.name)
print('BODY_FIX_STRUCTURE',len(pb),'rest',rest,'skin',float(np.max(np.abs(skin()-baseline))),flush=True)

def reset():
    for n in custom:
        pb[n].matrix_basis=Matrix.Identity(4)
        pb[n].rotation_mode='XYZ'
    for side in 'LR':
        for limb in ('ARM','LEG'):
            for key in ('FK_IK','IK_STRETCH','IK_PARENTS'):pb['PROPERTIES'][limb+'_'+key+'.'+side]=0
    update()
def angle(name):return math.degrees((pb[name].matrix@pb[name].bone.matrix_local.inverted()).to_quaternion().angle)
reset();pb['TORSO'].rotation_euler.x=math.radians(40);update()
assert abs(angle('pelvis')-40)<.002 and abs(angle('spine_05')-40)<.002
reset();pb['HIPS'].rotation_euler.x=math.radians(30);update()
assert abs(angle('pelvis')-30)<.002 and angle('spine_01')<.002 and angle('upperarm_l')<.002
assert matrix_error(pb['thigh_l'].matrix,pb['thigh_l'].bone.matrix_local)>.05
reset();pb['CHEST'].rotation_euler.x=math.radians(40);update()
angles=[angle(f'spine_{i:02}') for i in range(1,6)]
assert max(abs(v-i*8) for i,v in enumerate(angles,1))<.01,angles
print('BODY_FIX_SPINE_PITCH',angles,flush=True)
reset();pb['CHEST'].rotation_mode='QUATERNION'
pb['CHEST'].rotation_quaternion=(math.cos(math.radians(20)),math.sin(math.radians(20)),0,0);update()
angles=[angle(f'spine_{i:02}') for i in range(1,6)]
assert max(abs(v-i*8) for i,v in enumerate(angles,1))<.01,angles
assert all(pb['CHEST'].lock_location) and all(pb['CHEST'].lock_scale)
reset();pb['CHEST'].rotation_euler.y=math.radians(45);update()
angles=[angle(f'spine_{i:02}') for i in range(1,6)]
assert all(1<a<46 for a in angles) and angles[-1]>43,angles
print('BODY_FIX_SPINE_TWIST',angles,flush=True)
for fk in ('SPINE_01_FK','SPINE_02_FK'):
    reset();pb[fk].rotation_euler.x=math.radians(45);update()
    assert (pb['CHEST'].head-pb['SPINE_03_FK'].head).length<1e-5,(fk,pb['CHEST'].head,pb['SPINE_03_FK'].head)
for i in range(1,6):
    reset();pb[f'SPINE_{i:02}_FK'].rotation_euler.x=.2;update()
    assert abs(angle(f'spine_{i:02}')-math.degrees(.2))<.005
    if i>1:assert angle(f'spine_{i-1:02}')<.002
reset();pb['NECK_02_FK'].rotation_euler.x=.3;update()
assert angle('neck_01')<.002 and abs(angle('neck_02')-math.degrees(.3))<.005

pairs=[n for n in custom if n.endswith('.L') and n.startswith(('THUMB_','FINGER_','HAND_SIDE_OPEN','MCH_FINGER_','TOE_A_','TOE_B_','TOE_C_','TOE_D_','TOE_E_'))]
reflection=Matrix.Diagonal((-1,1,1))
for n in pairs:
    a=pb[n].bone.matrix_local.to_3x3();b=pb[n[:-2]+'.R'].bone.matrix_local.to_3x3()
    dots=[(reflection@a.col[i]).dot(b.col[i]) for i in range(3)]
    assert max(abs(x-y) for x,y in zip(dots,(-1,1,1)))<1e-5,(n,dots)
# Compare real skinned fingertips/toes, allowing the native palm correctives
# to retain their authored bilateral differences. Match neutral coordinates.
reset();tree=kdtree.KDTree(len(baseline))
for i,v in enumerate(baseline):tree.insert(v,i)
tree.balance();tip_indices=set();offset=0
terminal={f'{digit}_{segment:02}_l' for digit,segment in
          [('thumb',3),('index',3),('middle',3),('ring',3),('pinky',3)]+
          [(digit,i) for digit in ('bigtoe','indextoe','middletoe','ringtoe','littletoe') for i in (1,2)]}
for mesh in meshes:
    groups={g.index for g in mesh.vertex_groups if g.name in terminal}
    for v in mesh.data.vertices:
        if sum(g.weight for g in v.groups if g.group in groups)>.5:tip_indices.add(offset+v.index)
    offset+=len(mesh.data.vertices)
matched=[]
for i in tip_indices:
    v=baseline[i];_,j,d=tree.find((-v[0],v[1],v[2]))
    if d<.0001:matched.append((i,j))
matched=np.asarray(matched);assert len(matched)>100
mirror_error=0
for n in pairs:
    if n.startswith('MCH_'):continue
    reset();pb[n].rotation_euler.z=math.pi/4;pb[n[:-2]+'.R'].rotation_euler.z=-math.pi/4;update()
    assert (reflection@pb[n].tail-pb[n[:-2]+'.R'].tail).length<.0005,n
    delta=skin()-baseline
    assert np.isfinite(delta).all()
    error=float(np.linalg.norm(delta[matched[:,0]]*np.array((-1,1,1))-delta[matched[:,1]],axis=1).max())
    mirror_error=max(mirror_error,error);assert error<.0005,(n,error)
print('BODY_FIX_SKIN_TIP_MIRROR',len(matched),mirror_error,flush=True)
# Mirror direction alone is insufficient: curls must bend down, not sideways.
for n in ('FINGER_A_02','THUMB_02')+tuple(f'TOE_{c}_{i:02}' for c in 'ABCDE' for i in (1,2)):
    reset();before={side:pb[n+'.'+side].tail.copy() for side in 'LR'}
    for side,value in (('L',math.pi/4),('R',-math.pi/4)):
        pb[n+'.'+side].rotation_euler.z=value
    update()
    for side in 'LR':assert pb[n+'.'+side].tail.z-before[side].z < -.001,(n,side)
print('BODY_FIX_MIRROR_PAIRS',len(pairs),flush=True)
reset()
for side,sign in (('L',1),('R',-1)):
    pb['HAND_SIDE_OPEN.'+side].rotation_euler.z=sign*math.radians(30)
update()
for side in 'LR':
    for letter,degrees in (('B',9),('C',18)):
        assert abs(angle(f'MCH_FINGER_{letter}_01.{side}')-degrees)<.005

def twist_fraction():
    a=pb['upperarm_l'].head;b=pb['lowerarm_l'].head;c=pb['upperarm_twistCor_02_l'].head
    return (c-a).dot(b-a)/(b-a).length_squared
reset();assert abs(twist_fraction()-.67)<.0001
for letter,digit in zip('ABCDE',('bigtoe','indextoe','middletoe','ringtoe','littletoe')):
    for i in (1,2):
        for side in 'LR':
            n=f'TOE_{letter}_{i:02}.{side}';orig=f'{digit}_{i:02}_{side.lower()}'
            assert not pb[n].constraints
            reset();before=pb[orig].matrix.copy();pb[n].rotation_euler.z=.3;update()
            assert matrix_error(before,pb[orig].matrix)>.05
            assert np.max(np.abs(skin()-baseline))>1e-5

for side in 'LR':
    for limb,endpoint,org in (('ARM','HAND_IK','ORG_ARM'),('LEG','FOOT_IK','ORG_THIGH')):
        reset();pb['PROPERTIES'][limb+'_FK_IK.'+side]=1;pb['PROPERTIES'][limb+'_IK_STRETCH.'+side]=1
        pb[endpoint+'.'+side].location.x=.3;update()
        scale=pb[org+'.'+side].matrix.to_scale()
        if limb=='ARM' and side=='L':assert abs(twist_fraction()-.67)<.0001
        assert abs(scale.x-1)<.01 and abs(scale.z-1)<.01,(limb,side,scale[:])
        assert np.isfinite(skin()).all()
        print('BODY_FIX_STRETCH',limb,side,scale[:],flush=True)

reset()
for p in pb:
    if p.name in custom and 'TWEAK' in p.name and not p.name.startswith('MCH_'):
        if p.name.startswith(('HEAD','NECK')):continue # body fixture has no weighted head
        p.location.x=.005;update()
        assert np.max(np.abs(skin()-baseline))>1e-6,p.name
        p.location.x=0;update()
    if p.custom_shape:
        assert p.name in custom and [c for c in p.bone.collections if c.name not in ('MCH','ORG','DEF_BODY','DEF_MH_COR')],p.name
widgets=[c for c in bpy.data.collections if c.name.startswith(rig.name+'_WIDGETS')]
assert len(widgets)==1 and widgets[0].name==rig.name+'_WIDGETS' and widgets[0].hide_viewport and widgets[0].hide_render
used={p.custom_shape for p in pb if p.custom_shape}
assert set(widgets[0].objects)==used and not any(o.name.endswith('.001') for o in used)
assert not {'ACC','ACC_TWK','DEF_HEAD','TORSO_MUSCLE','ARM_MUSCLES.L','ARM_MUSCLES.R','SPINE_TWEAK','TORSO_TWK'}&set(rig.data.collections_all.keys())
assert {b.name for b in rig.data.collections['SPINE_FK'].bones}=={f'SPINE_{i:02}_FK' for i in range(1,5)}
assert [c.name for c in rig.data.bones['SPINE_05_FK'].collections]==['MCH'] and pb['SPINE_05_FK'].custom_shape is None
assert (rig.data.bones['SPINE_04_FK'].tail_local-rig.data.bones['NECK_01_FK'].head_local).length<1e-6
for tname in ('PELVIS_TWEAK','NECK_01_TWEAK','NECK_02_TWEAK','HEAD_TWEAK','HEAD_TIP_TWEAK',*(f'SPINE_{i:02}_TWEAK' for i in range(1,6))):
    assert [c.name for c in rig.data.bones[tname].collections]==['MCH'] and pb[tname].custom_shape is None,tname
assert {'TORSO','HIPS','CHEST','NECK_01_FK','NECK_02_FK'}<=set(rig.data.collections['TORSO'].bones.keys())
assert abs(rig.data.bones['TORSO'].length-.175)<1e-5
assert rig.show_in_front is False and rig.display_type=='SOLID' and all(not b.show_wire for b in rig.data.bones)
for vname in ('VIS_ARM_IK_POLE.L','VIS_ARM_IK_POLE.R','VIS_LEG_IK_POLE.L','VIS_LEG_IK_POLE.R'):
    assert pb[vname].custom_shape is not None and rig.data.bones[vname].hide_select,vname
for s in 'LR':
    assert rig.data.bones['VIS_ARM_IK_POLE.'+s].parent.name == 'MCH_SWITCH_ARM.'+s
    assert rig.data.bones['VIS_LEG_IK_POLE.'+s].parent.name == 'MCH_SWITCH_THIGH.'+s
assert pb['FOOT_TWEAK.L'].bone.length>=.07 and pb['THIGH_TWEAK.L'].bone.length>=.09 and pb['SPINE_01_TWEAK'].bone.length>=.055
visible={c.name for c in body_snap.visible_collections(rig)}
assert {'TOE.L','TOE.R','SPINE_FK'}<=visible
assert not any(n.startswith(('DEF','ORG','MCH')) for n in visible)
assert not any('ARM_BICEP_FLEXTION' in k for k in pb['PROPERTIES'].keys())
# Verify FK Y-axis twist and IK pole twist actually drive the upper arm and thigh.
for fk,defb,side in (('ARM_FK','upperarm','L'),('ARM_FK','upperarm','R'),('THIGH_FK','thigh','L'),('THIGH_FK','thigh','R')):
    reset();pb[fk+'.'+side].rotation_euler.y=math.radians(50);update()
    deg=math.degrees((pb[defb+'_'+side.lower()].bone.matrix_local.inverted()@pb[defb+'_'+side.lower()].matrix).to_quaternion().angle)
    assert deg>45,(fk,side,deg)
for pole,prop,defb in (('ARM_IK_POLE','ARM_FK_IK','upperarm'),('LEG_IK_POLE','LEG_FK_IK','thigh')):
    for side in 'LR':
        reset();pb['PROPERTIES'][prop+'.'+side]=1;pb[pole+'.'+side].location.x=.25;update()
        deg=math.degrees((pb[defb+'_'+side.lower()].bone.matrix_local.inverted()@pb[defb+'_'+side.lower()].matrix).to_quaternion().angle)
        assert deg>15,(pole,side,deg)
reset()
# Verify hand/digit colors and viewport selection/active highlight contrast.
for side,rgb in (('L',body_refine.BLUE),('R',body_refine.RED)):
    for n in [f'FINGER_{c}_{i:02}.{side}' for c in 'ABCD' for i in range(1,5)]+[f'THUMB_{i:02}.{side}' for i in (2,3)]:
        assert max(abs(a-b) for a,b in zip(pb[n].color.custom.normal,rgb))<1e-5,(n,pb[n].color.custom.normal[:])
for p in pb:
    if any(c.is_visible for c in p.bone.collections) and p.color.palette=='CUSTOM':
        assert tuple(p.color.custom.select)!=tuple(p.color.custom.normal),p.name
        assert tuple(p.color.custom.active)!=tuple(p.color.custom.select),p.name
# Reverse-foot MCH_TOE constraint must be active in IK so toes hold the floor.
for side in 'LR':
    c=next(c for c in pb['MCH_TOE.'+side].constraints if c.type=='COPY_ROTATION')
    assert not c.mute
    reset();pb['PROPERTIES']['LEG_FK_IK.'+side]=1;pb['HEEL.'+side].rotation_euler.x=math.radians(45);update()
    assert c.influence==1.0 and 28<angle('ORG_TOE.'+side)<38,(side,c.influence,angle('ORG_TOE.'+side))
# Parent-space slots must target distinct anchors across Torso vs Hips vs Chest vs Head.
for side in 'LR':
    for limb,owners,slots,bone in (
        ('ARM',('MCH_HAND_IK','MCH_ARM_IK_POLE'),5,'HAND_IK'),
        ('LEG',('MCH_PARENTS_FOOT_IK','MCH_PARENTS_LEG_IK_POLE'),4,'FOOT_IK')):
        poses=[]
        for slot in range(slots):
            reset();pb['PROPERTIES'][limb+'_FK_IK.'+side]=1;pb['PROPERTIES'][limb+'_IK_PARENTS.'+side]=slot
            pb['TORSO'].location.x=.03;pb['HIPS'].rotation_euler.x=.35;pb['CHEST'].rotation_euler.x=.25;pb['HEAD'].rotation_euler.z=.3
            if limb=='LEG' and slot==1:pb['FOOT_IK.'+side].location.y=.04
            update()
            for owner in owners:
                c=next(c for c in pb[owner+'.'+side].constraints if c.type=='ARMATURE')
                assert abs(sum(t.weight for t in c.targets)-1)<1e-6
                assert all(t.subtarget in pb for t in c.targets)
            poses.append(pb[('LEG_IK_POLE' if limb=='LEG' else bone)+'.'+side].parent.matrix.copy())
            for n,target in body_converter.bridge_map().items():
                expected=pb[target].matrix @ pb[target].bone.matrix_local.inverted() @ pb[n].bone.matrix_local
                assert matrix_error(expected,pb[n].matrix)<1e-5,(limb,side,slot,n)
        for i in range(len(poses)):
            for j in range(i+1,len(poses)):
                assert matrix_error(poses[i],poses[j])>1e-3,(limb,side,i,j)
try:
    body_remap.remap(rig)
    raise AssertionError('DEF-only remap should be rejected on NATIVE_BRIDGE_2')
except ValueError:
    pass
# Matching must not change hidden IK lock state, including custom user locks.
for limb,lower in (('ARM','FOREARM'),('LEG','SHIN')):
    for side in 'LR':
        reset();b=pb['MCH_IK_'+lower+'.'+side]
        b.lock_ik_x=True;b.lock_ik_y=True
        pb[lower+'_FK.'+side].rotation_euler.z=.6;update()
        before=(b.lock_ik_x,b.lock_ik_y,b.lock_ik_z)
        body_snap.snap(rig,limb,side,'IK',bpy.context)
        assert (b.lock_ik_x,b.lock_ik_y,b.lock_ik_z)==before
        body_snap.snap(rig,limb,side,'FK',bpy.context)
        assert (b.lock_ik_x,b.lock_ik_y,b.lock_ik_z)==before
        b.lock_ik_x=False;b.lock_ik_y=False
reset();bpy.ops.wm.save_as_mainfile(filepath=str(WORK/'body_fixes_verified.blend'))
addon.unregister()
bpy.ops.wm.open_mainfile(filepath=str(WORK/'body_fixes_verified.blend'),load_ui=False,use_scripts=False)
print('BODY_FIX_REPORT_PASS',flush=True)
