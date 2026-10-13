"""Live Link and video capture UI, main-thread animation, and native action baking."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import bake
from .mocap_core import Receiver, Recording, Sample, resample
from .mocap_mapping import face_board_pose
from .video_worker import environment_python

_live = None
_job = None


class MM_CaptureSettings(bpy.types.PropertyGroup):
    target: PointerProperty(name="Head Rig", type=bpy.types.Object,
                            poll=lambda self, obj: obj.type == 'ARMATURE' and bake.RIG_KEY_DATA in obj)
    host: StringProperty(name="Listen Address", default="0.0.0.0")
    port: IntProperty(name="Port", default=11111, min=1024, max=65535)
    subject: StringProperty(name="Subject", description="Optional actor filter; blank locks onto the first actor")
    mirror: BoolProperty(name="Mirror Left / Right", default=False)
    gain: FloatProperty(name="Expression Strength", default=1, min=0, max=3)
    smoothing: FloatProperty(name="Smoothing", default=.04, min=0, max=.5, subtype='TIME',
                             description="Smoothing time in seconds; zero disables smoothing")
    extreme: FloatProperty(name="Extreme Jaw", default=0, min=0, max=1,
                           description="Add Jaw Open Extreme near the top of the captured jaw range")
    end_mode: EnumProperty(name="At Timeline End", items=(
        ('EXTEND', 'Extend Timeline', 'Extend the timeline while recording'),
        ('STOP', 'Stop Keyframing', 'Finish the take at the end frame; live preview continues')), default='EXTEND')
    take_name: StringProperty(name="Take Name", default="Face Capture")
    status: StringProperty(default="Disconnected", options={'SKIP_SAVE'})
    last_take: StringProperty(name="Last Take", default="")
    video: StringProperty(name="Video", subtype='FILE_PATH')
    video_python: StringProperty(name="Python Executable", subtype='FILE_PATH',
                                 description="Optional Python executable for installing local video tools; blank uses Blender's Python")
    video_folder: StringProperty(name="Video Tools Folder", subtype='DIR_PATH',
                                 description="Optional existing video-tools installation")
    video_status: StringProperty(default="Choose a video to process", options={'SKIP_SAVE'})


def target_board(scene):
    rig = scene.mm_capture.target or bake.find_baked_rig(bpy.context)
    if rig is None or rig.name not in scene.objects:
        raise ValueError("Select an imported MetaMorphosis head rig in this scene")
    board = bpy.data.objects.get(str(rig.get(bake.RIG_KEY_BOARD_OBJECT, "")))
    if board is None or board.name not in scene.objects:
        raise ValueError("The rig's face board is missing")
    missing = {n for n, _ in face_board_pose({}) if n not in board.pose.bones}
    if missing:
        raise ValueError("Face board is missing capture controls: " + ", ".join(sorted(missing)[:3]))
    scene.mm_capture.target = rig
    return board


def capture_options(settings):
    return dict(gain=settings.gain, mirror=settings.mirror, extreme=settings.extreme)


def smooth_samples(samples, seconds):
    previous = None
    for sample in samples:
        values = sample.values
        if previous and seconds > 0:
            alpha = 1-math.exp(-max(0, sample.time-previous.time)/seconds)
            values = {n: previous.values.get(n, 0)*(1-alpha)+v*alpha for n, v in values.items()}
        previous = Sample(sample.time, values, sample.subject)
        yield previous


def bake_take(board, samples, fps, frame_start, name, options, smoothing=0, start_time=None):
    """Create a separate action; preserve the previous action and all its channels."""
    rows = [(frame_start+i, face_board_pose(v, **options))
            for i, v in resample(list(smooth_samples(samples, smoothing)), fps, start_time)]
    if not rows:
        raise ValueError("No captured frames to bake")
    action = bpy.data.actions.new(name or "Face Capture")
    try:
        slot = action.slots.new(id_type='OBJECT', name=board.name)
        layer = action.layers.new("Facial Capture")
        strip = layer.strips.new(type='KEYFRAME')
        bag = strip.channelbag(slot, ensure=True)
        for bone, axis in rows[0][1]:
            path = board.pose.bones[bone].path_from_id("location")
            curve = bag.fcurves.new(data_path=path, index=axis)
            curve.keyframe_points.add(len(rows))
            curve.keyframe_points.foreach_set("co", [x for frame, pose in rows for x in (frame, pose[(bone, axis)])])
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
            curve.update()
        board.animation_data_create()
        previous = board.animation_data.action
        if previous:
            previous.use_fake_user = True
        action.use_fake_user = True
        board.animation_data.action = action
        board.animation_data.action_slot = slot
    except Exception:
        bpy.data.actions.remove(action)
        raise
    return action, rows[-1][0]


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'DOPESHEET_EDITOR'}:
                area.tag_redraw()


def finish_recording():
    if not _live or not _live['recording']:
        return
    recording = _live['recording']
    scene, board = _live['scene'], _live['board']
    if not recording.samples:
        _live['recording'] = None
        scene.mm_capture.status = "No frames received during recording"
        return
    action, last = bake_take(board, recording.samples, recording.fps, recording.frame_start,
                            _live['take_name'], _live['options'], _live['smoothing'], recording.start_time)
    _live['recording'] = None
    scene.mm_capture.last_take = action.name
    scene.frame_set(min(last, recording.frame_end) if not recording.extend else last)
    if recording.extend:
        scene.frame_end = max(scene.frame_end, last)
    scene.mm_capture.status = f"Saved take: {action.name}"


def _tick_live():
    global _live
    if not _live:
        return None
    state = _live
    try:
        scene, board = state['scene'], state['board']
        if bpy.context.scene != scene or board.name not in scene.objects:
            disconnect()
            return None
        now = time.monotonic()
        packets = state['receiver'].drain()
        recording = state['recording']
        for packet in packets:
            if recording:
                recording.add(packet)
        if recording:
            if now < recording.start_time:
                scene.mm_capture.status = f"Recording in {math.ceil(recording.start_time-now)}…"
            elif recording.finished(now):
                finish_recording()
            else:
                frame = recording.frame(now)
                if recording.extend:
                    scene.frame_end = max(scene.frame_end, frame)
                scene.frame_set(frame)
                scene.mm_capture.status = f"Recording · frame {frame}"
                if not packets and (state['preview'] is None or now-state['preview'].time > 1):
                    scene.mm_capture.status += " · waiting for signal"
        if packets:
            packet = packets[-1]
            previous = state['preview']
            smoothed = list(smooth_samples(([previous] if previous else [])+[packet], scene.mm_capture.smoothing))[-1]
            state['preview'] = smoothed
            options = state['options'] if recording else capture_options(scene.mm_capture)
            for (bone, axis), value in face_board_pose(smoothed.values, **options).items():
                board.pose.bones[bone].location[axis] = value
            if not recording:
                scene.mm_capture.status = f"Live · {packet.subject}"
        elif not recording and (state['preview'] is None or now-state['preview'].time > 1):
            scene.mm_capture.status = "Listening · waiting for ARKit data"
        receiver = state['receiver']
        if receiver.error:
            raise RuntimeError(receiver.error)
        if receiver.dropped:
            scene.mm_capture.status += f" · {receiver.dropped} packets dropped"
        if receiver.bad_packets and not packets and state['preview'] is None:
            scene.mm_capture.status = "Unrecognized data · select ARKit mode in Live Link Face"
        _redraw()
        return 1/60
    except Exception as error:
        try:
            state['scene'].mm_capture.status = f"Capture stopped: {error}"
        except ReferenceError:
            pass
        disconnect(bake_recording=False)
        return None


def disconnect(bake_recording=True):
    global _live
    if _live:
        try:
            if bake_recording:
                finish_recording()
        finally:
            _live['receiver'].close()
            _live = None
    if bpy.app.timers.is_registered(_tick_live):
        bpy.app.timers.unregister(_tick_live)


class MM_OT_live_start(bpy.types.Operator):
    bl_idname = 'metamorphosis.live_start'
    bl_label = 'Connect Live Link'
    def execute(self, context):
        global _live
        if _live or _job:
            self.report({'ERROR'}, "Finish the current capture or video job first")
            return {'CANCELLED'}
        try:
            scene = context.scene
            board = target_board(scene)
            settings = scene.mm_capture
            receiver = Receiver(settings.host, settings.port, subject=settings.subject)
            _live = dict(scene=scene, board=board, receiver=receiver, recording=None, preview=None)
            bpy.app.timers.register(_tick_live, first_interval=0)
            settings.status = "Listening · waiting for ARKit data"
        except Exception as error:
            disconnect(False)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class MM_OT_live_stop(bpy.types.Operator):
    bl_idname = 'metamorphosis.live_stop'
    bl_label = 'Disconnect'
    def execute(self, context):
        disconnect()
        context.scene.mm_capture.status = "Disconnected"
        return {'FINISHED'}


class MM_OT_record_start(bpy.types.Operator):
    bl_idname = 'metamorphosis.record_start'
    bl_label = 'Start Recording'
    def execute(self, context):
        if not _live or _live['recording'] or _live['scene'] != context.scene:
            return {'CANCELLED'}
        scene = context.scene
        if context.screen and context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        settings = scene.mm_capture
        if settings.end_mode == 'STOP' and scene.frame_current > scene.frame_end:
            self.report({'ERROR'}, "Move the playhead inside the timeline before recording")
            return {'CANCELLED'}
        _live['options'] = capture_options(settings)
        _live['smoothing'] = settings.smoothing
        _live['take_name'] = settings.take_name
        _live['recording'] = Recording(time.monotonic(), scene.frame_current, scene.frame_end,
                                       scene.render.fps / scene.render.fps_base, settings.end_mode == 'EXTEND')
        settings.status = "Recording in 3…"
        return {'FINISHED'}


class MM_OT_record_stop(bpy.types.Operator):
    bl_idname = 'metamorphosis.record_stop'
    bl_label = 'Stop Recording'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        if _live and _live['recording']:
            for sample in _live['receiver'].drain():
                _live['recording'].add(sample)
        try:
            finish_recording()
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


def video_folder(settings):
    if settings.video_folder:
        return Path(bpy.path.abspath(settings.video_folder))
    return Path(bpy.utils.user_resource('DATAFILES', path="metamorphosis_video", create=True))


def _launch_job(scene, command, folder, **extra):
    global _job
    folder.mkdir(parents=True, exist_ok=True)
    log_path = folder/'process.log'
    log = log_path.open('w', encoding='utf-8')
    try:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except Exception:
        log.close()
        raise
    _job = dict(scene=scene, process=process, log=log, log_path=log_path, **extra)
    bpy.app.timers.register(_tick_video, first_interval=.2)


def _tick_video():
    global _job
    if not _job:
        return None
    job = _job
    try:
        settings = job['scene'].mm_capture
        if job['process'].poll() is None:
            progress = job.get('progress')
            if progress and progress.exists():
                settings.video_status = progress.read_text(encoding='utf-8')
            _redraw()
            return .25
        job['log'].close()
        if job['process'].returncode:
            lines = job['log_path'].read_text(encoding='utf-8', errors='replace').splitlines()
            raise ValueError(next((s[7:] for s in reversed(lines) if s.startswith('ERROR: ')),
                                  f"Processing failed; see {job['log_path']}"))
        if job.get('output'):
            with job['output'].open(encoding='utf-8') as stream:
                next(stream)  # worker metadata
                samples = [Sample(row['time'], row['values']) for row in map(json.loads, stream)]
            board = job['board']
            scene = job['scene']
            if board.name not in scene.objects:
                raise ValueError("Target rig was removed; animation was not applied")
            action, last = bake_take(board, samples, job['fps'], job['frame_start'], job['name'],
                                    job['options'], job['smoothing'])
            scene.frame_end = max(scene.frame_end, last)
            scene.frame_set(job['frame_start'])
            settings.video_status = f"Baked {action.name} · through frame {last}"
            settings.last_take = action.name
        else:
            settings.video_status = "Video tools ready"
    except Exception as error:
        try:
            job['scene'].mm_capture.video_status = str(error)
        except ReferenceError:
            pass
    _job = None
    _redraw()
    return None


class MM_OT_video_setup(bpy.types.Operator):
    bl_idname = 'metamorphosis.video_setup'
    bl_label = 'Install Video Tools'
    bl_description = 'Download local video-tracking tools and model; videos stay on this computer'
    def execute(self, context):
        if _job or _live:
            return {'CANCELLED'}
        if not bpy.app.online_access:
            self.report({'ERROR'}, "Enable Blender's Allow Online Access to download the video tools")
            return {'CANCELLED'}
        settings = context.scene.mm_capture
        python = Path(bpy.path.abspath(settings.video_python)) if settings.video_python else (
            Path(sys.prefix)/('bin/python.exe' if os.name == 'nt' else 'bin/python3'))
        if not python.is_file():
            self.report({'ERROR'}, "Select a Python executable in Video to Mocap settings")
            return {'CANCELLED'}
        folder = video_folder(settings)
        try:
            _launch_job(context.scene, [str(python), str(Path(__file__).with_name('video_worker.py')),
                                       '--setup', str(folder)], folder)
            settings.video_status = "Installing video tools and model…"
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class MM_OT_video_process(bpy.types.Operator):
    bl_idname = 'metamorphosis.video_process'
    bl_label = 'Process Video and Bake'
    def execute(self, context):
        if _job or _live:
            self.report({'ERROR'}, "Disconnect Live Link or finish the current video job first")
            return {'CANCELLED'}
        scene = context.scene
        settings = scene.mm_capture
        folder = video_folder(settings)
        python = environment_python(folder/'python')
        model = folder/'face_landmarker.task'
        try:
            board = target_board(scene)
            video = Path(bpy.path.abspath(settings.video))
            if not video.is_file():
                raise ValueError("Choose an existing video file")
            if not python.is_file() or not model.is_file():
                raise ValueError("Install Video Tools first")
            work = Path(tempfile.mkdtemp(prefix='mm_video_'))
            output, progress = work/'capture.jsonl', work/'progress.txt'
            _launch_job(scene, [str(python), str(Path(__file__).with_name('video_worker.py')),
                               '--video', str(video), '--model', str(model), '--output', str(output),
                               '--progress', str(progress)], work, output=output, progress=progress,
                        board=board, frame_start=scene.frame_current, fps=scene.render.fps/scene.render.fps_base,
                        name=settings.take_name, options=capture_options(settings), smoothing=settings.smoothing)
            settings.video_status = "Processing video locally…"
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


def cancel_video():
    global _job
    if _job:
        job = _job
        _job = None
        if job['process'].poll() is None:
            if os.name == 'nt':
                # Include setup's pip child process; never leave a download running after Cancel.
                subprocess.run(['taskkill', '/PID', str(job['process'].pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
            else:
                job['process'].terminate()
            try:
                job['process'].wait(timeout=2)
            except subprocess.TimeoutExpired:
                job['process'].kill()
        job['log'].close()
    if bpy.app.timers.is_registered(_tick_video):
        bpy.app.timers.unregister(_tick_video)


class MM_OT_video_cancel(bpy.types.Operator):
    bl_idname = 'metamorphosis.video_cancel'
    bl_label = 'Cancel Video Processing'
    def execute(self, context):
        cancel_video()
        context.scene.mm_capture.video_status = "Cancelled; no animation applied"
        return {'FINISHED'}


@persistent
def _before_load(_):
    disconnect(bake_recording=False)
    cancel_video()


def register():
    bpy.types.Scene.mm_capture = PointerProperty(type=MM_CaptureSettings)
    bpy.app.handlers.load_pre.append(_before_load)


def unregister():
    disconnect()
    cancel_video()
    if _before_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_before_load)
    del bpy.types.Scene.mm_capture


CLASSES = (MM_CaptureSettings, MM_OT_live_start, MM_OT_live_stop, MM_OT_record_start,
           MM_OT_record_stop, MM_OT_video_setup, MM_OT_video_process, MM_OT_video_cancel)
