"""Sidebar panel (3D Viewport > N panel > MetaMorphosis)."""

import bpy

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
        box = layout.box()
        box.label(text="Materials and Textures", icon='MATERIAL')
        box.prop(context.scene, 'mm_texture_folder')
        if bake.find_baked_rig(context):
            box.operator('metamorphosis.setup_materials', icon='MATERIAL')
        row = layout.row(align=True)
        row.scale_y = 1.25
        row.operator("metamorphosis.import_dna", text="Import DNA", icon="IMPORT")
        row.operator("metamorphosis.remove_all", text="Remove All", icon="TRASH")

        rig = bake.find_baked_rig(context)
        if rig is None:
            layout.label(text="Import a DNA file to get started.", icon="INFO")
            return
        box = layout.box()
        box.label(text=rig.name, icon="ARMATURE_DATA")
        box.label(text=f"Native drivers · {rig.get('mm_quality', 'LITE').title()}", icon="DRIVER")
        if rig.get("mm_stats"):
            for part in str(rig["mm_stats"]).split(", "):
                box.label(text=part)
        layout.separator()
        layout.label(text="Rig Controls", icon="POSE_HLT")
        row = layout.row(align=True)
        op = row.operator("metamorphosis.toggle_rig", text="Enable", icon="PLAY")
        op.enable = True
        op = row.operator("metamorphosis.toggle_rig", text="Disable", icon="PAUSE")
        op.enable = False
        layout.operator("metamorphosis.rebuild", icon="FILE_REFRESH")


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
        layout.label(text="Live Link Face: ARKit mode", icon='INFO')
        layout.label(text="Set the phone's target to this PC's IP.")
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
        box = col.box()
        box.label(text="One-time setup", icon='PREFERENCES')
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


CLASSES = (MM_PT_panel, MM_PT_live_link, MM_PT_video, MM_PT_diagnostics)
