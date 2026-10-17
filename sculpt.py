"""Opt-in neutral sculpt sessions, joint following and validated DNA export.

Only an active session registers a timer. Backups and metadata live in the
.blend; loading a file leaves the session paused until explicitly resumed.
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import uuid

import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector

from . import bake, cleanup, dnaio, dna_export, importer, organization
from .sculpt_field import SurfaceField, symmetry_pairs, sync_symmetry

SESSION = 'mm_sculpt_session'
_active = None


def coords(mesh):
    values = np.empty(len(mesh.vertices)*3, dtype=np.float64)
    mesh.vertices.foreach_get('co', values)
    return values.reshape(-1, 3)


def set_coords(mesh, values):
    mesh.vertices.foreach_set('co', np.asarray(values).ravel())
    mesh.update()


def to_dna(values, scale):
    return np.asarray(values)[:, (0, 2, 1)]*(1, 1, -1)/scale


def to_blender(values, scale):
    return np.asarray(values)[:, (0, 2, 1)]*(1, -1, 1)*scale


def topology(mesh):
    digest = hashlib.sha256()
    for items, prop in ((mesh.edges, 'vertices'), (mesh.loops, 'vertex_index'),
                        (mesh.polygons, 'loop_total')):
        values = np.empty(len(items)*(2 if prop == 'vertices' else 1), dtype=np.int32)
        items.foreach_get(prop, values); digest.update(values.tobytes())
    digest.update(str(len(mesh.vertices)).encode())
    return digest.hexdigest()


def fingerprint(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def encode(values):
    stream = io.BytesIO(); np.savez_compressed(stream, values=values)
    return base64.b64encode(stream.getvalue()).decode('ascii')


def decode(value):
    with np.load(io.BytesIO(base64.b64decode(value)), allow_pickle=False) as data:
        return data['values']


def head_mesh(rig):
    found = [m for m in bake.head_meshes(rig) if m.get('mm_mesh_kind', '').lower() == 'head']
    if len(found) != 1:
        raise ValueError('Select a rig with exactly one imported head mesh')
    return found[0]


def mesh_index(obj, reader):
    candidates = [int(obj['mm_dna_mesh_index'])] if 'mm_dna_mesh_index' in obj else range(reader.getMeshCount())
    for i in candidates:
        if not 0 <= i < reader.getMeshCount():
            continue
        if importer._kind_of(str(reader.getMeshName(i))).lower() != obj.get('mm_mesh_kind', '').lower():
            continue
        if reader.getVertexPositionCount(i) != len(obj.data.vertices):
            continue
        layouts = list(reader.getVertexLayoutPositionIndices(i))
        faces = [tuple(layouts[v] for v in reader.getFaceVertexLayoutIndices(i, f)) for f in range(reader.getFaceCount(i))]
        if faces == [tuple(p.vertices) for p in obj.data.polygons]:
            return i
    raise ValueError('Head topology/vertex order differs from the source DNA; reimport before sculpting')


def check_export_geometry(rig, reader):
    """Refuse to silently discard edits outside the supported sculpt workflow."""
    scale = rig[bake.RIG_KEY_SCALE]
    for obj in bake.head_meshes(rig):
        kind = obj.get('mm_mesh_kind', '').lower()
        side = kind[-1] if kind in ('eyeedge_l', 'eyeedge_r') else None
        source_kind = kind[:-2] if side else kind
        candidates = [int(obj['mm_dna_mesh_index'])] if 'mm_dna_mesh_index' in obj else range(reader.getMeshCount())
        matched = False
        for index in candidates:
            if not 0 <= index < reader.getMeshCount() or importer._kind_of(reader.getMeshName(index)).lower() != source_kind:
                continue
            points = dna_export.positions(reader, index)
            vertices = np.arange(len(points))
            if side:
                vertices = vertices[points[:, 0]*(1 if side == 'l' else -1) > 0]
            if len(vertices) != len(obj.data.vertices):
                continue
            mapping = {int(v): i for i, v in enumerate(vertices)}
            layout = reader.getVertexLayoutPositionIndices(index)
            faces = []
            for f in range(reader.getFaceCount(index)):
                original = [int(layout[v]) for v in reader.getFaceVertexLayoutIndices(index, f)]
                if all(v in mapping for v in original):
                    faces.append(tuple(mapping[v] for v in original))
            if faces != [tuple(p.vertices) for p in obj.data.polygons]:
                continue
            if not np.allclose(np.array(obj.matrix_local), np.eye(4), atol=1e-6):
                continue
            if np.allclose(to_dna(coords(obj.data), scale), points[vertices], atol=2e-5, rtol=2e-6):
                matched = True
                break
        if not matched:
            raise ValueError('Unbaked geometry/topology edits on '+obj.name+'; bake the head sculpt or restore this mesh')
    matrices, _ = dna_export.joint_rest(reader)
    names = [reader.getJointName(i) for i in range(reader.getJointCount())]
    if any(n not in rig.data.bones for n in names):
        raise ValueError('Original DNA joints are missing')
    rest = np.array([rig.data.bones[n].head_local[:] for n in names])
    if not np.allclose(rest, to_blender(matrices[:, :3, 3], scale), atol=3e-6, rtol=1e-6):
        raise ValueError('Unbaked rest-joint edits; bake the sculpt before exporting')


class ContextMode:
    """Mode switches for edit-bone writes, including return to mesh Sculpt/Edit."""
    def __enter__(self):
        self.obj = bpy.context.view_layer.objects.active
        self.mode = self.obj.mode if self.obj else 'OBJECT'
        self.selected = [o for o in bpy.context.view_layer.objects if o.select_get()]
        if self.obj and self.mode != 'OBJECT':
            set_mode(self.obj, 'OBJECT')
        return self

    def __exit__(self, *_):
        active = bpy.context.view_layer.objects.active
        if active and active.mode != 'OBJECT':
            set_mode(active, 'OBJECT')
        for obj in bpy.context.view_layer.objects:
            if obj.select_get():
                obj.select_set(False)
        for obj in self.selected:
            if obj.name in bpy.context.view_layer.objects:
                obj.select_set(True)
        if self.obj and self.obj.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = self.obj
            if self.mode != 'OBJECT':
                set_mode(self.obj, self.mode)
        else:
            bpy.context.view_layer.objects.active = None


def object_context(obj):
    """Pin operator context even when a sidebar/outer override has no object."""
    if obj is None or obj.name not in bpy.context.view_layer.objects:
        raise ValueError('Enable the character rig and head collections in the current view layer')
    return bpy.context.temp_override(object=obj, active_object=obj,
                                     selected_objects=[obj], selected_editable_objects=[obj])


def set_mode(obj, mode):
    if obj.mode == mode:
        return
    with object_context(obj):
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode=mode)


def set_joint_positions(rig, names, positions):
    with ContextMode():
        set_mode(rig, 'EDIT')
        for name, position in zip(names, positions):
            bone = rig.data.edit_bones.get(name)
            if bone is None:
                raise ValueError('DNA joint removed during sculpt: '+name)
            delta = Vector(position)-bone.head
            bone.head += delta; bone.tail += delta


def _delete_backups(meta):
    for item in meta['meshes']:
        backup = bpy.data.objects.get(item['backup'])
        if backup:
            data = backup.data
            bpy.data.objects.remove(backup, do_unlink=True)
            if data.users == 0:
                bpy.data.meshes.remove(data)


class Session:
    def __init__(self, rig):
        self.rig = rig
        self.meta = json.loads(rig[SESSION])
        self.head = bpy.data.objects[self.meta['head']]
        self.scale = float(rig[bake.RIG_KEY_SCALE])
        if fingerprint(self.meta['source']) != self.meta['source_hash']:
            raise ValueError('Source DNA changed on disk; restore the original file before resuming')
        self.reader = dnaio.open_reader(Path(self.meta['source']))
        self.base = dna_export.positions(self.reader, self.meta['index'])
        self.previous = decode(self.meta['last_valid'])
        self.pairs = symmetry_pairs(self.base)
        self.field = SurfaceField(self.base, self.previous)

    def close(self):
        dnaio.release_handle(self.reader); self.reader = None

    def save(self):
        self.rig[SESSION] = json.dumps(self.meta, separators=(',', ':'))

    def update(self, force=False):
        if any(m.type != 'ARMATURE' for m in self.head.modifiers):
            raise ValueError('Remove modifiers added during sculpting before continuing')
        if self.head.mode == 'SCULPT' and self.head.use_dynamic_topology_sculpting:
            if not self.rig.mm_sculpt_lock_topology:
                raise ValueError('Disable Dyntopo and undo topology edits before continuing')
            with object_context(self.head):
                bpy.ops.sculpt.dynamic_topology_toggle()
        if self.head.mode == 'EDIT':
            self.head.update_from_editmode()
        if topology(self.head.data) != self.meta['topology']:
            if self.rig.mm_sculpt_lock_topology:
                item = next(m for m in self.meta['meshes'] if m['object'] == self.head.name)
                backup = bpy.data.objects[item['backup']]
                with ContextMode():
                    old = self.head.data; self.head.data = backup.data.copy()
                    set_coords(self.head.data, to_blender(self.previous, self.scale))
                    if old.users == 0:
                        bpy.data.meshes.remove(old)
                self.rig['mm_sculpt_status'] = 'Topology change reverted; last valid sculpt restored'
                return False
            raise ValueError('Topology changed. DNA export requires original vertex IDs; undo the topology edit')
        current = to_dna(coords(self.head.data), self.scale)
        if not force and np.array_equal(current, self.previous):
            return False
        if self.rig.mm_sculpt_symmetry:
            current = sync_symmetry(self.base, self.previous, current, self.pairs)
        field = SurfaceField(self.base, current)
        moved, _, _ = dna_export.adapted_joints(self.reader, field)
        with ContextMode():
            set_coords(self.head.data, to_blender(current, self.scale))
            set_joint_positions(self.rig, self.meta['joint_names'], to_blender(moved, self.scale))
            # Apply the same field to dependent imported meshes and legacy keys.
            # Backups prevent repeated updates accumulating the displacement.
            for item in self.meta['meshes']:
                obj = bpy.data.objects.get(item['object']); backup = bpy.data.objects.get(item['backup'])
                if obj is None or backup is None:
                    raise ValueError('A sculpt-session mesh was removed')
                base = to_dna(coords(backup.data), self.scale)
                target = current if obj == self.head else field.evaluate(base)
                if obj != self.head:
                    set_coords(obj.data, to_blender(target, self.scale))
                jac = None
                if backup.data.has_custom_normals or obj.data.shape_keys:
                    _, jac = field.evaluate(base, jacobian=True)
                if backup.data.has_custom_normals:
                    normals = np.empty(len(backup.data.loops)*3)
                    backup.data.corner_normals.foreach_get('vector', normals)
                    vertices = np.empty(len(backup.data.loops), dtype=np.int32)
                    backup.data.loops.foreach_get('vertex_index', vertices)
                    normals = to_dna(normals.reshape(-1, 3), 1.)
                    normals = np.linalg.solve(jac[vertices].transpose(0, 2, 1), normals[..., None])[..., 0]
                    normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-12)
                    obj.data.normals_split_custom_set(to_blender(normals, 1.).tolist())
                if obj.data.shape_keys and backup.data.shape_keys:
                    keys = obj.data.shape_keys.key_blocks
                    for key in backup.data.shape_keys.key_blocks:
                        values = np.empty(len(key.data)*3)
                        key.data.foreach_get('co', values)
                        delta = to_dna(values.reshape(-1, 3), self.scale)-base
                        regenerated = target+np.einsum('nij,nj->ni', jac, delta)
                        keys[key.name].data.foreach_set('co', to_blender(regenerated, self.scale).ravel())
        self.field = field; self.previous = current
        self.meta['last_valid'] = encode(current); self.save()
        self.rig['mm_sculpt_status'] = 'Joints synchronized; Bake to DNA recalibrates all LODs and correctives'
        return True


def start(rig):
    global _active
    if 'mm_expression_session' in rig or _active is not None or any(SESSION in o for o in bpy.context.scene.objects):
        raise ValueError('Finish, cancel or resume the existing sculpt session first')
    if rig.data.users != 1 or rig.library or len(rig.users_scene) > 1:
        raise ValueError('Make the rig single-user before sculpting')
    head = head_mesh(rig)
    for obj in (rig, head):
        if obj.name not in bpy.context.view_layer.objects:
            raise ValueError('Enable the character rig and head collections in the current view layer')
    source = Path(bpy.path.abspath(rig[bake.RIG_KEY_DNA])).resolve()
    reader = dnaio.open_reader(source)
    try:
        index = mesh_index(head, reader)
        names = [reader.getJointName(i) for i in range(reader.getJointCount())]
        if any(n not in rig.data.bones for n in names):
            raise ValueError('The rig is missing original DNA joints')
        matrices, _ = dna_export.joint_rest(reader)
        rest = np.array([rig.data.bones[n].head_local[:] for n in names])
        if not np.allclose(rest, to_blender(matrices[:, :3, 3], rig[bake.RIG_KEY_SCALE]), atol=3e-6, rtol=1e-6):
            raise ValueError('Rest joints were edited outside the sculpt workflow; restore them before starting')
        meshes = bake.head_meshes(rig)
        for mesh in meshes:
            if mesh.data.users != 1 or mesh.library or len(mesh.users_scene) > 1:
                raise ValueError('Make character meshes single-user before sculpting')
            if not np.allclose(np.array(mesh.matrix_local), np.eye(4), atol=1e-6):
                raise ValueError('Character mesh object transforms changed; use vertex editing instead')
            if any(m.type != 'ARMATURE' for m in mesh.modifiers):
                raise ValueError('Remove topology/evaluation modifiers before starting a DNA sculpt')
        meta = {'source': str(source), 'source_hash': fingerprint(source), 'head': head.name,
                'index': index, 'topology': topology(head.data), 'pose': rig.data.pose_position,
                'joint_names': names, 'joints': [list(rig.data.bones[n].head_local) for n in names],
                'last_valid': encode(to_dna(coords(head.data), rig[bake.RIG_KEY_SCALE])), 'meshes': []}
        collection = organization.child_collection(rig.users_collection[0], 'SCULPT_BACKUP')
        collection[cleanup.OWNER] = rig.get(cleanup.OWNER, '')
        for mesh in meshes:
            backup = bpy.data.objects.new('MM_SCULPT_BACKUP', mesh.data.copy())
            collection.objects.link(backup)
            backup.hide_viewport = True; backup.hide_render = True; backup.hide_select = True
            backup[cleanup.OWNER] = rig.get(cleanup.OWNER, '')
            backup.data[cleanup.OWNER] = rig.get(cleanup.OWNER, '')
            meta['meshes'].append({'object': mesh.name, 'backup': backup.name})
        rig[SESSION] = json.dumps(meta); rig.data.pose_position = 'REST'
        if 'mm_sculpt_original_dna' not in rig:
            rig['mm_sculpt_original_dna'] = str(source)
        _active = Session(rig)
        try:
            _active.update(force=True)
        except Exception:
            cancel(rig)
            raise
        _start_timer()
        return _active
    finally:
        dnaio.release_handle(reader)


def pause():
    global _active
    if _active:
        _active.close(); _active = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)


def resume(rig):
    global _active
    if _active:
        if _active.rig == rig:
            return _active
        raise ValueError('Another sculpt session is active')
    _active = Session(rig)
    try:
        _active.update(force=True)
    except Exception:
        pause()
        raise
    _start_timer()
    return _active


def cancel(rig):
    pause()
    meta = json.loads(rig[SESSION])
    if any(item['object'] not in bpy.data.objects or item['backup'] not in bpy.data.objects for item in meta['meshes']):
        raise ValueError('A session mesh or backup is missing/renamed; restore it before cancelling')
    with ContextMode():
        for item in meta['meshes']:
            obj = bpy.data.objects.get(item['object']); backup = bpy.data.objects.get(item['backup'])
            if obj and backup:
                old = obj.data; obj.data = backup.data.copy()
                if old.users == 0:
                    bpy.data.meshes.remove(old)
        set_joint_positions(rig, meta['joint_names'], meta['joints'])
        rig.data.pose_position = meta['pose']
    _delete_backups(meta)
    del rig[SESSION]
    rig['mm_sculpt_status'] = 'Sculpt cancelled; original geometry and joints restored'


def prepare(rig, destination=None):
    """Bake once, rebuild the existing native driver graph, end the session."""
    session = resume(rig)
    session.update(force=True)
    if topology(session.head.data) != session.meta['topology']:
        raise ValueError('Undo topology changes before baking')
    if fingerprint(session.meta['source']) != session.meta['source_hash']:
        raise ValueError('Source DNA changed on disk during sculpting')
    if destination is None:
        folder = Path(bpy.utils.user_resource('DATAFILES', path='MetaMorphosis/SculptDNA', create=True))
        destination = folder / (Path(session.meta['source']).stem+'_'+uuid.uuid4().hex+'.dna')
    destination = dna_export.write_dna(session.meta['source'], destination, session.field,
        {session.meta['index']: session.previous})
    # Rebuild's own numeric validation runs before it removes any old drivers.
    old_source = rig[bake.RIG_KEY_DNA]
    with ContextMode():
        bpy.context.view_layer.objects.active = rig; rig.select_set(True)
        rig[bake.RIG_KEY_DNA] = str(destination)
        rig['mm_sculpt_rebuilding'] = True
        try:
            with object_context(rig):
                result = bpy.ops.metamorphosis.rebuild()
            if result != {'FINISHED'}:
                raise RuntimeError('Driver rebuild failed; sculpt session retained for recovery')
        except Exception:
            rig[bake.RIG_KEY_DNA] = old_source
            raise
        finally:
            del rig['mm_sculpt_rebuilding']
        rig.data.pose_position = session.meta['pose']
    meta = session.meta
    pause(); _delete_backups(meta); del rig[SESSION]
    rig['mm_sculpt_prepared'] = str(destination)
    rig['mm_sculpt_status'] = 'Baked; expressions recalibrated. Export DNA saves a portable copy'
    return destination


def _tick():
    if _active is None:
        return None
    try:
        if _active.rig.name not in bpy.context.scene.objects or SESSION not in _active.rig:
            pause(); return None
        if not bpy.context.screen or not bpy.context.screen.is_animation_playing:
            _active.update()
    except Exception as error:
        try:
            _active.rig['mm_sculpt_status'] = str(error)
        except (ReferenceError, AttributeError):
            pass
        pause(); return None
    return .5


def _start_timer():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=.5)


@persistent
def _pause_handler(*_):
    pause()


def selected_rig(context):
    obj = context.view_layer.objects.active
    if obj and obj.get('mm_expression_rig'):
        return bpy.data.objects.get(obj['mm_expression_rig'])
    return bake.find_baked_rig(context)


class MM_OT_sculpt_start(bpy.types.Operator):
    bl_idname = 'metamorphosis.sculpt_start'
    bl_label = 'Start 4D Sculpt'
    bl_description = 'Edit the neutral head with joint following; preserves current face-board pose'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            rig = selected_rig(context)
            if rig is None:
                raise ValueError('Select a MetaMorphosis rig or head mesh')
            session = resume(rig) if SESSION in rig else start(rig)
            active = context.view_layer.objects.active
            if active and active.mode != 'OBJECT':
                set_mode(active, 'OBJECT')
            for obj in context.view_layer.objects:
                if obj.select_get():
                    obj.select_set(False)
            session.head.select_set(True); context.view_layer.objects.active = session.head
            self.report({'INFO'}, 'Edit the neutral head in Sculpt or Edit Mode; topology must stay unchanged')
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


class MM_OT_sculpt_cancel(bpy.types.Operator):
    bl_idname = 'metamorphosis.sculpt_cancel'
    bl_label = 'Cancel Sculpt'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            cancel(selected_rig(context)); return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


class MM_OT_sculpt_bake(bpy.types.Operator):
    bl_idname = 'metamorphosis.sculpt_bake'
    bl_label = 'Bake to DNA'
    bl_description = 'Recalibrate all LODs, joint translations and corrective targets, then rebuild native drivers'

    def execute(self, context):
        try:
            prepare(selected_rig(context))
            self.report({'INFO'}, 'DNA prepared and native expression drivers rebuilt')
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


class MM_OT_export_dna(bpy.types.Operator, ExportHelper):
    bl_idname = 'metamorphosis.export_dna'
    bl_label = 'Export DNA'
    filename_ext = '.dna'
    filter_glob: StringProperty(default='*.dna', options={'HIDDEN'})

    def invoke(self, context, event):
        rig = selected_rig(context)
        if rig and not self.filepath:
            self.filepath = Path(rig[bake.RIG_KEY_DNA]).stem+'_edited.dna'
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            rig = selected_rig(context)
            if rig is None:
                raise ValueError('Select a MetaMorphosis rig')
            if SESSION in rig or 'mm_expression_session' in rig:
                raise ValueError('Use Bake to DNA before exporting the active sculpt')
            source = Path(bpy.path.abspath(rig[bake.RIG_KEY_DNA])).resolve()
            target = Path(self.filepath).resolve()
            original = Path(bpy.path.abspath(rig.get('mm_sculpt_original_dna', str(source)))).resolve()
            if target == original:
                raise ValueError('Choose a new DNA filename; the original DNA is protected')
            reader = dnaio.open_reader(source)
            try:
                head = head_mesh(rig)
                index = mesh_index(head, reader)
                if not np.allclose(to_dna(coords(head.data), rig[bake.RIG_KEY_SCALE]),
                                   dna_export.positions(reader, index), atol=2e-5, rtol=2e-6):
                    raise ValueError('Unbaked head edits detected; use Start 4D Sculpt and Bake to DNA first')
                check_export_geometry(rig, reader)
            finally:
                dnaio.release_handle(reader)
            dna_export.write_dna(source, target)
            # Use the portable export for future Rebuild instead of a local cache.
            rig[bake.RIG_KEY_DNA] = str(target)
            rig['mm_sculpt_original_dna'] = str(original)
            self.report({'INFO'}, 'DNA exported with original topology, LODs and control mappings')
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


class MM_PT_sculpt(bpy.types.Panel):
    bl_label = '4D Sculpt'
    bl_idname = 'MM_PT_sculpt'
    bl_parent_id = 'MM_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MetaMorphosis'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        from . import expression_sculpt
        layout = self.layout
        rig = selected_rig(context)
        if rig is None:
            layout.label(text='Select an imported character')
            return
        layout.label(text=rig.name, icon='ARMATURE_DATA')
        layout.prop(rig, 'mm_sculpt_symmetry')
        if expression_sculpt.SESSION in rig:
            meta = json.loads(rig[expression_sculpt.SESSION])
            layout.label(text='Editing: '+meta['name'])
            layout.label(text='Sculpt the working copy; keep this pose')
            layout.label(text='Original topology is required')
            layout.operator('metamorphosis.expression_apply', icon='CHECKMARK')
            layout.operator('metamorphosis.expression_cancel', icon='LOOP_BACK')
        elif SESSION in rig:
            layout.prop(rig, 'mm_sculpt_lock_topology')
            if _active is None:
                layout.operator('metamorphosis.sculpt_start', text='Resume Sculpt')
            layout.label(text='Edit the neutral HEAD mesh')
            layout.label(text='Dyntopo / remesh are not supported')
            layout.operator('metamorphosis.sculpt_bake', icon='CHECKMARK')
            layout.operator('metamorphosis.sculpt_cancel', icon='LOOP_BACK')
        else:
            layout.prop(rig, 'mm_sculpt_lock_topology')
            layout.operator('metamorphosis.sculpt_start', text='Sculpt Neutral Mesh', icon='SCULPTMODE_HLT')
            layout.operator('metamorphosis.expression_start', icon='POSE_HLT')
            layout.operator('metamorphosis.export_dna', icon='EXPORT')
        if rig.get('mm_sculpt_status'):
            box = layout.box()
            import textwrap
            for line in textwrap.wrap(rig['mm_sculpt_status'], 40):
                box.label(text=line)


CLASSES = (MM_OT_sculpt_start, MM_OT_sculpt_cancel, MM_OT_sculpt_bake, MM_OT_export_dna, MM_PT_sculpt)


def register():
    bpy.types.Object.mm_sculpt_lock_topology = BoolProperty(name='Lock Topology', default=True,
        description='Restore the last valid sculpt if vertex count or connectivity changes; export always requires original topology')
    bpy.types.Object.mm_sculpt_symmetry = BoolProperty(name='Symmetry Sync', default=False,
        description='Mirror new sculpt displacements across anatomical X; preserves original facial asymmetry')
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if _pause_handler not in handlers:
            handlers.append(_pause_handler)


def unregister():
    pause()
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if _pause_handler in handlers:
            handlers.remove(_pause_handler)
    del bpy.types.Object.mm_sculpt_lock_topology
    del bpy.types.Object.mm_sculpt_symmetry
