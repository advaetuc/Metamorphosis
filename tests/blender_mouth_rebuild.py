"""Rebuild a saved problem pose, compare native channels, and verify standalone playback.

Arguments: -- scene.blend [render]. Writes only work/ test artifacts.
"""
import importlib.util
from pathlib import Path
import sys
import numpy as np
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import bake,bakeplan,dnaio,verify,pipeline
from metamorphosis.logicmodel import RigLogicModel
args=sys.argv[sys.argv.index('--')+1:]
bpy.ops.wm.open_mainfile(filepath=args[0]);addon.register()
rig=next(o for o in bpy.data.objects if bake.RIG_KEY_DNA in o)
board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
reader=dnaio.open_reader(Path(rig[bake.RIG_KEY_DNA]));model=RigLogicModel.from_reader(reader)
_,rl,_=dnaio.load_bindings('')
verified=verify.verify_model(model,rl,reader,release=dnaio.release_handle);assert verified.ok
degrees,scale=dnaio.unit_flags(reader)
orientation=bakeplan.joint_orientation_inverse(reader,model.joint_count,degrees)
pose=np.array([board.pose.bones[c.bone].location[c.axis] if c.axis>=0 and c.bone in board.pose.bones else 0 for c in model.gui])
oracle=verify.run_oracle(model,rl,reader,np.vstack([np.zeros(len(model.gui)),pose]),
                       np.tile(model.default_raw(),(2,1)),dnaio.release_handle)
expected=(oracle.joints[1]-oracle.joints[0]).reshape(-1,9)
expected[:,:3]=np.einsum('jik,jk->ji',orientation,expected[:,:3])*scale
if degrees:expected[:,3:6]*=np.pi/180
expected[:,6:9]+=1
skip=verify.excluded_joints(model)|{model.joint_names.index(n) for n in pipeline.unneeded_bones(model,pipeline.weighted_bones(bake.head_meshes(rig)))}
def errors():
    bpy.context.view_layer.update()
    worst=np.zeros(3)
    for j,name in enumerate(model.joint_names):
        if j in skip:continue
        bone=rig.pose.bones[name]
        actual=np.array([*bone.location,*bone.rotation_euler,*bone.scale])
        worst=np.maximum(worst,np.abs(actual-expected[j]).reshape(3,3).max(axis=1))
    return worst
def unique_drivers():
    for obj in [rig,*[o for o in bpy.data.objects if o.animation_data and 'mm_values' in o]]:
        if obj.animation_data:
            targets=[(c.data_path,c.array_index) for c in obj.animation_data.drivers]
            assert len(targets)==len(set(targets)),obj.name
def render(name):
    scene=bpy.context.scene
    scene.render.filepath=str(ROOT/'work'/name)
    bpy.ops.render.render(write_still=True)
if 'render' in args:
    head=next(o for o in bake.head_meshes(rig) if o.get('mm_mesh_kind')=='head')
    for o in bpy.data.objects:
        if o.type in {'MESH','CURVE','FONT','SURFACE'} and not o.get('mm_head_mesh'):o.hide_render=True
        if o.type=='LIGHT':o.hide_render=True
    points=[head.matrix_world@Vector(c) for c in head.bound_box]
    low=Vector(tuple(min(p[i] for p in points) for i in range(3)));high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    target=Vector(((low.x+high.x)/2,(low.y+high.y)/2,high.z-.115))
    if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.camera_add(location=target+Vector((.03,-.7,.005)))
    cam=bpy.context.object;cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.type='ORTHO';cam.data.ortho_scale=.34
    scene=bpy.context.scene;scene.camera=cam
    for position,power,size in [((-.3,-.4,.3),18,.35),((.35,-.15,.1),10,.4)]:
        bpy.ops.object.light_add(type='AREA',location=target+Vector(position))
        light=bpy.context.object;light.data.energy=power;light.data.shape='DISK';light.data.size=size
        light.rotation_euler=(target-light.location).to_track_quat('-Z','Y').to_euler()
    scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True
    scene.render.resolution_x=640;scene.render.resolution_y=640;scene.render.resolution_percentage=100
    render('mouth_before.png')
before=errors();unique_drivers()
actions=set(bpy.data.actions)
materials={o.name:tuple(o.data.materials) for o in bake.head_meshes(rig)}
pose_before={b.name:tuple(b.location) for b in board.pose.bones if b.name.startswith('CTRL_')}
old_count=bake.validate_rig(rig)['drivers']
if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.objects.active=rig;rig.select_set(True)
assert bpy.ops.metamorphosis.rebuild()=={'FINISHED'}
after=errors();unique_drivers()
budget=np.array(pipeline.QUALITY['LITE'][0]);budget[0]*=scale/.01
assert np.all(after < budget+1.3e-4),(after,budget)
assert before[0]>.01 and after[0]<before[0]/20,(before,after)
assert actions==set(bpy.data.actions)
assert pose_before=={b.name:tuple(b.location) for b in board.pose.bones if b.name.startswith('CTRL_')}
assert materials=={o.name:tuple(o.data.materials) for o in bake.head_meshes(rig)}
info=bake.validate_rig(rig);assert not info['invalid'] and not info['needs_python'],info
if 'render' in args:render('mouth_after.png')
new_count=info['drivers']
file=ROOT/'work/mouth_corrected.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(file))
dnaio.release_handle(reader)
addon.unregister();bpy.ops.wm.open_mainfile(filepath=str(file))
rig=next(o for o in bpy.data.objects if bake.RIG_KEY_DNA in o);board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
assert np.all(errors()<budget+1.3e-4)
control=board.pose.bones['CTRL_L_mouth_cornerPull'];control.location.y=0
board.update_tag();bpy.context.view_layer.update()
control.location.y=pose_before[control.name][1];board.update_tag();bpy.context.view_layer.update()
assert np.all(errors()<budget+1.3e-4)
print('MOUTH_REBUILD_PASS','before',before.tolist(),'after',after.tolist(),'drivers',old_count,new_count,flush=True)
