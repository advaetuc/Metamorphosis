"""Sidebar panel (3D Viewport > N panel > MetaMorphosis)."""

import bpy
from bpy.props import FloatVectorProperty

from . import bake, mocap
from .constants import LABEL


class MM_PT_panel(bpy.types.Panel):
    bl_label = "MetaMorphosis DNA Addon"
    bl_idname = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL

    def draw_header(self, context):
        self.layout.label(text="", icon="ARMATURE_DATA")

    def draw_header_preset(self, context):
        self.layout.label(text="by TheClayMan3D")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        box = layout.box()
        box.label(text="Character Setup", icon='IMPORT')
        box.prop(context.scene, 'mm_texture_folder', text="Texture Source")
        if bake.find_baked_rig(context):
            box.operator('metamorphosis.setup_materials', text="Apply Materials", icon='MATERIAL')
        row = layout.row(align=True)
        row.scale_y = 1.35
        row.operator("metamorphosis.import_dna", text="Import DNA", icon="FILE_FOLDER")
        row.operator("metamorphosis.remove_all", text="Remove", icon="TRASH")

        rig = bake.find_baked_rig(context)
        if rig is None:
            box = layout.box()
            box.label(text="Ready for your character", icon="INFO")
            box.label(text="Import a MetaHuman DNA file to begin.")
            return
        box = layout.box()
        box.label(text="Active Character", icon="ARMATURE_DATA")
        box.label(text=rig.name, icon="OUTLINER_OB_ARMATURE")
        box.label(text=f"{rig.get('mm_quality', 'LITE').title()} rig · Native drivers", icon="DRIVER")
        if rig.get("mm_stats"):
            for part in str(rig["mm_stats"]).split(", "):
                box.label(text=part, icon="DOT")
        layout.separator()
        box = layout.box()
        box.label(text="Rig Controls", icon="POSE_HLT")
        row = box.row(align=True)
        op = row.operator("metamorphosis.toggle_rig", text="Enable", icon="PLAY")
        op.enable = True
        op = row.operator("metamorphosis.toggle_rig", text="Disable", icon="PAUSE")
        op.enable = False
        box.operator("metamorphosis.rebuild", text="Rebuild Drivers", icon="FILE_REFRESH")


class MM_PT_customization(bpy.types.Panel):
    bl_label = "Customization"
    bl_idname = "MM_PT_customization"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.label(text="Match the control board to your workspace.", icon="INFO")
        layout.prop(context.scene, "mm_face_board_color", text="Control Colour")
        layout.operator("metamorphosis.apply_face_board_color", icon="COLORSET_01_VEC")


class MM_PT_diagnostics(bpy.types.Panel):
    bl_label = "Diagnostics"
    bl_idname = "MM_PT_diagnostics"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="TOOL_SETTINGS")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column(align=True)
        col.enabled = bake.find_baked_rig(context) is not None
        col.operator("metamorphosis.validate", text="Check Drivers", icon="CHECKMARK")
        col.operator("metamorphosis.benchmark", text="Measure Speed", icon="TIME")
        if bpy.data.texts.get("MetaMorphosis Report"):
            layout.separator()
            layout.label(text="Text Editor → MetaMorphosis Report", icon="TEXT")


class MM_PT_live_link(bpy.types.Panel):
    bl_label = "Live Link"
    bl_idname = "MM_PT_live_link"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = LABEL
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='OUTLINER_DATA_CAMERA')

    def draw(self, context):
        layout = self.layout
        settings = context.scene.mm_capture
        live = mocap._live
        recording = bool(live and live['recording'])
        col = layout.column()
        col.enabled = not live and not mocap._job
        col.prop(settings, 'target')
        col.prop(settings, 'host')
        col.prop(settings, 'port')
        col.prop(settings, 'subject')
        info = layout.box()
        info.label(text="Epic Live Link Face · ARKit", icon='INFO')
        info.label(text="Send the phone stream to this computer.")
        layout.operator('metamorphosis.live_stop' if live else 'metamorphosis.live_start',
                        icon='PAUSE' if live else 'PLAY')
        layout.label(text=settings.status)
        if settings.last_take:
            layout.label(text=f"Last take: {settings.last_take}", icon='ACTION')
        col = layout.column()
        col.enabled = not recording
        col.prop(settings, 'mirror')
        col.prop(settings, 'gain')
        col.prop(settings, 'lips_gain')
        col.prop(settings, 'brow_gain')
        col.prop(settings, 'smoothing')
        col.prop(settings, 'extreme')
        col.prop(settings, 'take_name')
        col.prop(settings, 'end_mode')
        row = layout.row(align=True)
        row.enabled = bool(live)
        row.operator('metamorphosis.record_stop' if recording else 'metamorphosis.record_start',
                     icon='PAUSE' if recording else 'REC')
        layout.label(text="New take · starts at the current frame")


