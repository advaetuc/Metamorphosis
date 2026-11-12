"""Auto Key and standalone script smoke test for the custom body controls."""
import importlib.util
from pathlib import Path
import sys
import bpy

ROOT=Path(__file__).resolve().parents[1]
WORK=__import__('runpy').run_path(str(Path(__file__).with_name('_paths.py')))['WORK']
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon);addon.register()
assert bpy.ops.metamorphosis.import_body(filepath='F:/Project_Files/Metahumans/MH_John_Rambo/body.dna')=={'FINISHED'}
rig=next(o for o in bpy.context.scene.objects if o.get('mm_body_rig'))
bpy.context.view_layer.objects.active=rig;rig.select_set(True)
assert bpy.ops.metamorphosis.convert_body()=={'FINISHED'}
assert bpy.ops.metamorphosis.bake_rig_ui()=={'FINISHED'}
bpy.context.scene.tool_settings.use_keyframe_insert_auto=True
bpy.context.scene.frame_set(10)
rig.pose.bones['FOREARM_FK.L'].rotation_euler=(.12,.08,.8)
rig.update_tag();bpy.context.view_layer.update()
assert bpy.ops.john_rambo.ik_fk_arm(side='L')=={'FINISHED'}
matrix=rig.pose.bones['MCH_SWITCH_HAND.L'].matrix.copy()
action=rig.animation_data.action
assert action
curves=[]
for layer in action.layers:
    for strip in layer.strips:
        if hasattr(strip,'channelbags'):
            for bag in strip.channelbags:curves.extend(bag.fcurves)
paths={f.data_path for f in curves}
for name in ('HAND_IK.L','ARM_IK_POLE.L','MCH_IK_ARM.L','MCH_IK_FOREARM.L'):
    assert f'pose.bones["{name}"].rotation_euler' in paths,(name,paths)
assert any(p.endswith('.pole_angle') for p in paths)
assert 'pose.bones["PROPERTIES"]["ARM_FK_IK.L"]' in paths
path=WORK/'converter_autokey.blend';bpy.ops.wm.save_as_mainfile(filepath=str(path))
addon.unregister()
bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=False,use_scripts=False)
rig=next(o for o in bpy.context.scene.objects if o.get('mm_body_converter'))
bpy.context.scene.frame_set(10);bpy.context.view_layer.update()
assert max(abs(x-y) for ra,rb in zip(matrix,rig.pose.bones['MCH_SWITCH_HAND.L'].matrix) for x,y in zip(ra,rb))<1e-4
exec(compile(bpy.data.texts['MetaMorphosis_Custom_RigUI.py'].as_string(),'MetaMorphosis_Custom_RigUI.py','exec'),{'__name__':'__main__'})
bpy.context.view_layer.objects.active=rig
assert bpy.types.MM_PT_baked_rigui.bl_category=='Item' and bpy.types.MM_PT_baked_rigui.poll(bpy.context)
assert bpy.ops.mm_baked_rigui.fk_ik_arm(side='L')=={'FINISHED'}
print('BODY_AUTOKEY_STANDALONE_PASS',flush=True)
