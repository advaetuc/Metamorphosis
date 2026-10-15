"""Verify the matrix field in Blender's render depsgraph with hidden helpers.

Pass a native-sums .blend from blender_native_sums.py after --. This validation
handler only reads results; the add-on is never registered during rendering.
"""
import importlib.util
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py',
                                             submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bake, bakeplan, dnaio, native_sums, optimize, pipeline, verify
from metamorphosis.logicmodel import RigLogicModel

bpy.ops.wm.open_mainfile(filepath=sys.argv[sys.argv.index('--')+1])
rig = bake.find_baked_rig(bpy.context); board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
reader = dnaio.open_reader(Path(rig[bake.RIG_KEY_DNA])); model = RigLogicModel.from_reader(reader)
_, rl, _ = dnaio.load_bindings('')
verified = verify.verify_model(model, rl, reader, release=dnaio.release_handle); assert verified.ok
degrees, _ = dnaio.unit_flags(reader); scale = rig[bake.RIG_KEY_SCALE]
budget = list(pipeline.QUALITY['LITE'][0]); budget[0] *= scale/.01
plan = bakeplan.build_plan(model, verified.variant,
    bakeplan.joint_orientation_inverse(reader, model.joint_count, degrees), scale=scale,
    rotation_degrees=degrees, budget=tuple(budget), use_psd=False,
    face_board_bones=set(rig[bake.RIG_KEY_BOARD].split('\n')),
    skip_bones=pipeline.unneeded_bones(model, pipeline.weighted_bones(bake.head_meshes(rig))))
optimize.optimize_plan(plan); plan = native_sums.prepare_plan(plan)
helpers = [bpy.data.objects[n] for n in rig[bake.RIG_KEY_DATA].split('\n')]
output = next(h for h in helpers if h.modifiers)
board.animation_data_create(); board.animation_data.action = None
control = board.pose.bones['CTRL_L_mouth_cornerPull']
for frame, value in ((1, 0.), (2, 1.)):
    control.location.y = value; control.keyframe_insert('location', index=1, frame=frame)
scene = bpy.context.scene
camera = bpy.data.objects.new('TEST_CAMERA', bpy.data.cameras.new('TEST_CAMERA'))
scene.collection.objects.link(camera); camera.location = (0, -1, 1.5)
camera.rotation_euler = (1.57079632679, 0, 0); scene.camera = camera
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = scene.render.resolution_y = 32
scene.render.resolution_percentage = 100
scene.frame_start, scene.frame_end = 1, 2
scene.render.filepath = str(ROOT/'work'/'native_sum_render'/'frame_')
seen, failures = set(), []
def check(scene, graph):
    if graph.mode != 'RENDER': return
    try:
        props = {key:float(holder.evaluated_get(graph)['mm_values'][i])
                 for holder, group in zip(helpers, bake.helper_groups(plan))
                 for i,key in enumerate(group)}
        expected = {target:sum(w*(1. if key is None else props[key]) for key,w in terms)
                    for target,terms in plan.linear_channels}
        mesh = output.evaluated_get(graph).data
        field_error = max(abs(mesh.vertices[i].co.x/10000-expected[t])
                          for i,(t,_) in enumerate(plan.linear_channels))
        pose = rig.evaluated_get(graph).pose
        bone_error = max(abs(getattr(pose.bones[t[1]],t[2])[t[3]]-v) for t,v in expected.items())
        assert field_error < 3e-6 and bone_error < 1.05e-4, (field_error,bone_error)
        assert abs(board.evaluated_get(graph).pose.bones[control.name].location.y-(scene.frame_current-1)) < 1e-6
        seen.add(scene.frame_current)
    except Exception as error:
        failures.append(repr(error))
bpy.app.handlers.frame_change_post.append(check)
try:
    bpy.ops.render.render(animation=True)
finally:
    bpy.app.handlers.frame_change_post.remove(check)
assert seen == {1,2} and not failures, (seen,failures)
dnaio.release_handle(reader)
print('NATIVE_SUMS_RENDER_PASS',bpy.app.version_string,flush=True)
