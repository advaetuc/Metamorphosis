"""Test auto-detection and shader setup for modern 50% grey MetaHuman wrinkle maps."""
import importlib.util
import os
import sys
from pathlib import Path
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bindings' / 'windows' / 'x64' / f'py{sys.version_info.major}{sys.version_info.minor}'))
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
from metamorphosis import materials

# 1. Test is_delta_map logic
logan_folder = Path(r'F:\Project_Files\Metahumans\MH_Logan\Maps')
user_folder = Path(r'C:\Users\Advaet\.gemini\antigravity\brain\282e405c-d034-4c52-9c2f-05a49a9b1cd7\.user_uploaded')

files_logan = {
    'head_basecolor': logan_folder / 'Head_Basecolor.png',
    'head_normal': logan_folder / 'Head_Normal.png',
    'head_basecolor_animated_cm1': logan_folder / 'Head_Basecolor_Animated_CM1.png',
    'head_basecolor_animated_cm2': logan_folder / 'Head_Basecolor_Animated_CM2.png',
    'head_basecolor_animated_cm3': logan_folder / 'Head_Basecolor_Animated_CM3.png',
    'head_normal_animated_wm1': logan_folder / 'Head_Normal_Animated_WM1.png',
    'head_normal_animated_wm2': logan_folder / 'Head_Normal_Animated_WM2.png',
    'head_normal_animated_wm3': logan_folder / 'Head_Normal_Animated_WM3.png',
}

files_user = {
    'head_basecolor': user_folder / 'media_1794629933614_110bdf16.jpg',
    'head_normal': user_folder / 'media_1794629934696_a7e79c66.jpg',
    'head_basecolor_animated_cm1': user_folder / 'media_1794629933238_2c4fc4cc.jpg',
    'head_basecolor_animated_cm2': user_folder / 'media_1794629933240_386687bd.jpg',
    'head_basecolor_animated_cm3': user_folder / 'media_1794629933233_80f5b3dd.png',
    'head_normal_animated_wm1': user_folder / 'media_1794629933283_606f8b5b.jpg',
    'head_normal_animated_wm2': user_folder / 'media_1794629933305_b0541090.jpg',
    'head_normal_animated_wm3': user_folder / 'media_1794629933265_bbf414c9.jpg',
}
for name in materials.UNIVERSAL_TEXTURES:
    p = materials.ASSET.parent / name
    if p.is_file():
        files_user[p.stem.lower()] = p
        files_logan[p.stem.lower()] = p

det_logan = materials.detect_delta_maps(files_logan)
assert det_logan == (False, False, False), f'Expected Logan to be detected as legacy full diffuse, got {det_logan}'

det_user = materials.detect_delta_maps(files_user)
assert det_user == (True, True, True), f'Expected user grey wrinkle maps to be detected as delta with normal bleed, got {det_user}'

# 2. Test Material Generation with Delta Maps
mat = bpy.data.materials.new('TEST_HEAD_DELTA')
mat.use_nodes = True
tree = mat.node_tree
tree.nodes.clear()
bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
weights = materials.head_material(tree, bsdf, files_user, 'TEST_DELTA', scale=1.0)
assert weights is not None, 'Weights group should be generated'

# Check DNA_MATERIAL group has intensity sliders and detail defaults
dna_mat = tree.nodes.get('DNA_MATERIAL')
assert dna_mat is not None, 'DNA_MATERIAL node missing'
assert 'COLOR_WRINKLE_INTENSITY' in dna_mat.inputs, 'COLOR_WRINKLE_INTENSITY socket missing on DNA_MATERIAL'
assert abs(dna_mat.inputs['COLOR_WRINKLE_INTENSITY'].default_value - 0.45) < 1e-5, (
    f'Default color intensity should be 0.45, got {dna_mat.inputs["COLOR_WRINKLE_INTENSITY"].default_value}'
)
for i in (1, 2, 3):
    assert dna_mat.inputs[f'COLOR_WRINKLE_{i}'].is_linked, f'COLOR_WRINKLE_{i} should be linked'
assert 'NORMAL_WRINKLE_INTENSITY' in dna_mat.inputs, 'NORMAL_WRINKLE_INTENSITY socket missing on DNA_MATERIAL'
assert dna_mat.inputs['NORMAL_WRINKLE_INTENSITY'].default_value == 1.5, (
    f'Default normal intensity for delta maps should be 1.5, got {dna_mat.inputs["NORMAL_WRINKLE_INTENSITY"].default_value}'
)
assert dna_mat.inputs['DETAIL_STRENGTH'].default_value == 0.75, (
    f'DETAIL_STRENGTH default should be 0.75, got {dna_mat.inputs["DETAIL_STRENGTH"].default_value}'
)
assert dna_mat.inputs['DETAIL_TILING'].default_value == 15.0, (
    f'DETAIL_TILING default should be 15.0, got {dna_mat.inputs["DETAIL_TILING"].default_value}'
)

