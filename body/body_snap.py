"""Explicit IK/FK matching and bakeable standalone Rig UI ('Item' tab)."""
import inspect
import json
import math
import bpy
from mathutils import Matrix


COLLECTION_GROUPS = (
    (('ROOT',),),
    (('TORSO',), ('SPINE_FK',)),
    (('ARM_IK.L', 'ARM_IK.R'), ('ARM_FK.L', 'ARM_FK.R'), ('ARM_TWK.L', 'ARM_TWK.R'), ('HAND.L', 'HAND.R')),
    (('LEG_IK.L', 'LEG_IK.R'), ('LEG_FK.L', 'LEG_FK.R'), ('LEG_TWK.L', 'LEG_TWK.R'), ('TOE.L', 'TOE.R')),
)


def visible_collections(rig):
    return [c for c in rig.data.collections_all if len(c.bones) and not c.name.startswith(('DEF', 'ORG', 'MCH'))
            and c.name not in ('ACC', 'ACC_TWK', 'TORSO_MUSCLE', 'ARM_MUSCLES.L', 'ARM_MUSCLES.R')]


def draw_collections(layout, rig):
    cols = {c.name: c for c in visible_collections(rig)}
    drawn = set()
    main = layout.column(align=False)
    for gi, group_rows in enumerate(COLLECTION_GROUPS):
        any_row = False
        for pair in group_rows:
            present = [name for name in pair if name in cols]
            if not present:
                continue
            any_row = True
            row = main.row(align=False)
            for name in present:
                c = cols[name]
                drawn.add(name)
                sub = row.row(align=True)
                sub.prop(c, 'is_visible', text=c.name, toggle=True)
                sub.prop(c, 'is_solo', text='', icon='SOLO_ON' if c.is_solo else 'SOLO_OFF')
        if any_row and gi < len(COLLECTION_GROUPS) - 1:
            main.separator(factor=0.6)
    extra = [c for name, c in cols.items() if name not in drawn and name != 'PROPERTIES']
    if extra:
        main.separator(factor=0.6)
        for c in extra:
            row = main.row(align=True)
            row.prop(c, 'is_visible', text=c.name.replace('_', ' '), toggle=True)
            row.prop(c, 'is_solo', text='', icon='SOLO_ON' if c.is_solo else 'SOLO_OFF')


def draw_parent_labels(layout):
    layout.label(text='Arm: Root / Torso / Pelvis / Chest / Head')
    layout.label(text='Leg: Root / Foot / Torso / Pelvis')


def snap(rig, limb, side, mode, context):
    names=('ARM','FOREARM','HAND') if limb=='ARM' else ('THIGH','SHIN','FOOT')
    S='.'+side;pb=rig.pose.bones
    matrices=[pb['MCH_SWITCH_'+n+S].matrix.copy() for n in names]
    selected=[]
    if mode=='FK':
        for n,m in zip(names,matrices):
            b=pb[n+'_FK'+S];b.matrix=m;selected.append(b)
            context.view_layer.update()
    else:
        chain=[pb['MCH_IK_'+n+S] for n in names]
        ik=next(c for c in chain[1].constraints if c.type=='IK')
        # Respect the stored IK locks. Native v2 uses pole-guided free axes;
        # matching never changes lock flags or leaves hidden solver state.
        ik.mute=True;context.view_layer.update()
        for bone,matrix in zip(chain[:2],matrices[:2]):
            bone.matrix=matrix;context.view_layer.update()
        # Reverse-foot pivots must be reset before fitting the IK endpoint.
        if limb=='LEG':
            pb['HEEL'+S].matrix_basis=Matrix.Identity(4);selected.append(pb['HEEL'+S])
        end=pb[names[-1]+'_IK'+S]
        target=pb['MCH_IK_'+names[-1]+S]
        end.matrix=matrices[-1] @ target.bone.matrix_local.inverted() @ end.bone.matrix_local
        selected.append(end);context.view_layer.update()
        a,b,c=[m.translation for m in matrices];line=c-a
        offset=b-(a+line*(b-a).dot(line)/max(line.length_squared,1e-12))
        pole=pb[limb+'_IK_POLE'+S]
        if offset.length>1e-6:
            m=pole.matrix.copy();m.translation=b+offset.normalized()*(b-a).length
            pole.matrix=m
        selected.extend((pole,*chain[:2]))
        ik.mute=False
    props=pb['PROPERTIES'];props[f'{limb}_FK_IK{S}']=int(mode=='IK')
    rig.update_tag();context.view_layer.update()
    if mode=='IK':
        chain=[pb['MCH_IK_'+n+S] for n in names]
        ik=next(c for c in chain[1].constraints if c.type=='IK')
        def mismatch(angle):
            ik.pole_angle=angle;context.view_layer.update()
            return sum((chain[i].matrix.translation-matrices[i].translation).length_squared for i in (1,2))
        angle=min((-math.pi+i*math.tau/32 for i in range(32)),key=mismatch)
        step=math.tau/32
        for _ in range(18):
            angle=min((max(-math.pi,min(math.pi,angle+d)) for d in (-step,0,step)),key=mismatch);step*=.5
        mismatch(angle)
        if context.scene.tool_settings.use_keyframe_insert_auto:
            ik.keyframe_insert('pole_angle',group=chain[1].name)
    for bone in rig.pose.bones:
        target=bone if hasattr(bone,"select") else bone.bone
        target.select=False
    for bone in selected:
        target=bone if hasattr(bone,"select") else bone.bone
        target.select=True
        rig.data.bones.active=bone.bone
        if context.scene.tool_settings.use_keyframe_insert_auto:
            bone.keyframe_insert('location',group=bone.name)
            bone.keyframe_insert('rotation_quaternion' if bone.rotation_mode=='QUATERNION' else 'rotation_euler',group=bone.name)
            bone.keyframe_insert('scale',group=bone.name)
    if context.scene.tool_settings.use_keyframe_insert_auto:
        props.keyframe_insert(f'["{limb}_FK_IK{S}"]',group='PROPERTIES')


