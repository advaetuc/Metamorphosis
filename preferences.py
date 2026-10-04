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
            "Folder that contains dna.py and the compiled DNA/RigLogic modules (the 'bindings' folder of "
            "Poly Hammer's Character DNA add-on). Leave empty to use <addon>/bindings or auto-detect"
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
        layout.label(text="The imported rig is plain Blender drivers and works without this add-on.", icon="INFO")


CLASSES = (MM_Preferences,)