# Check texture node color spaces
for node in tree.nodes:
    if node.type == 'TEX_IMAGE' and node.image:
        if 'ANIMATED_CM' in node.name or 'ANIMATED_WM' in node.name:
            assert node.image.colorspace_settings.name == 'Non-Color', (
                f'{node.name} colorspace should be Non-Color, got {node.image.colorspace_settings.name}'
            )

# Check wrinkle node group internal merge configuration
wrinkle_group = weights.node_tree
merge_color = wrinkle_group.nodes['MERGEMAPS_001'].node_tree
for node_name in ('MIX_006', 'MIX_007', 'MIX_008'):
    n = merge_color.nodes[node_name]
    assert not n.inputs['B'].is_linked, f'{node_name}.B should be disconnected in delta mode'
    assert list(n.inputs['B'].default_value)[:3] == [0.5, 0.5, 0.5], (
        f'{node_name}.B default value should be 0.5, got {n.inputs["B"].default_value}'
    )

assert 'MM_COLOR_DELTA_MONO' in merge_color.nodes, 'MM_COLOR_DELTA_MONO node missing in MERGEMAPS_001'
assert merge_color.nodes['MM_COLOR_DELTA_MONO'].operation == 'DOT_PRODUCT'

merge_normal = wrinkle_group.nodes['MERGEMAPS_002'].node_tree
assert 'MM_NORMAL_DELTA_SCALE' in merge_normal.nodes, 'MM_NORMAL_DELTA_SCALE node missing in MERGEMAPS_002'
assert merge_normal.nodes['MM_NORMAL_DELTA_SCALE'].inputs['Scale'].default_value == 2.0, 'Normal delta scale should be 2.0'

# 3. Test Modular Eye Material Setup (John Rambo Maps)
rambo_maps = Path(r'F:\Project_Files\Metahumans\Polyhammer Plugin\MH_John_Rambo\Maps')
if rambo_maps.is_dir():
    files_rambo = materials.texture_files(rambo_maps)
    assert 'eyes_irisbasecolor' in files_rambo, 'Eyes_IrisBasecolor should be detected in Rambo maps'
    assert 'eyes_sclerabasecolor' in files_rambo, 'Eyes_ScleraBasecolor should be detected in Rambo maps'
    assert 'eyes_veins' in files_rambo, 'Eyes_Veins should be detected in Rambo maps'

    eye_mat = bpy.data.materials.new('TEST_RAMBO_EYE')
    eye_mat.use_nodes = True
    e_tree = eye_mat.node_tree
    e_tree.nodes.clear()
    e_bsdf = e_tree.nodes.new('ShaderNodeBsdfPrincipled')
    warn = materials.eye_material(e_tree, e_bsdf, files_rambo, 'RAMBO', rig_scale=0.01)
    assert warn is None, f'Eye material setup returned unexpected warning: {warn}'

    # Check modular eye node network
    assert 'EYE_COLOR_MIX' in e_tree.nodes, 'EYE_COLOR_MIX node missing in eye material'
    assert 'EYE_LIMBUS_MASK' in e_tree.nodes, 'EYE_LIMBUS_MASK node missing in eye material'
    assert 'EYE_SCLERA_VEINS' in e_tree.nodes, 'EYE_SCLERA_VEINS node missing in eye material'
    assert 'EYE_NORMAL_MIX' in e_tree.nodes, 'EYE_NORMAL_MIX node missing in eye material'
    assert 'SMOOTH_CORNEA' in e_tree.nodes, 'SMOOTH_CORNEA node missing in eye material'
    assert e_bsdf.inputs['Base Color'].is_linked, 'Base Color should be linked from EYE_COLOR_MIX'
    assert abs(e_bsdf.inputs['Specular IOR Level'].default_value - 0.1) < 1e-5, 'Specular should be 0.1'
    assert abs(e_bsdf.inputs['Coat Weight'].default_value - 1.0) < 1e-5, 'Coat Weight should be 1.0'
    assert abs(e_bsdf.inputs['Coat Roughness'].default_value - 0.035) < 1e-5, 'Coat Roughness should be 0.035'
    assert abs(e_bsdf.inputs['Sheen Weight'].default_value - 1.0) < 1e-5, 'Sheen Weight should be 1.0'
    assert abs(e_bsdf.inputs['Sheen Roughness'].default_value - 0.2) < 1e-5, 'Sheen Roughness should be 0.2'
    assert abs(e_bsdf.inputs['IOR'].default_value - 1.3) < 1e-5, 'IOR should be 1.3'
    e_norm = next(n for n in e_tree.nodes if n.type == 'NORMAL_MAP')
    assert abs(e_norm.inputs['Strength'].default_value - 2.0) < 1e-5, 'Normal Strength should be 2.0'