def _prop_row(layout, props_bone, key):
    if key not in props_bone:
        return
    row = layout.row()
    split = row.split(align=True, factor=0.68)
    split.row(align=True).label(text=key, translate=False)
    split.row(align=True).prop(props_bone, f'[{json.dumps(key)}]', text='', slider=True)


def render_rig_ui_script(rig):
    """Build a self-contained Item-tab UI script matching custom_rig_ui.py."""
    rig_id = rig.data.get('rig_id', 'j0hn$@mb0007')
    title = rig.name.removesuffix('_RIG').replace('_', ' ').title() + ' Rig UI'
    shared = '\n\n'.join((
        f'COLLECTION_GROUPS = {COLLECTION_GROUPS!r}',
        inspect.getsource(visible_collections),
        inspect.getsource(draw_collections),
        inspect.getsource(snap),
    ))
    return f'''"""Auto-generated standalone MetaMorphosis Body Rig UI (Item tab)."""
import json
import math
import bpy
from mathutils import Matrix

RIG_ID = {rig_id!r}

{shared}


def _has_rig(context):
    o = context.active_object
    return o is not None and o.type == 'ARMATURE' and o.data.get('rig_id') == RIG_ID


def _prop_row(layout, props_bone, key):
    if key not in props_bone:
        return
    row = layout.row()
    split = row.split(align=True, factor=0.68)
    split.row(align=True).label(text=key, translate=False)
    split.row(align=True).prop(props_bone, f'[{{json.dumps(key)}}]', text='', slider=True)


class MM_PT_baked_rigui(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'
    bl_label = {title!r}
    bl_idname = 'MM_PT_baked_rigui'

    @classmethod
    def poll(cls, context):
        return _has_rig(context)

    def draw(self, context):
        draw_collections(self.layout, context.active_object)


class MM_PT_baked_customprops(bpy.types.Panel):
    bl_category = 'Item'
    bl_label = 'Rig Properties'
    bl_idname = 'MM_PT_baked_customprops'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {{'DEFAULT_CLOSED'}}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return _has_rig(context) and 'PROPERTIES' in o.pose.bones

    def draw_header(self, context):
        self.layout.label(icon='TOOL_SETTINGS')

    def draw(self, context):
        pass


class MM_PT_baked_torso_props(bpy.types.Panel):
    bl_category = 'Item'
    bl_label = 'Torso Properties'
    bl_idname = 'MM_PT_baked_torso_props'
    bl_parent_id = 'MM_PT_baked_customprops'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {{'DEFAULT_CLOSED'}}

    def draw_header(self, context):
        self.layout.label(icon='BONE_DATA')

    def draw(self, context):
        props = context.active_object.pose.bones['PROPERTIES']
        box = self.layout.box()
        col = box.column(align=True)
        for key in ('HEAD_FOLLOW', 'NECK_FOLLOW'):
            _prop_row(col, props, key)


class MM_PT_baked_arm_props(bpy.types.Panel):
    bl_category = 'Item'
    bl_label = 'Arm Properties'
    bl_idname = 'MM_PT_baked_arm_props'
    bl_parent_id = 'MM_PT_baked_customprops'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {{'DEFAULT_CLOSED'}}

    def draw_header(self, context):
        self.layout.label(icon='VIEW_PAN')

    def draw(self, context):
        props = context.active_object.pose.bones['PROPERTIES']
        for prefix in ('ARM_FK_IK', 'ARM_ROT_FOLLOW', 'ARM_IK_PARENTS', 'ARM_IK_STRETCH'):
            box = self.layout.box()
            col = box.column(align=True)
            for side in ('L', 'R'):
                _prop_row(col, props, f'{{prefix}}.{{side}}')
        self.layout.label(text='Parents: Root / Torso / Pelvis / Chest / Head')


class MM_PT_baked_leg_props(bpy.types.Panel):
    bl_category = 'Item'
    bl_label = 'Leg Properties'
    bl_idname = 'MM_PT_baked_leg_props'
    bl_parent_id = 'MM_PT_baked_customprops'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {{'DEFAULT_CLOSED'}}

    def draw_header(self, context):
        self.layout.label(icon='POSE_HLT')

    def draw(self, context):
        props = context.active_object.pose.bones['PROPERTIES']
        for prefix in ('LEG_FK_IK', 'LEG_ROT_FOLLOW', 'LEG_IK_PARENTS', 'LEG_IK_STRETCH'):
            box = self.layout.box()
            col = box.column(align=True)
            for side in ('L', 'R'):
                _prop_row(col, props, f'{{prefix}}.{{side}}')
        self.layout.label(text='Parents: Root / Foot / Torso / Pelvis')


class _BakedSnap:
    bl_options = {{'REGISTER', 'UNDO'}}

    @classmethod
    def poll(cls, context):
        return _has_rig(context)

    def execute(self, context):
        snap(context.active_object, self.limb, self.side, self.mode, context)
        return {{'FINISHED'}}


class MM_OT_baked_ik_fk_arm(_BakedSnap, bpy.types.Operator):
    bl_idname = 'mm_baked_rigui.ik_fk_arm'
    bl_label = 'Match Arm to IK'
    limb = 'ARM'
    mode = 'IK'
    side: bpy.props.StringProperty(default='L')


class MM_OT_baked_fk_ik_arm(_BakedSnap, bpy.types.Operator):
    bl_idname = 'mm_baked_rigui.fk_ik_arm'
    bl_label = 'Match Arm to FK'
    limb = 'ARM'
    mode = 'FK'
    side: bpy.props.StringProperty(default='L')


class MM_OT_baked_ik_fk_leg(_BakedSnap, bpy.types.Operator):
    bl_idname = 'mm_baked_rigui.ik_fk_leg'
    bl_label = 'Match Leg to IK'
    limb = 'LEG'
    mode = 'IK'
    side: bpy.props.StringProperty(default='L')


class MM_OT_baked_fk_ik_leg(_BakedSnap, bpy.types.Operator):
    bl_idname = 'mm_baked_rigui.fk_ik_leg'
    bl_label = 'Match Leg to FK'
    limb = 'LEG'
    mode = 'FK'
    side: bpy.props.StringProperty(default='L')


class MM_PT_baked_snap(bpy.types.Panel):
    bl_category = 'Item'
    bl_label = 'Snap Utilities'
    bl_idname = 'MM_PT_baked_snap'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {{'DEFAULT_CLOSED'}}

    @classmethod
    def poll(cls, context):
        return _has_rig(context) and 'PROPERTIES' in context.active_object.pose.bones

    def draw_header(self, context):
        self.layout.label(icon='SNAP_ON')

    def draw(self, context):
        col = self.layout.column(align=True)
        for op_name, label in (
            ('mm_baked_rigui.ik_fk_arm', 'Arm {{side}} FK > IK'),
            ('mm_baked_rigui.fk_ik_arm', 'Arm {{side}} IK > FK'),
        ):
            row = col.row(align=True)
            for side in ('L', 'R'):
                row.operator(op_name, text=label.format(side=side), icon='SNAP_ON').side = side
        col.separator(factor=0.6)
        for op_name, label in (
            ('mm_baked_rigui.ik_fk_leg', 'Leg {{side}} FK > IK'),
            ('mm_baked_rigui.fk_ik_leg', 'Leg {{side}} IK > FK'),
        ):
            row = col.row(align=True)
            for side in ('L', 'R'):
                row.operator(op_name, text=label.format(side=side), icon='SNAP_ON').side = side


CLASSES = (
    MM_PT_baked_rigui,
    MM_PT_baked_customprops,
    MM_PT_baked_torso_props,
    MM_PT_baked_arm_props,
    MM_PT_baked_leg_props,
    MM_PT_baked_snap,
    MM_OT_baked_ik_fk_arm,
    MM_OT_baked_fk_ik_arm,
    MM_OT_baked_ik_fk_leg,
    MM_OT_baked_fk_ik_leg,
)


def register():
    for cls in CLASSES:
        bl_name = cls.__name__
        if '.' in getattr(cls, 'bl_idname', ''):
            prefix, op = cls.bl_idname.split('.', 1)
            bl_name = f'{{prefix.upper()}}_OT_{{op}}'
        existing = getattr(bpy.types, bl_name, None) or getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            bpy.utils.unregister_class(existing)
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            bpy.utils.unregister_class(existing)


if __name__ == '__main__':
    register()
'''


