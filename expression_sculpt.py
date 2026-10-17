"""Pose sculpting: fit original joints, then store fine detail in native DNA targets.

The working copy is a frozen evaluated pose. Original neutral geometry/rest bones
are never sculpted. Baking uses existing DNA raw-expression inputs, so no ML/RBF
control indices are shifted and playback requires no Python handler.
"""
import json
from pathlib import Path
import uuid

import bpy
import numpy as np
from bpy.props import EnumProperty

from . import bake, cleanup, dnaio, expression_dna, sculpt, verify
from .logicmodel import RigLogicModel

SESSION = 'mm_expression_session'
_choices = [('NONE', 'Move a face control first', '')]


def rig_for(context):
    obj = context.view_layer.objects.active
    if obj and obj.get('mm_expression_rig'):
        return bpy.data.objects.get(obj['mm_expression_rig'])
    return bake.find_baked_rig(context)


def evaluated(head):
    bpy.context.view_layer.update()
    return sculpt.coords(head.evaluated_get(bpy.context.evaluated_depsgraph_get()).data)


def raw_values(rig, reader):
    model = RigLogicModel.from_reader(reader)
    board = bpy.data.objects.get(rig[bake.RIG_KEY_BOARD_OBJECT]) or rig
    graph = bpy.context.evaluated_depsgraph_get()
    pose = board.evaluated_get(graph).pose
    gui = np.zeros((2, len(model.gui)))
    for g in model.gui:
        if g.axis >= 0 and g.bone in pose.bones:
            gui[0, g.index] = pose.bones[g.bone].location[g.axis]
    _, rl, _ = dnaio.load_bindings()
    if rl is None:
        raise ValueError('Native RigLogic bindings are required for expression sculpting')
    result = verify.run_oracle(model, rl, reader, gui, np.tile(model.default_raw(), (2, 1)), dnaio.release_handle)
    return model, result.raw[0], result.raw[1]


def choices(rig):
    reader = dnaio.open_reader(Path(rig[bake.RIG_KEY_DNA]))
    try:
        model, values, neutral = raw_values(rig, reader)
        return [(str(i), model.raw_names[i], f'Current activation: {values[i]:.3f}')
                for i in range(model.raw_count) if i not in model.quat_inputs
                and values[i] > .05 and abs(neutral[i]) < 1e-8]
    finally:
        dnaio.release_handle(reader)


def weights(head, rig, names):
    """Normalized LBS weights in original vertex order."""
    index = {name: i for i, name in enumerate(names)}
    mapping = {g.index: index[g.name] for g in head.vertex_groups if g.name in index}
    w = np.zeros((len(head.data.vertices), len(names)))
    for v in head.data.vertices:
        for group in v.groups:
            if group.group in mapping:
                w[v.index, mapping[group.group]] = group.weight
    total = w.sum(axis=1)
    if np.any(total < .999) or np.any(total > 1.001):
        raise ValueError('Expression sculpt needs normalized original DNA skin weights')
    return w/total[:, None]


def fit_joints(head, rig, reader, delta, activation):
    names = [reader.getJointName(i) for i in range(reader.getJointCount())]
    w = weights(head, rig, names)
    candidates = [i for i, name in enumerate(names) if name.startswith('FACIAL_')
                  and not any(part in name.lower() for part in ('root', 'jaw', 'eye', 'teeth', 'tongue'))
                  and np.any(w[:, i] > 0)]
    offsets = np.zeros((len(names), 3))
    if candidates:
        design = w[:, candidates]
        gram = design.T @ design
        gram += np.eye(len(candidates))*max(float(np.trace(gram)/len(candidates))*.02, 1e-8)
        fitted = np.linalg.solve(gram, design.T @ delta)
        # Bound poorly observed joints; residual shapes carry any finer detail.
        limit = max(float(np.linalg.norm(delta, axis=1).max())*2, 1e-8)
        length = np.linalg.norm(fitted, axis=1)
        fitted *= np.minimum(1., limit/np.maximum(length, 1e-12))[:, None]
        offsets[candidates] = fitted
    coefficients = np.zeros_like(offsets)
    for i, name in enumerate(names):
        parent = reader.getJointParentIndex(i)
        parent_offset = offsets[parent] if 0 <= parent != i else np.zeros(3)
        if 0 <= parent != i:
            matrix = np.array(rig.pose.bones[names[parent]].matrix)[:3, :3]
        else:
            from .importer import Y_UP_TO_Z_UP
            matrix = np.array(Y_UP_TO_Z_UP)[:3, :3]
        coefficients[i] = np.linalg.solve(matrix, offsets[i]-parent_offset)/rig[bake.RIG_KEY_SCALE]/activation
    return coefficients


