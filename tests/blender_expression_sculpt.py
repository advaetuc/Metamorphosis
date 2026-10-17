"""Real posed sculpt, DNA reimport, neutral/other poses, recovery and timing.

Run inside Blender with -- [optional baseline .blend]. Writes only to work/.
"""
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bake, dnaio, dna_export, expression_dna, expression_sculpt as ex, sculpt

args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
scene = Path(args[0]) if args else ROOT/'work/native_sums_mouth_corrected.blend'
prefix = ROOT/'work'/('expression_'+scene.stem+'_'+str(time.time_ns()))
bpy.ops.wm.open_mainfile(filepath=str(scene)); addon.register()
rig = bake.find_baked_rig(bpy.context); head = sculpt.head_mesh(rig)
board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
smile = 'CTRL_L_mouth_cornerPull'


def pose(amount=0., other=0.):
    for bone in board.pose.bones:
        if bone.name.startswith('CTRL_'):
            bone.location = (0, 0, 0)
    board.pose.bones[smile].location.y = amount
    board.pose.bones['CTRL_R_mouth_cornerPull'].location.y = other
    board.update_tag(); bpy.context.view_layer.update()
    return ex.evaluated(head)


def benchmark():
    bones = [b for b in board.pose.bones if b.name.startswith('CTRL_') and ('mouth' in b.name or 'jaw' in b.name)]
    saved = [tuple(b.location) for b in bones]
    samples = []
    try:
        for i in range(70):
            for j, bone in enumerate(bones):
                bone.location.y = .12+.08*np.sin(i*.7+j*.4)
            board.update_tag()
            start = time.perf_counter(); bpy.context.view_layer.update()
            if i >= 10:
                samples.append((time.perf_counter()-start)*1000)
    finally:
        for bone, location in zip(bones, saved):
            bone.location = location
        board.update_tag(); bpy.context.view_layer.update()
    return statistics.median(samples)


def sculpt_target(work, amount=.001):
    base = sculpt.coords(work.data)
    # Use a local face-space point; adapt height for differently sized fixtures.
    guess = np.array([.04, -.095, base[:, 2].max()-.22])
    center = base[np.argmin(np.linalg.norm(base-guess, axis=1))]
    target = base.copy()
    target[:, 1] += amount*np.exp(-np.sum(((base-center)/.012)**2, axis=1))
    sculpt.set_coords(work.data, target)
    return target


def rejects(fn, text):
    try:
        fn()
    except (ValueError, RuntimeError) as error:
        assert text in str(error), str(error)
    else:
        raise AssertionError('Expected rejection: '+text)


source = Path(rig[bake.RIG_KEY_DNA]); original_hash = sculpt.fingerprint(source)
neutral = pose(); unrelated = pose(other=.8); half = pose(.5); before_smile = pose(1.)
rest = {b.name: np.array(b.matrix_local) for b in rig.data.bones}
before_bones = np.array([b.matrix.translation[:] for b in rig.pose.bones if b.name.startswith('FACIAL_')])
before_ms = benchmark(); before_drivers = bake.validate_rig(rig)['drivers']
control = int(next(c[0] for c in ex.choices(rig) if c[1] == 'CTRL_expressions.mouthCornerPullL'))

# Cancel and no-op application must not touch the rig or DNA.
work = ex.start(rig, control)
rejects(lambda: ex.finish(rig, prefix.with_suffix('.dna')), 'No expression sculpt')
sculpt_target(work); ex.cancel(rig)
assert np.array_equal(ex.evaluated(head), before_smile)
assert rig[bake.RIG_KEY_DNA] == str(source)

# Saved sessions retain the frozen sculpt and explicit pose checks.
work = ex.start(rig, control); target = sculpt_target(work)
bpy.ops.wm.save_as_mainfile(filepath=str(prefix.with_suffix('.pending.blend')))
bpy.ops.wm.open_mainfile(filepath=str(prefix.with_suffix('.pending.blend')))
rig = next(o for o in bpy.data.objects if ex.SESSION in o)
head = sculpt.head_mesh(rig); board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
work = bpy.data.objects[json.loads(rig[ex.SESSION])['work']]
pose(.6)
rejects(lambda: ex.finish(rig, prefix.with_suffix('.dna')), 'pose changed')
pose(1.)
mod = work.modifiers.new('Invalid sculpt topology', 'SUBSURF')
rejects(lambda: ex.finish(rig, prefix.with_suffix('.dna')), 'topology changed')
work.modifiers.remove(mod)
# Apply from real Sculpt Mode, including active work-copy lookup.
bpy.context.view_layer.objects.active = work; work.select_set(True)
sculpt.set_mode(work, 'SCULPT')
assert ex.rig_for(bpy.context) == rig
output = ex.finish(rig, prefix.with_suffix('.dna'))
error = float(np.max(abs(ex.evaluated(head)-target)))
assert error < 5e-6, error
after_bones = np.array([b.matrix.translation[:] for b in rig.pose.bones if b.name.startswith('FACIAL_')])
assert np.max(abs(after_bones-before_bones)) > 1e-6, 'No original bones adapted'
assert all(np.array_equal(np.array(b.matrix_local), rest[b.name]) for b in rig.data.bones)
assert np.array_equal(pose(), neutral), np.max(abs(ex.evaluated(head)-neutral))
assert np.max(abs(pose(other=.8)-unrelated)) < 1e-6
assert np.max(abs(pose(.5)-half)) > 1e-5
assert np.max(abs(pose(1.)-target)) < 5e-6
assert sculpt.fingerprint(source) == original_hash
assert not bpy.app.timers.is_registered(sculpt._tick)

