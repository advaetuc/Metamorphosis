"""MetaMorphosis - MetaHuman head DNA importer that bakes RigLogic into Blender drivers.

Everything the importer creates is plain Blender data (bones, meshes, shape keys, custom
properties and drivers), so the face board keeps working after this add-on is disabled or removed.
"""

import bpy

from . import operators, preferences, ui

_classes = (*preferences.CLASSES, *operators.CLASSES, *ui.CLASSES)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(operators.menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(operators.menu_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
