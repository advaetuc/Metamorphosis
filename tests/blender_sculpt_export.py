"""DNA round-trip, neutral sculpt, recovery, native expressions and performance.

Run with Blender --background --factory-startup --python-exit-code 1 --python
tests/blender_sculpt_export.py -- [DNA paths ...]. Uses work/ only.
"""
import importlib.util
from pathlib import Path
import statistics
import sys
import time

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py',
                                             submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bake, cleanup, dnaio, dna_export, sculpt, verify
from metamorphosis.logicmodel import RigLogicModel
from metamorphosis.sculpt_field import SurfaceField, symmetry_pairs, sync_symmetry

OUT = ROOT/'work'; OUT.mkdir(exist_ok=True)
inputs = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [r'F:\BlendLAB\Metahumans\MH_BASE.dna']


def preserved(a, b):
    dna_export.validate_copy(a, b)
    for method in ('getPSDRowIndices', 'getPSDColumnIndices', 'getPSDValues',
                   'getGUIToRawInputIndices', 'getGUIToRawOutputIndices',
                   'getBlendShapeChannelInputIndices', 'getBlendShapeChannelOutputIndices',
                   'getAnimatedMapInputIndices', 'getAnimatedMapOutputIndices'):
        assert list(getattr(a, method)()) == list(getattr(b, method)()), method
    for m in range(a.getMeshCount()):
        for method in ('getVertexLayoutPositionIndices', 'getVertexLayoutTextureCoordinateIndices',
                       'getVertexLayoutNormalIndices', 'getVertexTextureCoordinateUs', 'getVertexTextureCoordinateVs'):
            assert list(getattr(a, method)(m)) == list(getattr(b, method)(m)), (method, m)
        for v in range(a.getVertexPositionCount(m)):
            assert list(a.getSkinWeightsJointIndices(m, v)) == list(b.getSkinWeightsJointIndices(m, v))
            assert list(a.getSkinWeightsValues(m, v)) == list(b.getSkinWeightsValues(m, v))
        for t in range(a.getBlendShapeTargetCount(m)):
            assert list(a.getBlendShapeTargetVertexIndices(m, t)) == list(b.getBlendShapeTargetVertexIndices(m, t))
            assert a.getBlendShapeChannelIndex(m, t) == b.getBlendShapeChannelIndex(m, t)


