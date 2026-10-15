"""DCC textures and native DNA animated-map drivers; no playback callbacks."""
import json
from pathlib import Path
import re

import bpy
from bpy.props import StringProperty

from . import bake, bakeplan, cleanup, dnaio, verify
from .exprplan import fmt_num
from .logicmodel import RigLogicModel

ASSET = Path(__file__).parent / 'assets' / 'wrinkle_materials.blend'
EYE_EDGE_ASSET = ASSET.with_name('eye_edge_materials.blend')
UNIVERSAL_TEXTURES = ('Teeth_Color.png', 'Teeth_Normal.png', 'EyeLashes_Alpha.PNG',
                      'T_SkinMicroNormal.PNG', 'T_SkinMicro3_N.PNG')


def caps(name):
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_').upper()


def rename_created(before):
    for pool in ('materials','node_groups'):
        collection = getattr(bpy.data,pool)
        for item in collection:
            if item.as_pointer() in before[pool]:
                continue
            base = candidate = caps(item.name)
            count = 1
            while collection.get(candidate) not in (None,item):
                candidate = f'{base}_{count:03d}'; count += 1
            item.name = candidate


def retire_material_sets(tokens):
    """Drop replaced generated graphs only when no other scene/user data references them."""
    for token in tokens:
        owned = {item for pool in cleanup.POOLS for item in getattr(bpy.data,pool)
                 if item.get('mm_material_set') == token}
        if not owned:
            continue
        users = bpy.data.user_map(subset=owned)
        containers = {bpy.context.scene, *cleanup.scene_collections(bpy.context.scene)}
        protected = any(item.use_fake_user or any(user not in owned and user not in containers
                        for user in users.get(item,set())) for item in owned)
        if protected:
            continue
        bpy.data.batch_remove(ids=owned)


def texture_files(folder):
    """Accept the export root or Maps; respect manifest folders without broad searches."""
    root = Path(bpy.path.abspath(folder))
    if not root.is_dir():
        raise ValueError('Choose the Unreal DCC export folder or its Maps folder')
    if root.name.lower() == 'maps':
        root = root.parent
    locations = [root, root/'Maps', root/'Masks', root/'Detail Maps']
    manifest = root/'ExportManifest.json'
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding='utf-8-sig'))
        for relative in data.get('folders', {}).values():
            candidate = (root/relative).resolve()
            if candidate.is_relative_to(root.resolve()):
                locations.append(candidate)
    files = {}
    for directory in dict.fromkeys(locations):
        if directory.is_dir():
            for file in sorted(directory.iterdir()):
                if file.is_file() and file.suffix.lower() in {'.png', '.tga', '.jpg', '.jpeg', '.exr'}:
                    files.setdefault(file.stem.lower(), file)
    if 'head_basecolor' not in files:
        raise ValueError('Head_Basecolor texture not found in the selected export')
    # These maps are shared by all characters and never require an external path.
    for name in UNIVERSAL_TEXTURES:
        path = ASSET.parent/name
        if not path.is_file():
            raise ValueError(f'Bundled material texture is missing: {name}')
        files[path.stem.lower()] = path
    return files


def node(tree, kind, name, x=0, y=0):
    n = tree.nodes.new(kind)
    n.name = n.label = caps(name)
    n.location = (x, y)
    return n


def texture(tree, files, key, color=False, x=-900, y=0):
    path = files.get(key.lower())
    if not path:
        return None
    image = bpy.data.images.load(str(path), check_existing=False)
    image.name = caps(path.stem)
    image.colorspace_settings.name = 'sRGB' if color else 'Non-Color'
    image.alpha_mode = 'CHANNEL_PACKED' if not color else 'STRAIGHT'
    if path.is_relative_to(ASSET.parent):
        image.pack()
    n = node(tree, 'ShaderNodeTexImage', key, x, y)
    n.image = image
    return n


