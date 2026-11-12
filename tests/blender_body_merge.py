"""Combined body/face rig, rebuild isolation, standalone playback and cleanup."""
import importlib.util,sys,time
from pathlib import Path
WORK = __import__("runpy").run_path(str(Path(__file__).with_name("_paths.py")))["WORK"]
import bpy,numpy as np
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',root/'__init__.py',submodule_search_locations=[str(root)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
addon.register()
from metamorphosis import bake,body_merge,cleanup,mocap
assert bpy.ops.metamorphosis.import_body(filepath=r'F:\Project_Files\Metahumans\MH_John_Rambo\body.dna')=={'FINISHED'}
body=next(o for o in bpy.context.scene.objects if o.get('mm_body_rig'))
assert body.show_in_front is False
assert 'ARMATURE' not in bpy.data.collections and 'HEAD' not in bpy.data.collections
assert bpy.ops.metamorphosis.import_dna(filepath=r'F:\Project_Files\Metahumans\MH_Logan\head.dna',join_face_board=True)=={'FINISHED'}
assert 'ARMATURE' in bpy.data.collections and 'HEAD' in bpy.data.collections
assert not any(c.name.startswith(('ARMATURE.','HEAD.')) for c in bpy.data.collections)
head=bake.find_baked_rig(bpy.context)
try:
    body_merge.merge(bpy.context,body,head)
    raise AssertionError('Should require Build Control Rig before merging head and body')
except ValueError:
    pass
bpy.context.view_layer.objects.active=body;body.select_set(True);head.select_set(False)
assert bpy.ops.metamorphosis.convert_body()=={'FINISHED'}
meshes=[o for o in bpy.context.scene.objects if o.get('mm_head_mesh') or o.get('mm_body_mesh')]
def geometry():
    bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get()
    return {o.name:np.asarray([v.co[:] for v in o.evaluated_get(dg).data.vertices]) for o in meshes}
before=geometry()
body,board=body_merge.merge(bpy.context,body,head)
assert all(len(c.bones) for c in body.data.collections_all)
assert not body.data.collections['DEF_HEAD'].is_visible
after=geometry()
error=max(float(np.max(np.abs(before[n]-after[n]))) for n in before)
print('BODY_MERGE_NEUTRAL',error,flush=True);assert error<1e-5,error
assert board!=body and all(n in board.pose.bones for n in body[bake.RIG_KEY_BOARD].split('\n'))
assert mocap.has_capture_controls(board)
assert len([o for o in bpy.context.scene.objects if o.type=='ARMATURE'])==2
assert not bake.validate_rig(body)['invalid'],bake.validate_rig(body)
board.pose.bones['CTRL_C_jaw'].location.y=.6
board.update_tag();facepose=geometry()
assert max(float(np.max(np.abs(facepose[n]-before[n]))) for n in before)>.001
body_driver_count=len(body.animation_data.drivers)
bpy.context.view_layer.objects.active=body
assert bpy.ops.metamorphosis.rebuild()=={'FINISHED'}
rebuild=geometry();error=max(float(np.max(np.abs(facepose[n]-rebuild[n]))) for n in before)
print('BODY_MERGE_REBUILD',error,flush=True);assert error<1e-5,error
assert len(body.animation_data.drivers)==body_driver_count
world=board.matrix_world.copy()
body.pose.bones['HEAD'].rotation_mode='XYZ';body.pose.bones['HEAD'].rotation_euler.z=.3
body.update_tag();geometry()
assert max(abs(a-b) for ra,rb in zip(world,board.matrix_world) for a,b in zip(ra,rb))>.1
times=[]
controls=[b for b in board.pose.bones if b.name.startswith('CTRL_') and ('mouth' in b.name or 'jaw' in b.name)]
poses=np.random.default_rng(190).uniform(0,1,(32,len(controls)))
for pose in poses:
    for bone,value in zip(controls,pose):bone.location.y=float(value)
    board.update_tag();started=time.perf_counter();bpy.context.view_layer.update();times.append((time.perf_counter()-started)*1000)
print('BODY_MERGE_FACE_MEDIAN_MS',float(np.median(times)),len(controls),'moving controls',flush=True)
for frame in (1,10):
    board.pose.bones['CTRL_C_jaw'].location.y=frame*.07
    board.pose.bones['CTRL_C_jaw'].keyframe_insert('location',frame=frame)
    body.pose.bones['ARM_FK.L'].rotation_mode='XYZ'
    body.pose.bones['ARM_FK.L'].rotation_euler.z=frame*.03
    body.pose.bones['ARM_FK.L'].keyframe_insert('rotation_euler',frame=frame)
expected={}
for frame in (1,5,10):bpy.context.scene.frame_set(frame);expected[frame]=geometry()
bpy.ops.wm.save_as_mainfile(filepath=str(WORK/'body_merge190.blend'))
addon.unregister()
bpy.ops.wm.open_mainfile(filepath=str(WORK/'body_merge190.blend'),load_ui=False,use_scripts=False)
meshes=[bpy.data.objects[n] for n in before]
for frame in (1,5,10):
    bpy.context.scene.frame_set(frame);actual=geometry()
    error=max(float(np.max(np.abs(actual[n]-expected[frame][n]))) for n in before)
    assert error<1e-6,(frame,error)
print('BODY_MERGE_STANDALONE_PASS',flush=True)
cube=bpy.data.objects.get('Cube');cleanup.remove_all(bpy.context)
assert not any(o.get('mm_import_id') for o in bpy.context.scene.objects)
assert cube is not None and cube.name in bpy.context.scene.objects
print('BODY_MERGE_CLEANUP_PASS',flush=True)
