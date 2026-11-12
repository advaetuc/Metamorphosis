"""Section 6 checks. Run against a saved converted .blend with factory startup.

Usage: blender --factory-startup -b converted.blend --python-exit-code 1
       --python tests/verify_body_converter.py
"""
import importlib.util
import json
import math
import sys
import time
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix,Vector

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import body_converter,body_snap

rig=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE' and o.get('mm_body_converter'))
bpy.context.view_layer.objects.active=rig;rig.select_set(True)
pb=rig.pose.bones
custom=set(json.loads(rig['mm_body_custom_bones']))
native=rig['mm_body_converter'].startswith('NATIVE')
refined=rig['mm_body_converter']=='NATIVE_BRIDGE_2'
assert len(custom)==(223 if refined else 454)
assert len(rig.data.bones)==(565 if refined else 796 if native else 461)
assert rig.data.get('rig_id')==body_converter.RIG_ID
if refined:
    collections={'PROPERTIES','ROOT','TORSO','SPINE_FK','TOE.L','TOE.R','MCH','ORG','DEF_BODY','DEF_MH_COR'}
    collections|={n+'.'+side for side in 'LR' for n in ('ARM_IK','ARM_FK','ARM_TWK','HAND','LEG_IK','LEG_FK','LEG_TWK')}
    assert collections==set(rig.data.collections_all.keys()),set(rig.data.collections_all.keys())^collections
    assert all(not rig.data.collections[n].is_visible for n in ('MCH','ORG','DEF_BODY','DEF_MH_COR'))
    assert [c.name for c in rig.data.bones['SPINE_05_FK'].collections]==['MCH']
    for tname in ('PELVIS_TWEAK','NECK_01_TWEAK','NECK_02_TWEAK','HEAD_TWEAK','HEAD_TIP_TWEAK',*(f'SPINE_{i:02}_TWEAK' for i in range(1,6))):
        assert [c.name for c in rig.data.bones[tname].collections]==['MCH'],tname
        assert pb[tname].custom_shape is None,tname
    assert abs(rig.data.bones['TORSO'].length-.175)<1e-5,rig.data.bones['TORSO'].length
    trot=rig.data.bones['TORSO'].matrix_local.to_3x3()
    assert (trot@Vector((0,1,0))-Vector((0,1,0))).length<1e-5
    assert (trot@Vector((0,0,1))-Vector((0,0,1))).length<1e-5
    for vname in ('VIS_ARM_IK_POLE.L','VIS_ARM_IK_POLE.R','VIS_LEG_IK_POLE.L','VIS_LEG_IK_POLE.R'):
        assert vname in rig.data.bones and pb[vname].custom_shape is not None and rig.data.bones[vname].hide_select,vname
    for s in 'LR':
        assert rig.data.bones['VIS_ARM_IK_POLE.'+s].parent.name == 'MCH_SWITCH_ARM.'+s
        assert rig.data.bones['VIS_LEG_IK_POLE.'+s].parent.name == 'MCH_SWITCH_THIGH.'+s
    assert rig.show_in_front is False
    if rig.get('mm_body_shape_preset','UNREAL')=='UNREAL':
        assert rig.display_type=='SOLID' and all(not b.show_wire for b in rig.data.bones)
    else:
        assert rig.display_type=='WIRE' and all(abs(p.custom_shape_wire_width-1.0)<1e-5 for p in pb if p.custom_shape)
    assert (rig.data.bones['SPINE_04_FK'].tail_local-rig.data.bones['NECK_01_FK'].head_local).length<1e-6
else:
    collections={'PROPERTIES','ROOT','TORSO','TORSO_FK','TORSO_TWK','TORSO_MUSCLE','ACC','ACC_TWK','MCH','ORG','DEF','DEF_COR','DEF_HEAD','DEF_BODY'}
    collections|={n+'.'+s for s in 'LR' for n in ('ARM_IK','ARM_FK','ARM_TWK','ARM_MUSCLES','HAND','LEG_IK','LEG_FK','LEG_TWK')}
    assert len(collections)==30
    assert collections<=set(rig.data.collections_all.keys())
    assert all(not rig.data.collections[n].is_visible for n in ('MCH','ORG','DEF','DEF_COR','DEF_HEAD','DEF_BODY'))

def reset():
    for p in pb:
        if p.name in custom:p.matrix_basis=Matrix.Identity(4)
    for side in 'LR':
        for limb in ('ARM','LEG'):
            pb['PROPERTIES'][limb+'_FK_IK.'+side]=0
            pb['PROPERTIES'][limb+'_IK_PARENTS.'+side]=0
    rig.update_tag();bpy.context.view_layer.update()

reset()
def error(a,b):return max(abs(x-y) for ra,rb in zip(a,b) for x,y in zip(ra,rb))
rest=max(error(p.matrix,p.bone.matrix_local) for p in pb)
# Float32 Stretch-To and Copy-Rotation stacks on the custom thigh chain
# accumulate up to 3e-5 matrix error. Original DNA bones remain below 1e-5.
# Do not weaken the native bridge / skin tolerance to hide a deformation bug.
assert rest<(1e-5 if refined else 5e-5),rest
if native:
    assert max(error(pb[n].matrix,pb[n].bone.matrix_local) for n in body_converter.bridge_map())<1e-5
    assert all(not rig.data.bones[n].use_deform for n in custom)
