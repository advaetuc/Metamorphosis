"""Independent body solver reference versus the native RigLogic binary."""
import importlib.util, sys
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('metamorphosis',root/'__init__.py',submodule_search_locations=[str(root)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import dnaio
from metamorphosis.body_rbf import BodyRBF
dna,native,_=dnaio.load_bindings('')
reader=dnaio.open_reader(r'F:\Project_Files\Metahumans\MH_John_Rambo\body.dna')
model=BodyRBF(reader,dna)
manager=native.RigLogic(reader,native.Configuration(),None)
instance=native.RigInstance(rigLogic=manager,memRes=None)
neutral=np.zeros(model.raw_count)
neutral[3::4]=1
samples=[neutral]
for solver in model.solvers:
    for target in solver.source_targets:
        raw=neutral.copy();raw[solver.inputs]=target;samples.append(raw)
rng=np.random.default_rng(190)
for _ in range(100):
    quats=rng.normal(size=(model.raw_count//4,4))
    quats/=np.linalg.norm(quats,axis=1)[:,None]
    samples.append(quats.ravel())
worst=0
for number,raw in enumerate(samples):
    for i,v in enumerate(raw):instance.setRawControl(i,float(v))
    manager.calculateRBFControls(instance)
    expected=np.array(list(instance.getRBFControlValues()))
    actual=model.evaluate(raw)
    error=float(np.max(np.abs(actual-expected)))
    worst=max(worst,error)
    if error>0.0002:
        where=int(np.argmax(np.abs(actual-expected)))
        raise AssertionError((number,error,where,actual[where],expected[where]))
print('BODY_RBF_ORACLE_PASS',len(samples),'poses',len(model.solvers),'solvers',worst,flush=True)
from metamorphosis.body_driverplan import Graph
import bpy,time,statistics
graph=Graph()
raw_nodes=[graph.emit(f'raw{i}') for i in range(len(neutral))]
outputs=graph.compile_rbf(model,raw_nodes)
twist_outputs=graph.compile_twist_swing(reader,raw_nodes)
source=bpy.data.objects.new('BODY_TEST_INPUT',None)
bpy.context.scene.collection.objects.link(source)
source['mm_body_raw']=neutral.tolist()
holders,locations=graph.realize(bpy.context.scene.collection,'BODY_TEST',source,len(raw_nodes))
for holder in holders:
    for curve in holder.animation_data.drivers:
        assert curve.driver.is_simple_expression, curve.driver.expression
times=[];worst=0;twist_worst=0
for number,raw in enumerate(samples[::7]):
    source['mm_body_raw']=raw.tolist()
    source.update_tag()
    started=time.perf_counter();bpy.context.view_layer.update();times.append((time.perf_counter()-started)*1000)
    actual=np.array([locations[outputs[i]][0]['mm_body_values'][locations[outputs[i]][1]]/10000
                     if i in outputs else 0 for i in range(model.offset,model.offset+model.count)])
    expected=model.evaluate(raw)
    error=float(np.max(np.abs(actual-expected)))
    worst=max(worst,error)
    assert error<.003,(number,error)
    for i,v in enumerate(raw):instance.setRawControl(i,float(v))
    manager.calculate(instance)
    joints=list(instance.getJointOutputs())
    from mathutils import Euler
    for joint,nodes in twist_outputs.items():
        q=Euler(tuple(np.radians(joints[joint*9+3:joint*9+6])),'XYZ').to_quaternion()
        expected=np.array([q.x,q.y,q.z,q.w])
        actual=np.array([locations[i][0]['mm_body_values'][locations[i][1]]/10000 for i in nodes])
        error=min(float(np.max(np.abs(actual-expected))),float(np.max(np.abs(actual+expected))))
        twist_worst=max(twist_worst,error)
        assert error<.0002,(number,joint,error,actual,expected)
print('BODY_RBF_DRIVERS_PASS',len(graph.nodes),'drivers',worst,'max weight difference',statistics.median(times),'ms',flush=True)
print('BODY_TWIST_SWING_PASS',len(twist_outputs),'joints',twist_worst,flush=True)
for handle in (instance,manager,reader):dnaio.release_handle(handle)
