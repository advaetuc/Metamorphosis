"""Native body rig cleanup, anatomical FK pivots and mirrored digit controls.

Runs only while building a rig. All resulting evaluation uses Blender data.
"""
import json
import bpy
from mathutils import Vector
from ..sculpting import sculpt
from . import body_geometry


BLUE=(76/255,108/255,1.0)
RED=(1.0,23/255,12/255)
YELLOW=(244/255,201/255,12/255)


def _set_color(pb, rgb):
    pb.color.palette='CUSTOM'
    pb.color.custom.normal=rgb
    pb.color.custom.select=tuple(v+(1.0-v)*.4 for v in rgb)
    pb.color.custom.active=tuple(v+(1.0-v)*.7 for v in rgb)


def prepare(rig, source, mapping):
    mapping=dict(mapping)
    mapping.update({'pelvis':'PELVIS_TWEAK', **{f'spine_{i:02}':f'SPINE_{i:02}_TWEAK' for i in range(1,6)},
                    'neck_01':'NECK_01_TWEAK','neck_02':'NECK_02_TWEAK'})
    for side in 'lr':
        for letter,digit in zip('ABCDE',('bigtoe','indextoe','middletoe','ringtoe','littletoe')):
            for i in (1,2):mapping[f'{digit}_{i:02}_{side}']=f'TOE_{letter}_{i:02}.{side.upper()}'
    new_tweaks=[];new_controls=[]
    with sculpt.object_context(rig):
        sculpt.set_mode(rig,'EDIT')
        try:
            bones=rig.data.edit_bones
            def make(name,head,tail,parent=None,z=(0,-1,0)):
                b=bones.get(name) or bones.new(name)
                b.use_connect=False;b.head=head;b.tail=tail;b.use_deform=False
                b.parent=bones.get(parent) if parent else None
                b.bbone_segments=1;b.bbone_custom_handle_start=None;b.bbone_custom_handle_end=None
                body_geometry.align_z(b,z)
                return b
            def position(name):return source[name].translation.copy()
            pelvis=position('pelvis');height=position('head').z-position('root').z
            spine01=position('spine_01')
            make('TORSO',pelvis,pelvis+Vector((0,.175,0)),'ROOT',z=(0,0,1))
            hips_tail=pelvis+(spine01-pelvis)*.7 if (spine01-pelvis).length>height*.02 else pelvis+Vector((0,height*.06,0))
            make('HIPS',pelvis,hips_tail,'TORSO')
            make('PELVIS_TWEAK',pelvis,pelvis+Vector((0,0,height*.04)),'HIPS')
            new_controls+=['TORSO','HIPS'];new_tweaks+=['PELVIS_TWEAK']
            parent='TORSO'
            for i in range(1,6):
                n=f'SPINE_{i:02}';h=position(n.lower())
                t_orig=position(f'spine_{i+1:02}' if i<5 else 'neck_01')
                t_fk=position('neck_01') if i>=4 else t_orig
                if i<=2:
                    make(n+'_FK',h,t_fk,'TORSO' if i==1 else 'SPINE_01_FK')
                    make('MCH_'+n,h,t_orig,parent)
                    make('MCH_'+n+'_BEND',h,t_orig,'MCH_'+n)
                    make(n+'_TWEAK',h,h+(t_orig-h).normalized()*height*.04,'MCH_'+n+'_BEND')
                else:
                    make('MCH_'+n+'_BEND',h,t_orig,parent)
                    make(n+'_FK',h,t_fk,'MCH_'+n+'_BEND')
                    make(n+'_TWEAK',h,h+(t_orig-h).normalized()*height*.04,n+'_FK')
                parent=n+'_TWEAK';new_controls.append(n+'_FK');new_tweaks.append(parent)
            # Parent CHEST after SPINE_01..02_FK leave template CHEST's subtree.
            make('CHEST',position('spine_03'),position('spine_04'),'SPINE_02_FK')
            new_controls.append('CHEST')
            bones['MCH_NECK'].parent=bones['SPINE_05_TWEAK']
            neck0=position('neck_01');head_base=bones['HEAD'].head.copy()
            neck_mid=neck0.lerp(head_base,.5)
            for i in (1,2):
                n=f'NECK_{i:02}';h=position(n.lower());t=position('neck_02' if i==1 else 'head')
                fk_h,fk_t=(neck0,neck_mid) if i==1 else (neck_mid,head_base)
                make(n+'_FK',fk_h,fk_t,'MCH_INT_NECK' if i==1 else 'NECK_01_TWEAK')
                make(n+'_TWEAK',h,h+(t-h).normalized()*height*.04,n+'_FK')
                new_controls.append(n+'_FK');new_tweaks.append(n+'_TWEAK')
            bones['MCH_HEAD'].parent=bones['NECK_02_TWEAK']
            for side in 'LR':
                bones['SHOULDER.'+side].parent=bones['SPINE_05_TWEAK']
                bones['MCH_THIGH_SOCKET.'+side].parent=bones['PELVIS_TWEAK']
                if 'VIS_ARM_IK_POLE.'+side in bones and 'MCH_SWITCH_ARM.'+side in bones:
                    bones['VIS_ARM_IK_POLE.'+side].parent=bones['MCH_SWITCH_ARM.'+side]
                if 'VIS_LEG_IK_POLE.'+side in bones and 'MCH_SWITCH_THIGH.'+side in bones:
                    bones['VIS_LEG_IK_POLE.'+side].parent=bones['MCH_SWITCH_THIGH.'+side]
            # Build left toe controls from the actual source joints. They carry
            # no constraints; the original weighted bones get the native bridge.
            for letter,digit in zip('ABCDE',('bigtoe','indextoe','middletoe','ringtoe','littletoe')):
                h=position(digit+'_01_l');p=position(digit+'_02_l')
                for i,a,t in ((1,h,p),(2,p,p+(p-h)*.85)):
                    n=f'TOE_{letter}_{i:02}.L'
                    # Local +Z curls the left toe downward; the mirrored right
                    # basis uses -Z for the same anatomical curl.
                    hinge=(t-a).cross(Vector((0,0,-1))).normalized()
                    make(n,a,t,'ORG_TOE.L' if i==1 else f'TOE_{letter}_01.L',z=hinge)
            # Exactly Blender's X-symmetrize basis: X changes handedness while
            # Y and Z reflect geometrically. Preserve the source deform bones.
            mirror=[b.name for b in bones if b.name.endswith('.L') and b.name.startswith(
                ('THUMB_','FINGER_','HAND_SIDE_OPEN','MCH_FINGER_','TOE_A_','TOE_B_','TOE_C_','TOE_D_','TOE_E_'))]
            for name in mirror:
                left=bones[name];right=bones.get(name[:-2]+'.R') or bones.new(name[:-2]+'.R')
                right.use_connect=False;right.use_deform=False
                right.head=(-left.head.x,left.head.y,left.head.z)
                right.tail=(-left.tail.x,left.tail.y,left.tail.z);right.roll=-left.roll
                parent=left.parent.name if left.parent else None
                right.parent=bones.get(parent[:-2]+'.R' if parent and parent.endswith('.L') else parent) if parent else None
        finally:
            sculpt.set_mode(rig,'OBJECT')
    for name in new_controls+new_tweaks:
        pb=rig.pose.bones[name]
        for c in list(pb.constraints):pb.constraints.remove(c)
        pb.rotation_mode='XYZ';pb.custom_shape=None;pb.custom_shape_transform=None
        rgb=RED if name=='TORSO' else YELLOW if (name in new_tweaks or name in ('HIPS','CHEST')) else BLUE
        _set_color(pb,rgb)
        if name in new_tweaks:
            pb.lock_location=(False,False,False);pb.lock_rotation=(True,True,True);pb.lock_scale=(True,True,True)
        elif name=='CHEST':
            pb.lock_location=(True,True,True);pb.lock_rotation=(False,False,False);pb.lock_scale=(True,True,True)
        else:pb.lock_location=pb.lock_rotation=pb.lock_scale=(False,False,False)
        if name=='SPINE_05_FK' or name in new_tweaks:
            group='MCH'
        elif name.startswith('SPINE_'):
            group='SPINE_FK'
        else:
            group='TORSO'
        for old in list(pb.bone.collections):old.unassign(pb.bone)
        (rig.data.collections.get(group) or rig.data.collections.new(group)).assign(pb.bone)
    for i in (1,2):
        pb=rig.pose.bones[f'MCH_SPINE_{i:02}']
        for c in list(pb.constraints):pb.constraints.remove(c)
        pb.rotation_mode='XYZ';pb.custom_shape=None;pb.custom_shape_transform=None
        c=pb.constraints.new('COPY_TRANSFORMS');c.target=rig;c.subtarget=f'SPINE_{i:02}_FK'
        c.owner_space=c.target_space='LOCAL'
        for old in list(pb.bone.collections):old.unassign(pb.bone)
        (rig.data.collections.get('MCH') or rig.data.collections.new('MCH')).assign(pb.bone)
    for i in range(1,6):
        pb=rig.pose.bones[f'MCH_SPINE_{i:02}_BEND'];pb.rotation_mode='XYZ'
        for old in list(pb.bone.collections):old.unassign(pb.bone)
        (rig.data.collections.get('MCH') or rig.data.collections.new('MCH')).assign(pb.bone)
        for ax,ch in enumerate('XYZ'):
            d=pb.driver_add('rotation_euler',ax).driver;d.type='SCRIPTED'
            v=d.variables.new();v.name='b';v.type='TRANSFORMS'
            t=v.targets[0];t.id=rig;t.bone_target='CHEST'
            t.transform_type='ROT_'+ch;t.transform_space='LOCAL_SPACE';t.rotation_mode='XYZ'
            d.expression='b/5'
    for side in 'LR':
        rgb=BLUE if side=='L' else RED
        for letter in 'ABCDE':
            for i in (1,2):
                pb=rig.pose.bones[f'TOE_{letter}_{i:02}.{side}'];pb.rotation_mode='XYZ'
                _set_color(pb,rgb)
                for old in list(pb.bone.collections):old.unassign(pb.bone)
                (rig.data.collections.get('TOE.'+side) or rig.data.collections.new('TOE.'+side)).assign(pb.bone)
        for letter in 'ABCD':
            for i in range(1,5):
                pb=rig.pose.bones[f'FINGER_{letter}_{i:02}.{side}']
                _set_color(pb,rgb)
        for i in (2,3):
            pb=rig.pose.bones[f'THUMB_{i:02}.{side}']
            _set_color(pb,rgb)
    retarget={'ORG_HIPS':'PELVIS_TWEAK','ORG_CHEST':'SPINE_05_TWEAK'}
    for pb in rig.pose.bones:
        for c in pb.constraints:
            if c.type=='ARMATURE':
                for target in c.targets:target.subtarget=retarget.get(target.subtarget,target.subtarget)
            if c.type=='STRETCH_TO':c.volume='NO_VOLUME'
    # Retain the dependency closure of actual outputs and animator controls.
    # A child of a live bone is not automatically live; dependencies run toward
    # parents/constraint targets, not toward every descendant of the skeleton.
    keep=set(mapping.values())|set(new_controls)|set(new_tweaks)|{'ROOT','PROPERTIES','HEAD'}
    for side in 'LR':
        keep|={n+'.'+side for n in ('ARM_FK','FOREARM_FK','HAND_FK','HAND_IK','ARM_IK_POLE','VIS_ARM_IK_POLE',
                                  'THIGH_FK','SHIN_FK','FOOT_FK','FOOT_IK','LEG_IK_POLE','VIS_LEG_IK_POLE','HEEL','TOE')}
    changed=True
    while changed:
        changed=False
        for name in list(keep):
            pb=rig.pose.bones[name];refs=set()
            if pb.parent:refs.add(pb.parent.name)
            for c in pb.constraints:
                if getattr(c,'target',None)==rig and getattr(c,'subtarget',''):refs.add(c.subtarget)
                if getattr(c,'pole_target',None)==rig and c.pole_subtarget:refs.add(c.pole_subtarget)
                if c.type=='ARMATURE':refs|={t.subtarget for t in c.targets if t.target==rig and t.subtarget}
            for b in (pb.bone.bbone_custom_handle_start,pb.bone.bbone_custom_handle_end):
                if b:refs.add(b.name)
            if refs-keep:keep|=refs;changed=True
    remove=set(rig.data.bones.keys())-keep
    if rig.animation_data:
        prefixes=tuple('pose.bones['+json.dumps(n)+']' for n in remove)
        for f in list(rig.animation_data.drivers):
            if f.data_path.startswith(prefixes):rig.animation_data.drivers.remove(f)
    with sculpt.object_context(rig):
        sculpt.set_mode(rig,'EDIT')
        try:
            for n in remove:rig.data.edit_bones.remove(rig.data.edit_bones[n])
        finally:sculpt.set_mode(rig,'OBJECT')
    for key in list(rig.pose.bones['PROPERTIES'].keys()):
        if key.startswith('ARM_BICEP_FLEXTION'):del rig.pose.bones['PROPERTIES'][key]
    for pb in rig.pose.bones:
        # Pole targets constrain the bend plane. Keep all rotational degrees
        # available for arbitrary DNA FK poses; snapping must not toggle locks.
        if pb.name.startswith(('MCH_IK_FOREARM.','MCH_IK_SHIN.')):
            pb.lock_ik_x=False;pb.lock_ik_y=False
        # The live hand tip is intentionally kept with the other final tweaks.
        if pb.name in new_tweaks or any(c.name in ('SPINE_TWEAK','TORSO_TWK') for c in pb.bone.collections):
            pb.custom_shape=None;pb.custom_shape_transform=None
            for old in list(pb.bone.collections):old.unassign(pb.bone)
            (rig.data.collections.get('MCH') or rig.data.collections.new('MCH')).assign(pb.bone)
        elif 'TWEAK' not in pb.name or pb.name.startswith('MCH_'):
            pb.custom_shape=None;pb.custom_shape_transform=None
        elif pb.custom_shape_transform and pb.custom_shape_transform.name not in keep:
            pb.custom_shape_transform=None
        if pb.color.palette=='CUSTOM':
            _set_color(pb,tuple(pb.color.custom.normal))
    for c in list(rig.data.collections_all):
        if not len(c.bones):rig.data.collections.remove(c)
    return mapping


