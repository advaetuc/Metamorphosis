"""Evaluate lip seal and inward roll on actual skinned vertices, not only mappings.

Pass DNA paths after --. Captured phone accuracy is not asserted by this test.
"""
import importlib.util
from pathlib import Path
import sys
import bpy

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import bake
from metamorphosis.mocap_mapping import face_board_pose
addon.register()
for filename in sys.argv[sys.argv.index('--')+1:]:
    assert bpy.ops.metamorphosis.import_dna(filepath=filename,face_board_file=str(ROOT/'assets/face_board.blend'))=={'FINISHED'}
    rig=bake.find_baked_rig(bpy.context);board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
    head=next(m for m in bake.head_meshes(rig) if m.get('mm_mesh_kind')=='head')
    def apply(values):
        for b in board.pose.bones:
            if b.name.startswith('CTRL_'): b.location=(0,0,0)
        for (bone,axis),value in face_board_pose(values).items():
            if bone in board.pose.bones: board.pose.bones[bone].location[axis]=value
        board.update_tag();bpy.context.view_layer.update()
        return [v.co.copy() for v in head.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.vertices]
    neutral=apply({})
    # Anatomical inner-seam and vermilion landmarks, chosen from neutral geometry.
    indices={name:min(range(len(neutral)),key=lambda i:(neutral[i]-rig.pose.bones['FACIAL_C_Lip'+name].head).length)
             for name in ('Upper2','Lower2','Upper1','Lower1')}
    def gap(vertices): return vertices[indices['Upper2']].z-vertices[indices['Lower2']].z
    opened=apply({'jawOpen':.6})
    sealed=apply({'jawOpen':.6,'mouthClose':.6,'mouthFunnel':.6,'mouthUpperUpLeft':.6,
                  'mouthUpperUpRight':.6,'mouthLowerDownLeft':.6,'mouthLowerDownRight':.6})
    assert board.pose.bones['CTRL_C_jaw'].location.y > .59
    assert abs(gap(sealed)) < .0015, (filename,'sealed gap',gap(sealed))
    assert gap(opened)-gap(sealed) > .005, (filename,'closure did not reduce gap')
    # Roll must tuck the selected lip inward; do not synthesize a bite pose.
    for vertical in ('Upper','Lower'):
        rolled=apply({'mouthRoll'+vertical:1})
        i=indices[vertical+'1']
        assert rolled[i].y-neutral[i].y > .001, (filename,vertical,'roll did not tuck inward')
        for s in 'LR':
            for p in 'UD': assert board.pose.bones[f'CTRL_{s}_mouth_lipBite{p}'].location.y==0
    assert max((a-b).length for a,b in zip(neutral,apply({})))<1e-6
    print('CAPTURE_GEOMETRY_PASS',filename,'open_gap',gap(opened),'sealed_gap',gap(sealed),flush=True)
    assert bpy.ops.metamorphosis.remove_all()=={'FINISHED'}
addon.unregister()
