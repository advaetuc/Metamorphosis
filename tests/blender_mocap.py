"""Run inside Blender; optional -- saved-rig.blend tracked-video.jsonl."""
import importlib.util
import json
from pathlib import Path
import socket
import struct
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
import bpy
from metamorphosis import bake, mocap, ui
from metamorphosis.mocap_core import ARKIT_NAMES, Receiver, Recording, Sample, decode_live_link, resample
from metamorphosis.mocap_mapping import face_board_pose

def packet(values, subject='Test Actor'):
    name = subject.encode()
    coefficients = [values.get(n, 0) for n in ARKIT_NAMES]+[0]*9
    return struct.pack('<I', 6)+b'$'+b'0'*36+struct.pack('!i', len(name))+name+struct.pack('!ifiiB61f', 1, 0, 60, 1, 61, *coefficients)

data = packet({'jawOpen': .7, 'mouthLeft': .4, 'mouthFrownRight': .9})
subject, values = decode_live_link(data)
assert subject == 'Test Actor' and abs(values['mouthLeft']-.4) < 1e-6 and values['mouthRight'] == 0
for invalid in (b'', data[:-1], data[:41]+struct.pack('!i', 999999)+data[45:], packet({'jawOpen': float('nan')})):
    try:
        decode_live_link(invalid)
        raise AssertionError('Malformed packet accepted')
    except ValueError:
        pass
receiver = Receiver('127.0.0.1', 0)
port = receiver.sock.getsockname()[1]
sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender.sendto(b'invalid', ('127.0.0.1', port))
sender.sendto(data, ('127.0.0.1', port))
deadline = time.monotonic()+2
received = []
while time.monotonic() < deadline and not received:
    received = receiver.drain()
    time.sleep(.01)
assert received and receiver.bad_packets == 1
receiver.close()
assert not receiver.thread.is_alive()
receiver2 = Receiver('127.0.0.1', port)
receiver2.close()
sender.close()
for extend in (False, True):
    rec = Recording(10, 17, 20, 30, extend)
    assert rec.frame(12) == 17
    rec.add(Sample(12.99, {}))
    assert not rec.samples
    rec.add(Sample(13, {'jawOpen': 1}))
    assert len(rec.samples) == 1
    assert rec.frame(13.1) == 20
    assert rec.finished(13.2) == (not extend)
    rec.add(Sample(13.2, {}))
    assert len(rec.samples) == (2 if extend else 1)
rows = list(resample([Sample(0, {'jawOpen': 0}), Sample(1, {'jawOpen': 1})], 24))
assert len(rows) == 25 and rows[12][1]['jawOpen'] == .5
pose = face_board_pose({'jawForward': 1, 'jawLeft': 1, 'tongueOut': 1, 'eyeWideLeft': 1, 'mouthClose': .8})
assert pose['CTRL_C_jaw_fwdBack', 1] == -1 and pose['CTRL_C_jaw', 0] == -1
assert pose['CTRL_C_tongue_inOut', 1] == -1 and pose['CTRL_L_eye_blink', 1] == -1
assert all(pose[f'CTRL_{s}_mouth_lipsTogether{p}', 1] == .8 for s in 'LR' for p in 'UD')
for name in ARKIT_NAMES:
    assert face_board_pose({name: 1}) != face_board_pose({}), ('unmapped input', name)
assert face_board_pose({'mouthSmileLeft': 1}, mirror=True)['CTRL_R_mouth_cornerPull', 1] == 1

args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
if args:
    bpy.ops.wm.open_mainfile(filepath=args[0])
    rig = bake.find_baked_rig(bpy.context)
    assert rig
else:
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    rig[bake.RIG_KEY_DATA] = 'test'
    rig[bake.RIG_KEY_BOARD_OBJECT] = rig.name
    bpy.ops.object.mode_set(mode='EDIT')
    for name, axis in face_board_pose({}):
        if name not in rig.data.edit_bones:
            bone = rig.data.edit_bones.new(name)
            bone.head, bone.tail = (0,0,0), (0,0,1)
    bpy.ops.object.mode_set(mode='OBJECT')
addon.register()
scene = bpy.context.scene
scene.mm_capture.target = rig
board = mocap.target_board(scene)
samples = [Sample(i/60, {'jawOpen': i/60, 'mouthClose': .5}) for i in range(61)]
action, end = mocap.bake_take(board, samples, 24, 17, 'TEST_CAPTURE', mocap.capture_options(scene.mm_capture))
assert end == 41 and len(action.layers[0].strips[0].channelbag(board.animation_data.action_slot).fcurves) == len(face_board_pose({}))
scene.frame_set(29)
assert abs(board.pose.bones['CTRL_C_jaw'].location.y-.5) < 1e-6
old_action = action
action, _ = mocap.bake_take(board, samples, 24, 17, 'NEW_CAPTURE', {})
assert action != old_action and old_action.use_fake_user and old_action.name in bpy.data.actions

# Invoke real operators, countdown and both end policies; inject timestamped receiver data.
scene.mm_capture.host = '127.0.0.1'
probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
probe.bind(('127.0.0.1', 0)); scene.mm_capture.port = probe.getsockname()[1]; probe.close()
assert bpy.ops.metamorphosis.live_start() == {'FINISHED'}
for mode in ('STOP', 'EXTEND'):
    scene.frame_set(17); scene.frame_end = 18; scene.mm_capture.end_mode = mode
    assert bpy.ops.metamorphosis.record_start() == {'FINISHED'}
    assert mocap._tick_live() and scene.frame_current == 17
    rec = mocap._live['recording']
    rec.start_time = time.monotonic()-.25
    with mocap._live['receiver'].lock:
        for i in range(16):
            mocap._live['receiver'].queue.append(Sample(rec.start_time+i/60, {'jawOpen': i/15}))
    mocap._tick_live()
    if mode == 'STOP':
        assert mocap._live['recording'] is None and scene.frame_current <= 18
    else:
        assert scene.frame_end > 18 and mocap._live['recording']
        assert bpy.ops.metamorphosis.record_stop() == {'FINISHED'}
assert bpy.ops.metamorphosis.live_stop() == {'FINISHED'}
assert not mocap._live and not bpy.app.timers.is_registered(mocap._tick_live)
if len(args) > 1:
    with open(args[1], encoding='utf-8') as stream:
        metadata = json.loads(next(stream))
        samples = [Sample(row['time'], row['values']) for row in map(json.loads, stream)]
    action, end = mocap.bake_take(board, samples, scene.render.fps/scene.render.fps_base, 1,
                                'VIDEO_TEST', {}, smoothing=.04)
    assert len(samples) > 100 and end > 100
    scene.frame_set(1)
    bpy.context.view_layer.update()
    old = [p.matrix.copy() for p in rig.pose.bones if p.name.startswith('FACIAL_')]
    scene.frame_set(min(end, 70)); bpy.context.view_layer.update()
    new = [p.matrix.copy() for p in rig.pose.bones if p.name.startswith('FACIAL_')]
    assert max(abs(a-b) for x,y in zip(old,new) for r,s in zip(x,y) for a,b in zip(r,s)) > 1e-4
    output = ROOT/'work'/'mocap_video_result.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    addon.unregister()
    bpy.ops.wm.open_mainfile(filepath=str(output))
    rig = bake.find_baked_rig(bpy.context)
    assert not bake.validate_rig(rig)['needs_python']
    print('VIDEO_ACTION_PASSED', len(samples), 'frames', end, flush=True)
else:
    addon.unregister()
print('MOCAP_TESTS_PASSED', bpy.app.version_string, flush=True)