def normal(tree, source, bsdf, x=-200, y=-200):
    n = node(tree, 'ShaderNodeNormalMap', 'TANGENT_NORMAL', x, y)
    n.uv_map = 'UVMap'
    if hasattr(n, 'convention'):
        n.convention = 'DIRECTX'
    else:
        # Only older supported Blender versions need this compatibility group.
        legacy = bpy.data.node_groups.new('MM_LEGACY_DIRECTX', 'ShaderNodeTree')
        legacy.interface.new_socket(name='DIRECTX_COLOR', in_out='INPUT', socket_type='NodeSocketColor')
        legacy.interface.new_socket(name='OPENGL_COLOR', in_out='OUTPUT', socket_type='NodeSocketColor')
        entry = node(legacy, 'NodeGroupInput', 'INPUT', -600)
        separate = node(legacy, 'ShaderNodeSeparateXYZ', 'CHANNELS', -400)
        flip = node(legacy, 'ShaderNodeMath', 'INVERT_GREEN', -200, -140)
        flip.operation = 'SUBTRACT'; flip.inputs[0].default_value = 1
        combine = node(legacy, 'ShaderNodeCombineXYZ', 'NORMAL_COLOR', 0)
        out = node(legacy, 'NodeGroupOutput', 'OUTPUT', 200)
        legacy.links.new(entry.outputs[0], separate.inputs[0])
        legacy.links.new(separate.outputs['X'], combine.inputs['X'])
        legacy.links.new(separate.outputs['Y'], flip.inputs[1])
        legacy.links.new(flip.outputs[0], combine.inputs['Y'])
        legacy.links.new(separate.outputs['Z'], combine.inputs['Z'])
        legacy.links.new(combine.outputs[0], out.inputs[0])
        convert = node(tree, 'ShaderNodeGroup', 'LEGACY_NORMAL_CONVENTION', x-220, y)
        convert.node_tree = legacy
        tree.links.new(source, convert.inputs[0])
        source = convert.outputs[0]
    tree.links.new(source, n.inputs['Color'])
    if bsdf is not None:
        tree.links.new(n.outputs[0], bsdf.inputs['Normal'])
    return n


def animated_rows(reader, lod):
    columns = [list(getattr(reader, 'getAnimatedMap'+name)()) for name in
               ('InputIndices', 'OutputIndices', 'FromValues', 'ToValues', 'SlopeValues', 'CutValues')]
    if len({len(c) for c in columns}) != 1:
        raise ValueError('Invalid DNA animated-map table')
    lods = list(reader.getAnimatedMapLODs())
    count = lods[min(lod, len(lods)-1)] if lods else len(columns[0])
    rows = {}
    for source, target, low, high, slope, cut in list(zip(*columns))[:count]:
        rows.setdefault(int(target), []).append((int(source), low, high, slope, cut))
    return rows


def wrinkle_plan(reader, model, variant, board, lod=0):
    """Keep full animated-map PSD combinations independently of Lite joint pruning."""
    plan = bakeplan.Plan()
    builder = bakeplan._Builder(model, variant, plan)
    builder.face_board_bones = set(board.pose.bones.keys())
    rows = animated_rows(reader, lod)
    outputs = {}
    identical = {}
    for index in range(reader.getAnimatedMapCount()):
        name = str(reader.getAnimatedMapName(index))
        table = tuple(rows.get(index, []))
        if table in identical:
            outputs[name] = identical[table]
            continue
        prop = f'mm_am{index}'
        plan.props[prop] = 0.0
        terms = []
        for source, low, high, slope, cut in table:
            if source >= model.raw_count + model.psd_count:
                raise ValueError('Animated map requires unsupported ML/RBF inputs')
            source_prop = builder.ensure_u(source)
            terms.append((f'({{0}}*{fmt_num(slope,9)}+{fmt_num(cut,9)})'
                          f'*({{0}}>={fmt_num(low,9)})*({{0}}<={fmt_num(high,9)})', [source_prop]))
        builder.emit_chunked(terms, '+', ('prop', prop), 'animated-map',
                             lambda vn, key: bakeplan.Var(vn, 'prop', key), clamp=(0, 1))
        outputs[name] = identical[table] = prop
    return plan, outputs