class MM_PT_video(bpy.types.Panel):
    bl_label = "Video to Mocap"
    bl_idname = "MM_PT_video"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = LABEL
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='SEQUENCE')

    def draw(self, context):
        layout = self.layout
        settings = context.scene.mm_capture
        col = layout.column()
        col.enabled = not mocap._job and not mocap._live
        col.prop(settings, 'target')
        col.prop(settings, 'video')
        col.prop(settings, 'take_name')
        col.prop(settings, 'mirror')
        col.prop(settings, 'gain')
        col.prop(settings, 'lips_gain')
        col.prop(settings, 'brow_gain')
        col.prop(settings, 'smoothing')
        col.prop(settings, 'extreme')
        col.operator('metamorphosis.video_process', icon='ACTION')
        if mocap._job:
            layout.operator('metamorphosis.video_cancel', icon='CANCEL')
        layout.label(text=settings.video_status)
        box = layout.box()
        box.label(text="Video Tools", icon='PREFERENCES')
        box.label(text="One-time local setup", icon='INFO')
        if mocap.video_ready(mocap.video_folder(settings)):
            box.label(text='Video tools installed',icon='CHECKMARK')
        else:
            box.operator('metamorphosis.video_setup', icon='IMPORT')
        box.prop(settings, 'video_advanced')
        if settings.video_advanced:
            box.prop(settings, 'video_python')
            box.prop(settings, 'video_folder')
            box.operator('metamorphosis.video_setup',text='Repair Video Tools',icon='FILE_REFRESH').repair = True
        layout.label(text="Videos are processed on this computer.")


class MM_OT_apply_face_board_color(bpy.types.Operator):
    bl_idname = "metamorphosis.apply_face_board_color"
    bl_label = "Apply Face Board Colour"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import bake
        rig = bake.find_baked_rig(context)
        if rig is None:
            self.report({'ERROR'}, 'Select an imported MetaHuman rig first')
            return {'CANCELLED'}
        board = bpy.data.objects.get(str(rig.get(bake.RIG_KEY_BOARD_OBJECT, '')))
        if board is None or board.type != 'ARMATURE':
            self.report({'ERROR'}, 'The face board armature is missing')
            return {'CANCELLED'}
        rgb = tuple(context.scene.mm_face_board_color)
        normal = rgb
        select = tuple(c+(1-c)*.4 for c in rgb)
        active = tuple(c+(1-c)*.7 for c in rgb)
        changed = 0
        for bone in board.pose.bones:
            if not bone.name.startswith('CTRL_') or bone.color is None:
                continue
            bone.color.palette = 'CUSTOM'
            bone.color.custom.normal = normal
            bone.color.custom.select = select
            bone.color.custom.active = active
            changed += 1
        self.report({'INFO'}, f'Updated {changed} face-board controls')
        return {'FINISHED'}


CLASSES = (MM_PT_panel, MM_PT_customization, MM_OT_apply_face_board_color, MM_PT_live_link, MM_PT_video, MM_PT_diagnostics)


def register():
    bpy.types.Scene.mm_face_board_color = FloatVectorProperty(
        name='Face Board Colour', subtype='COLOR', size=3,
        min=0.0, max=1.0, default=(0.956, 0.788, 0.047),
        description='Color used for all face-board control bones',
    )


def unregister():
    del bpy.types.Scene.mm_face_board_color
