"""MetaMorphosis - MetaHuman head DNA importer that bakes RigLogic into Blender drivers.

Everything the importer creates is plain Blender data (bones, meshes, shape keys, custom
properties and drivers), so the face board keeps working after this add-on is disabled or removed.
"""

import bpy

from . import bodyrig, operators, preferences, ui

_classes = (*preferences.CLASSES, *operators.CLASSES, *bodyrig.CLASSES, *ui.CLASSES)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mm_body_settings = bpy.props.PointerProperty(type=bodyrig.MM_BodySettings)
    bpy.types.TOPBAR_MT_file_import.append(operators.menu_import)


def unregister():
    del bpy.types.Scene.mm_body_settings
    bpy.types.TOPBAR_MT_file_import.remove(operators.menu_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