def realize_wrinkles(reader, model, variant, rig, board, group, collection, prefix, lod):
    plan, outputs = wrinkle_plan(reader, model, variant, board, lod)
    holders = [bake.create_data_object(collection, prefix+'_WRINKLES', i)
               for i in range(bake.holders_needed(plan))]
    lookup = {}
    for holder, names in zip(holders, bake.helper_groups(plan)):
        holder['mm_values'] = [float(plan.props[n]) for n in names]
        lookup.update({n: (holder, i) for i, n in enumerate(names)})
    counts = {'drivers': 0, 'variables': 0, 'not_simple': 0}
    for n in plan.nodes:
        holder, index = lookup[n.target[1]]
        bake._add_driver(holder, '["mm_values"]', index, n, holder_of=lookup,
                         rig=rig, board=board, counters=counts)
    for socket, name in wrinkle_sockets(group):
        prop = outputs.get(name)
        socket.default_value = 0
        if prop:
            n = bakeplan.Node((), 'SUM', '', [bakeplan.Var('w', 'prop', prop)])
            bake._add_driver(socket, 'default_value', -1, n, holder_of=lookup,
                             rig=rig, board=board, counters=counts)
    # The supplied shader uses the same mask for color and normals. Reject mismatched DNA
    # rather than silently applying normal weights to a different color behavior.
    for name, prop in outputs.items():
        if '_normal.' in name:
            color_name = name.replace('_wm', '_cm', 1).replace('_normal.', '_color.')
            if color_name in outputs and outputs[color_name] != prop:
                raise ValueError('This DNA has separate color/normal wrinkle weights; shared masks are incompatible')
    return counts['drivers'], holders


def load_wrinkles(prefix):
    with bpy.data.libraries.load(str(ASSET), link=False) as (source, target):
        target.node_groups = ['MM_WRINKLE_BLEND']
    root = target.node_groups[0]
    seen = set()
    def rename(group):
        if group in seen:
            return
        seen.add(group)
        group.name = caps(prefix+'_'+group.name)
        group.use_fake_user = False
        original = {}
        counts = {}
        for socket in group.interface.items_tree:
            if socket.item_type != 'SOCKET':
                continue
            original[socket.identifier] = socket.name
            name = {'cm_base':'BASE_COLOR', 'wm_base':'BASE_NORMAL',
                    'Color':'COLOR', 'Normal':'NORMAL', 'Mask':'MASK'}.get(socket.name, caps(socket.name))
            counts[name] = counts.get(name, 0)+1
            socket.name = name if counts[name] == 1 else f'{name}_{counts[name]:02d}'
        group['mm_original_sockets'] = json.dumps(original)
        for n in group.nodes:
            if n.type == 'GROUP':
                rename(n.node_tree)
    rename(root)
    return root


def wrinkle_sockets(group):
    """DNA names stay independent of presentation names and interface order."""
    original = json.loads(group.node_tree.get('mm_original_sockets', '{}'))
    for socket in group.inputs:
        name = original.get(socket.identifier, socket.name)
        if '.head_' in name:
            wm, mask = name.split('.', 1)
            yield socket, f'head_{wm}_normal.'+mask.removesuffix('_msk')


def wrinkle_node(material):
    surface = material.node_tree.nodes.get('DNA_MATERIAL')
    return surface.node_tree.nodes.get('DNA_WRINKLES') if surface else material.node_tree.nodes.get('DNA_WRINKLES')


def socket(tree, name, kind, direction='INPUT', default=None):
    s = tree.interface.new_socket(name=name, in_out=direction, socket_type='NodeSocket'+kind)
    if default is not None:
        s.default_value = default
    return s


