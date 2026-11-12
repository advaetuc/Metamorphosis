"""Convert the supplied OG fixture and automatically run Section 6 on saved files."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import bpy
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
WORK=__import__('runpy').run_path(str(Path(__file__).with_name('_paths.py')))['WORK']
source=Path(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else Path('F:/AI/Training_Data/Body Rig/Metahuman_Body_Rig_OG.blend')
spec=importlib.util.spec_from_file_location('metamorphosis',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon)
from metamorphosis import body_converter
bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
rig=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE' and all(n in o.data.bones for n in ('pelvis','upperarm_l','clavicle_l')))
original={b.name:(b.matrix_local.copy(),b.parent.name if b.parent else None) for b in rig.data.bones}
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
weights={o.name:[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices] for o in meshes}
body_converter.convert(rig,rig.users_collection[0])
for n,(matrix,parent) in original.items():
    b=rig.data.bones[n]
    assert max(abs(x-y) for ra,rb in zip(matrix,b.matrix_local) for x,y in zip(ra,rb))<1e-6,n
    assert (b.parent.name if b.parent else None)==parent
for o in meshes:assert weights[o.name]==[[(g.group,g.weight) for g in v.groups] for v in o.data.vertices]
version=''.join(map(str,bpy.app.version[:2]))
def save_verify(label):
    path=WORK/f'converter_{label}{version}.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    command=[bpy.app.binary_path,'--factory-startup','-b',str(path),'--python-exit-code','1','--python',str(ROOT/'tests/verify_body_converter.py')]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=240)
    (WORK/f'converter_{label}{version}_verify.log').write_text(result.stdout,encoding='utf-8')
    print(result.stdout,flush=True)
    assert result.returncode==0,(label,result.returncode)
    return path
save_verify('native')
assert rig['mm_body_converter']=='NATIVE_BRIDGE_2'
assert len(rig.data.bones)==565
print('BODY_CONVERTER_SAVED_SCENES_PASS',flush=True)
