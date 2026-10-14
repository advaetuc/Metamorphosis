import bpy,importlib.util,sys,time,statistics
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'bindings/windows/x64'/f'py{sys.version_info.major}{sys.version_info.minor}'))
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import bake,materials
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'work/materials_logan.blend'));addon.register()
rig=bake.find_baked_rig(bpy.context)
bpy.context.scene.mm_texture_folder=r'F:\Project_Files\Metahumans\MH_Logan'
assert bpy.ops.metamorphosis.setup_materials()=={'FINISHED'}
first={o for o in bpy.data.objects if o.get('mm_material_set')}
assert first
assert bpy.ops.metamorphosis.setup_materials()=={'FINISHED'}
second={o for o in bpy.data.objects if o.get('mm_material_set')}
assert len(second)==len(first),(len(first),len(second))
# Reapplying may not destroy a generated material reused by an unrelated mesh.
head=next(m for m in bake.head_meshes(rig) if m.get('mm_mesh_kind')=='head')
shared=head.active_material;token=shared['mm_material_set']
bpy.ops.mesh.primitive_cube_add();user=bpy.context.object;user.data.materials.append(shared)
bpy.context.view_layer.objects.active=rig
assert bpy.ops.metamorphosis.setup_materials()=={'FINISHED'}
assert user.active_material==shared
assert any(o.get('mm_material_set')==token for o in bpy.data.objects)
print('MATERIAL_REAPPLY_PASS',flush=True)
addon.unregister()
