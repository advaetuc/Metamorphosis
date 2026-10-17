"""Native DNA edits for authored expressions. Existing control indices stay fixed."""
import json
import numpy as np

from . import dna_export, importer
from .sculpt_field import SurfaceField

META = 'MetaMorphosis.ExpressionSculpts'


def records(reader):
    keys = {reader.getMetaDataKey(i) for i in range(reader.getMetaDataCount())}
    if META not in keys:
        return []
    items = json.loads(reader.getMetaDataValue(META))
    controls, channels = set(), set()
    if not isinstance(items, list):
        raise ValueError('Invalid authored-expression DNA metadata')
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid authored-expression DNA metadata')
        control, channel, name = (item.get(k) for k in ('control', 'channel', 'name'))
        if (type(control) is not int or not 0 <= control < reader.getRawControlCount()
                or control in controls or type(channel) is not int
                or not -1 <= channel < reader.getBlendShapeChannelCount()
                or not isinstance(name, str)):
            raise ValueError('Invalid authored-expression DNA indices')
        if channel >= 0:
            if channel in channels or name != reader.getBlendShapeChannelName(channel):
                raise ValueError('Invalid authored-expression DNA channel')
            channels.add(channel)
        controls.add(control)
    return items


def validate_expression(source, output):
    """Guard neutral data, authored target indices and every LOD association."""
    items = records(output)
    authored = {r['channel'] for r in items if r['channel'] >= 0}
    old_authored = {r['channel'] for r in records(source) if r['channel'] >= 0}
    if output.getBlendShapeChannelCount() != source.getBlendShapeChannelCount()+len(authored-old_authored):
        raise ValueError('Unexpected expression channel count')
    for name in ('GUIToRawInputIndices', 'GUIToRawOutputIndices', 'GUIToRawFromValues',
                 'GUIToRawToValues', 'GUIToRawSlopeValues', 'GUIToRawCutValues',
                 'PSDRowIndices', 'PSDColumnIndices', 'PSDValues',
                 'AnimatedMapInputIndices', 'AnimatedMapOutputIndices'):
        if list(getattr(source, 'get'+name)()) != list(getattr(output, 'get'+name)()):
            raise ValueError('Expression edit changed existing control wiring')
    for axis in 'XYZ':
        for kind in ('Translation', 'Rotation'):
            getter = 'getNeutralJoint'+kind+axis+'s'
            if list(getattr(source, getter)()) != list(getattr(output, getter)()):
                raise ValueError('Expression edit changed neutral joints')
    for mesh in range(source.getMeshCount()):
        if not np.array_equal(dna_export.positions(source, mesh), dna_export.positions(output, mesh)):
            raise ValueError('Expression edit changed neutral geometry')
        original_count = source.getBlendShapeTargetCount(mesh)
        is_head = importer._kind_of(output.getMeshName(mesh)).lower() == 'head'
        if output.getBlendShapeTargetCount(mesh) != original_count+(len(authored-old_authored) if is_head else 0):
            raise ValueError('Unexpected expression target count')
        for target in range(original_count):
            channel = source.getBlendShapeChannelIndex(mesh, target)
            if output.getBlendShapeChannelIndex(mesh, target) != channel:
                raise ValueError('Expression edit changed original target indices')
            if channel not in authored:
                for name in ('VertexIndices', 'DeltaXs', 'DeltaYs', 'DeltaZs'):
                    getter = 'getBlendShapeTarget'+name
                    if list(getattr(source, getter)(mesh, target)) != list(getattr(output, getter)(mesh, target)):
                        raise ValueError('Expression edit changed an unrelated DNA target')
        for target in range(output.getBlendShapeTargetCount(mesh)):
            indices = np.asarray(output.getBlendShapeTargetVertexIndices(mesh, target), dtype=int)
            delta = np.column_stack([getattr(output, 'getBlendShapeTargetDelta'+a+'s')(mesh, target) for a in 'XYZ'])
            if (len(indices) != len(delta) or not np.isfinite(delta).all()
                    or np.any(indices < 0) or np.any(indices >= output.getVertexPositionCount(mesh))
                    or len(np.unique(indices)) != len(indices)):
                raise ValueError('Invalid expression target vertices')
    inputs = list(output.getBlendShapeChannelInputIndices())
    outputs = list(output.getBlendShapeChannelOutputIndices())
    for item in items:
        channel = item['channel']
        if channel < 0:
            continue  # Joint-only intermediate preparation.
        pairs = [i for i, c in enumerate(outputs) if c == channel]
        if len(pairs) != 1 or inputs[pairs[0]] != item['control']:
            raise ValueError('Authored expression has an invalid activation mapping')
        for lod in range(output.getLODCount()):
            if channel not in output.getBlendShapeChannelIndicesForLOD(lod) or pairs[0] >= output.getBlendShapeChannelLODs()[lod]:
                raise ValueError('Authored expression is missing from a DNA LOD')
            mappings = [output.getMeshBlendShapeChannelMapping(i)
                        for i in output.getMeshBlendShapeChannelMappingIndicesForLOD(lod)]
            for mesh in output.getMeshIndicesForLOD(lod):
                if importer._kind_of(output.getMeshName(mesh)).lower() == 'head':
                    if not any(m.meshIndex == mesh and m.blendShapeChannelIndex == channel for m in mappings):
                        raise ValueError('Authored expression is missing its head LOD mapping')


