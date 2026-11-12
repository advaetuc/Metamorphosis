"""Body DNA import and a control layer inspired by the supplied custom rig."""
import math
import json
import numpy as np
import bpy
from mathutils import Vector
from bpy.props import StringProperty, FloatProperty, IntProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper

from ..dna import importer, dnaio
from ..core import cleanup
from ..riglogic import bakeplan
from ..sculpting import sculpt
from .body_rbf import BodyRBF
from .body_driverplan import Graph

COLORS={'L':(76/255,108/255,1),'R':(1,23/255,12/255),'C':(244/255,201/255,12/255)}


def control_name(name):
    side=''
    if name.endswith(('_l','_r')):
        side='.'+name[-1].upper();name=name[:-2]
    names={'root':'ROOT','pelvis':'HIPS','head':'HEAD','clavicle':'SHOULDER',
           'upperarm':'ARM_FK','lowerarm':'FOREARM_FK','hand':'HAND_FK',
           'thigh':'THIGH_FK','calf':'SHIN_FK','foot':'FOOT_FK','ball':'TOE_FK'}
    return names.get(name,name.upper())+side


def color_bone(bone):
    side=bone.name[-1] if bone.name.endswith(('.L','.R')) else 'C'
    rgb=COLORS[side]
    bone.color.palette='CUSTOM'
    bone.color.custom.normal=rgb
    bone.color.custom.select=tuple(v+(1-v)*.4 for v in rgb)
    bone.color.custom.active=tuple(v+(1-v)*.7 for v in rgb)


def build_controls(rig, reader, collection, shape_preset='UNREAL'):
    from .body_converter import convert
    return convert(rig, collection, shape_preset=shape_preset)