for path in inputs:
    path = Path(path)
    reader = dnaio.open_reader(path)
    base = dna_export.positions(reader, 0)
    original_hash = sculpt.fingerprint(path)
    dna_export.write_dna(path, OUT/'sculpt_noop.dna')
    check = dnaio.open_reader(OUT/'sculpt_noop.dna'); preserved(reader, check)
    for m in range(reader.getMeshCount()):
        assert np.array_equal(dna_export.positions(reader, m), dna_export.positions(check, m))
        for t in range(reader.getBlendShapeTargetCount(m)):
            for axis in 'XYZ':
                method = 'getBlendShapeTargetDelta'+axis+'s'
                assert list(getattr(reader, method)(m, t)) == list(getattr(check, method)(m, t))
    dnaio.release_handle(check)
    for mode in ('uniform', 'local'):
        target = base.copy()
        if mode == 'uniform':
            target = base*1.025 + (.2, -.1, .3)
        else:
            center = np.mean(base, axis=0); center[2] = base[:, 2].max()-3
            target[:, 2] += .08*np.exp(-np.sum(((base-center)/4)**2, axis=1))
        field = SurfaceField(base, target)
        assert not field.identity
        filename = OUT/f'sculpt_{path.stem}_{mode}.dna'
        start = time.perf_counter(); dna_export.write_dna(path, filename, field, {0: target})
        check = dnaio.open_reader(filename); preserved(reader, check)
        assert np.allclose(dna_export.positions(check, 0), target, atol=2e-5)
        moved, _, transforms = dna_export.adapted_joints(reader, field)
        assert np.allclose(dna_export.joint_rest(check)[0][:, :3, 3], moved, atol=4e-5)
        def group_outputs(dna, lod):
            result = np.zeros((dna.getJointCount(), 9))
            for g in range(dna.getJointGroupCount()):
                rows = np.asarray(dna.getJointGroupOutputIndices(g), dtype=int)
                cols = np.asarray(dna.getJointGroupInputIndices(g), dtype=int)
                n = dna.getJointGroupLODs(g)[lod]
                if len(cols) and len(rows):
                    weights = np.asarray(dna.getJointGroupValues(g)).reshape(len(rows), len(cols))
                    values = np.sin(cols*.7)*.3+.5
                    np.add.at(result.ravel(), rows[:n], weights[:n] @ values)
            return result
        for lod in range(reader.getLODCount()):
            expected = group_outputs(reader, lod)
            expected[:, :3] = np.einsum('nij,nj->ni', transforms, expected[:, :3])
            assert np.allclose(group_outputs(check, lod), expected, atol=2e-5), (mode, lod)
        if mode == 'uniform':
            for m in range(reader.getMeshCount()):
                assert np.allclose(dna_export.positions(check, m), dna_export.positions(reader, m)*1.025+(.2,-.1,.3), atol=2e-5)
                for t in range(reader.getBlendShapeTargetCount(m)):
                    for axis in 'XYZ':
                        method = 'getBlendShapeTargetDelta'+axis+'s'
                        assert np.allclose(getattr(check, method)(m, t), np.asarray(getattr(reader, method)(m, t))*1.025, atol=2e-6)
        model = RigLogicModel.from_reader(check)
        _, rl, _ = dnaio.load_bindings()
        result = verify.verify_model(model, rl, check, release=dnaio.release_handle)
        assert result.ok, result
        dnaio.release_handle(check)
        print('DNA_SCULPT_PASS', path.stem, mode, 'seconds', time.perf_counter()-start, flush=True)
    assert sculpt.fingerprint(path) == original_hash
    try:
        dna_export.write_dna(path, path)
        raise AssertionError('Source overwrite allowed')
    except ValueError:
        pass
    # Symmetry mirrors edits, not the existing asymmetric face.
    points = np.array([[-1., 0, 0], [1., 0, 0], [0, 0, 0]])
    edited = points.copy(); edited[0] += (-.1, .2, .3)
    mirrored = sync_symmetry(points, points, edited, symmetry_pairs(points))
    assert np.allclose(mirrored[1]-points[1], (.1, .2, .3))
    dnaio.release_handle(reader)