def clean_widgets(rig, candidates, collection):
    """Delete only supplied widget candidates unused by any other rig."""
    used={p.custom_shape for o in bpy.data.objects if o.type=='ARMATURE' for p in o.pose.bones if p.custom_shape}
    for obj in candidates-used:
        if obj.name not in bpy.data.objects:continue
        # A shared scene object or instanced widget is not ours to discard.
        if obj.users>len(obj.users_collection)+int(obj.use_fake_user):continue
        data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
        if data and data.users==0 and not data.use_fake_user:bpy.data.meshes.remove(data)
    collection.hide_viewport=True;collection.hide_render=True


def apply_shape_preset(rig, widgets_collection, preset='UNREAL'):
    """Import only the requested preset widgets ('UNREAL' or 'BLENDER') and assign them."""
    from pathlib import Path
    preset = str(preset or 'UNREAL').upper()
    if preset not in ('UNREAL', 'BLENDER'):
        raise ValueError(f'Unknown custom shape preset: {preset}')
    assets = Path(__file__).resolve().parents[1] / 'assets'
    spec = json.loads((assets / 'body_shapes.json').read_text(encoding='utf-8'))[preset]
    blend = assets / ('body_shapes_unreal.blend' if preset == 'UNREAL' else 'body_shapes_blender.blend')
    needed = sorted({entry['widget'] for entry in spec.values()})
    loaded = {}
    with bpy.data.libraries.load(str(blend), link=False) as (src, dst):
        missing = set(needed) - set(src.objects)
        if missing:
            raise ValueError(f'Missing widget objects in {blend.name}: {sorted(missing)[:5]}')
        dst.objects = list(needed)
    for name, obj in zip(needed, dst.objects):
        obj.use_fake_user = False
        if obj.data:
            obj.data.use_fake_user = False
        if obj.name not in widgets_collection.objects:
            widgets_collection.objects.link(obj)
        obj.hide_render = True
        obj.hide_set(True)
        obj.hide_select = True
        loaded[name] = obj
    for pb in rig.pose.bones:
        entry = spec.get(pb.name)
        if entry is None:
            pb.custom_shape = None
            pb.custom_shape_transform = None
            continue
        pb.custom_shape = loaded[entry['widget']]
        pb.custom_shape_scale_xyz = entry['scale']
        pb.custom_shape_translation = entry['translation']
        pb.custom_shape_rotation_euler = entry['rotation']
        pb.use_custom_shape_bone_size = bool(entry['bone_size'])
        pb.custom_shape_transform = rig.pose.bones.get(entry['transform']) if entry['transform'] else None
        if hasattr(pb, 'custom_shape_wire_width'):
            pb.custom_shape_wire_width = float(entry.get('wire_width', 1.0))
    return set(loaded.values())


def organize(rig, collection, meshes):
    """Name only owned body containers; never purge unrelated scene data."""
    token=rig.get('mm_import_id')
    root=bpy.data.collections.get(str(rig.get('mm_character_collection',''))) or collection
    for c in rig.users_collection:
        if c.get('mm_collection_role')=='ARMATURE' and c.name=='ARMATURE' and all(o==rig for o in c.objects):
            target_name=rig.name.removesuffix('_RIG')+'_ARMATURE'
            if target_name not in bpy.data.collections:c.name=target_name
    for mesh in meshes:
        for c in mesh.users_collection:
            if c.get('mm_collection_role')=='HEAD' and all(o in meshes for o in c.objects):
                c.name=rig.name.removesuffix('_RIG')+'_MESHES'
                c['mm_collection_role']='BODY'
    for c in list(bpy.data.collections):
        if c==collection or c.objects or c.children:continue
        owned=(token and c.get('mm_import_id')==token) or (c in root.children_recursive and c.get('mm_collection_role')=='RIGLOGICDATA')
        if owned:bpy.data.collections.remove(c)
    for c in list(rig.data.collections_all):
        if not c.bones:rig.data.collections.remove(c)
