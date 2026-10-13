"""Exercise the asynchronous video operator and cancellation on a saved test rig."""
import importlib.util
from pathlib import Path
import sys
import time
import tempfile
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
tempfile.tempdir = str(ROOT/'work')
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
import bpy
from metamorphosis import bake, mocap
args = sys.argv[sys.argv.index('--')+1:]
bpy.ops.wm.open_mainfile(filepath=args[0])
addon.register()
scene = bpy.context.scene
settings = scene.mm_capture
settings.target = bake.find_baked_rig(bpy.context)
settings.video_folder = str((ROOT/'work'/'video_tools').resolve())
settings.video = args[1]
board = mocap.target_board(scene)
original = board.animation_data.action
assert bpy.ops.metamorphosis.video_process() == {'FINISHED'}
assert bpy.ops.metamorphosis.video_cancel() == {'FINISHED'}
assert mocap._job is None and board.animation_data.action == original
scene.frame_set(11)
assert bpy.ops.metamorphosis.video_process() == {'FINISHED'}
deadline = time.monotonic()+180
while mocap._job and time.monotonic() < deadline:
    mocap._tick_video()
    time.sleep(.1)
assert not mocap._job, 'Video did not finish'
assert settings.video_status.startswith('Baked'), settings.video_status
assert board.animation_data.action != original and scene.frame_current == 11
print('VIDEO_JOB_PASSED', settings.video_status, flush=True)
addon.unregister()