def detail_group(prefix, files):
    """Keep tiling/mixing and tangent-space detail out of the main material view."""
    tree = bpy.data.node_groups.new(caps(prefix+'_SKIN_DETAIL'), 'ShaderNodeTree')
    socket(tree, 'BASE_NORMAL', 'Vector')
    socket(tree, 'DETAIL_STRENGTH', 'Float', default=.15)
    socket(tree, 'DETAIL_TILING', 'Float', default=20)
    socket(tree, 'NORMAL', 'Vector', 'OUTPUT')
    entry = node(tree, 'NodeGroupInput', 'INPUT', -1200, 350)
    out = node(tree, 'NodeGroupOutput', 'OUTPUT', 850, 100)
    uv = node(tree, 'ShaderNodeTexCoord', 'DETAIL_UV', -1200, -100)
    mapping = node(tree, 'ShaderNodeVectorMath', 'DETAIL_TILING', -1000, -100)
    mapping.operation = 'SCALE'
    tree.links.new(uv.outputs['UV'], mapping.inputs[0])
    tree.links.new(entry.outputs['DETAIL_TILING'], mapping.inputs['Scale'])
    a = texture(tree, files, 'T_SkinMicroNormal', x=-750, y=100)
    b = texture(tree, files, 'T_SkinMicro3_N', x=-750, y=-250)
    mix = node(tree, 'ShaderNodeMixRGB', 'MICRO_DETAIL_BLEND', -450, 100)
    mix.inputs[0].default_value = .5
    for image, index in ((a, 1), (b, 2)):
        tree.links.new(mapping.outputs[0], image.inputs['Vector'])
        tree.links.new(image.outputs['Color'], mix.inputs[index])
    micro = normal(tree, mix.outputs[0], None, -200, 100)
    tree.links.new(entry.outputs['DETAIL_STRENGTH'], micro.inputs['Strength'])
    delta = node(tree, 'ShaderNodeVectorMath', 'DETAIL_NORMAL_DELTA', 50, 100)
    delta.operation = 'SUBTRACT'
    geom = node(tree, 'ShaderNodeNewGeometry', 'SURFACE_NORMAL', -200, -200)
    tree.links.new(micro.outputs[0], delta.inputs[0])
    tree.links.new(geom.outputs['Normal'], delta.inputs[1])
    total = node(tree, 'ShaderNodeVectorMath', 'COMBINED_NORMAL', 300, 100)
    total.operation = 'ADD'
    tree.links.new(entry.outputs['BASE_NORMAL'], total.inputs[0])
    tree.links.new(delta.outputs[0], total.inputs[1])
    unit = node(tree, 'ShaderNodeVectorMath', 'NORMALIZE_DETAIL', 550, 100)
    unit.operation = 'NORMALIZE'
    tree.links.new(total.outputs[0], unit.inputs[0])
    tree.links.new(unit.outputs[0], out.inputs['NORMAL'])
    return tree


HEAD_INPUTS = (('BASE_COLOR', 'cm_base'), ('COLOR_WRINKLE_1', 'cm1'),
               ('COLOR_WRINKLE_2', 'cm2'), ('COLOR_WRINKLE_3', 'cm3'),
               ('BASE_NORMAL', 'wm_base'), ('NORMAL_WRINKLE_1', 'wm1'),
               ('NORMAL_WRINKLE_2', 'wm2'), ('NORMAL_WRINKLE_3', 'wm3'))


