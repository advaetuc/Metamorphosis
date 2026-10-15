"""Evaluate large joint matrices with native Geometry Nodes fields.

GUI/raw/PSD equations remain simple drivers. A hidden point mesh holds their
values at 10,000x scale; Sample Index and Accumulate Field evaluate the unchanged
rounded joint coefficients in bulk. Each bone driver reads one evaluated point.
All dependencies are Blender data: no handlers, Python expressions or add-on
code are needed for playback, rendering or reopening the saved rig.
"""

from dataclasses import replace

import bpy

from .bakeplan import Node, Var

TAG = "mm_native_sum_data"
SCALE = 10000.0
MIN_TERMS = 50000


def prepare_plan(plan):
    """Replace only the large linear channel stage; retain every coefficient."""
    if plan.stats.get('native_sums'):
        return plan
    terms = sum(len(row) for _, row in getattr(plan, 'linear_channels', []))
    if terms < MIN_TERMS:
        return plan
    removed = {n.target[1] for n in plan.nodes
               if n.level == 'channel-chunk' and n.target[0] == 'prop'}
    nodes = [n for n in plan.nodes if n.level not in {'channel', 'channel-chunk'}]
    inputs = {key for _, row in plan.linear_channels for key, _ in row if key is not None}
    nodes.extend(Node(target, 'SCRIPTED', 'v/10000', [Var('v', 'geometry', '', i)], 'channel')
                 for i, (target, _) in enumerate(plan.linear_channels))
    props = {key: value for key, value in plan.props.items() if key not in removed}
    stats = dict(plan.stats)
    stats.update(native_sums=True, native_sum_terms=terms,
                 native_sum_inputs=len(inputs), expression_drivers=len(plan.nodes),
                 nodes=len(nodes) + len(inputs), properties=len(props))
    return replace(plan, nodes=nodes, props=props, stats=stats)


def create(plan, *, rig, board, collection, holder_of, counters):
    """Create the matrix field and input drivers; return output and owned objects."""
    from . import bake

    owner = rig.get('mm_import_id') or collection.get('mm_import_id')
    prefix = str(rig.get(bake.RIG_KEY_PREFIX, rig.name)).upper()

    def tag(data):
        data[TAG] = True
        if owner:
            data['mm_import_id'] = owner
        return data

    def mesh(role, count):
        name = f'{prefix}_MM_{role}'
        data = tag(bpy.data.meshes.new(name))
        data.vertices.add(count)
        obj = tag(bpy.data.objects.new(name, data))
        collection.objects.link(obj)
        obj.hide_select = obj.hide_render = obj.hide_viewport = True
        return obj

    def attribute(obj, name, kind, values):
        attr = obj.data.attributes.new(name, kind, 'POINT')
        attr.data.foreach_set('value', values)

    inputs = sorted({key for _, row in plan.linear_channels for key, _ in row if key is not None})
    indices = {key: i for i, key in enumerate(inputs)}
    controls = mesh('CONTROL_VALUES', len(inputs) + 1)
    controls.data.vertices[-1].co.x = SCALE  # constant 1 for neutral offsets
    for key, i in indices.items():
        node = Node(('prop', key), 'SCRIPTED', 'v*10000', [Var('v', 'prop', key)])
        bake._add_driver(controls.data, f'vertices[{i}].co', 0, node,
                         holder_of=holder_of, rig=rig, board=board, counters=counters)

    weights, control_indices, channels, ends = [], [], [], []
    for i, (_, row) in enumerate(plan.linear_channels):
        for key, weight in row:
            weights.append(weight)
            control_indices.append(indices.get(key, len(inputs)))
            channels.append(i)
        ends.append(len(weights) - 1)
    coefficients = mesh('JOINT_COEFFICIENTS', len(weights))
    output = mesh('JOINT_VALUES', len(plan.linear_channels))
    attribute(coefficients, 'mm_weight', 'FLOAT', weights)
    attribute(coefficients, 'mm_control', 'INT', control_indices)
    attribute(coefficients, 'mm_channel', 'INT', channels)
    attribute(output, 'mm_end', 'INT', ends)

    group = tag(bpy.data.node_groups.new(f'{prefix}_MM_JOINT_SUMS', 'GeometryNodeTree'))
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    node, link = group.nodes.new, group.links.new

    def named(name, kind):
        n = node('GeometryNodeInputNamedAttribute')
        n.data_type = kind
        n.inputs['Name'].default_value = name
        return n.outputs['Attribute']

    def geometry(obj):
        n = node('GeometryNodeObjectInfo')
        n.inputs['Object'].default_value = obj
        n.transform_space = 'ORIGINAL'
        return n.outputs['Geometry']

    def sample(source, value, index):
        n = node('GeometryNodeSampleIndex')
        n.data_type = 'FLOAT'
        n.domain = 'POINT'
        link(source, n.inputs['Geometry'])
        link(value, n.inputs['Value'])
        link(index, n.inputs['Index'])
        return n.outputs['Value']

    position = node('GeometryNodeInputPosition')
    separate = node('ShaderNodeSeparateXYZ')
    link(position.outputs['Position'], separate.inputs[0])
    value = sample(geometry(controls), separate.outputs['X'], named('mm_control', 'INT'))
    multiply = node('ShaderNodeMath')
    multiply.operation = 'MULTIPLY'
    link(value, multiply.inputs[0])
    link(named('mm_weight', 'FLOAT'), multiply.inputs[1])
    accumulate = node('GeometryNodeAccumulateField')
    accumulate.data_type = 'FLOAT'
    accumulate.domain = 'POINT'
    link(multiply.outputs[0], accumulate.inputs['Value'])
    link(named('mm_channel', 'INT'), accumulate.inputs['Group ID'])
    total = sample(geometry(coefficients), accumulate.outputs['Total'], named('mm_end', 'INT'))
    combine = node('ShaderNodeCombineXYZ')
    link(total, combine.inputs['X'])
    source, destination = node('NodeGroupInput'), node('NodeGroupOutput')
    set_position = node('GeometryNodeSetPosition')
    link(source.outputs['Geometry'], set_position.inputs['Geometry'])
    link(combine.outputs[0], set_position.inputs['Position'])
    link(set_position.outputs['Geometry'], destination.inputs['Geometry'])
    # Keep the inspectable graph ordered by dependency, without overlapping nodes.
    for i, n in enumerate(group.nodes):
        n.location = ((i // 4) * 240, -(i % 4) * 240)
    modifier = output.modifiers.new('MM_JOINT_SUMS', 'NODES')
    modifier.node_group = group
    return output, [controls, coefficients, output]


def remove_objects(objects):
    """Remove helper objects and only their now-unused, tagged matrix data."""
    meshes, groups = set(), set()
    for obj in objects:
        if obj.get(TAG):
            if obj.type == 'MESH' and obj.data.get(TAG):
                meshes.add(obj.data)
            groups.update(mod.node_group for mod in obj.modifiers
                          if mod.type == 'NODES' and mod.node_group and mod.node_group.get(TAG))
        bpy.data.objects.remove(obj, do_unlink=True)
    for group in groups:
        if group.users == 0:
            bpy.data.node_groups.remove(group)
    for mesh in meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
