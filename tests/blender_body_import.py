"""Body importer and native corrective validation using the supplied body DNA."""
import importlib.util,sys,time
from pathlib import Path
WORK = __import__("runpy").run_path(str(Path(__file__).with_name("_paths.py")))["WORK"]
import bpy,numpy as np
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',root/'__init__.py',submodule_search_locations=[str(root)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
addon.register()
from metamorphosis import body_rig,dnaio
lod=int(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else 0
assert bpy.ops.metamorphosis.import_body(filepath=r'F:\Project_Files\Metahumans\MH_John_Rambo\body.dna',lod=lod)=={'FINISHED'}
rig=next(o for o in bpy.context.scene.objects if o.get('mm_body_rig'))
assert len(rig.data.bones)==342 and not rig.get('mm_body_converter')
bpy.context.view_layer.objects.active=rig;rig.select_set(True)
assert bpy.ops.metamorphosis.convert_body()=={'FINISHED'}
bpy.context.view_layer.update()
assert not any(c.get('mm_collection_role')=='RIGLOGICDATA' and not c.objects and not c.children for c in bpy.data.collections)
print('BODY_IMPORTED',len(rig.data.bones),rig['mm_body_corrective_drivers'],flush=True)
for obj in bpy.context.scene.objects:
    if obj.animation_data:
        for f in obj.animation_data.drivers:
            assert f.driver.is_valid and f.driver.is_simple_expression,(obj.name,f.data_path,f.driver.expression)
for name in ('ARM_FK.L','HAND_IK.R','TORSO'):
    assert name in rig.pose.bones
matrices={b.name:b.matrix.copy() for b in rig.pose.bones if b.bone.use_deform}
neutral=max(abs(a-b) for p in rig.pose.bones if p.name in matrices for ra,rb in zip(p.matrix,p.bone.matrix_local) for a,b in zip(ra,rb))
print('NEUTRAL_MATRIX_ERROR',neutral,flush=True)
print('WORST_BONES',sorted([(max(abs(a-b) for ra,rb in zip(p.matrix,p.bone.matrix_local) for a,b in zip(ra,rb)),p.name,list(p.location),list(p.scale)) for p in rig.pose.bones if p.name in matrices],reverse=True)[:8],flush=True)
assert neutral<1e-4,neutral
for label,end in (('ARM','hand'),('LEG','foot')):
    for side in ('L','R'):
        rig.pose.bones['PROPERTIES'][f'{label}_FK_IK.{side}']=1
        rig.update_tag();bpy.context.view_layer.update()
        current=rig.pose.bones[end+'_'+side.lower()].matrix
        error=max(abs(a-b) for ra,rb in zip(current,matrices[end+'_'+side.lower()]) for a,b in zip(ra,rb))
        print('IK_REST',label,side,error,flush=True)
        assert error<.001,(label,side,error)
        rig.pose.bones['PROPERTIES'][f'{label}_FK_IK.{side}']=0
        rig.update_tag();bpy.context.view_layer.update()
rig.pose.bones['ARM_FK.L'].rotation_mode='XYZ'
rig.pose.bones['ARM_FK.L'].rotation_euler.z=.5
rig.update_tag();bpy.context.view_layer.update()
assert max(abs(a-b) for ra,rb in zip(rig.pose.bones['upperarm_l'].matrix,matrices['upperarm_l']) for a,b in zip(ra,rb))>.1
print('BODY_FK_PASS',flush=True)
from mathutils import Euler
from metamorphosis import bakeplan
dna,native,_=dnaio.load_bindings('')
reader=dnaio.open_reader(r'F:\Project_Files\Metahumans\MH_John_Rambo\body.dna')
manager=native.RigLogic(reader,native.Configuration(),None)
instance=native.RigInstance(rigLogic=manager,memRes=None)
instance.setLOD(lod)
orientations=bakeplan.joint_orientation_inverse(reader,reader.getJointCount(),True)
raw_names=[str(reader.getRawControlName(i)) for i in range(reader.getRawControlCount())]
outputs={str(reader.getJointName(i)):i for i in range(reader.getJointCount())}
driven={f.data_path.rsplit('.',1)[0] for f in rig.animation_data.drivers if f.data_path.startswith('pose.bones[')}
times=[];worst=0;mesh_worst=0
meshes=[o for o in bpy.context.scene.objects if o.get('mm_body_mesh')]
def vertices():
    dg=bpy.context.evaluated_depsgraph_get()
    return np.concatenate([np.asarray([v.co[:] for v in o.evaluated_get(dg).data.vertices]) for o in meshes])
curves=[f for f in rig.animation_data.drivers if f.data_path.rsplit('.',1)[0] in driven and '.constraints[' not in f.data_path and not f.data_path.endswith('ik_stretch')]
bpy.context.view_layer.objects.active=rig
rig.select_set(True)
for number in range(40):
    for name in ('ARM_FK.L','FOREARM_FK.L','THIGH_FK.R','SHIN_FK.R','HAND_FK.R'):
        pb=rig.pose.bones[name];pb.rotation_mode='XYZ'
        pb.rotation_euler=(.3*np.sin(number*.27),.2*np.cos(number*.17),.3*np.sin(number*.19))
    for side,sign in (('L',1),('R',-1)):
        for name in ('FINGER_B_02','FINGER_B_03','THUMB_02'):
            rig.pose.bones[name+'.'+side].rotation_euler.z=sign*.8*np.sin(number*.13)
    rig.update_tag();started=time.perf_counter();bpy.context.view_layer.update()
    times.append((time.perf_counter()-started)*1000)
    for i,name in enumerate(raw_names):
        bone,axis=name.rsplit('.',1)
        # Blender's evaluated local transform, including the control constraint.
        pb=rig.pose.bones[bone]
        local=rig.convert_space(pose_bone=pb,matrix=pb.matrix,from_space='POSE',to_space='LOCAL')
        quat=local.to_quaternion()
        instance.setRawControl(i,float(getattr(quat,axis[-1].lower())))
    manager.calculate(instance)
    values=np.asarray(list(instance.getJointOutputs())).reshape(-1,9)
    for name,joint in outputs.items():
        pb=rig.pose.bones[name]
        if pb.path_from_id() not in driven:continue
        expected_location=orientations[joint]@values[joint,:3]*.01
        expected_rotation=Euler(tuple(np.radians(values[joint,3:6])),'XYZ').to_quaternion()
        actual_rotation=pb.rotation_quaternion if pb.rotation_mode=='QUATERNION' else pb.rotation_euler.to_quaternion()
        error=max(float(np.max(np.abs(np.asarray(pb.location)-expected_location))),
                  min(max(abs(a-b) for a,b in zip(actual_rotation,expected_rotation)),max(abs(a+b) for a,b in zip(actual_rotation,expected_rotation))),
                  float(np.max(np.abs(np.asarray(pb.scale)-(1+values[joint,6:9])))))
        worst=max(worst,error)
        assert error<.001,(number,name,error)
    if number%8==0:
        actual_mesh=vertices()
        for f in curves:f.mute=True
        for name,joint in outputs.items():
            pb=rig.pose.bones[name]
            if pb.path_from_id() not in driven:continue
            pb.location=orientations[joint]@values[joint,:3]*.01
            rotation=Euler(tuple(np.radians(values[joint,3:6])),'XYZ')
            if pb.rotation_mode=='QUATERNION':pb.rotation_quaternion=rotation.to_quaternion()
            else:pb.rotation_euler=rotation
            pb.scale=1+values[joint,6:9]
        rig.update_tag();bpy.context.view_layer.update()
        error=float(np.max(np.abs(vertices()-actual_mesh)));mesh_worst=max(mesh_worst,error)
        assert error<.0001,(number,error)
        for f in curves:f.mute=False
        rig.update_tag();bpy.context.view_layer.update()
print('BODY_POSED_ORACLE_PASS',worst,'median ms',float(np.median(times)),flush=True)
print('BODY_SKINNED_ORACLE_PASS',mesh_worst,flush=True)
for limb,names in (('ARM',('ARM','FOREARM','HAND')),('LEG',('THIGH','SHIN','FOOT'))):
    for side in ('L','R'):
        for mode in ('IK','FK'):
            before=[rig.pose.bones['MCH_SWITCH_'+n+'.'+side].matrix.copy() for n in names]
            assert bpy.ops.metamorphosis.body_snap(limb=limb,side=side,mode=mode)=={'FINISHED'}
            error=max(abs(a-b) for n,m in zip(names,before) for ra,rb in zip(rig.pose.bones['MCH_SWITCH_'+n+'.'+side].matrix,m) for a,b in zip(ra,rb))
            print('BODY_SNAP',limb,side,mode,error,flush=True)
            if error>.002:
                print('SNAP_DETAILS',[(n,list(m.translation),list(rig.pose.bones['MCH_SWITCH_'+n+'.'+side].matrix.translation)) for n,m in zip(names,before)],flush=True)
            assert error<.002,(limb,side,mode,error)
for h in (instance,manager,reader):dnaio.release_handle(h)
bpy.ops.wm.save_as_mainfile(filepath=str(WORK/'body_import190.blend'))
addon.unregister()