def head_group(prefix, files, animated):
    tree = bpy.data.node_groups.new(caps(prefix+'_DNA_MATERIAL'), 'ShaderNodeTree')
    for name, _ in HEAD_INPUTS:
        socket(tree, name, 'Color', default=(.5,.5,1,1) if 'NORMAL' in name else (.5,.5,.5,1))
    socket(tree, 'SPECULAR_ROUGHNESS_METALLIC', 'Color', default=(.5,.45,0,1))
    socket(tree, 'FUZZ_MASK', 'Float', default=0)
    socket(tree, 'DETAIL_STRENGTH', 'Float', default=.15)
    socket(tree, 'DETAIL_TILING', 'Float', default=20)
    for name, kind in (('COLOR','Color'), ('NORMAL','Vector'), ('SPECULAR','Float'),
                       ('ROUGHNESS','Float'), ('METALLIC','Float'), ('SHEEN','Float')):
        socket(tree, name, kind, 'OUTPUT')
    entry = node(tree, 'NodeGroupInput', 'TEXTURES_AND_SETTINGS', -700, 300)
    entry.width = 260
    out = node(tree, 'NodeGroupOutput', 'SURFACE_CHANNELS', 600, 300)
    color, norm = entry.outputs['BASE_COLOR'], entry.outputs['BASE_NORMAL']
    weights = None
    if animated:
        weights = node(tree, 'ShaderNodeGroup', 'DNA_WRINKLES', -350, 300)
        weights.node_tree = load_wrinkles(prefix)
        original = json.loads(weights.node_tree['mm_original_sockets'])
        inputs = {original[s.identifier]: s for s in weights.inputs}
        for name, original_name in HEAD_INPUTS:
            tree.links.new(entry.outputs[name], inputs[original_name])
        for s, _ in wrinkle_sockets(weights):
            s.hide = True
        weights.width = 230
        color, norm = weights.outputs['COLOR'], weights.outputs['NORMAL']
    tree.links.new(color, out.inputs['COLOR'])
    tangent = normal(tree, norm, None, -70, 100)
    detail = node(tree, 'ShaderNodeGroup', 'SKIN_DETAIL', 170, 100)
    detail.node_tree = detail_group(prefix, files)
    tree.links.new(tangent.outputs[0], detail.inputs['BASE_NORMAL'])
    for name in ('DETAIL_STRENGTH', 'DETAIL_TILING'):
        tree.links.new(entry.outputs[name], detail.inputs[name])
    tree.links.new(detail.outputs['NORMAL'], out.inputs['NORMAL'])
    packed = node(tree, 'ShaderNodeSeparateColor', 'SRMF_CHANNELS', -350, -300)
    tree.links.new(entry.outputs['SPECULAR_ROUGHNESS_METALLIC'], packed.inputs[0])
    for channel, name in (('Red','SPECULAR'), ('Green','ROUGHNESS'), ('Blue','METALLIC')):
        tree.links.new(packed.outputs[channel], out.inputs[name])
    fuzz = node(tree, 'ShaderNodeMath', 'FUZZ_STRENGTH', -70, -300)
    fuzz.operation = 'MULTIPLY'; fuzz.inputs[1].default_value = .15
    tree.links.new(entry.outputs['FUZZ_MASK'], fuzz.inputs[0])
    tree.links.new(fuzz.outputs[0], out.inputs['SHEEN'])
    return tree, weights


def frame(tree, title, children, location):
    f = node(tree, 'NodeFrame', title, *location)
    f.label = title.replace('_', ' ')
    f.use_custom_color = True; f.color = (.12,.16,.20)
    f.label_size = 22
    for child, x, y in children:
        if child:
            child.parent = f
            child.location = (x, y)
            child.width = 220
    return f