def inverse_skin_delta(head, rig, reader, delta):
    names = [reader.getJointName(i) for i in range(reader.getJointCount())]
    w = weights(head, rig, names)
    matrices = np.array([np.array(rig.pose.bones[n].matrix @ rig.data.bones[n].matrix_local.inverted())[:3, :3]
                         for n in names])
    linear = (w @ matrices.reshape(len(names), 9)).reshape(-1, 3, 3)
    if np.any(np.abs(np.linalg.det(linear)) < 1e-6):
        raise ValueError('Pose has singular skinning transforms; reduce the pose before sculpting')
    return np.linalg.solve(linear, delta[..., None])[..., 0]


def start(rig, control):
    if rig is None:
        raise ValueError('Select a MetaMorphosis character first')
    if sculpt.SESSION in rig or SESSION in rig:
        raise ValueError('Finish or cancel the current sculpt first')
    if rig.data.pose_position != 'POSE':
        raise ValueError('Enable the rig pose before editing an expression')
    head = sculpt.head_mesh(rig)
    if head.name not in bpy.context.view_layer.objects or rig.name not in bpy.context.view_layer.objects:
        raise ValueError('Enable the character collections in the current view layer')
    if head.data.users != 1 or rig.data.users != 1 or len(rig.users_scene) > 1:
        raise ValueError('Make the character single-user before expression sculpting')
    modifiers = list(head.modifiers)
    if len(modifiers) != 1 or modifiers[0].type != 'ARMATURE' or modifiers[0].object != rig:
        raise ValueError('Expression sculpt requires the original Armature modifier only')
    arm = modifiers[0]
    if (not arm.show_viewport or not arm.show_render or arm.use_deform_preserve_volume
            or arm.use_bone_envelopes or not arm.use_vertex_groups or arm.vertex_group):
        raise ValueError('Use standard vertex-group skinning without Preserve Volume or a modifier mask')
    if head.data.shape_keys and not head.data.shape_keys.use_relative:
        raise ValueError('Expression sculpt requires relative shape keys')
    source = Path(bpy.path.abspath(rig[bake.RIG_KEY_DNA])).resolve()
    reader = dnaio.open_reader(source)
    try:
        sculpt.check_export_geometry(rig, reader)
        model, values, neutral = raw_values(rig, reader)
        if not 0 <= control < model.raw_count or values[control] <= .05 or abs(neutral[control]) > 1e-8:
            raise ValueError('Choose an active facial expression that is zero at neutral')
        original = evaluated(head)
        index = sculpt.mesh_index(head, reader)
        # Export retains source weights. Refuse to fit a differently weighted rig
        # whose sculpt could not round-trip to the saved DNA.
        names = [reader.getJointName(i) for i in range(reader.getJointCount())]
        actual_weights = weights(head, rig, names)
        for vertex in range(len(head.data.vertices)):
            joints = np.asarray(reader.getSkinWeightsJointIndices(index, vertex), dtype=int)
            expected = np.asarray(reader.getSkinWeightsValues(index, vertex))
            if (abs(float(actual_weights[vertex, joints].sum())-1.) > 1e-6
                    or not np.allclose(actual_weights[vertex, joints], expected/expected.sum(), atol=1e-6, rtol=0)):
                raise ValueError('Skin weights changed; restore original DNA weights before expression sculpting')
        with sculpt.ContextMode():
            graph = bpy.context.evaluated_depsgraph_get()
            data = bpy.data.meshes.new_from_object(head.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)
            work = bpy.data.objects.new('MM_EXPRESSION_SCULPT', data)
            head.users_collection[0].objects.link(work)
            work.parent = rig; work.matrix_world = head.matrix_world.copy()
            work['mm_expression_rig'] = rig.name
            work[cleanup.OWNER] = rig.get(cleanup.OWNER, '')
            data[cleanup.OWNER] = rig.get(cleanup.OWNER, '')
            meta = {'source': str(source), 'hash': sculpt.fingerprint(source), 'head': head.name,
                    'work': work.name, 'index': index, 'control': control, 'name': model.raw_names[control],
                    'activation': float(values[control]), 'posed': sculpt.encode(original),
                    'topology': sculpt.topology(data), 'hidden': head.hide_get(), 'frame': bpy.context.scene.frame_current}
            rig[SESSION] = json.dumps(meta)
        active = bpy.context.view_layer.objects.active
        if active:
            sculpt.set_mode(active, 'OBJECT')
        head.hide_set(True)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        work.select_set(True); bpy.context.view_layer.objects.active = work
        return work
    finally:
        dnaio.release_handle(reader)