def bake_rig_ui(rig, run=True):
    """Create/update the standalone Item-tab Rig UI Text datablock."""
    name = 'MetaMorphosis_Custom_RigUI.py'
    text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    text.clear()
    source = render_rig_ui_script(rig)
    text.write(source)
    text.use_module = True
    if run:
        exec(compile(source, name, 'exec'), {'__name__': '__main__'})
    return text


class MM_OT_bake_rig_ui(bpy.types.Operator):
    bl_idname = 'metamorphosis.bake_rig_ui'
    bl_label = 'Bake Rig UI'
    bl_description = 'Create an embedded Python script so the Control Rig UI appears in the Item tab even when MetaMorphosis is disabled'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        o = context.object
        if o and o.type == 'MESH':
            o = next((m.object for m in o.modifiers if m.type == 'ARMATURE' and m.object), None)
        return o is not None and o.type == 'ARMATURE' and bool(o.get('mm_body_converter'))

    def execute(self, context):
        rig = context.object
        if rig and rig.type == 'MESH':
            rig = next((m.object for m in rig.modifiers if m.type == 'ARMATURE' and m.object), None)
        if rig is None:
            return {'CANCELLED'}
        text = bake_rig_ui(rig, run=True)
        self.report({'INFO'}, f'Baked standalone UI script "{text.name}" (Item tab)')
        return {'FINISHED'}