def head_material(tree, bsdf, files, prefix, scale):
    bsdf.inputs['Subsurface Weight'].default_value = .4
    bsdf.inputs['Subsurface Radius'].default_value = (1, .2, .1)
    bsdf.inputs['Subsurface Scale'].default_value = .005*scale/.01
    bsdf.inputs['IOR'].default_value = 1.4
    g = node(tree, 'ShaderNodeGroup', 'DNA_MATERIAL', 0, 300)
    g.width = 280
    animated = all(f'head_normal_animated_wm{i}' in files for i in (1,2,3)) and 'head_normal' in files and ASSET.is_file()
    g.node_tree, weights = head_group(prefix, files, animated)
    base = texture(tree, files, 'Head_Basecolor', True)
    norm = texture(tree, files, 'Head_Normal')
    packed = texture(tree, files, 'Head_SRMF')
    tree.links.new(base.outputs['Color'], g.inputs['BASE_COLOR'])
    if norm:
        tree.links.new(norm.outputs['Color'], g.inputs['BASE_NORMAL'])
    if packed:
        tree.links.new(packed.outputs['Color'], g.inputs['SPECULAR_ROUGHNESS_METALLIC'])
        tree.links.new(packed.outputs['Alpha'], g.inputs['FUZZ_MASK'])
    frame(tree, 'BASE_TEXTURES', [(base,0,0),(norm,260,0),(packed,520,0)], (-1100,350))
    colors, normals = [], []
    if animated:
        for i in (1,2,3):
            cm = texture(tree, files, f'Head_Basecolor_Animated_CM{i}', True)
            wm = texture(tree, files, f'Head_Normal_Animated_WM{i}')
            tree.links.new((cm or base).outputs['Color'], g.inputs[f'COLOR_WRINKLE_{i}'])
            tree.links.new(wm.outputs['Color'], g.inputs[f'NORMAL_WRINKLE_{i}'])
            colors.append((cm,(i-1)*260,0)); normals.append((wm,(i-1)*260,0))
        frame(tree, 'COLOR_WRINKLES', colors, (-1100,780))
        frame(tree, 'NORMAL_WRINKLES', normals, (-1100,-80))
    else:
        for name, _ in HEAD_INPUTS:
            if 'WRINKLE' in name:
                g.inputs[name].hide = True
    for source, target in (('COLOR','Base Color'), ('NORMAL','Normal'), ('SPECULAR','Specular IOR Level'),
                           ('ROUGHNESS','Roughness'), ('METALLIC','Metallic'), ('SHEEN','Sheen Weight')):
        tree.links.new(g.outputs[source], bsdf.inputs[target])
    return weights


def eye_edge_material(prefix, side):
    with bpy.data.libraries.load(str(EYE_EDGE_ASSET), link=False) as (_, target):
        target.materials = ['MM_EYE_EDGE_'+side]
    mat = target.materials[0]
    mat.name = caps(prefix+'_EYE_EDGE_'+side)
    mat.use_fake_user = False
    tree = mat.node_tree
    # Keep the supplied side-specific ramps/mapping and surface values intact.
    bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    if 'Thin Wall' in bsdf.inputs:
        bsdf.inputs['Thin Wall'].default_value = True
    # The supplied 5.2 material uses DIRECTX. The portable 5.0 library cannot
    # store that enum, so restore it (or its compatibility group) on append.
    original_normal = next(n for n in tree.nodes if n.type == 'NORMAL_MAP')
    source = original_normal.inputs['Color'].links[0].from_socket
    strength = original_normal.inputs['Strength'].default_value
    tree.nodes.remove(original_normal)
    tangent = normal(tree, source, bsdf)
    tangent.name = 'Normal Map'
    tangent.inputs['Strength'].default_value = strength
    for n in tree.nodes:
        if n.type == 'NORMAL_MAP':
            n.uv_map = 'UVMap'
        if n.type == 'TEX_IMAGE':
            n.image.pack()
        n.name = n.label = caps(n.name)
    frame(tree, 'PROCEDURAL_EDGE_FADE', [(tree.nodes[name],i*240,0) for i,name in enumerate(
        ('TEXTURE_COORDINATE','MAPPING','GRADIENT_TEXTURE','COLOR_RAMP'))], (-1100,450))
    details = ['TEXTURE_COORDINATE_001','MAPPING_001','IMAGE_TEXTURE']
    if 'LEGACY_NORMAL_CONVENTION' in tree.nodes:
        details.append('LEGACY_NORMAL_CONVENTION')
    details.append('NORMAL_MAP')
    frame(tree, 'SURFACE_DETAIL', [(tree.nodes[name],i*240,0) for i,name in enumerate(details)], (-1100,-50))
    bsdf.location = (400,450); bsdf.width = 240
    output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL')
    output.location = (750,450)
    return mat