def cancel(rig):
    meta = json.loads(rig[SESSION])
    work = bpy.data.objects.get(meta['work']); head = bpy.data.objects.get(meta['head'])
    active = bpy.context.view_layer.objects.active
    if active:
        sculpt.set_mode(active, 'OBJECT')
    if head:
        head.hide_set(meta['hidden']); bpy.context.view_layer.objects.active = head
        head.select_set(True)
    if work:
        data = work.data; bpy.data.objects.remove(work, do_unlink=True)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    del rig[SESSION]


def rebuild(rig, path):
    rig[bake.RIG_KEY_DNA] = str(path)
    rig['mm_expression_rebuilding'] = True
    try:
        with sculpt.ContextMode(), sculpt.object_context(rig):
            bpy.context.view_layer.objects.active = rig
            if bpy.ops.metamorphosis.rebuild() != {'FINISHED'}:
                raise RuntimeError('Expression driver rebuild failed')
    finally:
        del rig['mm_expression_rebuilding']


def finish(rig, destination=None):
    meta = json.loads(rig[SESSION])
    head, work = bpy.data.objects[meta['head']], bpy.data.objects[meta['work']]
    active = bpy.context.view_layer.objects.active
    if active:
        sculpt.set_mode(active, 'OBJECT')
    if sculpt.topology(work.data) != meta['topology'] or work.modifiers:
        raise ValueError('Working-copy topology changed; undo remesh/topology/modifier edits before applying')
    if not np.allclose(np.array(work.matrix_world), np.array(head.matrix_world), atol=1e-7, rtol=0):
        raise ValueError('Working-copy object transform changed; sculpt vertices instead')
    original = sculpt.decode(meta['posed'])
    if not np.allclose(evaluated(head), original, atol=5e-7, rtol=0):
        raise ValueError('Face pose changed during sculpting; return the face board to the captured pose')
    if sculpt.fingerprint(meta['source']) != meta['hash']:
        raise ValueError('Source DNA changed during sculpting')
    if Path(bpy.path.abspath(rig[bake.RIG_KEY_DNA])).resolve() != Path(meta['source']).resolve():
        raise ValueError('Rig DNA source changed during sculpting; restore it before applying')
    target = sculpt.coords(work.data)
    if not np.isfinite(target).all():
        raise ValueError('Sculpt has invalid coordinates')
    delta = target-original
    if np.max(np.abs(delta)) < 1e-8:
        raise ValueError('No expression sculpt changes to apply')
    if rig.mm_sculpt_symmetry:
        from .sculpt_field import symmetry_pairs, sync_symmetry
        # Match anatomical partners in the neutral mesh, not an asymmetric pose.
        target = sync_symmetry(original, original, target, symmetry_pairs(sculpt.coords(head.data)))
        delta = target-original
    if destination is None:
        folder = Path(bpy.utils.user_resource('DATAFILES', path='MetaMorphosis/SculptDNA', create=True))
        destination = folder/(Path(meta['source']).stem+'_expression_'+uuid.uuid4().hex+'.dna')
    destination = Path(destination).resolve()
    protected = {Path(meta['source']).resolve(), Path(rig.get('mm_sculpt_original_dna', meta['source'])).resolve()}
    if destination in protected or destination.exists():
        raise ValueError('Use a new filename for the expression preparation')
    draft = destination.with_name(destination.stem+'_joints_'+uuid.uuid4().hex+'.dna')
    reader = dnaio.open_reader(Path(meta['source']))
    # Keep a mesh copy for rollback, including existing authored keys/drivers.
    backup = head.data.copy()
    old_source = rig[bake.RIG_KEY_DNA]
    try:
        offsets = fit_joints(head, rig, reader, delta, meta['activation'])
        expression_dna.write_joints(meta['source'], draft, meta['control'], offsets)
        rebuild(rig, draft)
        # Compensate actual baked bone motion, including retained Lite/RNA tolerances.
        remaining = target-evaluated(head)
        residual = inverse_skin_delta(head, rig, reader, remaining)/meta['activation']
        expression_dna.write_residual(draft, destination, meta['control'], meta['index'],
                                      sculpt.to_dna(residual, rig[bake.RIG_KEY_SCALE]))
        rebuild(rig, destination)
        error = float(np.max(np.abs(evaluated(head)-target)))
        if error > 5e-6:
            raise ValueError(f'Expression reconstruction differs by {error*1000:.3f} mm; original rig restored')
        rig['mm_sculpt_original_dna'] = rig.get('mm_sculpt_original_dna', meta['source'])
        rig['mm_sculpt_status'] = f'Expression saved: {meta["name"]}. Reset its control to remove the detail.'
    except Exception:
        damaged = head.data; head.data = backup; backup = None
        if damaged.users == 0:
            bpy.data.meshes.remove(damaged)
        if destination.exists():
            destination.unlink()
        # Restore the source pointer even if an independent rebuild failure
        # prevents recovery; never leave it referencing the temporary draft.
        rig[bake.RIG_KEY_DNA] = old_source
        rebuild(rig, old_source)
        raise
    finally:
        dnaio.release_handle(reader)
        if backup is not None and backup.users == 0:
            bpy.data.meshes.remove(backup)
        if draft.exists():
            draft.unlink()
    cancel(rig)
    return destination


