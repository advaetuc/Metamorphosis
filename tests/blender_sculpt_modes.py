"""Exercise actual Edit/Sculpt mode transitions, local edits and export UI API."""
import importlib.util
from pathlib import Path
import statistics
import sys
import time
import bmesh
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bake, dnaio, dna_export, sculpt

addon.register()
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'work/native_sums_mouth_corrected.blend'))
rig = bake.find_baked_rig(bpy.context)
before = statistics.median(bake.benchmark(bpy.context, rig, 40)['ms'] for _ in range(3))
assert bpy.ops.metamorphosis.sculpt_start() == {'FINISHED'}
head = sculpt.head_mesh(rig)
baseline = sculpt.coords(head.data)
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(head.data)
center = baseline.mean(axis=0); center[1] = baseline[:, 1].min()+.03
for v in bm.verts:
    p = np.array(v.co)
    # A small local bulge on the front of the face, not a global scale.
    v.co.y -= .0008*np.exp(-np.sum(((p-center)/.04)**2))
bmesh.update_edit_mesh(head.data)
started = time.perf_counter(); sculpt._active.update(); edit_seconds = time.perf_counter()-started
assert bpy.context.object == head and head.mode == 'EDIT'
bpy.ops.object.mode_set(mode='OBJECT'); bpy.ops.object.mode_set(mode='SCULPT')
sculpt._active.update(force=True)
assert bpy.context.object == head and head.mode == 'SCULPT'
assert not sculpt._active.field.is_affine
sculpt.prepare(rig, ROOT/'work/sculpt_local_prepared.dna')
assert not bpy.app.timers.is_registered(sculpt._tick)
if head.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
after = statistics.median(bake.benchmark(bpy.context, rig, 40)['ms'] for _ in range(3))
assert after < before*1.5+2, (before, after)
assert bpy.ops.metamorphosis.export_dna(filepath=str(ROOT/'work/sculpt_local_export.dna')) == {'FINISHED'}
check = dnaio.open_reader(ROOT/'work/sculpt_local_export.dna')
assert np.allclose(dna_export.positions(check, 0), sculpt.to_dna(sculpt.coords(head.data), rig[bake.RIG_KEY_SCALE]), atol=2e-5)
dnaio.release_handle(check)
original = rig['mm_sculpt_original_dna']; original_hash = sculpt.fingerprint(original)
try:
    bpy.ops.metamorphosis.export_dna(filepath=original)
    raise AssertionError('Original DNA overwrite was allowed')
except RuntimeError as error:
    assert 'original DNA is protected' in str(error)
assert sculpt.fingerprint(original) == original_hash
prepared_vertices = sculpt.coords(head.data)
sculpt.set_coords(head.data, sculpt.coords(head.data)+(.001, 0, 0))
try:
    bpy.ops.metamorphosis.export_dna(filepath=str(ROOT/'work/sculpt_unbaked.dna'))
    raise AssertionError('Unbaked edits silently discarded')
except RuntimeError as error:
    assert 'Unbaked head edits' in str(error)
sculpt.set_coords(head.data, prepared_vertices)
# Legacy keys are optional; normal imports still have none. Their relative
# displacement must follow the base sculpt without compounding on each tick.
head.shape_key_add(name='Basis')
key = head.shape_key_add(name='LegacyTest')
key.data[200].co.z += .001
key_before = np.empty(len(key.data)*3); key.data.foreach_get('co', key_before)
sculpt.start(rig)
sculpt.set_coords(head.data, prepared_vertices*1.01)
sculpt._active.update()
key_after = np.empty_like(key_before); head.data.shape_keys.key_blocks['LegacyTest'].data.foreach_get('co', key_after)
assert np.max(abs(key_after-key_before*1.01)) < 1e-6
sculpt._active.update(force=True)
repeat = np.empty_like(key_after); head.data.shape_keys.key_blocks['LegacyTest'].data.foreach_get('co', repeat)
assert np.array_equal(key_after, repeat)
sculpt.cancel(rig)
restored = np.empty_like(key_before); head.data.shape_keys.key_blocks['LegacyTest'].data.foreach_get('co', restored)
assert np.array_equal(restored, key_before)
print('SCULPT_MODES_PASS', bpy.app.version_string, dict(before_ms=before, after_ms=after,
      edit_update_seconds=edit_seconds, drivers=bake.validate_rig(rig)), flush=True)
addon.unregister()