reader = dnaio.open_reader(output); old = dnaio.open_reader(source)
expression_dna.validate_expression(old, reader)
record = expression_dna.records(reader)[0]
channel = record['channel']; shape_count = reader.getBlendShapeChannelCount()
assert shape_count == old.getBlendShapeChannelCount()+1
assert len(head.data.shape_keys.key_blocks) == 2, 'Imported source corrective library'
for lod in range(reader.getLODCount()):
    # RigLogic must activate the authored native shape at all levels of detail.
    _, rl, _ = dnaio.load_bindings()
    manager = rl.RigLogic(reader, rl.Configuration(), None)
    instance = rl.RigInstance(rigLogic=manager, memRes=None); instance.setLOD(lod)
    for value in (0., .5, 1.):
        instance.setRawControl(control, value); manager.calculate(instance)
        assert abs(instance.getBlendShapeOutputs()[channel]-value) < 1e-6
    dnaio.release_handle(instance); dnaio.release_handle(manager)
dnaio.release_handle(reader); dnaio.release_handle(old)

# Another sculpt on the same expression merges into the same native target.
work = ex.start(rig, control); target = sculpt_target(work, .0004)
output = ex.finish(rig, prefix.with_suffix('.repeat.dna'))
reader = dnaio.open_reader(output)
assert reader.getBlendShapeChannelCount() == shape_count
assert len(expression_dna.records(reader)) == 1
dnaio.release_handle(reader)
assert np.max(abs(pose(1.)-target)) < 5e-6
assert np.array_equal(pose(), neutral)
assert np.max(abs(pose(other=.8)-unrelated)) < 1e-6
after_ms = benchmark(); info = bake.validate_rig(rig)
assert not any(info[k] for k in ('invalid', 'needs_python', 'muted')), info
assert after_ms < before_ms*1.35+2., (before_ms, after_ms)
assert info['drivers'] < before_drivers+30, info

# Export the prepared DNA through the user-facing operator.
bpy.context.view_layer.objects.active = rig; rig.select_set(True)
exported = prefix.with_suffix('.export.dna')
assert bpy.ops.metamorphosis.export_dna(filepath=str(exported)) == {'FINISHED'}
pose()
board.animation_data_create(); board.animation_data.action = None
bone = board.pose.bones[smile]
for frame, value in ((1, 0.), (2, 1.)):
    bone.location.y = value; bone.keyframe_insert('location', index=1, frame=frame)
bpy.context.scene.frame_set(2)
saved = prefix.with_suffix('.finished.blend')
bpy.ops.wm.save_as_mainfile(filepath=str(saved))
addon.unregister(); bpy.ops.wm.open_mainfile(filepath=str(saved))
rig = next(o for o in bpy.data.objects if o.get(bake.RIG_KEY_DNA) == str(exported))
head = sculpt.head_mesh(rig); board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
for frame, expected in ((1, neutral), (2, target), (1, neutral)):
    bpy.context.scene.frame_set(frame)
    assert np.max(abs(ex.evaluated(head)-expected)) < 5e-6, ('Standalone', frame)

# Fresh import must discover only our DNA-authored shapes and native drivers.
bpy.ops.wm.read_factory_settings(use_empty=True); addon.register()
assert bpy.ops.metamorphosis.import_dna(filepath=str(exported), character_name='ExpressionReimport') == {'FINISHED'}
rig = bake.find_baked_rig(bpy.context); head = sculpt.head_mesh(rig)
board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
assert len(head.data.shape_keys.key_blocks) == 2
assert np.max(abs(pose()-neutral)) < 2e-6
assert np.max(abs(pose(1.)-target)) < 5e-6, ('Reimport', np.max(abs(ex.evaluated(head)-target)))
print('EXPRESSION_SCULPT_PASS', scene.name, bpy.app.version_string,
      dict(target_error=error, before_ms=before_ms, after_ms=after_ms,
           before_drivers=before_drivers, after_drivers=info['drivers'], dna=str(exported)), flush=True)
addon.unregister()
