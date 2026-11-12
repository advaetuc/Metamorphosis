"""Join imported DNA skeletons while retaining a separate, following face board."""
import json
import bpy
from mathutils import Matrix
from ..riglogic import bake
from ..sculpting import sculpt


def driver_owners():
    for pool in ('objects','meshes','shape_keys','node_groups','materials'):
        for owner in getattr(bpy.data,pool):
            yield owner
            if pool=='materials' and owner.node_tree:yield owner.node_tree


def retarget(old,new,board=None,board_names=()):
    paths=tuple('pose.bones['+json.dumps(n)+']' for n in board_names)
    for owner in driver_owners():
        if not owner.animation_data:continue
        for curve in owner.animation_data.drivers:
            for var in curve.driver.variables:
                for target in var.targets:
                    if target.id==old:
                        is_board=target.bone_target in board_names or target.data_path.startswith(paths)
                        target.id=board if board is not None and is_board else new


def snapshot_drivers(obj):
    result=[]
    for curve in obj.animation_data.drivers if obj.animation_data else []:
        variables=[]
        for var in curve.driver.variables:
            targets=[]
            for t in var.targets:
                targets.append({key:getattr(t,key) for key in ('id_type','id','data_path','bone_target','transform_type','transform_space','rotation_mode')})
            variables.append((var.name,var.type,targets))
        result.append((curve.data_path,curve.array_index,curve.mute,curve.driver.type,curve.driver.expression,variables))
    return result


def restore_drivers(obj,drivers):
    for path,index,mute,kind,expression,variables in drivers:
        value=obj.path_resolve(path)
        curve=obj.driver_add(path,index) if hasattr(value,"__len__") else obj.driver_add(path)
        curve.mute=mute;driver=curve.driver;driver.type=kind
        for var in list(driver.variables):driver.variables.remove(var)
        for name,vtype,targets in variables:
            var=driver.variables.new();var.name=name;var.type=vtype
            for target,values in zip(var.targets,targets):
                for key,value in values.items():
                    if key=='id_type' and var.type!='SINGLE_PROP':continue
                    setattr(target,key,value)
        driver.expression=expression


