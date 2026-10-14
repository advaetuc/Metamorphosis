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
    # Unreal exports DirectX tangent normals; Blender expects an inverted green channel.
    separate = node(tree, 'ShaderNodeSeparateXYZ', 'NORMAL_CHANNELS', x-400, y)
    flip = node(tree, 'ShaderNodeMath', 'DIRECTX_GREEN_FLIP', x-200, y-140)
    flip.operation = 'SUBTRACT'; flip.inputs[0].default_value = 1
    combine = node(tree, 'ShaderNodeCombineXYZ', 'OPENGL_NORMAL', x, y)
    n = node(tree, 'ShaderNodeNormalMap', 'TANGENT_NORMAL', x+180, y)
    n.uv_map = 'UVMap'
    tree.links.new(source, separate.inputs[0])
    tree.links.new(separate.outputs['X'], combine.inputs['X'])
    tree.links.new(separate.outputs['Y'], flip.inputs[1])
    tree.links.new(flip.outputs[0], combine.inputs['Y'])
    tree.links.new(separate.outputs['Z'], combine.inputs['Z'])
    tree.links.new(combine.outputs[0], n.inputs['Color'])
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
    for socket in group.inputs:
        if '.head_' not in socket.name:
            continue
        wm, mask = socket.name.split('.', 1)
        name = f'head_{wm}_normal.'+mask.removesuffix('_msk')
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
        for n in group.nodes:
            if n.type == 'GROUP':
                rename(n.node_tree)
    rename(root)
    return root