class MM_OT_expression_start(bpy.types.Operator):
    bl_idname = 'metamorphosis.expression_start'
    bl_label = 'Sculpt Expression'
    bl_description = 'Capture the posed face; sculpt a correction driven by one active DNA expression'
    control: EnumProperty(name='Driven by', items=lambda self, context: _choices)

    def invoke(self, context, event):
        global _choices
        try:
            rig = rig_for(context)
            if rig is None:
                raise ValueError('Select a character first')
            _choices = choices(rig)
            if not _choices:
                raise ValueError('Move a facial control first, then choose Sculpt Expression')
            self.control = _choices[0][0]
            return context.window_manager.invoke_props_dialog(self, width=460)
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}

    def draw(self, context):
        self.layout.prop(self, 'control')
        self.layout.label(text='The correction follows this expression, including in mixed poses.')
        self.layout.label(text='Resetting this expression removes the correction.')
        self.layout.label(text='Original bones adapt; a DNA shape stores fine detail.')

    def execute(self, context):
        try:
            start(rig_for(context), int(self.control))
            self.report({'INFO'}, 'Sculpt the working copy; keep the face board at the captured pose')
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


class MM_OT_expression_apply(bpy.types.Operator):
    bl_idname = 'metamorphosis.expression_apply'
    bl_label = 'Apply Expression to DNA'
    def execute(self, context):
        try:
            finish(rig_for(context))
            self.report({'INFO'}, 'Expression saved; neutral geometry is unchanged')
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


class MM_OT_expression_cancel(bpy.types.Operator):
    bl_idname = 'metamorphosis.expression_cancel'
    bl_label = 'Cancel Expression Sculpt'
    def execute(self, context):
        try:
            cancel(rig_for(context)); return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


CLASSES = (MM_OT_expression_start, MM_OT_expression_apply, MM_OT_expression_cancel)
