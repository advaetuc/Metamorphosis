"""Update 1.2 asset/geometry checks against the real Logan DCC export.

Run after blender_materials.py, which creates work/materials_logan.blend.
"""
import importlib.util
from pathlib import Path
import sys
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bake, cleanup, dnaio, materials, ui

bpy.ops.wm.open_mainfile(filepath=str(ROOT/'work/materials_logan.blend'))
rig = bake.find_baked_rig(bpy.context)
meshes = {o['mm_mesh_kind'].lower(): o for o in bake.head_meshes(rig)}
assert not any('shell' in k or 'cartilage' in k for k in meshes), meshes.keys()
assert 'eyeedge_l' in meshes and 'eyeedge_r' in meshes and 'eyeedge' not in meshes
reader = dnaio.open_reader(Path(rig[bake.RIG_KEY_DNA]))
index = next(i for i in reader.getMeshIndicesForLOD(0) if reader.getMeshName(i).startswith('eyeEdge'))
positions = list(zip(reader.getVertexPositionXs(index), reader.getVertexPositionYs(index), reader.getVertexPositionZs(index)))
layout = list(reader.getVertexLayoutPositionIndices(index))
uv_index = list(reader.getVertexLayoutTextureCoordinateIndices(index))
us, vs = list(reader.getVertexTextureCoordinateUs(index)), list(reader.getVertexTextureCoordinateVs(index))
total_faces = 0
for side, sign in (('l',1), ('r',-1)):
    obj = meshes['eyeedge_'+side]
    selected = [i for i,p in enumerate(positions) if sign*p[0] > 0]
    assert len(selected) == len(obj.data.vertices)
    remap = {old: new for new,old in enumerate(selected)}
    scale = rig[bake.RIG_KEY_SCALE]
    for v, original in zip(obj.data.vertices, selected):
        x,y,z = positions[original]
        assert (v.co-Vector((x*scale,-z*scale,y*scale))).length < 1e-6
        expected = {reader.getJointName(j): w for j,w in zip(reader.getSkinWeightsJointIndices(index,original), reader.getSkinWeightsValues(index,original)) if w>0}
        actual = {obj.vertex_groups[g.group].name:g.weight for g in v.groups}
        assert actual.keys() == expected.keys()
        assert all(abs(w-expected[j])<1e-6 for j,w in actual.items())
    faces = [list(reader.getFaceVertexLayoutIndices(index,f)) for f in range(reader.getFaceCount(index))]
    faces = [ls for ls in faces if all(layout[i] in remap for i in ls)]
    assert len(faces) == len(obj.data.polygons)
    total_faces += len(faces)
    for poly, ls in zip(obj.data.polygons, faces):
        assert tuple(poly.vertices) == tuple(remap[layout[i]] for i in ls)
        for loop,i in zip(poly.loop_indices, ls):
            assert (obj.data.uv_layers['UVMap'].data[loop].uv-Vector((us[uv_index[i]],vs[uv_index[i]]))).length < 1e-6
    assert obj.parent == rig and obj.modifiers[0].object == rig
    assert obj.get(cleanup.OWNER) == rig.get(cleanup.OWNER)
    mat = obj.active_material
    assert mat.name.startswith('LOGAN_EYE_EDGE_'+side.upper())
    ramp = mat.node_tree.nodes['COLOR_RAMP'].color_ramp
    assert abs(ramp.elements[-1].position-({'l':.45,'r':.4}[side])) < 1e-6
    assert all(n.image.packed_file for n in mat.node_tree.nodes if n.type=='TEX_IMAGE')
    tangent = mat.node_tree.nodes['NORMAL_MAP']
    assert tangent.uv_map == 'UVMap'
    if hasattr(tangent,'convention'): assert tangent.convention == 'DIRECTX'
    else: assert tangent.inputs['Color'].links[0].from_node.type == 'GROUP'
assert total_faces == reader.getFaceCount(index)
dnaio.release_handle(reader)

head = meshes['head'].active_material
public = head.node_tree.nodes['DNA_MATERIAL']
assert len(public.inputs) == 12
assert len([n for n in head.node_tree.nodes if n.type == 'FRAME']) == 4
assert not [n for n in head.node_tree.nodes if n.type in {'MATH','MIX_RGB','VECT_MATH','NORMAL_MAP'}]
weights = materials.wrinkle_node(head)
assert len(list(materials.wrinkle_sockets(weights))) == 41
assert all(s.hide for s,_ in materials.wrinkle_sockets(weights))
for tree in bpy.data.node_groups:
    if not tree.get(cleanup.OWNER): continue
    for s in tree.interface.items_tree:
        if s.item_type=='SOCKET': assert s.name == materials.caps(s.name), (tree.name,s.name)
    for n in tree.nodes:
        if n.type=='NORMAL_MAP' and hasattr(n,'convention'):
            assert n.convention == 'DIRECTX', (tree.name,n.name)
if bpy.app.version >= (5,2,0):
    assert not any('LEGACY_DIRECTX' in g.name for g in bpy.data.node_groups)
teeth = meshes['teeth'].active_material
for name in ('TEETH_COLOR','TEETH_NORMAL'):
    img = teeth.node_tree.nodes[name].image
    assert img.packed_file and Path(bpy.path.abspath(img.filepath)).resolve().parent == ROOT/'assets'
lashes = meshes['eyelashes'].active_material.node_tree
alpha = lashes.nodes['EYELASHES_SURFACE'].inputs['Alpha'].links[0]
assert alpha.from_socket.name=='Color' and alpha.from_node.image.packed_file
assert alpha.from_node.image.colorspace_settings.name=='Non-Color'
assert all(p.is_file() for p in [materials.EYE_EDGE_ASSET, *[ROOT/'assets'/n for n in materials.UNIVERSAL_TEXTURES]])
from types import SimpleNamespace
labels=[]
ui.MM_PT_panel.draw_header_preset(SimpleNamespace(layout=SimpleNamespace(label=lambda **kw: labels.append(kw['text']))),bpy.context)
assert ui.MM_PT_panel.bl_label=='MetaMorphosis DNA Addon' and labels==['by TheClayMan3D']
print('UPDATE12_ASSETS_GEOMETRY_PASS',bpy.app.version_string,flush=True)