# 4. Test Legacy Eye Material Setup (Logan Maps)
files_logan_all = materials.texture_files(logan_folder)
eye_logan_mat = bpy.data.materials.new('TEST_LOGAN_EYE')
eye_logan_mat.use_nodes = True
l_tree = eye_logan_mat.node_tree
l_tree.nodes.clear()
l_bsdf = l_tree.nodes.new('ShaderNodeBsdfPrincipled')
warn_logan = materials.eye_material(l_tree, l_bsdf, files_logan_all, 'LOGAN', rig_scale=0.01)
assert warn_logan is None
assert l_bsdf.inputs['Base Color'].is_linked, 'Logan Base Color should be linked from Eyes_Color'
assert abs(l_bsdf.inputs['Specular IOR Level'].default_value - 0.1) < 1e-5, 'Logan Specular should be 0.1'
assert abs(l_bsdf.inputs['Coat Weight'].default_value - 1.0) < 1e-5, 'Logan Coat Weight should be 1.0'
assert abs(l_bsdf.inputs['Coat Roughness'].default_value - 0.035) < 1e-5, 'Logan Coat Roughness should be 0.035'
assert abs(l_bsdf.inputs['Sheen Weight'].default_value - 1.0) < 1e-5, 'Logan Sheen Weight should be 1.0'
assert abs(l_bsdf.inputs['Sheen Roughness'].default_value - 0.2) < 1e-5, 'Logan Sheen Roughness should be 0.2'
assert abs(l_bsdf.inputs['IOR'].default_value - 1.3) < 1e-5, 'Logan IOR should be 1.3'
l_norm = next(n for n in l_tree.nodes if n.type == 'NORMAL_MAP')
assert abs(l_norm.inputs['Strength'].default_value - 2.0) < 1e-5, 'Logan Normal Strength should be 2.0'

# 5. Test Teeth Setup Parameters
rig_dummy = bpy.data.objects.new('RIG_DUMMY', bpy.data.armatures.new('RIG_DUMMY'))
bpy.context.scene.collection.objects.link(rig_dummy)
mesh_teeth = bpy.data.objects.new('MESH_TEETH', bpy.data.meshes.new('MESH_TEETH'))
mesh_teeth['mm_mesh_kind'] = 'teeth'
mesh_teeth.parent = rig_dummy
bpy.context.scene.collection.objects.link(mesh_teeth)
materials.setup(None, None, None, rig_dummy, None, [mesh_teeth], str(logan_folder), bpy.context.scene.collection, 'TEETH_TEST')
t_mat = mesh_teeth.data.materials[0]
t_bsdf = next(n for n in t_mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
assert abs(t_bsdf.inputs['Roughness'].default_value - 0.3) < 1e-5
assert abs(t_bsdf.inputs['IOR'].default_value - 1.45) < 1e-5
assert abs(t_bsdf.inputs['Subsurface Weight'].default_value - 0.8) < 1e-5
assert tuple(round(v, 3) for v in t_bsdf.inputs['Subsurface Radius'].default_value[:3]) == (1.0, 0.2, 0.1)
assert abs(t_bsdf.inputs['Subsurface Scale'].default_value - 0.001) < 1e-5
assert abs(t_bsdf.inputs['Specular IOR Level'].default_value - 0.8) < 1e-5
aniso_socket = t_bsdf.inputs.get('Anisotropic') or t_bsdf.inputs.get('Specular Anisotropy')
assert aniso_socket is not None and abs(aniso_socket.default_value - 0.5) < 1e-5
assert abs(t_bsdf.inputs['Coat Weight'].default_value - 0.3) < 1e-5
assert abs(t_bsdf.inputs['Coat Roughness'].default_value - 0.6) < 1e-5
assert abs(t_bsdf.inputs['Coat IOR'].default_value - 1.0) < 1e-5
assert abs(t_bsdf.inputs['Sheen Weight'].default_value - 0.1) < 1e-5
assert abs(t_bsdf.inputs['Sheen Roughness'].default_value - 0.0) < 1e-5

print('WRINKLE_DELTA_AUTODETECT_TEST_PASSED', flush=True)
