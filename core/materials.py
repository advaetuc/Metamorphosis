"""DCC textures and native DNA animated-map drivers; no playback callbacks."""
import json
from pathlib import Path
import re

import bpy
from bpy.props import StringProperty

from ..riglogic import bake, bakeplan, verify
from . import cleanup
from ..dna import dnaio
from ..riglogic.exprplan import fmt_num
from ..riglogic.logicmodel import RigLogicModel

ASSET = Path(__file__).resolve().parents[1] / 'assets' / 'wrinkle_materials.blend'
EYE_EDGE_ASSET = ASSET.with_name('eye_edge_materials.blend')
UNIVERSAL_TEXTURES = ('Teeth_Color.png', 'Teeth_Normal.png', 'EyeLashes_Alpha.PNG',
                      'T_SkinMicroNormal.PNG', 'T_SkinMicro3_N.PNG',
                      'Eyes_ScleraBasecolor.png', 'Eyes_ScleraNormal.png',
                      'Eyes_Veins.png', 'Eyes_IrisNormal.png', 'Eyes_Dust.png')


def caps(name):
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_').upper()


def rename_created(before):
    if not before:
        return
    for pool in ('materials','node_groups'):
        if pool not in before:
            continue
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
    root = Path(bpy.path.abspath(str(folder)))
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
    if 'head_basecolor' not in files and 'body_basecolor' not in files:
        raise ValueError('Neither Head_Basecolor nor Body_Basecolor texture found in the selected export')
    if 'eyelashes_color' in files and 'eyelashes_alpha' not in files:
        files['eyelashes_alpha'] = files['eyelashes_color']
    for target, variants in (
        ('eyes_irisbasecolor', ('eyes_irisbasecolor', 'eyes_iris_basecolor', 'eyes_iriscolor', 'eye_irisbasecolor')),
        ('eyes_sclerabasecolor', ('eyes_sclerabasecolor', 'eyes_sclera_basecolor', 'eyes_scleracolor', 'eye_sclerabasecolor')),
        ('eyes_veins', ('eyes_veins', 'eyes_vein', 'eye_veins')),
        ('eyes_irisnormal', ('eyes_irisnormal', 'eyes_iris_normal', 'eye_irisnormal')),
        ('eyes_scleranormal', ('eyes_scleranormal', 'eyes_sclera_normal', 'eye_scleranormal')),
        ('eyes_dust', ('eyes_dust', 'eye_dust')),
    ):
        if target not in files:
            for v in variants:
                if v in files:
                    files[target] = files[v]
                    break
    # These maps are shared by all characters and fall back to bundled assets if not in character export.
    for name in UNIVERSAL_TEXTURES:
        path = ASSET.parent/name
        if not path.is_file():
            raise ValueError(f'Bundled material texture is missing: {name}')
        files.setdefault(path.stem.lower(), path)
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


