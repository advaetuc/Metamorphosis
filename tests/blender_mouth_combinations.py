"""Native RigLogic regression for combined mouth controls, including the reported pose.

Blender --background --python this_file -- DNA [DNA ...]
Compare whole poses and mouth deltas with fixed upper-face inputs. The latter
isolates the requested fix from intentionally omitted upper-face correctives.
"""
import copy
import importlib.util
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('metamorphosis', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec); sys.modules[spec.name] = addon; spec.loader.exec_module(addon)
from metamorphosis import bakeplan, dnaio, optimize, pipeline, verify
from metamorphosis.logicmodel import RigLogicModel
from metamorphosis.exprplan import fmt_num
_, riglogic, _ = dnaio.load_bindings('')

REPORTED = ('cornerDepress', 'cornerPull', 'dimple', 'lowerLipDepress',
            'sharpCornerPull', 'stretch', 'upperLipRaise')


def compile_plan(plan):
    targets = [n.target for n in plan.nodes]
    assert len(targets) == len(set(targets)), 'Driver targets would overwrite each other'
    for n in plan.nodes:
        if n.dtype == 'SCRIPTED':
            assert len(n.expr) <= 255
            n.expr = compile(n.expr, '<driver>', 'eval')
    return plan


for filename in sys.argv[sys.argv.index('--')+1:]:
    reader = dnaio.open_reader(Path(filename)); model = RigLogicModel.from_reader(reader)
    verified = verify.verify_model(model, riglogic, reader, release=dnaio.release_handle)
    assert verified.ok
    degrees, scale = dnaio.unit_flags(reader)
    orientation = bakeplan.joint_orientation_inverse(reader, model.joint_count, degrees)
    budget = np.array(pipeline.QUALITY['LITE'][0]); budget[0] *= scale/.01
    kwargs = dict(scale=scale, rotation_degrees=degrees, budget=tuple(budget), use_psd=False)
    current = bakeplan.build_plan(model, verified.variant, orientation, **kwargs)
    optimize.optimize_plan(current)
    assert current.stats['mouth_combination_correctives'] > 55
    old_model = copy.copy(model); old_model.matrix = model.matrix.copy()
    previous_columns = bakeplan.lips_together_columns(model, verified.variant) | bakeplan.jaw_open_extreme_columns(model, verified.variant)
    omitted = bakeplan.mouth_combination_columns(model, verified.variant)-previous_columns
    old_model.matrix[:, sorted(omitted)] = 0
    old = compile_plan(bakeplan.build_plan(old_model, verified.variant, orientation, **kwargs))
    compile_plan(current)
    controls = {c.name:c for c in model.gui}
    poses = []
    labels = []
    def add(label, values):
        p = np.zeros(len(model.gui))
        for name,value in values.items():
            if name in controls: p[controls[name].index] = value
        poses.append(p); labels.append(label)
    add('neutral', {})
    for strength in (.25,.6,1):
        for actions in (('cornerPull',), ('upperLipRaise',), ('cornerPull','upperLipRaise'), REPORTED):
            for sides in ('L','R','LR'):
                values = {f'CTRL_{s}_mouth_{a}.ty':strength for s in sides for a in actions}
                add(f'{actions}/{sides}/{strength}',values)
                if strength == 1 and sides == 'LR' and actions == REPORTED:
                    values.update({'CTRL_C_mouth.tx':-.01847013458609581, 'CTRL_C_mouth.ty':-.11515290290117264})
                    add('reported_scene',values)
    for opening in (0,.5,1):
        for horizontal in (-1,0,1):
            values = {f'CTRL_{s}_mouth_{a}.ty':1 for s in 'LR' for a in REPORTED}
            values.update({'CTRL_C_jaw.ty':opening, 'CTRL_C_jaw.tx':horizontal})
            add(f'jaw/{opening}/{horizontal}', values)
    full_count = len(poses)
    rng = np.random.default_rng(12101)
    ranges = model.clamp_ranges()
    mouth_gui = [c for c in model.gui if 'mouth' in c.bone.lower() or 'jaw' in c.bone.lower()]
    for i in range(12):
        fixed = {'CTRL_L_nose.ty':float(rng.random()), 'CTRL_R_nose.ty':float(rng.random()),
                 'CTRL_L_eye_cheekRaise.ty':float(rng.random()), 'CTRL_R_eye_cheekRaise.ty':float(rng.random())}
        add(f'fixed_upper_face/{i}', fixed)
        fixed.update({c.name:float(rng.uniform(*ranges[c.index])) for c in mouth_gui})
        add(f'mixed_mouth/{i}', fixed)
    gui = np.array(poses)
    oracle = verify.run_oracle(model, riglogic, reader, gui,
                              np.tile(model.default_raw(),(len(gui),1)), dnaio.release_handle)
    joints = oracle.joints.reshape(len(gui),-1,9)-oracle.joints[0].reshape(1,-1,9)
    joints[:,:,:3] = np.einsum('jik,sjk->sji',orientation,joints[:,:,:3])*scale
    if degrees: joints[:,:,3:6] *= np.pi/180
    joints[:,:,6:9] += 1
    indices = {name:i for i,name in enumerate(model.joint_names)}
    skip = verify.excluded_joints(model)
    # Lite's existing raw weights use four significant digits. Their rounding
    # error is separate from the coefficient-pruning budget, especially when
    # many maximum inputs contribute to the same rotation channel.
    rounding = np.zeros((model.joint_count,9))
    retained = bakeplan.mouth_combination_columns(model,verified.variant)|previous_columns
    columns = list(range(model.raw_count))+sorted(retained)
    for j in range(model.joint_count):
        block = model.matrix[j*9:j*9+9].astype(np.float64).copy()
        block[:3] = (orientation[j]@block[:3])*scale
        if degrees:block[3:6] *= np.pi/180
        for attr in range(9):
            rounding[j,attr] = sum(abs(block[attr,c]-float(fmt_num(block[attr,c],6 if c in retained else 4))) for c in columns)
    worst = np.zeros(3); old_translation = 0
    evaluated = []
    for i,p in enumerate(poses):
        loc = {(c.bone,c.axis):p[c.index] for c in model.gui if c.axis>=0}
        actual = bakeplan.evaluate_plan(current,loc); evaluated.append(actual)
        if i >= full_count: continue
        baseline = bakeplan.evaluate_plan(old,loc)
        for target in actual.keys() | baseline.keys():
            _,bone,path,axis = target
            j=indices[bone]
            if j in skip: continue
            kind={'location':0,'rotation_euler':1,'scale':2}[path]
            neutral=1 if kind==2 else 0
            expected=joints[i,j,kind*3+axis]
            error=abs(actual.get(target,neutral)-expected)
            worst[kind]=max(worst[kind],error)
            assert error < budget[kind]+rounding[j,kind*3+axis]+2e-5, (filename,labels[i],target,error)
            if labels[i]=='reported_scene' and kind==0:
                old_translation=max(old_translation,abs(baseline.get(target,neutral)-expected))
    assert old_translation > .01*scale/.01, 'Regression fixture no longer exposes the original defect'
    for i in range(full_count,len(poses),2):
        off,on=evaluated[i:i+2]
        for target in off.keys() | on.keys():
            _,bone,path,axis=target; j=indices[bone]
            if j in skip:continue
            kind={'location':0,'rotation_euler':1,'scale':2}[path]; neutral=1 if kind==2 else 0
            error=abs(on.get(target,neutral)-off.get(target,neutral)-(joints[i+1,j,kind*3+axis]-joints[i,j,kind*3+axis]))
            assert error < 2*budget[kind]+2*rounding[j,kind*3+axis]+3e-5, (filename,labels[i+1],target,error)
    print('MOUTH_COMBINATIONS_PASS',filename,'poses',len(poses),'old_reported_translation_error',old_translation,
          'new_max_errors',worst.tolist(),'correctives',current.stats['mouth_combination_correctives'],
          'drivers',current.stats['nodes'],flush=True)
    dnaio.release_handle(reader)
