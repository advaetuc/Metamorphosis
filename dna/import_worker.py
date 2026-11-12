"""Isolated Blender import worker. Called only by import_job.py."""
import importlib.util
import json
import sys
import traceback
from pathlib import Path
import bpy


def main():
    config=Path(sys.argv[sys.argv.index('--')+1])
    request=json.loads(config.read_text(encoding='utf-8'))
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('metamorphosis',root/'__init__.py',submodule_search_locations=[str(root)])
    addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
    addon.register()
    from metamorphosis import progress_ui,bake,operators
    from types import SimpleNamespace
    operators.get_preferences=lambda context:SimpleNamespace(bindings_folder=request.get('bindings_folder',''),face_board_file='')
    status=config.parent/'progress.json'
    def progress(percent,stage=None,force=False):
        temp=status.with_suffix('.tmp')
        temp.write_text(json.dumps({'percent':percent,'stage':stage or 'Preparing character'}),encoding='utf-8')
        temp.replace(status)
    progress_ui.update=progress
    try:
        bpy.data.objects.remove(bpy.data.objects['Cube'],do_unlink=True)
        result=bpy.ops.metamorphosis.import_dna(**request['options'])
        if result!={'FINISHED'}:raise RuntimeError('DNA import did not finish')
        rig=bake.find_baked_rig(bpy.context)
        report=bpy.data.texts.get('MetaMorphosis Report')
        result={'collection':rig['mm_character_collection'],'rig':rig.name,
                'report':report.as_string() if report else ''}
        for pool in (bpy.data.objects,bpy.data.collections):
            for item in pool:
                if item.get('mm_import_id'):item['_mm_transfer_name']=item.name
        bpy.ops.wm.save_as_mainfile(filepath=str(config.parent/'character.blend'))
        (config.parent/'result.json').write_text(json.dumps(result),encoding='utf-8')
    except Exception:
        (config.parent/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise


if __name__=='__main__':main()