def setup(reader, model, variant, rig, board, meshes, folder, collection, prefix, lod=0):
    files = texture_files(folder)
    before = cleanup.snapshot()
    token = rig.get(cleanup.OWNER) or cleanup.new_token()
    material_set = cleanup.new_token()
    assignments, warnings, holders = [], [], []
    driver_count = 0
    try:
        for mesh in meshes:
            kind = str(mesh.get('mm_mesh_kind', mesh.name.rsplit('_',1)[-1])).lower()
            if 'head' in kind:
                category, color, norm = 'HEAD', 'Head_Basecolor', 'Head_Normal'
            elif 'teeth' in kind:
                category, color, norm = 'TEETH', 'Teeth_Color', 'Teeth_Normal'
            elif 'eyeleft' in kind or 'eyeright' in kind:
                category, color, norm = caps(kind), 'Eyes_Color', 'Eyes_Normal'
            elif 'eyelash' in kind:
                category, color, norm = 'EYELASHES', '', ''
            elif kind in {'eyeedge_l', 'eyeedge_r'}:
                mat = eye_edge_material(prefix, kind[-1].upper())
                mat['mm_material_version'] = '1.2.0'
                assignments.append((mesh, mat))
                continue
            elif 'eyeshell' in kind or 'saliva' in kind or 'eyeedge' in kind:
                category, color, norm = caps(kind), '', ''
                if 'eyeedge' in kind:
                    warnings.append('Legacy combined eye-edge mesh: reimport DNA for separate left/right procedural eye edges')
            else:
                warnings.append(f'No material preset for {mesh.name}; existing slots preserved')
                continue
            mat = bpy.data.materials.new(caps(prefix+'_'+category))
            mat['mm_material_version'] = '1.2.0'
            tree = mat.node_tree
            tree.nodes.clear()
            bsdf = node(tree, 'ShaderNodeBsdfPrincipled', category+'_SURFACE', 400, 300)
            bsdf.width = 240
            output = node(tree, 'ShaderNodeOutputMaterial', 'MATERIAL_OUTPUT', 760, 300)
            tree.links.new(bsdf.outputs[0], output.inputs['Surface'])
            base = texture(tree, files, color, True, x=-500, y=400) if color and category != 'HEAD' else None
            nm = texture(tree, files, norm, x=-500, y=0) if norm and category != 'HEAD' else None
            if base:
                tree.links.new(base.outputs['Color'], bsdf.inputs['Base Color'])
            elif color and category != 'HEAD':
                warnings.append(f'{color} is missing; using a fallback material')
            if nm:
                normal(tree, nm.outputs['Color'], bsdf)
            if category == 'HEAD':
                g = head_material(tree,bsdf,files,prefix,float(rig.get(bake.RIG_KEY_SCALE,.01)))
                if g:
                    count, new_holders = realize_wrinkles(reader,model,variant,rig,board,g,collection,prefix,lod)
                    driver_count += count; holders += new_holders
                else:
                    warnings.append('Animated normal maps missing; head uses static shading')
                frame(tree, 'SURFACE_OUTPUT', [(bsdf,0,0),(output,320,0)], (400,300))
            elif category == 'TEETH':
                bsdf.inputs['Roughness'].default_value = .28
                bsdf.inputs['Subsurface Weight'].default_value = .08
                bsdf.inputs['Subsurface Scale'].default_value = .001
            elif color == 'Eyes_Color':
                bsdf.inputs['Roughness'].default_value = .22
                bsdf.inputs['Coat Weight'].default_value = .3
            elif category == 'EYELASHES':
                bsdf.inputs['Base Color'].default_value = (.015,.008,.005,1)
                alpha = texture(tree, files, 'EyeLashes_Alpha', x=-200, y=300)
                # The supplied image is grayscale coverage, not its opaque PNG alpha.
                tree.links.new(alpha.outputs['Color'],bsdf.inputs['Alpha'])
                bsdf.inputs['Roughness'].default_value = .4
            else:
                # Transparent wet overlay preserves the iris and mouth below it.
                tree.links.remove(output.inputs['Surface'].links[0])
                transparent = node(tree,'ShaderNodeBsdfTransparent','CLEAR_OVERLAY',700,-100)
                tree.links.new(transparent.outputs[0],output.inputs['Surface'])
            assignments.append((mesh,mat))
        old_sets = {mesh.data.materials[0].get('mm_material_set') for mesh,mat in assignments
                    if mesh.data.materials and mesh.data.materials[0]}
        for mesh, mat in assignments:
            if mesh.data.materials:
                mesh.data.materials[0] = mat
            else:
                mesh.data.materials.append(mat)
        rig['mm_texture_folder'] = str(Path(bpy.path.abspath(folder)))
        rig['mm_material_drivers'] = driver_count
    except Exception:
        # No assignment occurs until every material is built successfully.
        created = [item for pool in cleanup.POOLS for item in getattr(bpy.data,pool)
                   if item.as_pointer() not in before[pool]]
        bpy.data.batch_remove(ids=created)
        raise
    rename_created(before)
    cleanup.mark_created(before,token)
    for pool in cleanup.POOLS:
        for item in getattr(bpy.data,pool):
            if item.as_pointer() not in before[pool]:
                item['mm_material_set'] = material_set
    retire_material_sets(old_sets-{None})
    return [f'Materials: {len(assignments)}; {driver_count} native wrinkle drivers',
            *[f'Warning: {w}' for w in warnings]]


