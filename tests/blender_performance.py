"""Compare old/new driver performance and native bone accuracy against the DNA model."""
import importlib.util
from pathlib import Path
import statistics
import sys
import time
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
import bpy
import numpy as np
from metamorphosis import bake, bakeplan, pipeline, dnaio, verify
from metamorphosis.logicmodel import RigLogicModel
from metamorphosis.mocap_mapping import face_board_pose
sys.path.insert(0, str(ROOT/'bindings'/'windows'/'x64'/f'py{sys.version_info.major}{sys.version_info.minor}'))
import dna, riglogic
bpy.ops.wm.open_mainfile(filepath=sys.argv[sys.argv.index('--')+1])
addon.register()
rig = bake.find_baked_rig(bpy.context)
board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
# Optional saved 1.0.8 expression compiler permits a same-session comparison
# with both graphs freshly evaluated, rather than relying on saved driver caches.
baseline_file = ROOT/'work'/'exprplan_baseline.py'
current = None
if baseline_file.exists():
    baseline_spec = importlib.util.spec_from_file_location('metamorphosis._baseline_exprplan', baseline_file)
    baseline = importlib.util.module_from_spec(baseline_spec); baseline_spec.loader.exec_module(baseline)
    builder_spec = importlib.util.spec_from_file_location('metamorphosis._baseline_bakeplan', ROOT/'work'/'bakeplan_baseline.py')
    builder = importlib.util.module_from_spec(builder_spec); sys.modules[builder_spec.name] = builder; builder_spec.loader.exec_module(builder)
    builder.fmt_num, builder.plan_sum, builder.plan_prod = baseline.fmt_num, baseline.plan_sum, baseline.plan_prod
    current = pipeline.bakeplan
    pipeline.bakeplan = builder
    assert bpy.ops.metamorphosis.rebuild() == {'FINISHED'}
for bone in board.pose.bones:
    if bone.name.startswith('CTRL_'):
        bone.location = (0,0,0)
poses = [face_board_pose({'jawOpen': i/7, 'mouthClose': (i%3)/2, 'mouthSmileLeft': i/7,
                         'eyeBlinkRight': i%2, 'browDownLeft': (7-i)/7}, extreme=1) for i in range(8)]

def apply(pose):
    for (name,axis), value in pose.items():
        board.pose.bones[name].location[axis] = value
    bpy.context.view_layer.update()

def geometry():
    graph = bpy.context.evaluated_depsgraph_get()
    matrices = np.array([list(row) for p in rig.evaluated_get(graph).pose.bones for row in p.matrix])
    meshes = []
    for mesh in bake.head_meshes(rig):
        evaluated = mesh.evaluated_get(graph)
        data = np.empty(len(evaluated.data.vertices)*3, dtype=np.float32)
        evaluated.data.vertices.foreach_get('co', data)
        meshes.append(data)
    return matrices, np.concatenate(meshes)

def measure():
    for pose in poses:
        apply(pose)
    measurements = []
    for _ in range(5):
        start = time.perf_counter()
        for pose in poses:
            apply(pose)
        measurements.append((time.perf_counter()-start)*1000/len(poses))
    return statistics.median(measurements)

before = []
channels = []
for pose in poses:
    apply(pose); before.append(geometry())
    channels.append(np.array([list(p.location)+list(p.rotation_euler)+list(p.scale) for p in rig.pose.bones]))
old_count = bake.validate_rig(rig)['drivers']
old_ms = measure()
if current:
    pipeline.bakeplan = current
assert bpy.ops.metamorphosis.rebuild() == {'FINISHED'}
new_count = bake.validate_rig(rig)['drivers']
new_ms = measure()
print('TIMING', old_count, new_count, old_ms, new_ms, flush=True)
reader = dnaio.open_reader(Path(rig[bake.RIG_KEY_DNA]))
model = RigLogicModel.from_reader(reader)
verified = verify.verify_model(model, riglogic, reader, release=dnaio.release_handle)
assert verified.ok
orientation = bakeplan.joint_orientation_inverse(reader, model.joint_count, True)
plan = bakeplan.build_plan(model, verified.variant, orientation, use_psd=False,
                           budget=pipeline.QUALITY['LITE'][0],
                           skip_bones=pipeline.unneeded_bones(model, pipeline.weighted_bones(bake.head_meshes(rig))))
bone_index = {p.name: i for i,p in enumerate(rig.pose.bones)}
old_error = new_error = 0
for pose, old_channels in zip(poses,channels):
    apply(pose)
    expected = bakeplan.evaluate_plan(plan, pose)
    for (_, bone, path, axis), value in expected.items():
        attr = {'location':0, 'rotation_euler':3, 'scale':6}[path]+axis
        # Native RNA writes have a small-value/update tolerance around 1e-4.
        # Partial sums must not accumulate additional losses before the final write.
        native_value = value
        actual = getattr(rig.pose.bones[bone], path)[axis]
        old_error = max(old_error, abs(old_channels[bone_index[bone], attr]-native_value))
        new_error = max(new_error, abs(actual-native_value))
assert new_error < 1.01e-4, new_error
assert new_error < old_error, (old_error, new_error)
dnaio.release_handle(reader)
assert new_count < old_count, (old_count, new_count)
print('PERFORMANCE_PASSED', dict(old_drivers=old_count, new_drivers=new_count,
                                before_ms=old_ms, after_ms=new_ms,
                                old_native_error=old_error, new_native_error=new_error), flush=True)
addon.unregister()
