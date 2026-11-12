"""ARKit coefficients -> existing MetaHuman face-board channels, without shape keys."""
from .mocap_core import ARKIT_NAMES


def face_board_pose(values, gain=1.0, mirror=False, extreme=0.0, lips_gain=1.35, brow_gain=1.4):
    v = {n: max(0.0, min(1.0, float(values.get(n, 0.0)) * gain)) for n in ARKIT_NAMES}
    if mirror:
        for name in ARKIT_NAMES:
            if name.endswith("Left"):
                other = name[:-4] + "Right"
                v[name], v[other] = v[other], v[name]
    for name in v:
        if name.startswith(('mouthClose','mouthFunnel','mouthPucker','mouthRoll','mouthPress')):
            v[name] = min(1.0, v[name]*lips_gain)
        elif name.startswith('brow'):
            v[name] = min(1.0, v[name]*brow_gain)
    pose = {}
    closure = min(1.0, v['mouthClose']/max(.15,v['jawOpen']))
    # A bilateral press or inward roll can seal the lips even when the tracker
    # reports a weak mouthClose. A single rolled lip must not force both shut.
    closure = max(closure, min(v['mouthRollUpper'], v['mouthRollLower']),
                  min(v['mouthPressLeft'], v['mouthPressRight']))
    def put(bone, value, axis=1):
        pose[(bone, axis)] = max(-1.0, min(1.0, value))
    put("CTRL_C_jaw", v["jawOpen"])
    put("CTRL_C_jaw", v["jawRight"] - v["jawLeft"], 0)
    put("CTRL_C_jaw_fwdBack", -v["jawForward"])
    put("CTRL_C_jaw_openExtreme", max(0.0, (v["jawOpen"]-.8)/.2) * extreme)
    put("CTRL_C_mouth", v["mouthLeft"]-v["mouthRight"], 0)
    put("CTRL_C_tongue_inOut", -v["tongueOut"])
    # Individual eye inputs own capture gaze; clear the shared offset to prevent doubling.
    put("CTRL_C_eye", 0.0, 0)
    put("CTRL_C_eye", 0.0)
    for side, word in (("L", "Left"), ("R", "Right")):
        prefix = f"CTRL_{side}_"
        put(prefix+"eye_blink", v["eyeBlink"+word]-v["eyeWide"+word])
        put(prefix+"eye_squintInner", v["eyeSquint"+word])
        put(prefix+"eye_cheekRaise", v["cheekSquint"+word])
        put(prefix+"eye", v["eyeLookUp"+word]-v["eyeLookDown"+word])
        horizontal = v["eyeLookOut"+word]-v["eyeLookIn"+word]
        put(prefix+"eye", horizontal if side == "L" else -horizontal, 0)
        for target, source in (("brow_down", "browDown"), ("brow_raiseOut", "browOuterUp"),
                               ("mouth_cornerPull", "mouthSmile"), ("mouth_cornerDepress", "mouthFrown"),
                               ("mouth_dimple", "mouthDimple"), ("mouth_stretch", "mouthStretch"),
                               ("mouth_lowerLipDepress", "mouthLowerDown"),
                               ("mouth_upperLipRaise", "mouthUpperUp"), ("nose", "noseSneer")):
            value = v[source+word]
            if source in {'mouthLowerDown','mouthUpperUp'}:
                roll = v['mouthRollLower' if source == 'mouthLowerDown' else 'mouthRollUpper']
                value *= 1-max(closure, roll)
            put(prefix+target, value)
        put(prefix+"brow_raiseIn", v["browInnerUp"])
        put(prefix+"brow_lateral", .5*v['browDown'+word])
        put(prefix+"mouth_suckBlow", v["cheekPuff"])
        for part, vertical in (("U", "Upper"), ("D", "Lower")):
            press = v['mouthPress'+word]
            roll = v['mouthRoll'+vertical]
            put(prefix+"mouth_funnel"+part, v["mouthFunnel"]*(1-max(closure, roll)))
            put(prefix+"mouth_purse"+part, v["mouthPucker"]*(1-roll))
            # ARKit closure is an absolute action; DNA Lips Together is relative
            # to the current jaw opening. Normalize it before applying the PSD.
            put(prefix+"mouth_lipsTogether"+part, max(closure,press,roll))
            put(prefix+"mouth_lipsRoll"+part, roll)
            # ARKit roll is not a bite. Clear the old approximation in live
            # preview as well as newly recorded takes, without editing old takes.
            put(prefix+"mouth_lipBite"+part, 0.0)
            put(prefix+"mouth_towards"+part, v['mouthPucker']*.75*(1-roll))
            put(prefix+"mouth_tighten"+part, press*.6)
            put(prefix+"mouth_press"+part, press)
            put(prefix+"jaw_ChinRaise"+part, v["mouthShrug"+vertical])
        put(prefix+'mouth_lipsPressU',v['mouthPress'+word]*.5)
    return pose