class _Snap:
    bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context):
        o=context.object
        return o is not None and o.type=='ARMATURE' and o.data.get('rig_id')=='j0hn$@mb0007'
    def execute(self,context):
        snap(context.object,self.limb,self.side,self.mode,context)
        return {'FINISHED'}


class JOHN_RAMBO_OT_ik_fk_arm(_Snap,bpy.types.Operator):
    bl_idname='john_rambo.ik_fk_arm';bl_label='Match Arm to IK';limb='ARM';mode='IK'
    side:bpy.props.StringProperty(default='L')
class JOHN_RAMBO_OT_fk_ik_arm(_Snap,bpy.types.Operator):
    bl_idname='john_rambo.fk_ik_arm';bl_label='Match Arm to FK';limb='ARM';mode='FK'
    side:bpy.props.StringProperty(default='L')
class JOHN_RAMBO_OT_ik_fk_leg(_Snap,bpy.types.Operator):
    bl_idname='john_rambo.ik_fk_leg';bl_label='Match Leg to IK';limb='LEG';mode='IK'
    side:bpy.props.StringProperty(default='L')
class JOHN_RAMBO_OT_fk_ik_leg(_Snap,bpy.types.Operator):
    bl_idname='john_rambo.fk_ik_leg';bl_label='Match Leg to FK';limb='LEG';mode='FK'
    side:bpy.props.StringProperty(default='L')


CLASSES=(
    MM_OT_bake_rig_ui,
    JOHN_RAMBO_OT_ik_fk_arm,
    JOHN_RAMBO_OT_fk_ik_arm,
    JOHN_RAMBO_OT_ik_fk_leg,
    JOHN_RAMBO_OT_fk_ik_leg,
)
