"""Custom body rig conversion with an intact native MetaHuman skinning bridge."""
import json
import math
import re
from pathlib import Path
import bpy
from mathutils import Matrix
from ..sculpting import sculpt
from . import body_geometry

RIG_ID = 'j0hn$@mb0007'
ASSET = Path(__file__).resolve().parents[1] / 'assets' / 'body_controls.blend'


def bridge_map():
    result = {'root':'ROOT','pelvis':'PELVIS_TWEAK','spine_01':'SPINE_01_TWEAK',
              'spine_02':'SPINE_02_TWEAK','spine_03':'SPINE_03_TWEAK','spine_04':'SPINE_04_TWEAK',
              'spine_05':'SPINE_05_TWEAK','neck_01':'NECK_01_TWEAK','neck_02':'NECK_02_TWEAK','head':'ORG_HEAD'}
    for side in 'lr':
        suffix='.'+side.upper()
        for source,target in (('clavicle','SHOULDER'),('upperarm','ORG_ARM'),('lowerarm','ORG_FOREARM'),
                              ('hand','ORG_HAND'),('thigh','ORG_THIGH'),('calf','ORG_SHIN'),
                              ('foot','ORG_FOOT'),('ball','ORG_TOE')):
            result[source+'_'+side]=target+suffix
        for digit,letter in (('thumb',None),('index','A'),('middle','B'),('ring','C'),('pinky','D')):
            if letter:result[digit+'_metacarpal_'+side]='FINGER_'+letter+'_01'+suffix
            for i in (1,2,3):
                result[f'{digit}_{i:02}_{side}']=(f'FINGER_{letter}_{i+1:02}' if letter else f'THUMB_{i:02}')+suffix
        for letter,digit in zip('ABCDE',('bigtoe','indextoe','middletoe','ringtoe','littletoe')):
            for i in (1,2):result[f'{digit}_{i:02}_{side}']=f'TOE_{letter}_{i:02}'+suffix
    assert len(result)==84
    return result


def property_driver(rig, owner, path, prop, expression='v'):
    f=owner.driver_add(path);d=f.driver;d.type='SCRIPTED'
    for v in list(d.variables):d.variables.remove(v)
    v=d.variables.new();v.name='v';v.type='SINGLE_PROP';v.targets[0].id=rig
    v.targets[0].data_path='pose.bones["PROPERTIES"]['+json.dumps(prop)+']'
    d.expression=expression