def is_delta_map(image):
    """Detect whether a wrinkle map is a signed delta map centered at 0.5 grey."""
    if not image:
        return False
    w, h = image.size
    if w <= 0 or h <= 0:
        return False
    sample_indices = (
        0,
        4 * (w - 1),
        4 * w * (h - 1),
        4 * (w * h - 1),
        4 * (w // 2),
        4 * (w * (h - 1) + w // 2)
    )
    samples = []
    try:
        for idx in sample_indices:
            r = image.pixels[idx]
            g = image.pixels[idx + 1]
            b = image.pixels[idx + 2]
            samples.append((r, g, b))
    except (IndexError, RuntimeError):
        return False
    if not samples:
        return False
    delta_count = 0
    for r, g, b in samples:
        if (0.44 <= r <= 0.56 and 0.44 <= g <= 0.56 and 0.44 <= b <= 0.56 and
            abs(r - g) < 0.05 and abs(r - b) < 0.05 and abs(g - b) < 0.05):
            delta_count += 1
    return delta_count >= (len(samples) // 2)


def is_normal_delta(image):
    """Detect whether a 0.5-grey delta image contains tangent normal slope vectors."""
    if not image or not is_delta_map(image):
        return False
    w, h = image.size
    if w <= 0 or h <= 0:
        return False
    step = max(1, (w * h) // 1000)
    g_over_r_count = 0
    active_count = 0
    try:
        px = image.pixels
        for i in range(0, len(px), step * 4):
            r = px[i]
            g = px[i+1]
            b = px[i+2]
            if abs(r - 0.5) > 0.04 or abs(g - 0.5) > 0.04 or abs(b - 0.5) > 0.04:
                active_count += 1
                if (g - r) > 0.035:
                    g_over_r_count += 1
    except (IndexError, RuntimeError):
        return False
    return active_count > 10 and (g_over_r_count / active_count) > 0.02


def detect_delta_maps(files):
    """Auto-detect whether wrinkle files use 0.5-grey delta format and detect normal slope bleed."""
    delta_color = False
    delta_normal = False
    is_cm_normal = False
    for i in (1, 2, 3):
        cm_path = files.get(f'head_basecolor_animated_cm{i}')
        if cm_path and Path(cm_path).is_file():
            try:
                probe = bpy.data.images.load(str(cm_path), check_existing=False)
                delta_color = is_delta_map(probe)
                if delta_color:
                    is_cm_normal = is_normal_delta(probe)
                bpy.data.images.remove(probe)
            except Exception:
                pass
            break
    for i in (1, 2, 3):
        wm_path = files.get(f'head_normal_animated_wm{i}')
        if wm_path and Path(wm_path).is_file():
            try:
                probe = bpy.data.images.load(str(wm_path), check_existing=False)
                delta_normal = is_delta_map(probe)
                bpy.data.images.remove(probe)
            except Exception:
                pass
            break
    return delta_color, delta_normal, is_cm_normal


def _configure_delta_merge(tree, is_normal=False, is_cm_normal=False):
    for node_name in ('MIX_006', 'MIX_007', 'MIX_008'):
        n = tree.nodes.get(node_name)
        if not n:
            continue
        for l in list(tree.links):
            if l.to_node == n and l.to_socket.name == 'B':
                tree.links.remove(l)
        n.inputs['B'].default_value = (0.5, 0.5, 0.5, 1.0)
    top_mix = tree.nodes.get('MIX')
    if top_mix:
        top_mix.clamp_result = True
    mix_001 = tree.nodes.get('MIX_001')
    if is_normal and mix_001 and top_mix:
        scale_node = tree.nodes.new('ShaderNodeVectorMath')
        scale_node.name = 'MM_NORMAL_DELTA_SCALE'
        scale_node.operation = 'SCALE'
        scale_node.inputs['Scale'].default_value = 2.0
        for l in list(tree.links):
            if l.from_node == mix_001 and l.to_node == top_mix:
                tree.links.remove(l)
        tree.links.new(mix_001.outputs['Result'], scale_node.inputs[0])
        b_socket = top_mix.inputs.get('B_Color') or top_mix.inputs[7]
        tree.links.new(scale_node.outputs['Vector'], b_socket)
    elif is_cm_normal and mix_001 and top_mix:
        dot_node = tree.nodes.new('ShaderNodeVectorMath')
        dot_node.name = 'MM_COLOR_DELTA_MONO'
        dot_node.operation = 'DOT_PRODUCT'
        dot_node.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
        for l in list(tree.links):
            if l.from_node == mix_001 and l.to_node == top_mix:
                tree.links.remove(l)
        tree.links.new(mix_001.outputs['Result'], dot_node.inputs[0])
        b_socket = top_mix.inputs.get('B_Color') or top_mix.inputs[7]
        tree.links.new(dot_node.outputs['Value'], b_socket)


def load_wrinkles(prefix, is_delta_color=False, is_delta_normal=False, is_cm_normal=False):
    with bpy.data.libraries.load(str(ASSET), link=False) as (source, target):
        target.node_groups = ['MM_WRINKLE_BLEND']
    root = target.node_groups[0]
    if is_delta_color and 'MERGEMAPS_001' in root.nodes:
        m1 = root.nodes['MERGEMAPS_001']
        c_tree = m1.node_tree.copy()
        c_tree.name = 'MM_MERGEMAPS_COLOR'
        m1.node_tree = c_tree
        _configure_delta_merge(c_tree, is_normal=False, is_cm_normal=is_cm_normal)
    if is_delta_normal and 'MERGEMAPS_002' in root.nodes:
        m2 = root.nodes['MERGEMAPS_002']
        n_tree = m2.node_tree.copy()
        n_tree.name = 'MM_MERGEMAPS_NORMAL'
        m2.node_tree = n_tree
        _configure_delta_merge(n_tree, is_normal=True)
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
    name = caps(prefix+'_SKIN_DETAIL')
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    socket(tree, 'BASE_NORMAL', 'Vector')
    socket(tree, 'DETAIL_STRENGTH', 'Float', default=.75)
    default_tiling = 45.0 if 'body' in prefix.lower() else 15.0
    socket(tree, 'DETAIL_TILING', 'Float', default=default_tiling)
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
        if image:
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


def head_group(prefix, files, animated, is_delta_color=False, is_delta_normal=False, is_cm_normal=False):
    tree = bpy.data.node_groups.new(caps(prefix+'_DNA_MATERIAL'), 'ShaderNodeTree')
    for name, _ in HEAD_INPUTS:
        socket(tree, name, 'Color', default=(.5,.5,1,1) if 'NORMAL' in name else (.5,.5,.5,1))
    socket(tree, 'SPECULAR_ROUGHNESS_METALLIC', 'Color', default=(.5,.45,0,1))
    socket(tree, 'FUZZ_MASK', 'Float', default=0)
    socket(tree, 'DETAIL_STRENGTH', 'Float', default=.75)
    socket(tree, 'DETAIL_TILING', 'Float', default=15.0)
    default_norm_intensity = 1.5 if is_delta_normal else 1.0
    default_color_intensity = 0.45 if is_delta_color else 1.0
    socket(tree, 'NORMAL_WRINKLE_INTENSITY', 'Float', default=default_norm_intensity)
    socket(tree, 'COLOR_WRINKLE_INTENSITY', 'Float', default=default_color_intensity)
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
        weights.node_tree = load_wrinkles(prefix, is_delta_color, is_delta_normal, is_cm_normal)
        original = json.loads(weights.node_tree['mm_original_sockets'])
        inputs = {original[s.identifier]: s for s in weights.inputs}
        for name, original_name in HEAD_INPUTS:
            tree.links.new(entry.outputs[name], inputs[original_name])
        for s, _ in wrinkle_sockets(weights):
            s.hide = True
        weights.width = 230

        color_mix = node(tree, 'ShaderNodeMix', 'COLOR_WRINKLE_BLEND', 100, 300)
        color_mix.data_type = 'RGBA'
        color_mix.clamp_factor = True
        color_mix.clamp_result = True
        tree.links.new(entry.outputs['COLOR_WRINKLE_INTENSITY'], color_mix.inputs['Factor'])
        tree.links.new(entry.outputs['BASE_COLOR'], color_mix.inputs[6])
        tree.links.new(weights.outputs['COLOR'], color_mix.inputs[7])
        color = color_mix.outputs[2]

        n_delta = node(tree, 'ShaderNodeVectorMath', 'NORMAL_WRINKLE_DELTA', -50, 200)
        n_delta.operation = 'SUBTRACT'
        tree.links.new(weights.outputs['NORMAL'], n_delta.inputs[0])
        tree.links.new(entry.outputs['BASE_NORMAL'], n_delta.inputs[1])

        n_scale = node(tree, 'ShaderNodeVectorMath', 'NORMAL_WRINKLE_INTENSITY_SCALE', 150, 200)
        n_scale.operation = 'SCALE'
        tree.links.new(n_delta.outputs['Vector'], n_scale.inputs[0])
        tree.links.new(entry.outputs['NORMAL_WRINKLE_INTENSITY'], n_scale.inputs['Scale'])

        n_comb = node(tree, 'ShaderNodeVectorMath', 'NORMAL_WRINKLE_COMBINE', 350, 200)
        n_comb.operation = 'ADD'
        tree.links.new(entry.outputs['BASE_NORMAL'], n_comb.inputs[0])
        tree.links.new(n_scale.outputs['Vector'], n_comb.inputs[1])
        norm = n_comb.outputs['Vector']
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
    delta_color, delta_normal, is_cm_normal = detect_delta_maps(files)
    animated = all(f'head_normal_animated_wm{i}' in files for i in (1,2,3)) and 'head_normal' in files and ASSET.is_file()
    g.node_tree, weights = head_group(prefix, files, animated, delta_color, delta_normal, is_cm_normal)
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
            cm = texture(tree, files, f'Head_Basecolor_Animated_CM{i}', color=not delta_color)
            wm = texture(tree, files, f'Head_Normal_Animated_WM{i}')
            if cm:
                tree.links.new(cm.outputs['Color'], g.inputs[f'COLOR_WRINKLE_{i}'])
            elif not delta_color and base:
                tree.links.new(base.outputs['Color'], g.inputs[f'COLOR_WRINKLE_{i}'])
            if wm:
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


def body_group(prefix, files):
    name = caps(prefix+'_BODY_MATERIAL')
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    socket(tree, 'BASE_COLOR', 'Color', default=(.5,.5,.5,1))
    socket(tree, 'BASE_NORMAL', 'Color', default=(.5,.5,1,1))
    socket(tree, 'SPECULAR_ROUGHNESS_METALLIC', 'Color', default=(.5,.45,0,1))
    socket(tree, 'FUZZ_MASK', 'Float', default=0)
    socket(tree, 'DETAIL_STRENGTH', 'Float', default=.75)
    socket(tree, 'DETAIL_TILING', 'Float', default=45.0)
    for name, kind in (('COLOR','Color'), ('NORMAL','Vector'), ('SPECULAR','Float'),
                       ('ROUGHNESS','Float'), ('METALLIC','Float'), ('SHEEN','Float')):
        socket(tree, name, kind, 'OUTPUT')
    entry = node(tree, 'NodeGroupInput', 'TEXTURES_AND_SETTINGS', -700, 300)
    entry.width = 260
    out = node(tree, 'NodeGroupOutput', 'SURFACE_CHANNELS', 600, 300)
    tree.links.new(entry.outputs['BASE_COLOR'], out.inputs['COLOR'])
    tangent = normal(tree, entry.outputs['BASE_NORMAL'], None, -70, 100)
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
    return tree


def body_material(tree, bsdf, files, prefix, scale):
    bsdf.inputs['Subsurface Weight'].default_value = .4
    bsdf.inputs['Subsurface Radius'].default_value = (1, .2, .1)
    bsdf.inputs['Subsurface Scale'].default_value = .005*scale/.01
    bsdf.inputs['IOR'].default_value = 1.4
    g = node(tree, 'ShaderNodeGroup', 'BODY_MATERIAL', 0, 300)
    g.width = 280
    g.node_tree = body_group(prefix, files)
    if 'DETAIL_TILING' in g.inputs:
        g.inputs['DETAIL_TILING'].default_value = 45.0
    base = texture(tree, files, 'Body_Basecolor', True)
    norm = texture(tree, files, 'Body_Normal')
    packed = texture(tree, files, 'Body_SRMF')
    if base:
        tree.links.new(base.outputs['Color'], g.inputs['BASE_COLOR'])
    if norm:
        tree.links.new(norm.outputs['Color'], g.inputs['BASE_NORMAL'])
    if packed:
        tree.links.new(packed.outputs['Color'], g.inputs['SPECULAR_ROUGHNESS_METALLIC'])
        tree.links.new(packed.outputs['Alpha'], g.inputs['FUZZ_MASK'])
    frame(tree, 'BASE_TEXTURES', [(base,0,0),(norm,260,0),(packed,520,0)], (-1100,350))
    for source, target in (('COLOR','Base Color'), ('NORMAL','Normal'), ('SPECULAR','Specular IOR Level'),
                           ('ROUGHNESS','Roughness'), ('METALLIC','Metallic'), ('SHEEN','Sheen Weight')):
        tree.links.new(g.outputs[source], bsdf.inputs[target])
    return g


def eye_material(tree, bsdf, files, prefix, rig_scale=0.01):
    has_modular = ('eyes_irisbasecolor' in files) or ('eyes_sclerabasecolor' in files and 'eyes_color' not in files)
    has_baked = ('eyes_color' in files)

    bsdf.inputs['Roughness'].default_value = .32
    bsdf.inputs['IOR'].default_value = 1.3
    bsdf.inputs['Coat Weight'].default_value = 1.0
    bsdf.inputs['Coat Roughness'].default_value = .035
    bsdf.inputs['Coat IOR'].default_value = 1.376
    bsdf.inputs['Specular IOR Level'].default_value = 0.1
    if 'Sheen Weight' in bsdf.inputs:
        bsdf.inputs['Sheen Weight'].default_value = 1.0
    if 'Sheen Roughness' in bsdf.inputs:
        bsdf.inputs['Sheen Roughness'].default_value = 0.2
    geometry = node(tree, 'ShaderNodeNewGeometry', 'SMOOTH_CORNEA', 100, -240)
    tree.links.new(geometry.outputs['Normal'], bsdf.inputs['Coat Normal'])
    bsdf.inputs['Subsurface Weight'].default_value = .025
    bsdf.inputs['Subsurface Radius'].default_value = (1.0, .35, .2)
    bsdf.inputs['Subsurface Scale'].default_value = .00025 * rig_scale / .01

    if has_modular:
        tex_coord = node(tree, 'ShaderNodeTexCoord', 'EYE_TEXCOORD', -1000, 300)
        uv_sub = node(tree, 'ShaderNodeVectorMath', 'EYE_UV_CENTER', -800, 300)
        uv_sub.operation = 'SUBTRACT'
        tree.links.new(tex_coord.outputs['UV'], uv_sub.inputs[0])
        uv_sub.inputs[1].default_value = (0.5, 0.5, 0.0)

        uv_dist = node(tree, 'ShaderNodeVectorMath', 'EYE_UV_RADIUS', -600, 150)
        uv_dist.operation = 'LENGTH'
        tree.links.new(uv_sub.outputs['Vector'], uv_dist.inputs[0])

        iris_scale = node(tree, 'ShaderNodeVectorMath', 'EYE_IRIS_UV_SCALE', -600, 450)
        iris_scale.operation = 'SCALE'
        tree.links.new(uv_sub.outputs['Vector'], iris_scale.inputs[0])
        iris_scale.inputs['Scale'].default_value = 3.0303

        iris_uv = node(tree, 'ShaderNodeVectorMath', 'EYE_IRIS_UV', -400, 450)
        iris_uv.operation = 'ADD'
        tree.links.new(iris_scale.outputs['Vector'], iris_uv.inputs[0])
        iris_uv.inputs[1].default_value = (0.5, 0.5, 0.0)

        limbus = node(tree, 'ShaderNodeMapRange', 'EYE_LIMBUS_MASK', -400, 150)
        limbus.clamp = True
        limbus.inputs['From Min'].default_value = 0.145
        limbus.inputs['From Max'].default_value = 0.175
        limbus.inputs['To Min'].default_value = 0.0
        limbus.inputs['To Max'].default_value = 1.0
        tree.links.new(uv_dist.outputs['Value'], limbus.inputs['Value'])

        iris_col = texture(tree, files, 'Eyes_IrisBasecolor', color=True, x=-200, y=550)
        if iris_col:
            tree.links.new(iris_uv.outputs['Vector'], iris_col.inputs['Vector'])
            iris_col.extension = 'CLIP'

        sclera_col = texture(tree, files, 'Eyes_ScleraBasecolor', color=True, x=-200, y=250)
        if sclera_col:
            tree.links.new(tex_coord.outputs['UV'], sclera_col.inputs['Vector'])

        veins = texture(tree, files, 'Eyes_Veins', color=True, x=-200, y=50)
        if veins:
            tree.links.new(tex_coord.outputs['UV'], veins.inputs['Vector'])

        if veins and sclera_col:
            mix_veins = node(tree, 'ShaderNodeMix', 'EYE_SCLERA_VEINS', 50, 200)
            mix_veins.data_type = 'RGBA'
            mix_veins.blend_type = 'MULTIPLY'
            mix_veins.inputs['Factor'].default_value = 1.0
            tree.links.new(sclera_col.outputs['Color'], mix_veins.inputs[6])
            tree.links.new(veins.outputs['Color'], mix_veins.inputs[7])
            sclera_out = mix_veins.outputs[2]
        else:
            sclera_out = sclera_col.outputs['Color'] if sclera_col else None

        if iris_col and sclera_out:
            mix_col = node(tree, 'ShaderNodeMix', 'EYE_COLOR_MIX', 250, 400)
            mix_col.data_type = 'RGBA'
            mix_col.blend_type = 'MIX'
            tree.links.new(limbus.outputs['Result'], mix_col.inputs['Factor'])
            tree.links.new(iris_col.outputs['Color'], mix_col.inputs[6])
            tree.links.new(sclera_out, mix_col.inputs[7])
            tree.links.new(mix_col.outputs[2], bsdf.inputs['Base Color'])
        elif iris_col:
            tree.links.new(iris_col.outputs['Color'], bsdf.inputs['Base Color'])
        elif sclera_out:
            tree.links.new(sclera_out, bsdf.inputs['Base Color'])

        iris_norm = texture(tree, files, 'Eyes_IrisNormal', color=False, x=-200, y=-200)
        if iris_norm:
            tree.links.new(iris_uv.outputs['Vector'], iris_norm.inputs['Vector'])
        sclera_norm = texture(tree, files, 'Eyes_ScleraNormal', color=False, x=-200, y=-400)
        if sclera_norm:
            tree.links.new(tex_coord.outputs['UV'], sclera_norm.inputs['Vector'])

        if iris_norm and sclera_norm:
            mix_norm = node(tree, 'ShaderNodeMix', 'EYE_NORMAL_MIX', 50, -300)
            mix_norm.data_type = 'RGBA'
            mix_norm.blend_type = 'MIX'
            tree.links.new(limbus.outputs['Result'], mix_norm.inputs['Factor'])
            tree.links.new(iris_norm.outputs['Color'], mix_norm.inputs[6])
            tree.links.new(sclera_norm.outputs['Color'], mix_norm.inputs[7])
            n_node = normal(tree, mix_norm.outputs[2], bsdf, x=250, y=-300)
            n_node.inputs['Strength'].default_value = 2.0
        elif iris_norm:
            n_node = normal(tree, iris_norm.outputs['Color'], bsdf, x=250, y=-300)
            n_node.inputs['Strength'].default_value = 2.0
        elif sclera_norm:
            n_node = normal(tree, sclera_norm.outputs['Color'], bsdf, x=250, y=-300)
            n_node.inputs['Strength'].default_value = 2.0

        dust = texture(tree, files, 'Eyes_Dust', color=False, x=-200, y=-50)
        if dust:
            tree.links.new(tex_coord.outputs['UV'], dust.inputs['Vector'])
            dust_mix = node(tree, 'ShaderNodeMix', 'EYE_DUST_ROUGHNESS', 100, -100)
            dust_mix.data_type = 'FLOAT'
            dust_mix.blend_type = 'MIX'
            dust_mix.inputs['Factor'].default_value = 0.15
            dust_mix.inputs[2].default_value = 0.32
            tree.links.new(dust.outputs['Color'], dust_mix.inputs[3])
            tree.links.new(dust_mix.outputs[0], bsdf.inputs['Roughness'])
        return None
    elif has_baked:
        base = texture(tree, files, 'Eyes_Color', True, x=-500, y=400)
        nm = texture(tree, files, 'Eyes_Normal', x=-500, y=0)
        if not nm and 'eyes_scleranormal' in files:
            nm = texture(tree, files, 'Eyes_ScleraNormal', x=-500, y=0)
        if base:
            tree.links.new(base.outputs['Color'], bsdf.inputs['Base Color'])
        if nm:
            n_node = normal(tree, nm.outputs['Color'], bsdf)
            n_node.inputs['Strength'].default_value = 2.0
        return None
    else:
        return 'Eyes_Color is missing; using a fallback material'


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


def find_character_rigs(context):
    """Find the active or scene head and body rigs."""
    active = context.active_object
    active_arm = active if active and active.type == 'ARMATURE' else (active.parent if active and active.parent and active.parent.type == 'ARMATURE' else None)
    head_rig = None
    body_rig = None
    if active_arm:
        if bake.RIG_KEY_DATA in active_arm:
            head_rig = active_arm
        if active_arm.get('mm_body_rig'):
            body_rig = active_arm
    for o in context.scene.objects:
        if o.type == 'ARMATURE':
            if head_rig is None and bake.RIG_KEY_DATA in o:
                head_rig = o
            if body_rig is None and o.get('mm_body_rig'):
                body_rig = o
    return head_rig, body_rig


def body_meshes(rig):
    if rig is None:
        return []
    return [o for o in bpy.data.objects if o.type == 'MESH' and o.parent == rig
            and (o.get('mm_body_mesh') or str(o.get('mm_mesh_kind','')).lower() == 'body')]


def setup(reader, model, variant, rig, board, meshes, folder, collection, prefix, lod=0, body_rig=None):
    files = texture_files(folder)
    before = cleanup.snapshot()
    primary_rig = rig or body_rig
    token = (primary_rig.get(cleanup.OWNER) if primary_rig else None) or cleanup.new_token()
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
            elif 'body' in kind or mesh.get('mm_body_mesh'):
                category, color, norm = 'BODY', 'Body_Basecolor', 'Body_Normal'
            else:
                warnings.append(f'No material preset for {mesh.name}; existing slots preserved')
                continue
            if category == 'HEAD' and 'head_basecolor' not in files:
                warnings.append('Head_Basecolor texture not found; head material skipped')
                continue
            if category == 'BODY' and 'body_basecolor' not in files:
                warnings.append('Body_Basecolor texture not found; body material skipped')
                continue
            mat_prefix = prefix
            if category == 'BODY' and body_rig:
                mat_prefix = body_rig.get('mm_body_prefix') or (body_rig.name.replace('_RIG','') if body_rig.name.endswith('_RIG') else body_rig.name)
            mat = bpy.data.materials.new(caps(mat_prefix+'_'+category))
            mat['mm_material_version'] = '1.2.0'
            tree = mat.node_tree
            tree.nodes.clear()
            bsdf = node(tree, 'ShaderNodeBsdfPrincipled', category+'_SURFACE', 400, 300)
            bsdf.width = 240
            output = node(tree, 'ShaderNodeOutputMaterial', 'MATERIAL_OUTPUT', 760, 300)
            tree.links.new(bsdf.outputs[0], output.inputs['Surface'])
            base = texture(tree, files, color, True, x=-500, y=400) if color and category not in ('HEAD', 'BODY', 'EYELEFT', 'EYERIGHT') else None
            nm = texture(tree, files, norm, x=-500, y=0) if norm and category not in ('HEAD', 'BODY', 'EYELEFT', 'EYERIGHT') else None
            if base:
                tree.links.new(base.outputs['Color'], bsdf.inputs['Base Color'])
            elif color and category not in ('HEAD', 'BODY', 'EYELEFT', 'EYERIGHT'):
                warnings.append(f'{color} is missing; using a fallback material')
            if nm:
                normal(tree, nm.outputs['Color'], bsdf)
            if category == 'HEAD':
                scale = float(rig.get(bake.RIG_KEY_SCALE, .01) if rig else .01)
                g = head_material(tree, bsdf, files, prefix, scale)
                if g and reader and model and board:
                    count, new_holders = realize_wrinkles(reader, model, variant, rig, board, g, collection, prefix, lod)
                    driver_count += count; holders += new_holders
                elif g:
                    warnings.append('Animated normal maps missing or static rig; head uses static shading')
                frame(tree, 'SURFACE_OUTPUT', [(bsdf,0,0),(output,320,0)], (400,300))
            elif category == 'BODY':
                scale = float(body_rig.get('mm_body_scale', primary_rig.get('mm_body_scale', primary_rig.get(bake.RIG_KEY_SCALE, .01))) if body_rig else primary_rig.get('mm_body_scale', primary_rig.get(bake.RIG_KEY_SCALE, .01)))
                body_material(tree, bsdf, files, mat_prefix, scale)
                frame(tree, 'SURFACE_OUTPUT', [(bsdf,0,0),(output,320,0)], (400,300))
            elif category in ('EYELEFT', 'EYERIGHT'):
                scale = float(primary_rig.get(bake.RIG_KEY_SCALE, .01)) if primary_rig else .01
                warn = eye_material(tree, bsdf, files, mat_prefix, scale)
                if warn:
                    warnings.append(warn)
                frame(tree, 'SURFACE_OUTPUT', [(bsdf,0,0),(output,320,0)], (400,300))
            elif category == 'TEETH':
                def set_input(name, val):
                    if name in bsdf.inputs:
                        bsdf.inputs[name].default_value = val

                set_input('Roughness', 0.3)
                set_input('IOR', 1.45)
                set_input('Alpha', 1.0)
                set_input('Thin Wall', False)
                set_input('Diffuse Roughness', 0.0)
                set_input('Subsurface Weight', 0.8)
                set_input('Subsurface Radius', (1.0, 0.2, 0.1))
                scale = float(rig.get(bake.RIG_KEY_SCALE, .01) if rig else .01)
                set_input('Subsurface Scale', 0.001 * scale / .01)
                set_input('Subsurface Anisotropy', 0.0)
                set_input('Specular IOR Level', 0.8)
                if 'Anisotropic' in bsdf.inputs:
                    bsdf.inputs['Anisotropic'].default_value = 0.5
                elif 'Specular Anisotropy' in bsdf.inputs:
                    bsdf.inputs['Specular Anisotropy'].default_value = 0.5
                set_input('Coat Weight', 0.3)
                set_input('Coat Roughness', 0.6)
                set_input('Coat IOR', 1.0)
                set_input('Sheen Weight', 0.1)
                set_input('Sheen Roughness', 0.0)
            elif category == 'EYELASHES':
                bsdf.inputs['Base Color'].default_value = (.015,.008,.005,1)
                alpha = texture(tree, files, 'EyeLashes_Alpha', x=-200, y=300)
                # The supplied image is grayscale coverage, not its opaque PNG alpha.
                if alpha:
                    tree.links.new(alpha.outputs['Color'],bsdf.inputs['Alpha'])
                bsdf.inputs['Roughness'].default_value = .4
            else:
                # Transparent wet overlay preserves the iris and mouth below it.
                tree.links.remove(output.inputs['Surface'].links[0])
                transparent = node(tree,'ShaderNodeBsdfTransparent','CLEAR_OVERLAY',700,-100)
                tree.links.new(transparent.outputs[0],output.inputs['Surface'])
            assignments.append((mesh,mat))
        if not assignments:
            raise ValueError('No matching character textures found in the selected folder')
        old_sets = {mesh.data.materials[0].get('mm_material_set') for mesh,mat in assignments
                    if mesh.data.materials and mesh.data.materials[0]}
        for mesh, mat in assignments:
            if mesh.data.materials:
                mesh.data.materials[0] = mat
            else:
                mesh.data.materials.append(mat)
        for r in {r for r in (rig, body_rig) if r is not None}:
            r['mm_texture_folder'] = str(Path(bpy.path.abspath(str(folder))))
            if r == rig and driver_count:
                r['mm_material_drivers'] = driver_count
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


def set_body_detail_tiling(target=None, value=45.0):
    """Ensure all body materials and node groups have Detail Tiling set to value (default 45.0)."""
    val = float(value)
    # 1. Update any existing node groups related to body
    for ng in bpy.data.node_groups:
        if 'body' in ng.name.lower() or 'skin_detail' in ng.name.lower():
            if hasattr(ng, 'interface') and hasattr(ng.interface, 'items_tree'):
                if 'DETAIL_TILING' in ng.interface.items_tree:
                    try:
                        ng.interface.items_tree['DETAIL_TILING'].default_value = val
                    except Exception:
                        pass
    # 2. Check materials
    materials_to_check = set()
    if target is not None:
        objs = target if isinstance(target, (list, tuple, set)) else [target]
        for obj in objs:
            if hasattr(obj, 'material_slots'):
                for slot in obj.material_slots:
                    if slot.material:
                        materials_to_check.add(slot.material)
    if not materials_to_check:
        for mat in bpy.data.materials:
            if 'body' in mat.name.lower():
                materials_to_check.add(mat)
    for mat in materials_to_check:
        if mat and mat.node_tree:
            for n in mat.node_tree.nodes:
                if 'DETAIL_TILING' in n.inputs:
                    n.inputs['DETAIL_TILING'].default_value = val


def setup_materials(context, folder):
    """Apply materials from the specified folder to the character meshes."""
    context.scene.mm_texture_folder = str(folder)
    head_rig, body_rig = find_character_rigs(context)
    if head_rig is None and body_rig is None:
        raise ValueError('Select an imported head or body rig')
    reader = None
    try:
        head_m = bake.head_meshes(head_rig) if head_rig else []
        body_m = body_meshes(body_rig) if body_rig else []
        all_meshes = head_m + body_m
        if not all_meshes:
            raise ValueError('No head or body meshes found to apply materials to')
        model = None
        variant = None
        board = None
        if head_rig and head_m:
            from .operators import get_preferences
            prefs = get_preferences(context)
            bindings = prefs.bindings_folder if prefs else ''
            reader = dnaio.open_reader(Path(head_rig[bake.RIG_KEY_DNA]), bindings)
            model = RigLogicModel.from_reader(reader)
            _, rl, _ = dnaio.load_bindings(bindings)
            result = verify.verify_model(model, rl, reader, release=dnaio.release_handle)
            if result.status == 'failed':
                raise ValueError(result.message)
            variant = result.variant or model.variants()[0]
            board = bpy.data.objects.get(str(head_rig.get(bake.RIG_KEY_BOARD_OBJECT, '')))
        primary_rig = head_rig or body_rig
        collection = primary_rig.users_collection[0] if primary_rig.users_collection else context.scene.collection
        prefix = primary_rig.get(bake.RIG_KEY_PREFIX) or primary_rig.name.replace('_RIG', '')
        lod = int(primary_rig.get('mm_lod', 0))
        report = setup(reader, model, variant, head_rig or primary_rig, board,
                       all_meshes, folder, collection, prefix, lod, body_rig=body_rig)
        set_body_detail_tiling(all_meshes, value=45.0)
        bake.write_report(report)
        return report
    finally:
        if reader is not None:
            dnaio.release_handle(reader)


class MM_OT_materials(bpy.types.Operator):
    bl_idname = 'metamorphosis.setup_materials'
    bl_label = 'Apply Materials to Rig'
    bl_options = {'REGISTER','UNDO'}

    def execute(self,context):
        folder = context.scene.mm_texture_folder
        if not folder:
            self.report({'ERROR'}, 'Choose a texture source folder'); return {'CANCELLED'}
        try:
            report = setup_materials(context, folder)
            self.report({'INFO'}, report[0])
        except Exception as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = (MM_OT_materials,)


def register():
    bpy.types.Scene.mm_texture_folder = StringProperty(name='Textures Folder',subtype='DIR_PATH',
        description='Unreal DCC export root or Maps folder; blank imports without textures')


def unregister():
    if hasattr(bpy.types.Scene, 'mm_texture_folder'):
        del bpy.types.Scene.mm_texture_folder
