"""Regression for missing/stale sidebar active-object context and panel nesting."""
import importlib.util
from contextlib import nullcontext
from pathlib import Path
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py',
                                             submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bake, sculpt

bpy.ops.wm.open_mainfile(filepath=str(ROOT/'work/native_sums_mouth_corrected.blend'))
addon.register()
assert bpy.types.MM_PT_sculpt.bl_parent_id == 'MM_PT_panel'
assert bpy.types.MM_PT_sculpt.bl_category == bpy.types.MM_PT_panel.bl_category == 'MetaMorphosis'
rig = bake.find_baked_rig(bpy.context); head = sculpt.head_mesh(rig)
baseline = sculpt.coords(head.data)
names = [b.name for b in rig.data.bones if not b.name.startswith('CTRL_')]
rest = np.array([rig.data.bones[n].head_local[:] for n in names])
drivers = bake.validate_rig(rig)

for target, mode, overridden in ((None, 'OBJECT', False), (None, 'OBJECT', True),
                                 (head, 'OBJECT', True), (rig, 'POSE', True),
                                 (head, 'EDIT', True), (head, 'SCULPT', True)):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = target
    if target:
        target.select_set(True)
        sculpt.set_mode(target, mode)
    # Supplying None replicates the reported poll error even when the view
    # layer has an object: setting view_layer.objects.active alone cannot fix it.
    override = bpy.context.temp_override(object=None, active_object=None,
        selected_objects=[], selected_editable_objects=[]) if overridden else nullcontext()
    with override:
        sculpt.set_joint_positions(rig, names, rest)
        assert bpy.context.view_layer.objects.active == target
        assert target is None or target.mode == mode
        assert bpy.ops.metamorphosis.sculpt_start() == {'FINISHED'}
        assert bpy.context.view_layer.objects.active == head and head.mode == 'OBJECT'
        sculpt.pause()
        assert bpy.ops.metamorphosis.sculpt_start() == {'FINISHED'}  # recover a paused session
        assert bpy.ops.metamorphosis.sculpt_cancel() == {'FINISHED'}
    assert np.array_equal(sculpt.coords(head.data), baseline)
    assert np.max(abs(np.array([rig.data.bones[n].head_local[:] for n in names])-rest)) < 2e-6
    assert not bpy.app.timers.is_registered(sculpt._tick)
    assert rig.mode == 'OBJECT'
    print('CONTEXT_CASE_PASS', target.name if target else None, mode, overridden, flush=True)

assert bake.validate_rig(rig) == drivers
assert not any(o.name.startswith('MM_SCULPT_BACKUP') for o in bpy.data.objects)
addon.unregister(); addon.register(); addon.unregister()
print('SCULPT_CONTEXT_PASS', bpy.app.version_string, flush=True)