def merge(context,body,head):
    if body==head or not body.get('mm_body_rig') or bake.RIG_KEY_DATA not in head:
        raise ValueError('Select one imported body rig and one imported head rig')
    if body.get(bake.RIG_KEY_DATA):raise ValueError('This body already has an attached head')
    for rig in (body,head):
        if rig.library or rig.data.users!=1 or len(rig.users_scene)!=1:
            raise ValueError('Use local, single-user rigs before connecting the head and body')
        if rig.animation_data and (rig.animation_data.action or rig.animation_data.nla_tracks):
            raise ValueError('Connect the skeletons before creating animation takes')
        if rig.get('mm_sculpt_session') or rig.get('mm_expression_session'):
            raise ValueError('Finish the sculpt session before connecting skeletons')
    if abs(float(head.get(bake.RIG_KEY_SCALE,.01))-float(body['mm_body_scale']))>1e-8:
        raise ValueError('Head and body import scales must match')
    if 'mm_body_control_map' not in body or 'PROPERTIES' not in body.pose.bones:
        raise ValueError('Build Control Rig before connecting the head and body')
    identity=Matrix.Identity(4)
    controls=json.loads(body['mm_body_control_map']).values()
    if any(max(abs(a-b) for ra,rb in zip(body.pose.bones[n].matrix_basis,identity) for a,b in zip(ra,rb))>1e-5 for n in controls):
        raise ValueError('Reset the body controls to their rest pose before connecting')
    if any(float(v)>0 for k,v in body.pose.bones['PROPERTIES'].items() if '_FK_IK.' in k):
        raise ValueError('Switch the body limbs to FK before connecting')
    board_names=set(filter(None,str(head.get(bake.RIG_KEY_BOARD,'')).split('\n')))
    board=bpy.data.objects.get(str(head.get(bake.RIG_KEY_BOARD_OBJECT,''))) or head
    if not board_names or 'head' not in body.data.bones or 'head' not in head.data.bones:
        raise ValueError('The DNA head, body head bone and face-board metadata are required')
    collisions=set(body.data.bones.keys())&set(head.data.bones.keys())-board_names
    renames={name:'BODY_BIND_'+name for name in collisions}
    if any(n in head.data.bones or n in body.data.bones for n in renames.values()):
        raise ValueError('Reserved body attachment bone names already exist')
    meshes=[o for o in context.scene.objects if o.type=='MESH' and any(m.type=='ARMATURE' and m.object==body for m in o.modifiers)]
    # Keep the head's source names intact for face rebuilding and DNA sculpting.
    # Namespaced body bind bones retain their original rest matrices and weights.
    for old,new in renames.items():
        body.data.bones[old].name=new
        for mesh in meshes:
            if old in mesh.vertex_groups:mesh.vertex_groups[old].name=new
    body['mm_body_joint_map']=json.dumps(renames)
    if board==head:
        previous=set(bpy.data.objects)
        with sculpt.object_context(head):
            sculpt.set_mode(head,'EDIT')
            for bone in head.data.edit_bones:
                bone.select=bone.select_head=bone.select_tail=bone.name in board_names
            bpy.ops.armature.separate()
            sculpt.set_mode(head,'OBJECT')
        board=next(o for o in set(bpy.data.objects)-previous if o.type=='ARMATURE')
        board.name=head.name+'_FACE_BOARD'
        if board.animation_data:
            for curve in list(board.animation_data.drivers):
                if not any(curve.data_path.startswith('pose.bones['+json.dumps(n)+']') for n in board_names):
                    board.animation_data.drivers.remove(curve)
        for key in list(board.keys()):
            if key.startswith('mm_') and key!='mm_import_id':del board[key]
        retarget(head,head,board,board_names)
    metadata={k:head[k] for k in head.keys() if k.startswith('mm_') and k not in {'mm_import_id','mm_character_collection'}}
    children=[(o,o.matrix_world.copy()) for o in context.scene.objects if o.parent==head]
    retarget(head,body,board,board_names)
    # Armature joining keeps the active object's animation data. Explicitly
    # transfer facial drivers before the source ID is removed.
    facial_drivers=snapshot_drivers(head)
    for obj in context.scene.objects:
        for modifier in obj.modifiers:
            if modifier.type=='ARMATURE' and modifier.object==head:modifier.object=body
        constraints=list(obj.constraints)
        if obj.type=='ARMATURE':constraints.extend(c for bone in obj.pose.bones for c in bone.constraints)
        for constraint in constraints:
            if getattr(constraint,'target',None)==head:
                constraint.target=board if getattr(constraint,'subtarget','') in board_names else body
    for obj in context.view_layer.objects.selected:obj.select_set(False)
    body.select_set(True);head.select_set(True);context.view_layer.objects.active=body
    bpy.ops.object.join()
    restore_drivers(body,facial_drivers)
    for child,world in children:
        is_board=child.parent_bone in board_names or (child.get('mm_import_id')==board.get('mm_import_id') and not child.get('mm_head_mesh'))
        child.parent=board if is_board else body
        child.matrix_world=world
    with sculpt.object_context(body):
        sculpt.set_mode(body,'EDIT')
        for name,parent in renames.items():
            bone=body.data.edit_bones[name]
            bone.use_connect=False;bone.parent=body.data.edit_bones[parent]
        sculpt.set_mode(body,'OBJECT')
    for key,value in metadata.items():body[key]=value
    body[bake.RIG_KEY_BOARD_OBJECT]=board.name
    body['mm_attached_head']=True
    for c in list(body.data.collections_all):
        if not len(c.bones):
            body.data.collections.remove(c)
        elif c.name in ('MCH','ORG','DEF','DEF_COR','DEF_HEAD','DEF_BODY','DEF_MH_COR','CONTROLS'):
            c.is_visible=False
    world=board.matrix_world.copy()
    board.parent=None;board.matrix_world=world
    constraint=board.constraints.new('CHILD_OF');constraint.name='Follow MetaHuman Head'
    constraint.target=body;constraint.subtarget='head'
    context.view_layer.update()
    constraint.inverse_matrix=(body.matrix_world@body.pose.bones['head'].matrix).inverted()
    context.view_layer.update()
    return body,board


class MM_OT_connect_body(bpy.types.Operator):
    bl_idname='metamorphosis.connect_body'
    bl_label='Connect Head and Body'
    bl_description='Select an imported head and body; join skeletons and keep the face board separate'
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        bodies=[o for o in context.selected_objects if o.type=='ARMATURE' and o.get('mm_body_rig')]
        heads=[o for o in context.selected_objects if o.type=='ARMATURE' and bake.RIG_KEY_DATA in o and not o.get('mm_body_rig')]
        if len(bodies)!=1 or len(heads)!=1:
            self.report({'ERROR'},'Select one MetaMorphosis head rig and one body rig');return {'CANCELLED'}
        try:merge(context,bodies[0],heads[0])
        except (ValueError,RuntimeError) as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}
        self.report({'INFO'},'Connected skeletons; the separate face board follows the head')
        return {'FINISHED'}


CLASSES=(MM_OT_connect_body,)