def configure(rig,H):
    """Repair reference WIP asymmetries and rebuild the 66 property drivers."""
    rig.animation_data_clear()
    props=rig.pose.bones['PROPERTIES']
    for key in list(props.keys()):
        if key.startswith(('ARM_','LEG_')):
            if 'ROT_FOLLOW' in key:props[key]=1.0
            else:props[key]=0.0 if 'FLEXTION' in key else 0
    props['HEAD_FOLLOW']=props['NECK_FOLLOW']=1.0
    for pb in rig.pose.bones:
        pb.matrix_basis=Matrix.Identity(4);pb.rotation_mode='XYZ';pb.bone.use_deform=False
        for c in pb.constraints:
            if hasattr(c,'target') and c.target:c.target=rig
            if c.type=='ARMATURE':
                for t in c.targets:t.target=rig
            if c.type=='STRETCH_TO':
                c.rest_length=0  # recompute for the fitted landmarks
            if c.type=='TRANSFORM':
                # Translation ranges are authored in meters on the reference.
                for key in ('to_min_x','to_max_x','to_min_y','to_max_y','to_min_z','to_max_z'):
                    setattr(c,key,getattr(c,key)*H/1.6176)
        if pb.custom_shape:
            pb.custom_shape.hide_render=True;pb.custom_shape.hide_set(True)
    for side in 'LR':
        S='.'+side
        for i,influence in enumerate((.5,.7,.8,.9),1):
            for c in rig.pose.bones[f'ORG_ARM_{i:02}'+S].constraints:
                if c.type=='COPY_ROTATION':c.influence=influence
        tricep=rig.pose.bones['ORG_COR_BBONE_02_TRICEP'+S]
        transforms=[c for c in tricep.constraints if c.type=='TRANSFORM']
        for c in transforms[1:]:tricep.constraints.remove(c)
        for kind in ('FRONT','BACK'):
            for prefix in ('ORG_','DEF_'):
                b=rig.data.bones[prefix+'COR_THIGH_'+kind+S]
                b.bbone_handle_type_start=b.bbone_handle_type_end='ABSOLUTE'
                b.bbone_custom_handle_start=rig.data.bones['COR_THIGH_'+kind+'_01'+S]
                b.bbone_custom_handle_end=rig.data.bones['COR_THIGH_'+kind+'_02'+S]
        props['ARM_BICEP_FLEXTION'+S]=0.0
        props.id_properties_ui('ARM_BICEP_FLEXTION'+S).update(min=0,max=1)
        for i in (1,2):
            for c in rig.pose.bones[f'ORG_COR_BBONE_{i:02}_BICEP'+S].constraints:
                if c.type=='TRANSFORM':property_driver(rig,c,'influence','ARM_BICEP_FLEXTION'+S)
        for twist, switch in (('MCH_TWIST_ARM', 'MCH_SWITCH_ARM'), ('MCH_THIGH_TWIST', 'MCH_SWITCH_THIGH')):
            tpb = rig.pose.bones[twist + S]
            for c in [c for c in tpb.constraints if c.type in ('DAMPED_TRACK', 'COPY_ROTATION')]:
                tpb.constraints.remove(c)
            cr = tpb.constraints.new('COPY_ROTATION')
            cr.name = 'Copy Twist Rotation'
            cr.target = rig
            cr.subtarget = switch + S
            cr.target_space = cr.owner_space = 'WORLD'
        for limb,names,socket,endpoint,parents,poleparents in (
            ('ARM',('ARM','FOREARM','HAND'),'ARM','HAND','MCH_HAND_IK','MCH_ARM_IK_POLE'),
            ('LEG',('THIGH','SHIN','FOOT'),'THIGH','FOOT','MCH_PARENTS_FOOT_IK','MCH_PARENTS_LEG_IK_POLE')):
            for name in names:
                c=rig.pose.bones['MCH_SWITCH_'+name+S].constraints.get('IK')
                if c is None:raise ValueError('Template IK switch is missing')
                c.mute=False
                property_driver(rig,c,'influence',limb+'_FK_IK'+S)
            c=next(c for c in rig.pose.bones['MCH_INT_'+socket+'_SOCKET'+S].constraints if c.type=='COPY_ROTATION')
            property_driver(rig,c,'influence',limb+'_ROT_FOLLOW'+S)
            end=rig.pose.bones['MCH_IK_'+endpoint+S]
            limit=next(c for c in end.constraints if c.type=='LIMIT_DISTANCE')
            a=rig.data.bones['MCH_IK_'+names[0]+S];b=rig.data.bones['MCH_IK_'+names[1]+S]
            limit.distance=a.length+b.length
            property_driver(rig,limit,'influence',limb+'_IK_STRETCH'+S,'1-v')
            ik=next(c for c in rig.pose.bones[b.name].constraints if c.type=='IK')
            ik.target=ik.pole_target=rig;ik.pole_subtarget=limb+'_IK_POLE'+S
            ik.pole_angle=body_geometry.pole_angle(rig.data.bones,a.name,b.name,ik.pole_subtarget)
            ik.iterations=500;ik.chain_count=2
            for owner in (parents,poleparents):
                c=next(c for c in rig.pose.bones[owner+S].constraints if c.type=='ARMATURE')
                for i,target in enumerate(c.targets):
                    expr=f'v=={i}'
                    if limb=='LEG' and owner==parents:expr=('v==0 or v==1','v==2','v==3')[i]
                    property_driver(rig,target,'weight',limb+'_IK_PARENTS'+S,expr)
        for c in rig.pose.bones['MCH_TOE'+S].constraints:
            if c.type=='COPY_ROTATION':
                c.mute=False
                property_driver(rig,c,'influence','LEG_FK_IK'+S)
    for name in ('HEAD','NECK'):
        c=next(c for c in rig.pose.bones['MCH_INT_'+name].constraints if c.type=='COPY_ROTATION')
        property_driver(rig,c,'influence',name+'_FOLLOW')
    # Match the intended bilateral contact equations, fixing the source WIP
    # differences in inner forearm, bicep and duplicate tricep constraints.
    for left in rig.pose.bones:
        if not left.name.endswith('.L'):continue
        right=rig.pose.bones.get(left.name[:-2]+'.R')
        if right is None:continue
        for lc in left.constraints:
            if lc.type!='TRANSFORM' or lc.map_to!='LOCATION':continue
            rc=right.constraints.get(lc.name)
            if rc is None or rc.type!='TRANSFORM':continue
            rc.use_motion_extrapolate=lc.use_motion_extrapolate
            rc.influence=lc.influence
            rc.from_min_z_rot=-lc.from_max_z_rot;rc.from_max_z_rot=-lc.from_min_z_rot
            for axis in 'xyz':
                sign=-1 if axis=='x' else 1
                setattr(rc,'to_min_'+axis,sign*getattr(lc,'to_max_'+axis))
                setattr(rc,'to_max_'+axis,sign*getattr(lc,'to_min_'+axis))
    rig.data['rig_id']=RIG_ID


