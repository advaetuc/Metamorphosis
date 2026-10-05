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

    def draw(self, context):
        layout = self.layout
        layout.operator("metamorphosis.import_dna", icon="IMPORT")

        rig = bake.find_baked_rig(context)
        box = layout.box()
        if rig is None:
            box.label(text="No baked rig in this scene", icon="INFO")
            return
        box.label(text=rig.name, icon="ARMATURE_DATA")
        row = box.row(align=True)
        op = row.operator("metamorphosis.toggle_rig", text="Enable", icon="PLAY")
        op.enable = True
        op = row.operator("metamorphosis.toggle_rig", text="Disable", icon="PAUSE")
        op.enable = False
        stats = rig.get("mm_stats")
        if stats:
            box.label(text=f"{rig.get('mm_quality', '?').title()}: {stats}")
        box.operator("metamorphosis.rebuild", icon="FILE_REFRESH")
        box.operator("metamorphosis.validate", icon="CHECKMARK")
        box.operator("metamorphosis.benchmark", icon="TIME")
        body_box = layout.box()
        body_box.label(text="Combine Body Rig", icon="ARMATURE_DATA")
        settings = context.scene.mm_body_settings
        body_box.prop(settings, "body")
        if settings.body:
            body_box.prop_search(settings, "attach_bone", settings.body.data, "bones")
        body_box.label(text="Align rest poses before combining.")
        body_box.operator("metamorphosis.combine_body")
        if bpy.data.texts.get("MetaMorphosis Report"):
            box.label(text="Details: Text Editor > MetaMorphosis Report")


CLASSES = (MM_PT_panel,)
