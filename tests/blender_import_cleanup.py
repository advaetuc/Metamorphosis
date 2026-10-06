"""Integration test: pass a head DNA path after --; optional final argument 'separate'."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
import bpy
from metamorphosis import bake, cleanup, ui
native=ROOT/'bindings'/'windows'/'x64'/f'py{sys.version_info.major}{sys.version_info.minor}'
sys.path.insert(0,str(native))
import dna,riglogic
args=sys.argv[sys.argv.index('--')+1:]
addon.register()
before={o.name for o in bpy.data.objects}
result=bpy.ops.metamorphosis.import_dna(filepath=args[0],face_board_file=str(ROOT/'assets'/'face_board.blend'),
    join_face_board='separate' not in args)
assert result=={'FINISHED'}
rig=bake.find_baked_rig(bpy.context)
assert rig and rig.get(cleanup.OWNER)
assert all(o.data.shape_keys is None for o in bake.head_meshes(rig))
assert all(o.get(cleanup.OWNER) for o in bpy.context.scene.objects if o.name not in before)
info=bake.validate_rig(rig)
assert not info['invalid'] and not info['needs_python'],info
board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
for n in rig[bake.RIG_KEY_BOARD].split('\n'):
    if n.startswith('CTRL_'):board.pose.bones[n].location=(0,0,0)
bpy.context.view_layer.update()
old=[rig.pose.bones[n].matrix.copy() for n in ('FACIAL_L_Eye','FACIAL_R_Eye')]
board.pose.bones['CTRL_C_eye'].location.x=.5
bpy.context.view_layer.update()
for name,matrix in zip(('FACIAL_L_Eye','FACIAL_R_Eye'),old):
    assert max(abs(a-b) for ra,rb in zip(matrix,rig.pose.bones[name].matrix) for a,b in zip(ra,rb))>1e-3

def check_lips():
    rig=bake.find_baked_rig(bpy.context)
    board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
    controls=[f'CTRL_{side}_mouth_lipsTogether{part}' for side in ('L','R') for part in ('U','D')]
    for n in rig[bake.RIG_KEY_BOARD].split('\n'):
        if n.startswith('CTRL_'):board.pose.bones[n].location=(0,0,0)
    board.pose.bones['CTRL_C_jaw'].location.y=.7
    def vertices():
        bpy.context.view_layer.update()
        graph=bpy.context.evaluated_depsgraph_get()
        return [v.co.copy() for mesh in bake.head_meshes(rig)
                for v in mesh.evaluated_get(graph).data.vertices]
    opened=vertices()
    for names in [[c] for c in controls]+[controls]:
        for c in controls:board.pose.bones[c].location.y=1 if c in names else 0
        moved=vertices()
        assert max((a-b).length for a,b in zip(opened,moved))>1e-4,names
    # Extreme extends the open jaw, including when the Lips Together controls are used.
    for lips_enabled in (False, True):
        for c in controls:board.pose.bones[c].location.y=1 if lips_enabled else 0
        board.pose.bones['CTRL_C_jaw_openExtreme'].location.y=0
        normal=vertices()
        board.pose.bones['CTRL_C_jaw_openExtreme'].location.y=1
        moved=vertices()
        assert max((a-b).length for a,b in zip(normal,moved))>1e-4,'Jaw Open Extreme'
    info=bake.validate_rig(rig)
    assert not info['invalid'] and not info['needs_python'],info
    return moved

check_lips()
assert bpy.ops.metamorphosis.rebuild()=={'FINISHED'}
expected=check_lips()

# Exercise panel code and ensure every icon and operator identifier is valid.
icons=set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())
class Layout:
    def __getattr__(self,name):
        def call(*args,**kwargs):
            if 'icon' in kwargs:assert kwargs['icon'] in icons,kwargs
            if name=='operator':
                category,op=args[0].split('.')
                getattr(getattr(bpy.ops,category),op).get_rna_type()
            return Layout()
        return call
from types import SimpleNamespace
for panel in ui.CLASSES:
    fake=SimpleNamespace(layout=Layout())
    panel.draw_header(fake,bpy.context);panel.draw(fake,bpy.context)

# Save/reopen ensures ownership survives between sessions. The scene is a test file only.
output=ROOT/'work'/('cleanup_separate.blend' if 'separate' in args else 'cleanup_joined.blend')
output.parent.mkdir(exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(output))
addon.unregister()
bpy.ops.wm.open_mainfile(filepath=str(output))
actual=check_lips()
assert max((a-b).length for a,b in zip(expected,actual))<1e-6
addon.register()
assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
assert {o.name for o in bpy.data.objects}==before,sorted(o.name for o in bpy.data.objects if o.name not in before)
assert not [o for o in bpy.data.collections if o.get(cleanup.OWNER)]
assert not [item for pool in cleanup.POOLS[2:] for item in getattr(bpy.data,pool)
            if item.get(cleanup.OWNER) and item.users==0]
addon.unregister()
print('IMPORT_CLEANUP_PASSED',bpy.app.version_string,args,info,flush=True)
