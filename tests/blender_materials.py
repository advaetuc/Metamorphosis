"""Run in Blender: real DCC import, native wrinkle parity, standalone save and cleanup."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np
import bpy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bindings'/'windows'/'x64'/f'py{sys.version_info.major}{sys.version_info.minor}'))
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import materials,bake,dnaio,verify,cleanup
from metamorphosis.logicmodel import RigLogicModel
import riglogic
addon.register()
folder=Path(r'F:\Project_Files\Metahumans\MH_Logan')
bpy.context.scene.mm_texture_folder=str(folder)
assert bpy.ops.metamorphosis.import_dna(filepath=str(folder/'head.dna'),character_name='LOGAN',face_board_file=str(ROOT/'assets'/'face_board.blend'))=={'FINISHED'}
rig=bake.find_baked_rig(bpy.context);board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
head=next(m for m in bake.head_meshes(rig) if m.get('mm_mesh_kind')=='head')
group=head.active_material.node_tree.nodes['DNA_WRINKLES']
assert len([i for i in group.inputs if '.head_' in i.name])==41
reader=dnaio.open_reader(folder/'head.dna');model=RigLogicModel.from_reader(reader)
res=verify.verify_model(model,riglogic,reader,release=dnaio.release_handle)
manager=riglogic.RigLogic(reader,riglogic.Configuration(),None);instance=riglogic.RigInstance(rigLogic=manager,memRes=None)
name_index={reader.getAnimatedMapName(i):i for i in range(reader.getAnimatedMapCount())}
poses,_=model.make_samples();worst=0
for pose in poses[:model.FACE_ONLY_SAMPLES]:
 for c in model.gui:
  instance.setGUIControl(c.index,float(pose[c.index]))
  if c.bone in board.pose.bones and c.axis>=0:board.pose.bones[c.bone].location[c.axis]=float(pose[c.index])
 manager.mapGUIToRawControls(instance);manager.calculate(instance)
 oracle=list(instance.getAnimatedMapOutputs())
 board.update_tag();bpy.context.view_layer.update()
 for socket in group.inputs:
  if '.head_' not in socket.name:continue
  wm,mask=socket.name.split('.',1);idx=name_index['head_'+wm+'_normal.'+mask.removesuffix('_msk')]
  err=abs(socket.default_value-oracle[idx]);worst=max(worst,err)
  assert err<1.1e-4,(socket.name,socket.default_value,oracle[idx],err)
print('WRINKLE_ORACLE_PASS',worst,rig['mm_material_drivers'],flush=True)
for pool in (bpy.data.materials,bpy.data.node_groups):
 for item in pool:
  if item.get(cleanup.OWNER):assert item.name==materials.caps(item.name),item.name
for obj in bpy.data.objects:
 if obj.animation_data:
  for curve in obj.animation_data.drivers:
   assert curve.driver.is_valid and (curve.driver.type!='SCRIPTED' or curve.driver.is_simple_expression),(obj.name,curve.data_path)
assert all(i.packed_file or Path(bpy.path.abspath(i.filepath)).is_file() for i in bpy.data.images if i.get(cleanup.OWNER))
# Failure leaves existing material assignment untouched.
original=head.active_material
try:materials.setup(reader,model,res.variant,rig,board,[head],str(ROOT/'work'),rig.users_collection[0],'INVALID')
except ValueError:pass
else:raise AssertionError('Invalid folder accepted')
assert head.active_material==original
for c in model.gui:
 if c.bone in board.pose.bones:board.pose.bones[c.bone].location=(0,0,0)
board.pose.bones['CTRL_L_brow_raiseIn'].location.y=.8
board.update_tag();bpy.context.view_layer.update()
value=group.inputs['wm1.head_wm1_browsRaiseInner_L_msk'].default_value
assert value>0
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'work'/'materials_logan.blend'))
dnaio.release_handle(instance);dnaio.release_handle(manager);dnaio.release_handle(reader)
addon.unregister();bpy.ops.wm.open_mainfile(filepath=str(ROOT/'work'/'materials_logan.blend'))
rig=bake.find_baked_rig(bpy.context);board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
head=next(m for m in bake.head_meshes(rig) if m.get('mm_mesh_kind')=='head');group=head.active_material.node_tree.nodes['DNA_WRINKLES']
assert abs(group.inputs['wm1.head_wm1_browsRaiseInner_L_msk'].default_value-value)<1e-5
board.pose.bones['CTRL_L_brow_raiseIn'].location.y=0;board.update_tag();bpy.context.view_layer.update()
assert group.inputs['wm1.head_wm1_browsRaiseInner_L_msk'].default_value==0
addon.register()
shared=bpy.data.objects.new('UNRELATED',None);bpy.context.scene.collection.objects.link(shared)
assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
assert shared.name in bpy.data.objects
assert not [m for m in bpy.data.materials if m.get(cleanup.OWNER)]
assert not [g for g in bpy.data.node_groups if g.get(cleanup.OWNER)]
print('MATERIALS_TESTS_PASSED',bpy.app.version_string,flush=True)
addon.unregister()
