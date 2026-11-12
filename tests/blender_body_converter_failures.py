"""Failed fitting and user-added bone preservation checks."""
import bpy,sys,importlib.util
from pathlib import Path
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('metamorphosis',root/'__init__.py',submodule_search_locations=[str(root)])
a=importlib.util.module_from_spec(s);sys.modules[s.name]=a;s.loader.exec_module(a);a.register()
from metamorphosis import body_geometry,cleanup
bpy.ops.wm.open_mainfile(filepath=r'F:/AI/Training_Data/Body Rig/Metahuman_Body_Rig_OG.blend',load_ui=False,use_scripts=False)
r=bpy.data.objects['METAHUMAN_BODY_RIG'];bpy.context.view_layer.objects.active=r;r.select_set(True)
before=cleanup.snapshot();old=body_geometry.fit
body_geometry.fit=lambda *args:(_ for _ in ()).throw(ValueError('Injected fitting failure'))
try:
 try:bpy.ops.metamorphosis.convert_body()
 except RuntimeError:pass
finally:body_geometry.fit=old
assert cleanup.snapshot()==before,'Fitting failure leaked or deleted data'
assert len(r.data.bones)==342
# A prototype-like root control plus a user-added accessory must be rejected.
bpy.ops.object.mode_set(mode='EDIT')
for name in ('ROOT','USER_ACCESSORY'):
 b=r.data.edit_bones.new(name);b.head=(0,0,0);b.tail=(0,1,0);b.use_deform=False
bpy.ops.object.mode_set(mode='OBJECT')
for name in ('ROOT','USER_ACCESSORY'):
 for c in list(r.data.bones[name].collections):c.unassign(r.data.bones[name])
r['mm_body_control_map']='{"root":"ROOT"}'
before=cleanup.snapshot()
try:bpy.ops.metamorphosis.convert_body()
except RuntimeError:pass
assert cleanup.snapshot()==before
assert 'USER_ACCESSORY' in r.data.bones and len(r.data.bones)==344
print('CONVERTER_FAILURE_PRESERVATION_PASS',flush=True)
