"""Real subprocess import, cancellation, append and standalone pose validation."""
import importlib.util,sys,time
from pathlib import Path
WORK = __import__("runpy").run_path(str(Path(__file__).with_name("_paths.py")))["WORK"]
import bpy
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',root/'__init__.py',submodule_search_locations=[str(root)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
addon.register()
from metamorphosis import import_job,bake,cleanup
options={'filepath':r'F:\Project_Files\Metahumans\MH_Logan\head.dna','character_name':'JOB_TEST',
         'face_board_file':str(root/'assets/face_board.blend'),'synchronous':True,'join_face_board':False}
existing=bpy.data.objects.new('FACE_GUI',None);bpy.context.scene.collection.objects.link(existing)
before=set(bpy.data.objects)
cancel=import_job.Job(options,directory=WORK);folder=cancel.path;cancel.close()
assert not folder.exists() and set(bpy.data.objects)==before
job=import_job.Job(options,directory=WORK);progress=set();deadline=time.monotonic()+180
try:
    while job.process.poll() is None:
        progress.add(job.progress()['percent'])
        assert time.monotonic()<deadline,'Worker exceeded test timeout'
        time.sleep(.1)
    rig=job.append(bpy.context)
    assert rig.name.startswith('JOB_TEST')
finally:job.close()
assert len(progress)>1,progress
board=bpy.data.objects[rig[bake.RIG_KEY_BOARD_OBJECT]]
old=rig.pose.bones['FACIAL_C_Jaw'].matrix.copy()
board.pose.bones['CTRL_C_jaw'].location.y=.8;board.update_tag();bpy.context.view_layer.update()
assert max(abs(a-b) for ra,rb in zip(old,rig.pose.bones['FACIAL_C_Jaw'].matrix) for a,b in zip(ra,rb))>.01
assert not bake.validate_rig(rig)['invalid'],bake.validate_rig(rig)
assert all(o.get('mm_import_id') for o in set(bpy.data.objects)-before)
print('IMPORT_JOB_PASS',sorted(progress),flush=True)
cleanup.remove_all(bpy.context)
assert set(bpy.data.objects)==before
addon.unregister()
