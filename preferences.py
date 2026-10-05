"""Add-on preferences (no ``from __future__ import annotations`` here: Blender needs real annotations)."""

import bpy

from bpy.props import StringProperty

from .constants import ADDON_ID, LABEL


class MM_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    bindings_folder: StringProperty(  # type: ignore[valid-type]
        name="OpenRigLogic Bindings Folder",
        subtype="DIR_PATH",
        default="",
        description=(
            "The 'bindings' folder of Poly Hammer's Character DNA add-on, or any folder above it. Sub-folders are "
            "searched for dna.py and the compiled _py3dna / _py3riglogic files. Leave empty to auto-detect"
        ),
    )
    face_board_file: StringProperty(  # type: ignore[valid-type]
        name="Face Board File",
        subtype="FILE_PATH",
        default="",
        description="face_board.blend that contains the face board armature and its bone widgets",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"{LABEL} needs two things only while importing:")
        layout.prop(self, "face_board_file")
        layout.prop(self, "bindings_folder")
        layout.operator("metamorphosis.test_bindings", icon="CHECKMARK")
        layout.label(text="The imported rig is plain Blender drivers and works without this add-on.", icon="INFO")


CLASSES = (MM_Preferences,)