def convert(rig,collection,shape_preset='UNREAL'):
    """Convert a neutral body in place. Original names/rest/weights are retained."""
    shape_preset = str(shape_preset or 'UNREAL').upper()
    if shape_preset not in ('UNREAL', 'BLENDER'):
        raise ValueError(f'Unknown custom shape preset: {shape_preset}')
    from .body_merge import snapshot_drivers,restore_drivers
    recorded=bpy.data.collections.get(str(rig.get('mm_character_collection','')))
    if recorded is not None and rig in recorded.all_objects.values():collection=recorded
    if rig.library or rig.data.users!=1:
        raise ValueError('Use a local, single-user armature for conversion')
    if rig.animation_data and (rig.animation_data.action or rig.animation_data.nla_tracks):
        raise ValueError('Convert a neutral body before creating animation takes')
    if rig.get('mm_body_converter') not in (None,'','NATIVE_BRIDGE_1'):
        raise ValueError('This body already has the current native controls, or uses the legacy DEF-only system')
    if rig.get('mm_body_joint_map') or any(b.name.startswith('FACIAL_') for b in rig.data.bones):
        raise ValueError('Convert a body-only rig first, then use Connect Body to attach the head')
    mapping=bridge_map()
    absent=set(mapping)-set(rig.data.bones.keys())
    if absent:raise ValueError('Body landmarks missing: '+', '.join(sorted(absent)))
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==rig for m in o.modifiers)]
    if not meshes:raise ValueError('Select a body with a skinned mesh')
    if rig.mode not in ('OBJECT','POSE'):
        raise ValueError('Leave Edit Mode before converting the body')
    identity=Matrix.Identity(4)
    if any(max(abs(x-y) for ra,rb in zip(rig.pose.bones[n].matrix_basis,identity) for x,y in zip(ra,rb))>1e-6 for n in mapping):
        raise ValueError('Reset the original body bones before converting')
    sculpt.set_mode(rig,'OBJECT')
    mesh=max(meshes,key=lambda o:len(o.data.vertices))
    points=[rig.matrix_world.inverted()@mesh.matrix_world@v.co for v in mesh.data.vertices]
    source={b.name:b.matrix_local.copy() for b in rig.data.bones}
    old_shapes={p.custom_shape for p in rig.pose.bones if p.custom_shape}
    with bpy.data.libraries.load(str(ASSET),link=False) as (src,dst):
        dst.objects=['MM_CUSTOM_BODY_TEMPLATE']
    template=dst.objects[0];collection.objects.link(template)
    template.data.use_fake_user=False
    template.use_fake_user=False
    shapes={p.custom_shape for p in template.pose.bones if p.custom_shape}
    widgets=bpy.data.collections.new(rig.name+'_WIDGETS');collection.children.link(widgets)
    for shape in shapes:
        shape.use_fake_user=False;shape.data.use_fake_user=False
        if not shape.users_collection:widgets.objects.link(shape)
        shape.hide_render=True;shape.hide_set(True);shape.hide_select=True
    generated=set(template.data.bones.keys())
    collisions=generated & set(source)
    remove=set()
    # Only our old prototype can be upgraded automatically. Animated prototypes
    # require a fresh import because their control axes/hierarchy are different.
    if collisions:
        if not rig.get('mm_body_control_map'):raise ValueError('Custom bone names already exist')
        if rig.animation_data and (rig.animation_data.action or rig.animation_data.nla_tracks):
            raise ValueError('Import a fresh body before converting an animated prototype')
        original={b.name for b in rig.data.bones if any(c.name in ('DEF_BODY','DEF_MH_COR') for c in b.collections)}
        if not set(mapping)<=original:
            raise ValueError('Cannot identify the original DNA bone collection safely')
        remove=set(source)-original
        legacy=json.loads(rig['mm_body_control_map'])
        owned=set(legacy.values())|{'PROPERTIES'}|{'MCH_BIND_'+n for n in legacy}
        owned|={prefix+n+'.'+side for side in 'LR' for prefix in ('MCH_IK_','MCH_SWITCH_') for n in ('ARM','FOREARM','HAND','THIGH','SHIN','FOOT')}
        owned|={n+'.'+side for side in 'LR' for n in ('HAND_IK','FOOT_IK','ARM_IK_POLE','LEG_IK_POLE')}
        owned|={prefix+n for prefix in ('MCH_FOLLOW_','MCH_SPACE_') for n in ('head','neck_01')}
        owned|=set(json.loads(rig.get('mm_body_custom_bones','[]')))
        if remove-owned:
            raise ValueError('Custom-added bones need a fresh body import; conversion will not delete them')
        if any(b.matrix_basis!=Matrix.Identity(4) for b in rig.pose.bones if b.name in remove):
            raise ValueError('Reset the prototype controls before converting')
        source={n:m for n,m in source.items() if n in original}
    with sculpt.object_context(template):
        sculpt.set_mode(template,'EDIT')
        try:
            H=body_geometry.fit(template,source,points)
        finally:
            sculpt.set_mode(template,'OBJECT')
    configure(template,H)
    from . import body_refine
    mapping=body_refine.prepare(template,source,mapping)
    generated=set(template.data.bones.keys())
    template.matrix_world=rig.matrix_world.copy()
    body_refine.apply_shape_preset(template,widgets,shape_preset,mesh=mesh)
    body_refine.clean_widgets(template,shapes,widgets)
    # Finish all fallible template fitting before changing a prototype.
    if remove:
        if rig.animation_data:
            for f in list(rig.animation_data.drivers):
                if any(f.data_path.startswith('pose.bones['+json.dumps(n)+']') for n in remove):rig.animation_data.drivers.remove(f)
        for name in original:
            for c in list(rig.pose.bones[name].constraints):
                if c.name=='MetaMorphosis Control' or c.name.startswith(('MetaMorphosis Bridge Base','MetaMorphosis Native Bridge')):rig.pose.bones[name].constraints.remove(c)
        with sculpt.object_context(rig):
            sculpt.set_mode(rig,'EDIT')
            for name in remove:rig.data.edit_bones.remove(rig.data.edit_bones[name])
            sculpt.set_mode(rig,'OBJECT')
    template.matrix_world=rig.matrix_world.copy()
    drivers=snapshot_drivers(template)
    for _,_,_,_,_,variables in drivers:
        for _,_,targets in variables:
            for t in targets:
                if t['id']==template:t['id']=rig
    with bpy.context.temp_override(object=rig,active_object=rig,selected_objects=[rig,template],selected_editable_objects=[rig,template]):
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True);template.select_set(True)
        bpy.context.view_layer.objects.active=rig
        bpy.ops.object.join()
    restore_drivers(rig,drivers)
    rig.data['rig_id']=RIG_ID
    # The supplied 'untouched' fixture retains dangling prototype constraints
    # after its controls were deleted. Replace only our named legacy bridge.
    for name in source:
        for old in list(rig.pose.bones[name].constraints):
            if old.name=='MetaMorphosis Control' or old.name.startswith(('MetaMorphosis Bridge Base','MetaMorphosis Native Bridge')):rig.pose.bones[name].constraints.remove(old)
    for name,target in mapping.items():
        # Reset the inherited pose in armature space before applying the
        # absolute custom target delta. A lone CHILD_OF double-transforms
        # every descendant while still appearing correct at rest.
        pb=rig.pose.bones[name]
        for kind in ('LOCATION','ROTATION','SCALE'):
            reset=pb.constraints.new('LIMIT_'+kind)
            reset.name='MetaMorphosis Bridge Base '+kind
            reset.owner_space='POSE'
            for axis in 'xyz':
                setattr(reset,'min_'+axis,1 if kind=='SCALE' else 0)
                setattr(reset,'max_'+axis,1 if kind=='SCALE' else 0)
                if kind=='ROTATION':setattr(reset,'use_limit_'+axis,True)
                else:
                    setattr(reset,'use_min_'+axis,True);setattr(reset,'use_max_'+axis,True)
        c=rig.pose.bones[name].constraints.new('CHILD_OF')
        c.name='MetaMorphosis Native Bridge';c.target=rig;c.subtarget=target
        c.inverse_matrix=rig.data.bones[target].matrix_local.inverted() @ source[name]
    for b in rig.data.bones:
        if b.name in generated:continue
        if b.name not in source:continue
        name='DEF_BODY' if b.name in mapping else 'DEF_MH_COR'
        group=rig.data.collections.get(name) or rig.data.collections.new(name)
        for old in list(b.collections):old.unassign(b)
        group.assign(b)
    empty=rig.data.collections.get('CONTROLS')
    if empty is not None and not len(empty.bones):rig.data.collections.remove(empty)
    for c in rig.data.collections_all:c.is_visible=c.name not in ('MCH','ORG','DEF','DEF_COR','DEF_HEAD','DEF_BODY','DEF_MH_COR','CONTROLS')
    helpers=[bpy.data.objects.get(n) for n in str(rig.get('mm_body_helpers','')).splitlines()]
    helpers=[o for o in helpers if o is not None and o.get('mm_body_helper')]
    if helpers:
        data_collection=next((c for c in helpers[0].users_collection if c.get('mm_collection_role')=='BODY_RIGLOGICDATA'),None)
        if data_collection is None:
            data_collection=bpy.data.collections.new(rig.name+'_RIGLOGICDATA')
            data_collection['mm_collection_role']='BODY_RIGLOGICDATA'
            collection.children.link(data_collection)
        for obj in helpers:
            if obj.name not in data_collection.objects:data_collection.objects.link(obj)
            if collection in obj.users_collection:collection.objects.unlink(obj)
            obj.hide_set(True);obj.hide_render=True;obj.hide_select=True
    rig['mm_body_rig']=True;rig['mm_body_converter']='NATIVE_BRIDGE_2'
    rig['mm_body_shape_preset']=shape_preset
    rig['mm_body_control_map']=json.dumps(mapping)
    rig['mm_body_custom_bones']=json.dumps(sorted(generated))
    body_refine.clean_widgets(rig,old_shapes,widgets)
    body_refine.organize(rig,collection,meshes)
    rig.show_in_front=False
    if shape_preset=='UNREAL':
        rig.display_type='SOLID'
        for bone in rig.data.bones:bone.show_wire=False
    else:
        rig.display_type='WIRE'
    for old_collection in list(bpy.data.collections):
        if old_collection!=widgets and old_collection.name.startswith(rig.name+'_WIDGETS') and not old_collection.objects and not old_collection.children:
            bpy.data.collections.remove(old_collection)
    if widgets.name!=rig.name+'_WIDGETS' and rig.name+'_WIDGETS' not in bpy.data.collections:
        widgets.name=rig.name+'_WIDGETS'
    for obj in list(widgets.objects):
        stem=re.sub(r'\.\d{3}$','',obj.name)
        if stem!=obj.name and stem not in bpy.data.objects:
            obj.name=stem
            if obj.data and obj.data.name!=stem and stem not in bpy.data.meshes:obj.data.name=stem
    rig.update_tag();bpy.context.view_layer.update()
    return mapping