class MM_OT_materials(bpy.types.Operator):
    bl_idname = 'metamorphosis.setup_materials'
    bl_label = 'Apply Materials to Rig'
    bl_options = {'REGISTER','UNDO'}

    def execute(self,context):
        rig = bake.find_baked_rig(context)
        reader = None
        try:
            if rig is None:
                raise ValueError('Select an imported head rig')
            from .operators import get_preferences
            prefs = get_preferences(context)
            bindings = prefs.bindings_folder if prefs else ''
            reader = dnaio.open_reader(Path(rig[bake.RIG_KEY_DNA]),bindings)
            model = RigLogicModel.from_reader(reader)
            _, rl, _ = dnaio.load_bindings(bindings)
            result = verify.verify_model(model,rl,reader,release=dnaio.release_handle)
            if result.status == 'failed':
                raise ValueError(result.message)
            board = bpy.data.objects.get(rig[bake.RIG_KEY_BOARD_OBJECT])
            report = setup(reader,model,result.variant or model.variants()[0],rig,board,
                           bake.head_meshes(rig),context.scene.mm_texture_folder,
                           rig.users_collection[0],rig[bake.RIG_KEY_PREFIX],int(rig.get('mm_lod',0)))
            bake.write_report(report)
            self.report({'INFO'},report[0])
        except Exception as error:
            self.report({'ERROR'},str(error)); return {'CANCELLED'}
        finally:
            if reader is not None:
                dnaio.release_handle(reader)
        return {'FINISHED'}


CLASSES = (MM_OT_materials,)


def register():
    bpy.types.Scene.mm_texture_folder = StringProperty(name='Textures Folder',subtype='DIR_PATH',
        description='Unreal DCC export root or Maps folder; blank imports without textures')


def unregister():
    del bpy.types.Scene.mm_texture_folder
