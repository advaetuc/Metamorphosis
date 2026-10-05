"""Sidebar panel (3D Viewport > N panel > MetaMorphosis)."""

import bpy

from . import bake
from .constants import LABEL


class MM_PT_panel(bpy.types.Panel):
    bl_label = LABEL
    bl_idname = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL

    def draw_header(self, context):
        self.layout.label(text="", icon="ARMATURE_DATA")

    def draw(self, context):
        layout = self.layout
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


CLASSES = (MM_PT_panel, MM_PT_diagnostics)