# Real saved scene exercises joined face board, geometry, expressions and assets.
scene = OUT/'native_sums_mouth_corrected.blend'
if scene.exists():
    bpy.ops.wm.open_mainfile(filepath=str(scene)); addon.register()
    assert not bpy.app.timers.is_registered(sculpt._tick)
    rig = bake.find_baked_rig(bpy.context); head = sculpt.head_mesh(rig)
    board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
    actions = set(bpy.data.actions.keys())
    materials = {m.name: tuple(v.name if v else None for v in m.data.materials) for m in bake.head_meshes(rig)}
    original = sculpt.coords(head.data)
    joints = np.array([b.head_local[:] for b in rig.data.bones])
    source = rig[bake.RIG_KEY_DNA]
    timings = [bake.benchmark(bpy.context, rig, 40)['ms'] for _ in range(3)]
    before_ms = statistics.median(timings)
    baseline_drivers = bake.validate_rig(rig)['drivers']
    # Native geometric expression baseline, including the supplied extreme pose.
    controls = [b for b in board.pose.bones if b.name.startswith('CTRL_') and ('mouth' in b.name or 'jaw' in b.name)]
    saved = {b.name: tuple(b.location) for b in controls}
    poses = [saved, dict.fromkeys(saved, (0., 0., 0.))]
    for y in (.3, .7, 1.):
        poses.append({b.name: (0., y, 0.) for b in controls})
    def pose(values):
        for name, value in values.items(): board.pose.bones[name].location = value
        board.update_tag(); bpy.context.view_layer.update()
    def geometry():
        return sculpt.coords(head.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)
    old = []
    for p in poses:
        pose(p); old.append(geometry())
    pose(saved)
    session = sculpt.start(rig)
    assert rig.data.pose_position == 'REST'
    assert bpy.app.timers.is_registered(sculpt._tick)
    sculpt.set_coords(head.data, original+(0, .0003, 0)); session.update()
    valid = sculpt.coords(head.data).copy()
    # A changed vertex count restores the last valid coordinates and topology.
    with sculpt.ContextMode():
        import bmesh
        bm = bmesh.new(); bm.from_mesh(head.data); bm.verts.new((0, 0, 0)); bm.to_mesh(head.data); bm.free()
    assert not session.update()
    assert np.allclose(sculpt.coords(head.data), valid, atol=1e-7)
    # Save/reload pauses tracking, retaining backups and cancellation.
    recovery = OUT/'sculpt_recovery.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(recovery))
    bpy.ops.wm.open_mainfile(filepath=str(recovery))
    assert sculpt._active is None and not bpy.app.timers.is_registered(sculpt._tick)
    rig = bake.find_baked_rig(bpy.context); head = sculpt.head_mesh(rig)
    sculpt.resume(rig); sculpt.cancel(rig)
    assert np.array_equal(sculpt.coords(head.data), original)
    assert np.max(abs(np.array([b.head_local[:] for b in rig.data.bones])-joints)) < 2e-6
    assert rig[bake.RIG_KEY_DNA] == source
    assert not bpy.app.timers.is_registered(sculpt._tick)
    session = sculpt.start(rig)
    sculpt.set_coords(head.data, original*1.02+(.001, .002, .003)); session.update()
    prepared = sculpt.prepare(rig, OUT/'sculpt_prepared.dna')
    board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
    errors = []
    for p, expected in zip(poses, old):
        pose(p); errors.append(float(np.max(abs(geometry()-(expected*1.02+(.001,.002,.003))))))
    # Includes existing Lite pruning and Blender's 1e-4 RNA write tolerance.
    assert max(errors) < 3e-4, errors
    pose(saved)
    assert {m.name: tuple(v.name if v else None for v in m.data.materials) for m in bake.head_meshes(rig)} == materials
    assert set(bpy.data.actions.keys()) == actions
    assert not sculpt.SESSION in rig
    assert not bpy.app.timers.is_registered(sculpt._tick)
    assert not any(o.name.startswith('MM_SCULPT_BACKUP') for o in bpy.data.objects)
    info = bake.validate_rig(rig)
    assert not info['invalid'] and not info['needs_python'] and not info['muted'], info
    after_ms = statistics.median(bake.benchmark(bpy.context, rig, 40)['ms'] for _ in range(3))
    assert after_ms < before_ms*1.5+2, (before_ms, after_ms)
    saved_scene = OUT/'sculpt_prepared.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(saved_scene))
    addon.unregister(); bpy.ops.wm.open_mainfile(filepath=str(saved_scene))
    rig = bake.find_baked_rig(bpy.context); head = sculpt.head_mesh(rig)
    board = bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
    for p, expected in zip(poses, old):
        pose(p); assert np.max(abs(geometry()-(expected*1.02+(.001,.002,.003)))) < 3e-4
    addon.register()
    sculpt.start(rig)
    assert bpy.ops.metamorphosis.remove_all() == {'FINISHED'}
    sculpt._tick()
    assert not bpy.app.timers.is_registered(sculpt._tick)
    assert not any(o.name.startswith('MM_SCULPT_BACKUP') for o in bpy.data.objects)
    addon.unregister()
    print('SCULPT_SCENE_PASS', bpy.app.version_string, {'before_ms':before_ms, 'after_ms':after_ms,
        'before_drivers':baseline_drivers, 'after_drivers':info['drivers'], 'affine_geometry_errors_m':errors}, flush=True)
