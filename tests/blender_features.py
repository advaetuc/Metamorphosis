"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("metamorphosis", ROOT / "__init__.py",
                                            submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
import bpy
from metamorphosis import cleanup, bake

addon.register()
assert not hasattr(bpy.types.Scene, 'mm_body_settings')
assert 'import_shape_keys' not in bpy.ops.metamorphosis.import_dna.get_rna_type().properties
assert not hasattr(bpy.types, 'MM_OT_combine_body')
confirm=bpy.types.WindowManager.bl_rna.functions['invoke_confirm'].parameters
assert 'WARNING' in confirm['icon'].enum_items.keys()
assert all(name in confirm for name in ('title','message','confirm_text'))

def add_object(name, collection, mesh=None):
    obj=bpy.data.objects.new(name,mesh)
    collection.objects.link(obj)
    return obj

# Unrelated orphan data must survive. Shared imported materials must survive too.
orphan=bpy.data.meshes.new('USER_ORPHAN')
user=add_object('USER',bpy.context.scene.collection,bpy.data.meshes.new('USER_MESH'))
before=cleanup.snapshot()
root=bpy.data.collections.new('CHARACTER')
bpy.context.scene.collection.children.link(root)
child=bpy.data.collections.new('HEAD');root.children.link(child)
material=bpy.data.materials.new('IMPORTED_MATERIAL')
data=bpy.data.meshes.new('IMPORTED_MESH');data.materials.append(material)
obj=add_object('IMPORTED',child,data)
obj.shape_key_add(name='Basis')
curve=bpy.data.curves.new('IMPORTED_CURVE','CURVE')
add_object('WIDGET',child,curve)
cleanup.mark_created(before,'test-import')
user.data.materials.append(material)
user.parent=obj
user.location=(1,2,3)
bpy.context.view_layer.update()
world=user.matrix_world.copy()
# Keep a manually added object inside the imported collection.
manual=add_object('MANUAL',child)
holder=bake.create_data_object(child,'REBUILT')
assert holder[cleanup.OWNER]=='test-import'
obj.name='RENAMED'
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
assert 'RENAMED' not in bpy.data.objects and 'WIDGET' not in bpy.data.objects
assert 'REBUILT_MM_RIGLOGICDATA_00' not in bpy.data.objects
assert 'IMPORTED_MESH' not in bpy.data.meshes and 'IMPORTED_CURVE' not in bpy.data.curves
assert 'IMPORTED_MATERIAL' in bpy.data.materials and 'USER_ORPHAN' in bpy.data.meshes
assert user.parent is None and user.matrix_world==world
assert 'MANUAL' in bpy.data.objects and 'HEAD' in bpy.data.collections

# Second removal clears an empty retained imported collection, never MANUAL.
bpy.data.objects.remove(manual,do_unlink=True)
assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
assert 'CHARACTER' not in bpy.data.collections and 'HEAD' not in bpy.data.collections

# Objects shared with another scene must remain usable there.
before=cleanup.snapshot()
shared=add_object('SHARED',bpy.context.scene.collection)
cleanup.mark_created(before,'shared-import')
other=bpy.data.scenes.new('OTHER')
other.collection.objects.link(shared)
assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
assert 'SHARED' in other.objects and 'SHARED' not in bpy.context.scene.objects

# Interrupted imports can be cleaned without a completed rig.
before=cleanup.snapshot()
partial=add_object('PARTIAL',bpy.context.scene.collection)
cleanup.mark_created(before,'failed-import')
assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
assert 'PARTIAL' not in bpy.data.objects

# Legacy rigs remain removable through explicit references, not collection names.
root=bpy.data.collections.new('LEGACY');bpy.context.scene.collection.children.link(root)
arm=bpy.data.armatures.new('LEGACY_RIG')
rig=add_object('LEGACY_RIG',root,arm)
rig[bake.RIG_KEY_DATA]=''
rig['mm_character_collection']=root.name
user_extra=add_object('USER_EXTRA',root)
assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
assert 'LEGACY_RIG' not in bpy.data.objects and 'USER_EXTRA' in bpy.data.objects

# A previously combined body is user data embedded in the same armature.
mixed=add_object('MIXED_RIG',root,bpy.data.armatures.new('MIXED_RIG'))
mixed[bake.RIG_KEY_DATA]=''
mixed['mm_combined_body']='USER_BODY'
assert mixed not in cleanup.targets(bpy.context.scene)[0]

addon.unregister()
addon.register()
addon.unregister()
print('FEATURE_TESTS_PASSED',bpy.app.version_string)