else:
    assert all(b.use_deform for b in rig.data.bones if any(c.name in ('DEF','DEF_COR') for c in b.collections))
print('SECTION6_REST',rest,flush=True)

for p in pb:
    for c in p.constraints:
        if c.type=='ARMATURE':
            assert all(t.target==rig and t.subtarget in rig.data.bones for t in c.targets),(p.name,c.name)
        elif c.type in ('LIMIT_ROTATION','LIMIT_LOCATION','LIMIT_SCALE'):
            continue  # These bounds have no target by Blender design.
        elif hasattr(c,'target'):
            assert c.target==rig and c.subtarget in rig.data.bones,(p.name,c.name,c.type)
        if c.type=='IK':
            assert c.pole_target==rig and c.pole_subtarget in rig.data.bones and math.isfinite(c.pole_angle)
for owner in list(bpy.data.objects)+list(bpy.data.meshes):
    if owner.animation_data:
        assert all(f.driver.is_valid for f in owner.animation_data.drivers),owner.name
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
def skin():
    dg=bpy.context.evaluated_depsgraph_get()
    result=[]
    for o in meshes:
        pts=np.asarray([v.co[:] for v in o.evaluated_get(dg).data.vertices])
        assert np.isfinite(pts).all()
        assert (pts.max(axis=0)-pts.min(axis=0)).max()>.2
        result.append(pts)
    return result

base=skin();matrix0={n:pb[n].matrix.copy() for n in body_converter.bridge_map() if n in pb}
if native:
    assert len(meshes[0].vertex_groups)==285  # supplied OG LOD0 fixture
    pb['ROOT'].location.x=.1;rig.update_tag();bpy.context.view_layer.update()
    for name,m in matrix0.items():
        delta=pb[name].matrix.translation-m.translation
        assert abs(delta.x-.1)<1e-5 and abs(delta.y)+abs(delta.z)<1e-5,(name,delta)
    reset()
else:
    for obj in meshes:
        old=set(obj['mm_body_original_groups'].splitlines())
        assert not old&set(obj.vertex_groups.keys())
        assert sum(m.type=='ARMATURE' and m.object==rig for m in obj.modifiers)==2
        assert 'DEF_PRESERVE_VOLUME' in obj.vertex_groups
        for v in obj.data.vertices:
            weights=[g.weight for g in v.groups if obj.vertex_groups[g.group].name!='DEF_PRESERVE_VOLUME']
            assert abs(sum(weights)-1)<2e-6

for cls in body_snap.CLASSES:
    if not hasattr(bpy.types,cls.__name__):bpy.utils.register_class(cls)
for limb,names,angle in (('ARM',('ARM','FOREARM','HAND'),90),('LEG',('THIGH','SHIN','FOOT'),120)):
    for side in 'LR':
        reset();S='.'+side
        pb[names[1]+'_FK'+S].rotation_euler.z=math.radians(angle)*(1 if side=='L' else -1)
        rig.update_tag();bpy.context.view_layer.update();skin()
        if native:
            bone=('lowerarm_fwd_' if limb=='ARM' else 'calf_knee_')+side.lower()
            assert error(pb[bone].matrix,pb[bone].bone.matrix_local)>.01
        target=pb['MCH_SWITCH_'+names[-1]+S].matrix.copy()
        forward=getattr(bpy.ops.john_rambo,'ik_fk_'+limb.lower())
        backward=getattr(bpy.ops.john_rambo,'fk_ik_'+limb.lower())
        assert forward(side=side)=={'FINISHED'}
        assert (pb['MCH_SWITCH_'+names[-1]+S].matrix.translation-target.translation).length<1e-3
        assert backward(side=side)=={'FINISHED'}
        assert (pb['MCH_SWITCH_'+names[-1]+S].matrix.translation-target.translation).length<1e-3

for side in 'LR':
    for x,z in [(-30,0),(15,0),(45,0),(80,0),(0,-30),(0,30)]:
        reset();pb['PROPERTIES']['LEG_FK_IK.'+side]=1
        pb['HEEL.'+side].rotation_euler=(math.radians(x),0,math.radians(z))
        rig.update_tag();bpy.context.view_layer.update();skin()
        for name in ('MCH_FOOT_ROLL_01','MCH_FOOT_ROLL_02','MCH_FOOT_SIDE_ROLL_01','MCH_FOOT_SIDE_ROLL_02'):
            bone=pb[name+'.'+side]
            local=rig.convert_space(pose_bone=bone,matrix=bone.matrix,from_space='POSE',to_space='LOCAL').to_euler('XYZ')
            limit=next(c for c in bone.constraints if c.type=='LIMIT_ROTATION')
            for axis in 'xyz':
                if getattr(limit,'use_limit_'+axis):
                    assert getattr(limit,'min_'+axis)-1e-4<=getattr(local,axis)<=getattr(limit,'max_'+axis)+1e-4,(name,x,z,local[:])
reset();times=[]
for i in range(40):
    for n in ('ARM_FK.L','FOREARM_FK.L','THIGH_FK.R','SHIN_FK.R','HAND_FK.R'):
        pb[n].rotation_euler.z=.5*math.sin(i*.2)
    rig.update_tag();start=time.perf_counter();bpy.context.view_layer.update();times.append((time.perf_counter()-start)*1000)
    skin()
print('SECTION6_PASS',rig['mm_body_converter'],'bones',len(pb),'median_ms',float(np.median(times[8:])),flush=True)