def build_correctives(reader,rig,collection,prefix,scale,lod):
    dna,_,_=dnaio.load_bindings('')
    model=BodyRBF(reader,dna,lod)
    graph=Graph();raw=[graph.emit(f'raw{i}') for i in range(model.raw_count)]
    controls=graph.compile_rbf(model,raw)
    rotations=graph.compile_rotations(reader,controls,lod)
    rotations.update(graph.compile_twist_swing(reader,raw))
    rows={}
    for group in range(reader.getJointGroupCount()):
        inputs=list(reader.getJointGroupInputIndices(group))
        outputs=list(reader.getJointGroupOutputIndices(group))
        values=np.array(list(reader.getJointGroupValues(group))).reshape(len(outputs),len(inputs))
        count=list(reader.getJointGroupLODs(group))[lod]
        for output,weights in zip(outputs[:count],values[:count]):
            dest=rows.setdefault(output,{})
            for index,value in zip(inputs,weights):dest[index]=dest.get(index,0)+value
    orientations=bakeplan.joint_orientation_inverse(reader,reader.getJointCount(),True)
    targets=[]
    for joint in range(reader.getJointCount()):
        name=str(reader.getJointName(joint))
        translation=[rows.get(joint*9+i,{}) for i in range(3)]
        for axis in range(9):
            if axis<3:
                weights={}
                for component in range(3):
                    for index,value in translation[component].items():
                        weights[index]=weights.get(index,0)+value*orientations[joint,axis,component]*scale
            else:
                weights={index:value*(math.pi/180 if axis<6 else 1) for index,value in rows.get(joint*9+axis,{}).items()}
            weights={i:w for i,w in weights.items() if w!=0}
            if not weights or axis in (3,4,5) and joint in rotations:continue
            node=graph.weighted([controls[i] for i in weights],list(weights.values()))
            if axis>=6:node=graph.emit('1+a',node)
            targets.append((name,('location','rotation_euler','scale')[axis//3],axis%3,node))
        if joint in rotations:
            for axis,index in enumerate((3,0,1,2)):
                targets.append((name,'rotation_quaternion',axis,rotations[joint][index]))
    from . import body_fields
    helpers=bpy.data.collections.new(prefix+'_RIGLOGICDATA')
    helpers['mm_collection_role']='BODY_RIGLOGICDATA'
    collection.children.link(helpers)
    output,indices,holders=body_fields.realize(graph,helpers,prefix,model.raw_names,rig)
    for holder in holders:holder.hide_select=True
    for bone,path,axis,node in targets:
        pb=rig.pose.bones[bone];pb.rotation_mode='QUATERNION' if path=='rotation_quaternion' else pb.rotation_mode
        if path=='rotation_euler':pb.rotation_mode='XYZ'
        d=pb.driver_add(path,axis).driver;d.type='SCRIPTED'
        v=d.variables.new();v.name='value';v.type='SINGLE_PROP'
        v.targets[0].id=output;v.targets[0].data_path=f'data.vertices[{indices[node]}].co[0]'
        d.expression='value/10000'
    rig['mm_body_helpers']='\n'.join(h.name for h in holders)
    rig['mm_body_corrective_drivers']=model.raw_count+len(targets)
    return model,graph


class MM_OT_import_body(bpy.types.Operator,ImportHelper):
    bl_idname='metamorphosis.import_body'
    bl_label='Import Body DNA'
    bl_options={'REGISTER','UNDO'}
    filename_ext='.dna'
    filter_glob:StringProperty(default='*.dna',options={'HIDDEN'})
    scale:FloatProperty(name='Scale',default=.01,min=.0001)
    lod:IntProperty(name='LOD',default=0,min=0,max=3)


    def execute(self,context):
        reader=None;before=cleanup.snapshot();token=cleanup.new_token()
        try:
            reader=dnaio.open_reader(self.filepath)
            if reader.getGUIControlCount() or not reader.getRBFSolverCount():
                raise ValueError('Select a body DNA with RBF corrective data')
            if not dnaio.unit_flags(reader)[0]:
                raise ValueError('Body DNA rotations must be stored in degrees')
            if self.lod>=reader.getLODCount():raise ValueError('The selected body LOD is not present in this DNA')
            prefix=importer.unique_prefix('METAHUMAN_BODY')
            options=importer.ImportOptions(scale=self.scale,lod=self.lod,prefix=prefix)
            imported=importer.import_head(reader,options)
            if imported.warnings:
                raise ValueError('; '.join(imported.warnings))
            for mesh in imported.meshes:
                mesh.pop('mm_head_mesh',None);mesh['mm_body_mesh']=True
            build_correctives(reader,imported.rig,imported.collection,prefix,self.scale,self.lod)
            for c in list(imported.collection.children):
                role=c.get('mm_collection_role')
                if role=='ARMATURE':c.name=prefix+'_ARMATURE'
                elif role=='HEAD':c.name=prefix+'_MESHES';c['mm_collection_role']='BODY'
                elif role=='RIGLOGICDATA' and not c.objects and not c.children:bpy.data.collections.remove(c)
            imported.rig.show_in_front=False
            imported.rig['mm_body_rig']=True
            imported.rig['mm_body_dna']=self.filepath
            imported.rig['mm_body_scale']=self.scale
            cleanup.mark_created(before,token)
            self.report({'INFO'},'Imported original body DNA with native correctives; click Build Control Rig when ready')
            return {'FINISHED'}
        except Exception as exc:
            created=[item for pool in cleanup.POOLS for item in getattr(bpy.data,pool) if item.as_pointer() not in before[pool]]
            bpy.data.batch_remove(ids=created)
            self.report({'ERROR'},str(exc));return {'CANCELLED'}
        finally:
            if reader is not None:dnaio.release_handle(reader)


def active_body(context):
    obj=context.object
    if obj and obj.type=='MESH':
        obj=next((m.object for m in obj.modifiers if m.type=='ARMATURE' and m.object),None)
    return obj if obj and obj.type=='ARMATURE' and obj.get('mm_body_rig') else None


class MM_OT_body_snap(bpy.types.Operator):
    bl_idname='metamorphosis.body_snap'
    bl_label='Match Body IK / FK'
    bl_options={'REGISTER','UNDO'}
    limb:EnumProperty(items=(('ARM','Arm',''),('LEG','Leg','')))
    side:EnumProperty(items=(('L','Left',''),('R','Right','')))
    mode:EnumProperty(items=(('FK','FK','Match FK controls to the current pose'),('IK','IK','Match IK controls to the current pose')))

    def execute(self,context):
        rig=active_body(context)
        if rig is None:return {'CANCELLED'}
        if rig.get('mm_body_converter'):
            from .body_snap import snap
            snap(rig,self.limb,self.side,self.mode,context)
            return {'FINISHED'}
        names=('ARM','FOREARM','HAND') if self.limb=='ARM' else ('THIGH','SHIN','FOOT')
        switches=[rig.pose.bones['MCH_SWITCH_'+name+'.'+self.side] for name in names]
        matrices=[b.matrix.copy() for b in switches]
        if self.mode=='FK':
            for name,matrix in zip(names,matrices):
                rig.pose.bones[name+'_FK.'+self.side].matrix=matrix
                context.view_layer.update()
        else:
            chain=[rig.pose.bones['MCH_IK_'+name+'.'+self.side] for name in names]
            constraint=next(c for c in chain[1].constraints if c.type=='IK')
            constraint.mute=True
            context.view_layer.update()
            for name,matrix in zip(names,matrices):
                rig.pose.bones['MCH_IK_'+name+'.'+self.side].matrix=matrix
                context.view_layer.update()
            rig.pose.bones[names[-1]+'_IK.'+self.side].matrix=matrices[-1]
            a,b,c=[m.translation for m in matrices]
            line=c-a
            offset=b-(a+line*((b-a).dot(line)/max(line.length_squared,1e-12)))
            if offset.length>1e-5:
                pole=rig.pose.bones[self.limb+'_IK_POLE.'+self.side]
                matrix=pole.matrix.copy();matrix.translation=b+offset.normalized()*(b-a).length
                pole.matrix=matrix
                normal=(c-a).cross(matrix.translation-a)
                direction=(b-a).normalized()
                projected=normal.cross(direction).normalized()
                axis=matrices[0].to_3x3().col[0].normalized()
                constraint.pole_angle=math.atan2(axis.cross(projected).dot(direction),axis.dot(projected))
            constraint.mute=False
            # Match the pole angle in the evaluated chain's current basis. This
            # is an explicit snap operation, never a playback callback.
            def mismatch(angle):
                constraint.pole_angle=angle
                context.view_layer.update()
                return sum((chain[i].matrix.translation-matrices[i].translation).length_squared for i in (1,2))
            candidates=[-math.pi+i*math.tau/24 for i in range(24)]
            angle=min(candidates,key=mismatch)
            step=math.tau/24
            for _ in range(14):
                choices=[max(-math.pi,min(math.pi,angle+d)) for d in (-step,0,step)]
                angle=min(choices,key=mismatch);step*=.5
            mismatch(angle)
        rig.pose.bones['PROPERTIES'][f'{self.limb}_FK_IK.{self.side}']=1.0 if self.mode=='IK' else 0.0
        rig.update_tag();context.view_layer.update()
        return {'FINISHED'}


class MM_PT_body(bpy.types.Panel):
    bl_label='Body Rig'
    bl_idname='MM_PT_body'
    bl_parent_id='MM_PT_panel'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='MetaMorphosis'
    bl_options={'DEFAULT_CLOSED'}

    def draw_header(self,context):
        from ..core import ui
        self.layout.label(text='',icon_value=ui.icon('body'))

    def draw(self,context):
        layout=self.layout
        settings=layout.box()
        settings.label(text='Import Settings',icon='PREFERENCES')
        settings.prop(context.scene,'mm_body_custom_shapes',text='Custom Shapes')
        layout.operator('metamorphosis.import_body',icon='ARMATURE_DATA')
        layout.operator('metamorphosis.convert_body',text='Build Control Rig',icon='MOD_ARMATURE')
        layout.operator('metamorphosis.connect_body',icon='CONSTRAINT_BONE')
        rig=active_body(context)
        if rig is None:
            layout.label(text='Select a body rig to show its controls.')
            return
        box=layout.box();box.label(text=rig.name,icon='ARMATURE_DATA')
        if not rig.get('mm_body_converter'):
            box.label(text='Original DNA rig (click Build Control Rig)',icon='INFO')
            return
        preset=rig.get('mm_body_shape_preset')
        if preset:
            box.label(text=f'Shapes: {str(preset).title()}',icon='MESH_CUBE')
        props=rig.pose.bones.get('PROPERTIES')
        if props:
            for limb in ('ARM','LEG'):
                for side in ('L','R'):
                    key=f'{limb}_FK_IK.{side}'
                    if key not in props:continue
                    row=box.row(align=True)
                    row.prop(props,f'[{json.dumps(key)}]',text=f'{limb.title()} {side}',slider=True)
                    for mode in ('FK','IK'):
                        op=row.operator('metamorphosis.body_snap',text=mode)
                        op.limb=limb;op.side=side;op.mode=mode
                    box.prop(props,f'[{json.dumps(limb+"_IK_STRETCH."+side)}]',text=f'{limb.title()} {side} stretch')
            for key in ('HEAD_FOLLOW','NECK_FOLLOW'):
                if key in props:box.prop(props,f'[{json.dumps(key)}]',text=key.replace('_',' ').title(),slider=True)
        if props and rig.get('mm_body_converter'):
            pbox=layout.box();pbox.label(text='Follow and Parent Spaces')
            for side in ('L','R'):
                for key in ('ARM_ROT_FOLLOW','LEG_ROT_FOLLOW','ARM_IK_PARENTS','LEG_IK_PARENTS'):
                    name=key+'.'+side
                    if name in props:pbox.prop(props,f'[{json.dumps(name)}]',text=name.replace('_',' ').title())
            pbox.label(text='Arm parents: Root / Torso / Pelvis / Chest / Head')
            pbox.label(text='Leg parents: Root / Foot / Torso / Pelvis')
        rbox=layout.box();rbox.label(text='Rig UI',icon='OUTLINER_OB_ARMATURE')
        from .body_snap import draw_collections
        draw_collections(rbox,rig)
        layout.operator('metamorphosis.bake_rig_ui',text='Bake Rig UI',icon='FILE_SCRIPT')


def register():
    bpy.types.Scene.mm_body_custom_shapes = EnumProperty(
        name='Custom Shapes',
        description='Control shape style used when building the body control rig',
        items=(
            ('UNREAL', 'Unreal', 'Unreal Engine MetaHuman-style custom control shapes'),
            ('BLENDER', 'Blender', 'Blender wireframe custom control shapes'),
        ),
        default='UNREAL',
    )


def unregister():
    if hasattr(bpy.types.Scene, 'mm_body_custom_shapes'):
        del bpy.types.Scene.mm_body_custom_shapes


CLASSES=(MM_OT_import_body,MM_OT_body_snap,MM_PT_body)
