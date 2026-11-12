"""Retired legacy DEF-only conversion; never used by NATIVE_BRIDGE_2."""
import re
import bpy
from ..sculpting import sculpt

ANCHORS={'spine_04','spine_05','clavicle_l','clavicle_r','neck_01','neck_02','head'}


def target_group(name):
    center={'pelvis':'HIPS','spine_01':'SPINE_01','spine_02':'SPINE_02',
            'spine_03':'CHEST','spine_04':'CHEST','spine_05':'CHEST','neck_01':'NECK','neck_02':'NECK','head':'HEAD','root':'HIPS'}
    if name in center:return 'DEF_'+center[name]
    if not name.endswith(('_l','_r')):return None
    stem=name[:-2];S='.'+name[-1].upper()
    exact={'clavicle':'SHOULDER','clavicle_out':'SHOULDER','clavicle_pec':'COR_CHEST_UPPER',
           'clavicle_scap':'COR_BACK_UPPER','spine_04_latissimus':'COR_BACK_LOWER',
           'upperarm_in':'COR_UNDERARM','upperarm_out':'ARM_01','upperarm_fwd':'ARM_01','upperarm_bck':'ARM_01',
           'upperarm':'ARM_01','upperarm_twistCor_01':'ARM_02','upperarm_twistCor_02':'ARM_03',
           'upperarm_twist_01':'ARM_02','upperarm_twist_02':'ARM_03',
           'upperarm_bicep':'COR_BICEP','upperarm_tricep':'COR_TRICEP',
           'lowerarm_fwd':'COR_INNER_FORRARM','lowerarm_bck':'COR_ELBOW',
           'lowerarm':'FOREARM_01','lowerarm_in':'FOREARM_01','lowerarm_out':'FOREARM_01',
           'lowerarm_twist_02':'FOREARM_02','lowerarm_twist_01':'FOREARM_04',
           'hand':'HAND','wrist_inner':'HAND','wrist_outer':'HAND',
           'thigh_fwd':'COR_THIGH_FRONT','thigh_bck':'COR_THIGH_BACK','thigh_bck_lwr':'COR_THIGH_BACK',
           'thigh_out':'COR_THIGH_OUT','thigh_in':'COR_THIGH_INN','thigh_fwd_lwr':'THIGH_01',
           'thigh':'THIGH_01','thigh_twistCor_01':'THIGH_01','thigh_twistCor_02':'THIGH_02',
           'thigh_twist_01':'THIGH_01','thigh_twist_02':'THIGH_02',
           'calf_knee':'COR_KNEE','calf_kneeBack':'COR_THIGH_INN.',
           'calf':'SHIN','calf_twist_01':'SHIN','calf_twist_02':'SHIN','calf_twistCor_02':'SHIN',
           'foot':'FOOT','ankle_bck':'FOOT','ankle_fwd':'COR_FOOT_UPPER','ball':'TOE'}
    if stem in exact:return 'DEF_'+exact[stem]+S
    if re.fullmatch(r'(bigtoe|indextoe|middletoe|ringtoe|littletoe)_0[12]',stem):return 'DEF_TOE'+S
    m=re.match(r'(thumb|index|middle|ring|pinky)_(metacarpal|0[123])(?:_|$)',stem)
    if m:
        digit,part=m.groups()
        if digit=='thumb':return 'DEF_THUMB_'+part+S
        i=1 if part=='metacarpal' else int(part)+1
        return f'DEF_FINGER_{dict(index="A",middle="B",ring="C",pinky="D")[digit]}_{i:02}'+S
    return None


