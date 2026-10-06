"""Lips Together / Jaw Open Extreme: Blender --background --python this_file -- DNA [DNA ...]."""
import copy
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("metamorphosis", ROOT / "__init__.py",
                                            submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
native = ROOT / "bindings" / "windows" / "x64" / f"py{sys.version_info.major}{sys.version_info.minor}"
sys.path.insert(0, str(native))
import dna, riglogic
import numpy as np
from metamorphosis import bakeplan, dnaio, optimize, pipeline, verify
from metamorphosis.logicmodel import RigLogicModel


def compile_plan(plan):
    # Compile once for many test poses; production still stores expression strings.
    for node in plan.nodes:
        if node.dtype == "SCRIPTED":
            assert len(node.expr) <= 255
            node.expr = compile(node.expr, "<driver>", "eval")
    return plan


for filename in sys.argv[sys.argv.index("--") + 1:]:
    reader = dnaio.open_reader(Path(filename))
    model = RigLogicModel.from_reader(reader)
    result = verify.verify_model(model, riglogic, reader, release=dnaio.release_handle)
    assert result.ok, result.message
    rotation_degrees, scale = dnaio.unit_flags(reader)
    orientation = bakeplan.joint_orientation_inverse(reader, model.joint_count, rotation_degrees)
    budget = pipeline.QUALITY["LITE"][0]
    kwargs = dict(scale=scale, rotation_degrees=rotation_degrees,
                  budget=(budget[0] * scale / .01, *budget[1:]), use_psd=False)
    plan = bakeplan.build_plan(model, result.variant, orientation, **kwargs)
    optimize.optimize_plan(plan)
    assert plan.stats["lips_together_correctives"] == 24, plan.stats
    assert plan.stats["jaw_open_extreme_correctives"] == 31, plan.stats
    extreme = next(c for c in model.gui if c.name == "CTRL_C_jaw_openExtreme.ty")
    lips = [c for c in model.gui if "lipsTogether" in c.bone]
    assert len(lips) == 4
    assert all(any(v.kind == "loc" and v.ref == c.bone for n in plan.nodes for v in n.vars) for c in lips)

    # Reconstruct the old raw-only Lite plan to guard all unrelated expressions.
    old_model = copy.copy(model)
    old_model.matrix = model.matrix.copy()
    old_model.matrix[:, model.raw_count:] = 0
    old_plan = bakeplan.build_plan(old_model, result.variant, orientation, **kwargs)
    compile_plan(old_plan)
    compile_plan(plan)

    samples, _ = model.make_samples()
    samples = samples[:model.FACE_ONLY_SAMPLES]
    samples[:, [c.index for c in lips]] = 0
    samples[:, extreme.index] = 0
    jaw = next(c for c in model.gui if c.name == "CTRL_C_jaw.ty")
    # Individual quarters and all four together, at partial/full jaw opening.
    poses = []
    for opening in (.25, .6, 1.0):
        for selected in [[c] for c in lips] + [lips]:
            pose = np.zeros(len(model.gui))
            pose[jaw.index] = opening
            poses.append(pose.copy())
            for c in selected:
                pose[c.index] = 1.0
            poses.append(pose)
    # Mixed facial poses exercise jaw sideways, mouth press and asymmetric lips.
    for pose in samples[1:9]:
        poses.append(pose.copy())
        pose = pose.copy()
        for i, c in enumerate(lips):
            pose[c.index] = (i + 1) / 4
        poses.append(pose)
    jaw_start = len(poses)
    for opening in (0.0, .25, .6, 1.0):
        for strength in (.25, .6, 1.0):
            pose = np.zeros(len(model.gui))
            pose[jaw.index] = opening
            poses.append(pose.copy())
            pose[extreme.index] = strength
            poses.append(pose)
    # Jaw/mouth combinations, including Lips Together, must match native RigLogic.
    mixed, _ = model.make_samples()
    for pose in mixed[1:model.FACE_ONLY_SAMPLES]:
        pose = pose.copy()
        pose[extreme.index] = 0
        poses.append(pose.copy())
        pose[extreme.index] = .8
        poses.append(pose)
    gui = np.array(poses)
    raw = np.tile(model.default_raw(), (len(gui), 1))
    oracle = verify.run_oracle(model, riglogic, reader, gui, raw, dnaio.release_handle)
    joint_index = {name: j for j, name in enumerate(model.joint_names)}

    def evaluate(pose, selected_plan=plan):
        loc = {(c.bone, c.axis): pose[c.index] for c in model.gui if c.axis >= 0}
        return bakeplan.evaluate_plan(selected_plan, loc)

    worst = 0.0
    for i in range(0, len(gui), 2):
        off, on = evaluate(gui[i]), evaluate(gui[i + 1])
        expected = (oracle.joints[i + 1] - oracle.joints[i]).reshape(-1, 9)
        expected[:, :3] = np.einsum("jik,jk->ji", orientation, expected[:, :3]) * scale
        if rotation_degrees:
            expected[:, 3:6] *= np.pi / 180
        for target in on:
            _, bone, path, axis = target
            attr = {"location": 0, "rotation_euler": 3, "scale": 6}[path] + axis
            error = abs(on[target] - off[target] - expected[joint_index[bone], attr])
            worst = max(worst, error)
            assert error < 2e-5, (filename, i, target, error)
        if i < 30:
            assert max(abs(on[t] - off[t]) for t in on) > 1e-4, (filename, i, "dead control")
        if jaw_start <= i < jaw_start + 24:
            motion = max(abs(on[t] - off[t]) for t in on)
            if gui[i, jaw.index] > 0:
                assert motion > 1e-4, (filename, i, "dead extreme jaw")
            else:
                assert motion < 1e-10, (filename, i, "extreme must extend the regular jaw")
    for pose in samples:
        old, new = evaluate(pose, old_plan), evaluate(pose)
        for target in old.keys() | new.keys():
            neutral = 1.0 if target[2] == "scale" else 0.0
            assert abs(old.get(target, neutral) - new.get(target, neutral)) < 1e-10, target
    # Compare against 1.0.7 with its Lips Together fix when Extreme is at zero.
    previous = copy.copy(model)
    previous.matrix = model.matrix.copy()
    previous.matrix[:, sorted(bakeplan.jaw_open_extreme_columns(model, result.variant))] = 0
    previous_plan = compile_plan(bakeplan.build_plan(previous, result.variant, orientation, **kwargs))
    for pose in mixed[:model.FACE_ONLY_SAMPLES]:
        pose = pose.copy()
        pose[extreme.index] = 0
        old, new = evaluate(pose, previous_plan), evaluate(pose)
        for target in old.keys() | new.keys():
            neutral = 1.0 if target[2] == "scale" else 0.0
            assert abs(old.get(target, neutral) - new.get(target, neutral)) < 1e-10, target
    dnaio.release_handle(reader)
    print("MOUTH_CONTROLS_PASSED", filename, "poses", len(gui), "max_error", worst,
          "drivers", plan.stats["nodes"], flush=True)
