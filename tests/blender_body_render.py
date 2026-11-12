"""Compare standalone body/face skinning in viewport and render dependency graphs."""
from pathlib import Path
WORK = __import__("runpy").run_path(str(Path(__file__).with_name("_paths.py")))["WORK"]
import bpy
import numpy as np
bpy.ops.wm.open_mainfile(filepath=str(WORK/'body_merge190.blend'),load_ui=False,use_scripts=False)
scene=bpy.context.scene
meshes=[o for o in scene.objects if o.get('mm_body_mesh') or o.get('mm_head_mesh')]
assert any(o.get('mm_body_mesh') for o in meshes)
def geometry(graph):
    return {o.name:np.asarray([v.co[:] for v in o.evaluated_get(graph).data.vertices]) for o in meshes}
expected={}
for frame in (1,5,9):
    scene.frame_set(frame);bpy.context.view_layer.update()
    expected[frame]=geometry(bpy.context.evaluated_depsgraph_get())
seen=set();failures=[]
def check(scene,graph):
    if graph.mode!='RENDER' or scene.frame_current not in expected:return
    try:
        actual=geometry(graph)
        error=max(float(np.max(np.abs(actual[n]-expected[scene.frame_current][n]))) for n in actual)
        assert error<1e-6,(scene.frame_current,error)
        seen.add(scene.frame_current)
    except Exception as exc:failures.append(repr(exc))
camera=bpy.data.objects.new('BODY_RENDER_CAMERA',bpy.data.cameras.new('BODY_RENDER_CAMERA'))
scene.collection.objects.link(camera);scene.camera=camera
camera.location=(0,-3,1);camera.rotation_euler=(1.57079632679,0,0)
scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_x=scene.render.resolution_y=32
scene.render.resolution_percentage=100
scene.frame_start=1;scene.frame_end=9;scene.frame_step=4
scene.render.filepath=str(WORK/'body_render'/'frame_')
bpy.app.handlers.frame_change_post.append(check)
try:bpy.ops.render.render(animation=True)
finally:bpy.app.handlers.frame_change_post.remove(check)
assert seen=={1,5,9} and not failures,(seen,failures)
print('BODY_RENDER_STANDALONE_PASS',bpy.app.version_string,flush=True)