def remap(rig):
    if rig.get('mm_body_converter')=='NATIVE_BRIDGE_2' or 'DEF_SPINE_02' not in rig.data.bones:
        raise ValueError('Custom DEF Only conversion is retired; use Native Correctives (NATIVE_BRIDGE_2)')
    if rig.get('mm_body_joint_map') or any(b.name.startswith('FACIAL_') for b in rig.data.bones):
        raise ValueError('Convert the body to DEF-only before connecting a face')
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
    plans=[]
    for obj in meshes:
        mapping={g.index:target_group(g.name) for g in obj.vertex_groups}
        used={g.group for v in obj.data.vertices for g in v.groups if g.weight>0}
        missing=[obj.vertex_groups[i].name for i in used if not mapping[i] or mapping[i] not in rig.data.bones]
        if missing:raise ValueError('Unmapped body weights: '+', '.join(sorted(missing)))
        if obj.data.users!=1:raise ValueError('Make the body mesh single-user before DEF-only conversion')
        rows=[];mask=[]
        height=rig.data.bones['DEF_SPINE_02'].head_local.z
        for vertex in obj.data.vertices:
            weights={};pelvis=thigh=0
            for g in vertex.groups:
                target=mapping[g.group]
                if target:weights[target]=weights.get(target,0)+g.weight
                name=obj.vertex_groups[g.group].name
                if name=='pelvis':pelvis+=g.weight
                if name.startswith('thigh'):thigh+=g.weight
            total=sum(weights.values())
            if total:weights={n:w/total for n,w in weights.items()}
            rows.append(weights)
            upper=sum(w for n,w in weights.items() if n.startswith(('DEF_SPINE_02','DEF_CHEST','DEF_SHOULDER','DEF_ARM','DEF_FOREARM','DEF_HAND','DEF_THUMB','DEF_FINGER')))
            mask.append(max(min(1,2*min(pelvis,thigh)),min(1,upper) if vertex.co.z>height else 0))
        plans.append((obj,rows,mask,[g.name for g in obj.vertex_groups]))
    # All mappings are checked before the first skin weight changes.
    for obj,rows,mask,old_names in plans:
        obj.vertex_groups.clear()
        groups={n:obj.vertex_groups.new(name=n) for n in sorted({n for row in rows for n in row})}
        for i,row in enumerate(rows):
            for n,w in row.items():groups[n].add([i],w,'REPLACE')
        volume=obj.vertex_groups.new(name='DEF_PRESERVE_VOLUME')
        for i,w in enumerate(mask):
            if w:volume.add([i],w,'REPLACE')
        primary=next(m for m in obj.modifiers if m.type=='ARMATURE' and m.object==rig)
        primary.use_deform_preserve_volume=False;primary.use_multi_modifier=False;primary.use_vertex_groups=True
        secondary=obj.modifiers.new('PRESERVE_VOLUME','ARMATURE');secondary.object=rig
        secondary.use_deform_preserve_volume=True;secondary.use_multi_modifier=True
        secondary.vertex_group=volume.name
        obj['mm_body_original_groups']='\n'.join(old_names)
    native={b.name for b in rig.data.bones if any(c.name in ('DEF_BODY','DEF_MH_COR') for c in b.collections)}
    remove=native-ANCHORS
    if rig.animation_data:
        import json
        for f in list(rig.animation_data.drivers):
            if any(f.data_path.startswith('pose.bones['+json.dumps(n)+']') for n in remove):rig.animation_data.drivers.remove(f)
    with sculpt.object_context(rig):
        sculpt.set_mode(rig,'EDIT')
        for n in remove:rig.data.edit_bones.remove(rig.data.edit_bones[n])
        sculpt.set_mode(rig,'OBJECT')
    for b in rig.data.bones:
        b.use_deform=any(c.name in ('DEF','DEF_COR') for c in b.collections)
    for name in str(rig.get('mm_body_helpers','')).splitlines():
        obj=bpy.data.objects.get(name)
        if obj and obj.get('mm_body_helper'):
            data=obj.data
            bpy.data.objects.remove(obj,do_unlink=True)
            if data.users==0:bpy.data.meshes.remove(data)
    # Orphaned owned graphs are safe to remove; other characters' graphs stay.
    changed=True
    while changed:
        changed=False
        for group in list(bpy.data.node_groups):
            if group.get('mm_body_helper') and group.users==0:
                bpy.data.node_groups.remove(group);changed=True
    rig['mm_body_helpers']='';rig['mm_body_corrective_drivers']=0
    rig['mm_body_converter']='DEF_ONLY_1'
    rig.update_tag();bpy.context.view_layer.update()