def _resolve_body_rig(context):
    obj = getattr(context, 'active_object', None) or getattr(context, 'object', None)
    if obj and obj.type == 'MESH':
        obj = next((m.object for m in obj.modifiers if m.type == 'ARMATURE' and m.object), None)
    if obj and obj.type == 'ARMATURE' and (obj.get('mm_body_rig') or 'pelvis' in obj.data.bones):
        return obj
    return next((o for o in context.scene.objects if o.type == 'ARMATURE' and (o.get('mm_body_rig') or 'pelvis' in o.data.bones)), None)


class MM_OT_convert_body(bpy.types.Operator):
    bl_idname='metamorphosis.convert_body'
    bl_label='Build Control Rig'
    bl_description='Build or upgrade the body control rig using the selected Custom Shapes preset'
    bl_options={'REGISTER','UNDO'}
    shape_preset: bpy.props.EnumProperty(
        name='Custom Shapes',
        items=(
            ('SCENE', 'Use Import Settings', 'Use the Custom Shapes preset chosen in Import Settings'),
            ('UNREAL', 'Unreal', 'Unreal Engine MetaHuman-style control shapes'),
            ('BLENDER', 'Blender', 'Blender wireframe control shapes'),
        ),
        default='SCENE',
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls,context):
        o=_resolve_body_rig(context)
        return o is not None and o.type=='ARMATURE' and 'pelvis' in o.data.bones and o.get('mm_body_converter') in (None,'','NATIVE_BRIDGE_1')
    def execute(self,context):
        from ..core import cleanup
        rig=_resolve_body_rig(context)
        if rig is None:return {'CANCELLED'}
        before=cleanup.snapshot()
        initial_bones=set(rig.data.bones.keys())
        original_mode=rig.mode
        preset=getattr(context.scene,'mm_body_custom_shapes','UNREAL') if self.shape_preset=='SCENE' else self.shape_preset
        try:
            convert(rig,rig.users_collection[0],shape_preset=preset)
            token=rig.get('mm_import_id') or cleanup.new_token()
            cleanup.mark_created(before,token)
            try:
                from ..core import organization
                organization.close_all_collections(context)
            except Exception:
                pass
            self.report({'INFO'},f'Control rig built ({preset.title()} shapes); native correctives retained')
            return {'FINISHED'}
        except Exception as exc:
            created=[item for pool in cleanup.POOLS for item in getattr(bpy.data,pool) if item.as_pointer() not in before[pool]]
            # Preflight/asset preparation failures must not leave appended widgets.
            if set(rig.data.bones.keys())==initial_bones:
                bpy.data.batch_remove(ids=created)
            context.view_layer.objects.active=rig;rig.select_set(True)
            if original_mode=='POSE':sculpt.set_mode(rig,'POSE')
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

CLASSES=(MM_OT_convert_body,)
