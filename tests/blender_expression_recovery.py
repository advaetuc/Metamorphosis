"""Expression rollback, missing context, neutral sculpt coexistence and cleanup."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import faulthandler

import bpy
import numpy as np

faulthandler.enable()

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bake, cleanup, dnaio, expression_dna, expression_sculpt as ex, sculpt

scene = sys.argv[sys.argv.index('--')+1]
bpy.ops.wm.open_mainfile(filepath=scene); addon.register()
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE' and o.get(bake.RIG_KEY_DNA))
head = sculpt.head_mesh(rig); board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
if board.animation_data:
    board.animation_data.action = None


def pose(value):
    for b in board.pose.bones:
        if b.name.startswith('CTRL_'):
            b.location = (0, 0, 0)
    board.pose.bones['CTRL_L_mouth_cornerPull'].location.y = value
    board.update_tag(); bpy.context.view_layer.update()
    return ex.evaluated(head)


neutral = pose(0); posed = pose(1)
print('RECOVERY baseline', flush=True)
control = int(next(c[0] for c in ex.choices(rig) if c[1] == 'CTRL_expressions.mouthCornerPullL'))
source = rig[bake.RIG_KEY_DNA]; counts = bake.validate_rig(rig)
base = sculpt.coords(head.data)
reader = dnaio.open_reader(Path(source)); records = expression_dna.records(reader); dnaio.release_handle(reader)
filename = ROOT/'work'/('expression_rollback_'+str(time.time_ns())+'.dna')

# Context can be empty even while the actual view-layer active object exists.
with bpy.context.temp_override(object=None, active_object=None, selected_objects=[], selected_editable_objects=[]):
    print('RECOVERY start override', flush=True)
    work = ex.start(rig, control)
    print('RECOVERY work created', flush=True)
    target = sculpt.coords(work.data); target[100, 1] += .0005
    sculpt.set_coords(work.data, target)
    target = sculpt.coords(work.data)  # Mesh coordinates are stored as float32.
    assert ex.rig_for(bpy.context) == rig
    real_writer = expression_dna.write_residual
    def fail(*args, **kwargs):
        raise ValueError('Injected residual writer failure')
    expression_dna.write_residual = fail
    try:
        try:
            ex.finish(rig, filename)
        except ValueError as error:
            assert 'Injected' in str(error), error
        else:
            raise AssertionError('Injected failure did not abort')
    finally:
        expression_dna.write_residual = real_writer
    assert rig[bake.RIG_KEY_DNA] == source and not filename.exists()
    assert ex.SESSION in rig and np.array_equal(sculpt.coords(work.data), target)
    assert np.max(abs(ex.evaluated(head)-posed)) < 5e-7
    assert bake.validate_rig(rig) == counts
    ex.cancel(rig)
print('RECOVERY rollback passed', flush=True)
assert np.array_equal(sculpt.coords(head.data), base)

# Starting from the original head in Sculpt Mode must not restore that mode
# after hiding it, and must still select the frozen work mesh.
bpy.context.view_layer.objects.active = head; head.select_set(True)
sculpt.set_mode(head, 'SCULPT')
work = ex.start(rig, control)
print('RECOVERY sculpt context passed', flush=True)
assert bpy.context.view_layer.objects.active == work and work.mode == 'OBJECT'
ex.cancel(rig)

# Neutral editing still transports authored keys and equations together.
pose(0); sculpt.start(rig)
sculpt.set_coords(head.data, base*1.01)
sculpt._active.update(force=True)
prepared = ROOT/'work'/('expression_neutral_'+str(time.time_ns())+'.dna')
sculpt.prepare(rig, prepared)
assert np.max(abs(pose(0)-neutral*1.01)) < 2e-6
assert np.max(abs(pose(1)-posed*1.01)) < 1e-4
reader = dnaio.open_reader(prepared)
assert expression_dna.records(reader) == records
dnaio.release_handle(reader)
assert not bpy.app.timers.is_registered(sculpt._tick)

# Normalization also works when capturing a partially activated expression.
neutral = pose(0); pose(.6)
work = ex.start(rig, control)
target = sculpt.coords(work.data); target[150, 1] += .0003
sculpt.set_coords(work.data, target)
ex.finish(rig, ROOT/'work'/('expression_partial_'+str(time.time_ns())+'.dna'))
assert np.max(abs(pose(.6)-target)) < 5e-6
assert np.max(abs(pose(0)-neutral)) < 1e-6
left_only = pose(1)
pose(0); board.pose.bones['CTRL_R_mouth_cornerPull'].location.y = .8
board.update_tag(); bpy.context.view_layer.update()
right = int(next(c[0] for c in ex.choices(rig) if c[1] == 'CTRL_expressions.mouthCornerPullR'))
work = ex.start(rig, right)
target = sculpt.coords(work.data); target[250, 1] += .0003
sculpt.set_coords(work.data, target)
second = ex.finish(rig, ROOT/'work'/('expression_second_'+str(time.time_ns())+'.dna'))
assert np.max(abs(ex.evaluated(head)-target)) < 5e-6
assert np.max(abs(pose(0)-neutral)) < 1e-6
assert np.max(abs(pose(1)-left_only)) < 1e-6
reader = dnaio.open_reader(second)
assert len(expression_dna.records(reader)) == 2
dnaio.release_handle(reader)

# An active expression work copy belongs to its character's scoped cleanup.
work = ex.start(rig, control); work_name = work.name
unrelated = bpy.data.objects.new('USER_KEEP', None); bpy.context.scene.collection.objects.link(unrelated)
assert bpy.ops.metamorphosis.remove_all() == {'FINISHED'}
assert work_name not in bpy.data.objects and 'USER_KEEP' in bpy.data.objects
assert not any(key.get(cleanup.OWNER) for key in bpy.data.shape_keys)
addon.unregister()
print('EXPRESSION_RECOVERY_PASS', bpy.app.version_string, flush=True)
# Blender's Windows shutdown probes trigger the same handled native exceptions
# in an empty factory-startup process; keep diagnostics scoped to this test.
faulthandler.disable()
