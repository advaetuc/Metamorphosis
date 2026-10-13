"""ARKit coefficients -> existing MetaHuman face-board channels, without shape keys."""
from .mocap_core import ARKIT_NAMES


def face_board_pose(values, gain=1.0, mirror=False, extreme=0.0):
    v = {n: max(0.0, min(1.0, float(values.get(n, 0.0)) * gain)) for n in ARKIT_NAMES}
    if mirror:
        for name in ARKIT_NAMES:
            if name.endswith("Left"):
                other = name[:-4] + "Right"
                v[name], v[other] = v[other], v[name]
    pose = {}
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
            put(prefix+target, v[source+word])
        put(prefix+"brow_raiseIn", v["browInnerUp"])
        put(prefix+"mouth_suckBlow", v["cheekPuff"])
        for part, vertical in (("U", "Upper"), ("D", "Lower")):
            put(prefix+"mouth_funnel"+part, v["mouthFunnel"])
            put(prefix+"mouth_purse"+part, v["mouthPucker"])
            put(prefix+"mouth_lipsTogether"+part, v["mouthClose"])
            put(prefix+"mouth_lipsRoll"+part, v["mouthRoll"+vertical])
            put(prefix+"mouth_press"+part, v["mouthPress"+word])
            put(prefix+"jaw_ChinRaise"+part, v["mouthShrug"+vertical])
    return pose
