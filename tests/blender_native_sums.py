"""Performance and deformation regression for the native joint matrix backend.

Run in Blender with -- corrected-v1.2.1.blend [DNA ...]. The saved old rig allows
a like-for-like benchmark without compiler snapshots. DNA arguments exercise
fresh imports. Test outputs are written only under work/.
"""
import copy
import importlib.util
from pathlib import Path
import statistics
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py',
                                             submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
from metamorphosis import bake, bakeplan, cleanup, dnaio, native_sums, optimize, pipeline, verify
from metamorphosis.logicmodel import RigLogicModel

addon.register()
for filename in sys.argv[sys.argv.index('--') + 1:]:
    source = Path(filename)
    is_scene = source.suffix.lower() == '.blend'
    if is_scene:
        bpy.ops.wm.open_mainfile(filepath=str(source))
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        threshold = native_sums.MIN_TERMS
        try:
            # Build the pre-optimization equations for a same-session baseline.
            native_sums.MIN_TERMS = 10**12
            assert bpy.ops.metamorphosis.import_dna(filepath=str(source),
                face_board_file=str(ROOT/'assets/face_board.blend')) == {'FINISHED'}
        finally:
            native_sums.MIN_TERMS = threshold
    rig = bake.find_baked_rig(bpy.context)
    board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
    reader = dnaio.open_reader(Path(rig[bake.RIG_KEY_DNA]))
    model = RigLogicModel.from_reader(reader)
    _, rl, _ = dnaio.load_bindings('')
    result = verify.verify_model(model, rl, reader, release=dnaio.release_handle)
    assert result.ok
    degrees, _ = dnaio.unit_flags(reader)
    scale = rig[bake.RIG_KEY_SCALE]
    orientation = bakeplan.joint_orientation_inverse(reader, model.joint_count, degrees)
    budget = list(pipeline.QUALITY['LITE'][0]); budget[0] *= scale/.01
    plan = bakeplan.build_plan(model, result.variant, orientation, scale=scale,
        rotation_degrees=degrees, budget=tuple(budget), use_psd=False,
        face_board_bones=set(rig[bake.RIG_KEY_BOARD].split('\n')),
        skip_bones=pipeline.unneeded_bones(model, pipeline.weighted_bones(bake.head_meshes(rig))))
    optimize.optimize_plan(plan)
    compact = native_sums.prepare_plan(plan)
    assert compact.stats['native_sums'] and compact.stats['mouth_combination_correctives'] == plan.stats['mouth_combination_correctives']
    assert compact.linear_channels == plan.linear_channels  # every coefficient retained
    full = copy.deepcopy(plan)
    for node in full.nodes:
        if node.dtype == 'SCRIPTED': node.expr = compile(node.expr, '<driver>', 'eval')
    controls = [c for c in model.gui if c.axis >= 0 and c.bone in board.pose.bones]
    def locations():
        pose = {(c.bone, c.axis):float(board.pose.bones[c.bone].location[c.axis]) for c in controls}
        if 'CTRL_C_eye' in board.pose.bones:
            pose.update({('CTRL_C_eye', i):board.pose.bones['CTRL_C_eye'].location[i] for i in (0, 1)})
        return pose
    original = locations()
    poses = [original, dict.fromkeys(original, 0.)]
    spans = model.clamp_ranges()
    for bound in (0, 1):
        poses.append({(c.bone, c.axis):spans.get(c.index, (0, 0))[bound] for c in controls})
    rng = np.random.default_rng(12201)
    for _ in range(28):
        poses.append({(c.bone, c.axis):float(rng.uniform(*spans.get(c.index, (0, 0)))) for c in controls})
    def apply(pose):
        for (name, axis), value in pose.items(): board.pose.bones[name].location[axis] = value
        board.update_tag(); bpy.context.view_layer.update()
    def geometry():
        graph = bpy.context.evaluated_depsgraph_get()
        vertices = []
        for mesh in bake.head_meshes(rig):
            data = mesh.evaluated_get(graph).data
            coords = np.empty(len(data.vertices)*3, np.float32)
            data.vertices.foreach_get('co', coords); vertices.append(coords)
        return np.concatenate(vertices)
    old_geometry = []
    for pose in poses:
        apply(pose); old_geometry.append(geometry())
    apply(original)
    bake.benchmark(bpy.context, rig, 10)
    old_ms = statistics.median(bake.benchmark(bpy.context, rig, 50)['ms'] for _ in range(3))
    old_drivers = bake.validate_rig(rig)['drivers']
    actions = set(bpy.data.actions)
    materials = {m.name:tuple(m.data.materials) for m in bake.head_meshes(rig)}
    saved_locations = {b.name:tuple(b.location) for b in board.pose.bones if b.name.startswith('CTRL_')}
    if bpy.context.object and bpy.context.object.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = rig; rig.select_set(True)
    assert bpy.ops.metamorphosis.rebuild() == {'FINISHED'}
    assert actions == set(bpy.data.actions)
    assert materials == {m.name:tuple(m.data.materials) for m in bake.head_meshes(rig)}
    assert saved_locations == {b.name:tuple(b.location) for b in board.pose.bones if b.name.startswith('CTRL_')}
    info = bake.validate_rig(rig)
    assert not info['invalid'] and not info['needs_python'] and not info['muted'], info
    assert info['drivers'] == compact.stats['nodes'], (info, compact.stats)
    def native_expected():
        # GUI/raw/PSD helpers retain Blender's existing small-write tolerance.
        # Compare the changed matrix stage with its actual native inputs rather
        # than attributing pre-existing GUI rounding to this optimization.
        helpers = [bpy.data.objects[n] for n in rig[bake.RIG_KEY_DATA].split('\n')]
        props = {key:float(holder['mm_values'][i])
                 for holder, group in zip(helpers, bake.helper_groups(compact))
                 for i, key in enumerate(group)}
        return {target:sum(w*(1. if key is None else props[key]) for key,w in row)
                for target,row in compact.linear_channels}
    worst = geometry_error = formula_error = 0.
    for i, pose in enumerate(poses):
        apply(pose)
        expected = bakeplan.evaluate_plan(full, locations())
        factored = bakeplan.evaluate_plan(compact, locations())
        formula_error = max(formula_error, max(abs(expected[t]-factored[t]) for t in expected))
        native = native_expected()
        error = max(abs(getattr(rig.pose.bones[t[1]], t[2])[t[3]]-v) for t, v in native.items())
        worst = max(worst, error)
        assert error < 1.05e-4, (source, i, error)  # final native RNA write tolerance
        output = next(bpy.data.objects[n] for n in rig[bake.RIG_KEY_DATA].split('\n')
                      if bpy.data.objects[n].modifiers)
        evaluated = output.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
        field_error = max(abs(evaluated.vertices[j].co.x/10000-native[target])
                          for j,(target,_) in enumerate(compact.linear_channels))
        assert field_error < 3e-6, (source, i, 'field arithmetic', field_error)
        if old_geometry:
            geometry_error = max(geometry_error, float(abs(geometry()-old_geometry[i]).max()))
    assert formula_error < 1e-11, formula_error
    assert geometry_error < 3e-4, geometry_error
    # Toggle includes the control-mesh drivers, not just object drivers.
    bake.set_baked_enabled(rig, False)
    assert bake.validate_rig(rig)['muted'] == info['drivers']
    bake.set_baked_enabled(rig, True); apply(original)
    bake.benchmark(bpy.context, rig, 10)
    new_ms = statistics.median(bake.benchmark(bpy.context, rig, 50)['ms'] for _ in range(3))
    if old_ms is not None:
        assert new_ms < old_ms * .6, (old_ms, new_ms)
    # Rebuild must retire old matrix meshes/groups without accumulating orphans.
    counts = tuple(sum(bool(d.get(native_sums.TAG)) for d in getattr(bpy.data, pool))
                   for pool in ('objects', 'meshes', 'node_groups'))
    assert bpy.ops.metamorphosis.rebuild() == {'FINISHED'}
    assert counts == tuple(sum(bool(d.get(native_sums.TAG)) for d in getattr(bpy.data, pool))
                           for pool in ('objects', 'meshes', 'node_groups'))
    saved = ROOT/'work'/f'native_sums_{source.stem}.blend'
    apply(original)
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    addon.unregister(); bpy.ops.wm.open_mainfile(filepath=str(saved))
    rig = bake.find_baked_rig(bpy.context); board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
    # Scrubbing an action must update the field graph with the add-on disabled.
    board.animation_data_create(); old_action = board.animation_data.action; board.animation_data.action = None
    bone = board.pose.bones['CTRL_L_mouth_cornerPull']
    for frame, value in ((1, 0.), (2, 1.)):
        bone.location.y = value; bone.keyframe_insert('location', index=1, frame=frame)
    for frame in (1, 2, 1):
        bpy.context.scene.frame_set(frame)
        expected = native_expected()
        error = max(abs(getattr(rig.pose.bones[t[1]], t[2])[t[3]]-v) for t, v in expected.items())
        assert error < 1.05e-4, ('standalone animation', frame, error)
    board.animation_data.action = old_action
    addon.register()
    dnaio.release_handle(reader)
    print('NATIVE_SUMS_PASS', source, 'Blender', bpy.app.version_string,
          dict(old_drivers=old_drivers, new_drivers=info['drivers'], before_ms=old_ms, after_ms=new_ms,
               formula_error=formula_error, native_channel_error=worst, vertex_error=geometry_error), flush=True)
    assert bpy.ops.metamorphosis.remove_all() == {'FINISHED'}
    assert not [d for pool in ('objects', 'meshes', 'node_groups') for d in getattr(bpy.data, pool)
                if d.get(native_sums.TAG)], 'Matrix helper data leaked'
addon.unregister()