def skin(tree, bsdf, files, scale):
    bsdf.inputs['Subsurface Weight'].default_value = .4
    bsdf.inputs['Subsurface Radius'].default_value = (1, .35, .2)
    bsdf.inputs['Subsurface Scale'].default_value = .005 * scale/.01
    bsdf.inputs['IOR'].default_value = 1.4
    bsdf.inputs['Roughness'].default_value = .45
    packed = texture(tree, files, 'Head_SRMF', x=-900, y=-600)
    if packed:
        separate = node(tree, 'ShaderNodeSeparateColor', 'SRMF_CHANNELS', -600, -650)
        tree.links.new(packed.outputs['Color'], separate.inputs['Color'])
        for source, target in [('Red','Specular IOR Level'),('Green','Roughness'),('Blue','Metallic')]:
            tree.links.new(separate.outputs[source], bsdf.inputs[target])
        fuzz = node(tree, 'ShaderNodeMath', 'FUZZ_STRENGTH', -350, -650)
        fuzz.operation = 'MULTIPLY'; fuzz.inputs[1].default_value = .15
        tree.links.new(packed.outputs['Alpha'], fuzz.inputs[0])
        tree.links.new(fuzz.outputs[0], bsdf.inputs['Sheen Weight'])
    # Optional user-provided tiling detail maps; preserve the main wrinkle normal.
    files = dict(files)
    for key in ('T_SkinMicroNormal','T_SkinMicro3_N'):
        bundled = ASSET.parent/(key+'.PNG')
        if bundled.is_file():
            files.setdefault(key.lower(),bundled)
    detail = texture(tree, files, 'T_SkinMicroNormal', x=-900, y=-1100)
    if detail:
        uv = node(tree, 'ShaderNodeTexCoord', 'DETAIL_UV', -1350, -1100)
        mapping = node(tree, 'ShaderNodeVectorMath', 'DETAIL_TILING', -1150, -1100)
        mapping.operation = 'SCALE'; mapping.inputs['Scale'].default_value = 20
        tree.links.new(uv.outputs['UV'], mapping.inputs[0])
        tree.links.new(mapping.outputs[0], detail.inputs['Vector'])
        previous = bsdf.inputs['Normal'].links[0].from_socket if bsdf.inputs['Normal'].is_linked else None
        second = texture(tree,files,'T_SkinMicro3_N',x=-900,y=-1400)
        source = detail.outputs['Color']
        if second:
            tree.links.new(mapping.outputs[0],second.inputs['Vector'])
            mix = node(tree,'ShaderNodeMixRGB','MICRO_DETAIL_BLEND',-650,-1300)
            mix.inputs[0].default_value = .5
            tree.links.new(source,mix.inputs[1]);tree.links.new(second.outputs['Color'],mix.inputs[2])
            source = mix.outputs[0]
        micro = normal(tree, source, bsdf, x=-450, y=-1100)
        micro.inputs['Strength'].default_value = .15
        if previous:
            add = node(tree, 'ShaderNodeVectorMath', 'DETAIL_NORMAL_DELTA', 0, -1100)
            add.operation = 'SUBTRACT'
            geom = node(tree, 'ShaderNodeNewGeometry', 'SURFACE_NORMAL', -250, -1300)
            tree.links.new(micro.outputs[0], add.inputs[0]); tree.links.new(geom.outputs['Normal'], add.inputs[1])
            total = node(tree, 'ShaderNodeVectorMath', 'COMBINED_NORMAL', 220, -900)
            total.operation = 'ADD'
            tree.links.new(previous,total.inputs[0]); tree.links.new(add.outputs[0],total.inputs[1])
            unit = node(tree, 'ShaderNodeVectorMath', 'NORMALIZE_DETAIL', 420, -900)
            unit.operation = 'NORMALIZE'
            tree.links.new(total.outputs[0],unit.inputs[0]); tree.links.new(unit.outputs[0],bsdf.inputs['Normal'])


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
                category, color, norm = 'EYELASHES', 'Eyelashes_Color', ''
            elif 'eyeshell' in kind or 'saliva' in kind or 'eyeedge' in kind:
                category, color, norm = caps(kind), '', ''
            else:
                warnings.append(f'No material preset for {mesh.name}; existing slots preserved')
                continue
            mat = bpy.data.materials.new(caps(prefix+'_'+category))
            mat['mm_material_version'] = '1.0.10'
            tree = mat.node_tree
            tree.nodes.clear()
            bsdf = node(tree, 'ShaderNodeBsdfPrincipled', category+'_SURFACE', 700, 100)
            output = node(tree, 'ShaderNodeOutputMaterial', 'MATERIAL_OUTPUT', 1050, 100)
            tree.links.new(bsdf.outputs[0], output.inputs['Surface'])
            base = texture(tree, files, color, True, y=400) if color else None
            nm = texture(tree, files, norm, y=-100) if norm else None
            if base:
                tree.links.new(base.outputs['Color'], bsdf.inputs['Base Color'])
            elif color:
                warnings.append(f'{color} is missing; using a fallback material')
            if nm:
                normal(tree, nm.outputs['Color'], bsdf)
            if category == 'HEAD':
                animated = all(f'head_normal_animated_wm{i}' in files for i in (1,2,3))
                if animated and nm and ASSET.is_file():
                    g = node(tree, 'ShaderNodeGroup', 'DNA_WRINKLES', -500, 500)
                    g.node_tree = load_wrinkles(prefix)
                    tree.links.new(base.outputs['Color'], g.inputs['cm_base'])
                    tree.links.new(nm.outputs['Color'], g.inputs['wm_base'])
                    for i in (1,2,3):
                        cm = texture(tree,files,f'Head_Basecolor_Animated_CM{i}',True,y=850+i*260)
                        wm = texture(tree,files,f'Head_Normal_Animated_WM{i}',y=-1400-i*260)
                        tree.links.new((cm or base).outputs['Color'],g.inputs[f'cm{i}'])
                        tree.links.new(wm.outputs['Color'],g.inputs[f'wm{i}'])
                    tree.links.new(g.outputs['Color'],bsdf.inputs['Base Color'])
                    normal(tree,g.outputs['Normal'],bsdf,x=-100,y=-150)
                    count, new_holders = realize_wrinkles(reader,model,variant,rig,board,g,collection,prefix,lod)
                    driver_count += count; holders += new_holders
                else:
                    warnings.append('Animated normal maps missing; head uses static shading')
                skin(tree,bsdf,files,float(rig.get(bake.RIG_KEY_SCALE,.01)))
            elif category == 'TEETH':
                bsdf.inputs['Roughness'].default_value = .28
                bsdf.inputs['Subsurface Weight'].default_value = .08
                bsdf.inputs['Subsurface Scale'].default_value = .001
            elif color == 'Eyes_Color':
                bsdf.inputs['Roughness'].default_value = .22
                bsdf.inputs['Coat Weight'].default_value = .3
            elif category == 'EYELASHES':
                bsdf.inputs['Base Color'].default_value = (.015,.008,.005,1)
                if base:
                    tree.links.new(base.outputs['Alpha'],bsdf.inputs['Alpha'])
                else:
                    # The DCC export contains no eyelash alpha. Opaque cards cover the eyes.
                    bsdf.inputs['Alpha'].default_value = 0
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
