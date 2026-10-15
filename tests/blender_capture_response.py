"""Response and DNA wrinkle equations; independent of the network and rendered frame rate."""
import importlib.util,sys
from pathlib import Path
from types import SimpleNamespace
import bpy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bindings'/'windows'/'x64'/f'py{sys.version_info.major}{sys.version_info.minor}'))
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import materials,bakeplan,dnaio,verify,mocap
from metamorphosis.mocap_mapping import face_board_pose
from metamorphosis.mocap_core import Sample
from metamorphosis.logicmodel import RigLogicModel
import riglogic
neutral=face_board_pose({});assert all(v==0 for v in neutral.values())
close=face_board_pose({'jawOpen':.6,'mouthClose':.6,'mouthUpperUpLeft':.5})
assert close['CTRL_C_jaw',1]==.6
for side in 'LR':
 for part in 'UD':assert close[f'CTRL_{side}_mouth_lipsTogether{part}',1]==1
assert close['CTRL_L_mouth_upperLipRaise',1]<.1
for key,target in [('mouthPucker','towardsU'),('mouthRollUpper','lipsRollU'),('mouthPressLeft','tightenU'),('mouthPressLeft','lipsPressU')]:
 assert face_board_pose({key:.7})['CTRL_L_mouth_'+target,1]>.3,(key,target)
assert face_board_pose({'mouthPressLeft':.8},mirror=True)['CTRL_R_mouth_pressU',1]==1
assert face_board_pose({'browInnerUp':.75})['CTRL_L_brow_raiseIn',1]==1
assert face_board_pose({'browOuterUpRight':.75})['CTRL_R_brow_raiseOut',1]==1
assert face_board_pose({'mouthSmileLeft':.4})['CTRL_L_mouth_cornerPull',1]==.4
rows=list(mocap.smooth_samples([Sample(0,{'mouthClose':0,'browInnerUp':0}),Sample(1/60,{'mouthClose':1,'browInnerUp':1})],.04))
assert rows[-1].values['mouthClose']>rows[-1].values['browInnerUp']
for filename in sys.argv[sys.argv.index('--')+1:]:
 r=dnaio.open_reader(Path(filename));m=RigLogicModel.from_reader(r)
 result=verify.verify_model(m,riglogic,r,release=dnaio.release_handle);assert result.ok
 board=SimpleNamespace(pose=SimpleNamespace(bones={c.bone:None for c in m.gui}))
 plan,outputs=materials.wrinkle_plan(r,m,result.variant,board)
 for name,prop in outputs.items():plan.nodes.append(bakeplan.Node(('map',name),'SUM','',[bakeplan.Var('w','prop',prop)]))
 manager=riglogic.RigLogic(r,riglogic.Configuration(),None);instance=riglogic.RigInstance(rigLogic=manager,memRes=None)
 poses,_=m.make_samples();worst=0
 for pose in poses[:m.FACE_ONLY_SAMPLES]:
  for c in m.gui:instance.setGUIControl(c.index,float(pose[c.index]))
  manager.mapGUIToRawControls(instance);manager.calculate(instance)
  oracle=list(instance.getAnimatedMapOutputs())
  actual=bakeplan.evaluate_plan(plan,{(c.bone,c.axis):float(pose[c.index]) for c in m.gui if c.axis>=0})
  for i,value in enumerate(oracle):
   error=abs(actual['map',r.getAnimatedMapName(i)]-value);worst=max(worst,error)
 assert worst<2e-5,(filename,worst)
 print('WRINKLE_EQUATIONS_PASS',filename,worst,flush=True)
 dnaio.release_handle(instance);dnaio.release_handle(manager);dnaio.release_handle(r)
print('CAPTURE_RESPONSE_PASS',flush=True)
