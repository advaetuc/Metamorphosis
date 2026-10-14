import importlib.util,sys,time
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import mocap
args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
tools = Path(args[0]).resolve() if args else ROOT/'work'/'video_tools'
addon.register()
root=ROOT/'work'/'setup_shared_test'
mocap.shared_video_root=lambda:root
s=bpy.context.scene.mm_capture
assert s.video_folder==s.video_python==''
print('AUTOMATIC_PYTHON',mocap.setup_python(s),flush=True)
# Exercise checking and remembering a tested installation without any per-scene paths.
root.mkdir(exist_ok=True)
mocap.remember_video_folder(tools)
assert mocap.video_folder(s)==tools
assert bpy.ops.metamorphosis.video_setup()=={'FINISHED'}
while mocap._job:
 mocap._tick_video();time.sleep(.1)
assert s.video_status=='Video tools ready',s.video_status
new=bpy.data.scenes.new('NEW_SCENE')
assert new.mm_capture.video_folder==''
assert mocap.video_folder(new.mm_capture)==tools
print('SETUP_PERSISTENCE_PASS',flush=True)
addon.unregister()