def patch_joints(reader, writer, control, offsets):
    """Add one expression's parent-space translation coefficients, once per row."""
    groups, owners, joint_group = [], {}, {}
    for g in range(reader.getJointGroupCount()):
        rows = list(reader.getJointGroupOutputIndices(g))
        cols = list(reader.getJointGroupInputIndices(g))
        values = np.asarray(reader.getJointGroupValues(g), dtype=float).reshape(len(rows), len(cols))
        lods = list(reader.getJointGroupLODs(g))
        tiers = [sum(i < n for n in lods) for i in range(len(rows))]
        groups.append([rows, cols, values, tiers, list(reader.getJointGroupJointIndices(g))])
        for row in rows:
            owners.setdefault(row, g); joint_group.setdefault(row//9, g)
    joint_lods = [set(reader.getJointIndicesForLOD(lod)) for lod in range(reader.getLODCount())]
    changed = set()
    for j, delta in enumerate(offsets):
        for axis, amount in enumerate(delta):
            if abs(amount) < 1e-9:
                continue
            row = j*9+axis
            g = owners.get(row, joint_group.get(j))
            if g is None:
                g = len(groups); joint_group[j] = g
                groups.append([[], [], np.zeros((0, 0)), [], [j]])
            rows, cols, values, tiers, joints = groups[g]
            if control not in cols:
                cols.append(control); values = np.column_stack((values, np.zeros(len(rows))))
            if row not in rows:
                rows.append(row); values = np.vstack((values, np.zeros(len(cols))))
                tiers.append(sum(j in lod for lod in joint_lods))
            values[rows.index(row), cols.index(control)] += amount
            if j not in joints:
                joints.append(j)
            groups[g][2] = values; changed.add(g)
    for g in sorted(changed):
        rows, cols, values, tiers, joints = groups[g]
        order = sorted(range(len(rows)), key=lambda i: tiers[i], reverse=True)
        writer.setJointGroupInputIndices(g, cols)
        writer.setJointGroupOutputIndices(g, [rows[i] for i in order])
        writer.setJointGroupValues(g, values[order].ravel().tolist())
        writer.setJointGroupLODs(g, [sum(t > lod for t in tiers) for lod in range(reader.getLODCount())])
        writer.setJointGroupJointIndices(g, joints)


def write_joints(source, target, control, offsets):
    def edit(reader, writer):
        patch_joints(reader, writer, control, offsets)
        items = records(reader)
        if not any(item['control'] == control for item in items):
            items.append({'control': control, 'channel': -1, 'name': ''})
        writer.setMetaData(META, json.dumps(items))
    return dna_export.write_dna(source, target, edit=edit, validate=validate_expression)


def write_residual(source, target, control, source_mesh, delta):
    """Merge repeated edits into one channel per raw expression; include head LODs."""
    def edit(reader, writer):
        items = records(reader)
        item = next((r for r in items if r['control'] == control), None)
        if item is None:
            item = {'control': control, 'channel': -1, 'name': ''}; items.append(item)
        new_channel = item['channel'] < 0
        if new_channel:
            channel = reader.getBlendShapeChannelCount()
            item.update(channel=channel, name=f'MM_EXPR_{control}_{channel}')
            writer.setBlendShapeChannelName(channel, item['name'])
            writer.setBlendShapeChannelInputIndices([control, *reader.getBlendShapeChannelInputIndices()])
            writer.setBlendShapeChannelOutputIndices([channel, *reader.getBlendShapeChannelOutputIndices()])
            writer.setBlendShapeChannelLODs([n+1 for n in reader.getBlendShapeChannelLODs()])
            writer.clearBlendShapeChannelIndices(); writer.clearLODBlendShapeChannelMappings()
            for lod in range(reader.getLODCount()):
                writer.setBlendShapeChannelIndices(lod, [*reader.getBlendShapeChannelIndicesForLOD(lod), channel])
                writer.setLODBlendShapeChannelMapping(lod, lod)
        channel = item['channel']
        base = dna_export.positions(reader, source_mesh)
        field = SurfaceField(base, base+delta)
        mapping = reader.getMeshBlendShapeChannelMappingCount()
        for mesh in range(reader.getMeshCount()):
            if importer._kind_of(reader.getMeshName(mesh)).lower() != 'head':
                continue
            points = dna_export.positions(reader, mesh)
            extra = delta.copy() if mesh == source_mesh else field.evaluate(points)-points
            targets = [t for t in range(reader.getBlendShapeTargetCount(mesh))
                       if reader.getBlendShapeChannelIndex(mesh, t) == channel]
            if targets:
                t = targets[0]
                indices = np.asarray(reader.getBlendShapeTargetVertexIndices(mesh, t), dtype=int)
                extra[indices] += np.column_stack([getattr(reader, 'getBlendShapeTargetDelta'+a+'s')(mesh, t) for a in 'XYZ'])
            else:
                t = reader.getBlendShapeTargetCount(mesh)
                writer.setBlendShapeChannelIndex(mesh, t, channel)
                writer.setMeshBlendShapeChannelMapping(mapping, mesh, channel); mapping += 1
            indices = np.flatnonzero(np.linalg.norm(extra, axis=1) > 1e-7)
            writer.setBlendShapeTargetVertexIndices(mesh, t, indices.tolist())
            writer.setBlendShapeTargetDeltas(mesh, t, extra[indices].tolist())
        writer.setMetaData(META, json.dumps(items))
    return dna_export.write_dna(source, target, edit=edit, validate=validate_expression)


def load_shapes(reader, meshes):
    """Load only deliberately authored expression targets, never the source library."""
    authored = {r['channel']: r['name'] for r in records(reader) if r['channel'] >= 0}
    result = {}
    if not authored:
        return result
    from . import sculpt
    for obj in meshes:
        if obj.get('mm_mesh_kind', '').lower() != 'head':
            continue
        index = sculpt.mesh_index(obj, reader)
        scale = obj.parent.get('mm_scale', .01)
        for target in range(reader.getBlendShapeTargetCount(index)):
            channel = reader.getBlendShapeChannelIndex(index, target)
            if channel not in authored:
                continue
            if obj.data.shape_keys is None:
                obj.shape_key_add(name='Basis', from_mix=False)
                from .cleanup import OWNER
                if obj.get(OWNER):
                    obj.data.shape_keys[OWNER] = obj[OWNER]
            name = authored[channel]
            key = obj.data.shape_keys.key_blocks.get(name) or obj.shape_key_add(name=name, from_mix=False)
            base = np.empty(len(key.data)*3)
            obj.data.shape_keys.reference_key.data.foreach_get('co', base)
            base = base.reshape(-1, 3)
            indices = np.asarray(reader.getBlendShapeTargetVertexIndices(index, target), dtype=int)
            delta = np.column_stack([getattr(reader, 'getBlendShapeTargetDelta'+a+'s')(index, target) for a in 'XYZ'])
            base[indices] += sculpt.to_blender(delta, scale)
            key.data.foreach_set('co', base.ravel())
            result.setdefault(channel, []).append((obj.data.shape_keys, name))
        obj.data.update()
    return result
