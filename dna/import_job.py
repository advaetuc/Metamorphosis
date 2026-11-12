"""Responsive import job: isolate heavy Blender work, then append owned data."""
import json
from pathlib import Path
import subprocess
import tempfile
import bpy
from ..core import cleanup, progress_ui

_active=[]


class Job:
    def __init__(self,options,directory=None,bindings_folder=''):
        self.folder=tempfile.TemporaryDirectory(prefix='MetaMorphosisImport_',dir=directory)
        self.path=Path(self.folder.name)
        request=self.path/'request.json'
        self.process=None;self.log=None
        try:
            request.write_text(json.dumps({'options':options,'bindings_folder':bindings_folder}),encoding='utf-8')
            self.log=(self.path/'worker.log').open('w',encoding='utf-8')
            self.process=subprocess.Popen([bpy.app.binary_path,'--background','--factory-startup','--threads','2',
                '--python-exit-code','1','--python',str(Path(__file__).with_name('import_worker.py')),'--',str(request)],
                stdout=self.log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:
            self.close();raise

    def progress(self):
        try:return json.loads((self.path/'progress.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {'percent':0,'stage':'Preparing DNA import'}

    def append(self,context):
        error=self.path/'error.txt'
        if self.process.returncode!=0 or not (self.path/'result.json').is_file():
            message=error.read_text(encoding='utf-8') if error.is_file() else (self.path/'worker.log').read_text(encoding='utf-8')
            raise RuntimeError(message[-6000:] or 'The isolated import process stopped unexpectedly')
        result=json.loads((self.path/'result.json').read_text(encoding='utf-8'))
        before=cleanup.snapshot()
        try:
            with bpy.data.libraries.load(str(self.path/'character.blend'),link=False) as (source,target):
                if result['collection'] not in source.collections:raise RuntimeError('Imported character collection is missing')
                target.collections=[result['collection']]
            collection=target.collections[0]
            context.scene.collection.children.link(collection)
            names={}
            created_objects=[o for o in bpy.data.objects if o.as_pointer() not in before['objects']]
            created_collections=[c for c in bpy.data.collections if c.as_pointer() not in before['collections']]
            for item in [*created_objects,*created_collections]:
                original=item.get('_mm_transfer_name')
                if original:names[original]=item.name;del item['_mm_transfer_name']
            for obj in created_objects:
                for key in ('mm_board_object','mm_data_object','mm_character_collection'):
                    if key in obj:obj[key]='\n'.join(names.get(n,n) for n in str(obj[key]).split('\n'))
            rig=next(o for o in collection.all_objects if o.get('mm_source_dna') and o.type=='ARMATURE')
            for obj in context.selected_objects:obj.select_set(False)
            rig.hide_set(False);rig.select_set(True);context.view_layer.objects.active=rig
            report=bpy.data.texts.get('MetaMorphosis Report') or bpy.data.texts.new('MetaMorphosis Report')
            report.clear();report.write(result['report'])
            context.view_layer.update()
            return rig
        except Exception:
            created=[item for pool in cleanup.POOLS for item in getattr(bpy.data,pool) if item.as_pointer() not in before[pool]]
            bpy.data.batch_remove(ids=created)
            raise

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.log:self.log.close()
        self.folder.cleanup()


def start(operator,context):
    from ..core import operators
    from . import faceboard, importer
    prefs=operators.get_preferences(context)
    board=faceboard.find_face_board_file(operator.face_board_file or (prefs.face_board_file if prefs else ''))
    if board is None:raise ValueError('The face-board asset is missing')
    options={name:getattr(operator,name) for name in ('filepath','scale','lod','join_face_board','quality','force_bake')}
    options.update(character_name=importer.unique_prefix(operator.character_name.strip() or Path(operator.filepath).stem),
                   face_board_file=str(board),face_board_location=list(operator.face_board_location),
                   texture_folder=operator.texture_folder or context.scene.mm_texture_folder,synchronous=True)
    operator._job=Job(options,bindings_folder=prefs.bindings_folder if prefs else '')
    operator._timer=context.window_manager.event_timer_add(.08,window=context.window)
    _active.append(operator)
    context.window_manager.modal_handler_add(operator)
    progress_ui.begin('Preparing DNA import')
    return {'RUNNING_MODAL'}


def finish(operator,context):
    if operator in _active:_active.remove(operator)
    if getattr(operator,'_timer',None):
        context.window_manager.event_timer_remove(operator._timer);operator._timer=None
    if getattr(operator,'_job',None):operator._job.close();operator._job=None
    progress_ui.end()


def modal(operator,context,event):
    if getattr(operator,'_job',None) is None:return {'CANCELLED'}
    if event.type=='ESC':
        finish(operator,context);operator.report({'INFO'},'Import cancelled');return {'CANCELLED'}
    if event.type!='TIMER':return {'RUNNING_MODAL'}
    job=operator._job
    status=job.progress();progress_ui.update(min(98,status['percent']),status['stage'])
    if job.process.poll() is None:return {'RUNNING_MODAL'}
    try:
        progress_ui.update(99,'Connecting your character',force=True)
        rig=job.append(context)
        operator.report({'INFO'},f'Imported {rig.name}')
        result={'FINISHED'}
    except Exception as exc:
        report=bpy.data.texts.get('MetaMorphosis Report') or bpy.data.texts.new('MetaMorphosis Report')
        report.clear();report.write(str(exc))
        operator.report({'ERROR'},'Import failed; see MetaMorphosis Report')
        result={'CANCELLED'}
    finally:finish(operator,context)
    return result


def shutdown():
    for operator in list(_active):finish(operator,bpy.context)
