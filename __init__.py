"""MetaMorphosis - MetaHuman head DNA importer that bakes RigLogic into Blender drivers.

Everything the importer creates is plain Blender data (bones, meshes, shape keys, custom
properties and drivers), so the face board keeps working after this add-on is disabled or removed.
"""

import bpy

from . import operators, preferences, mocap, materials, sculpt, expression_sculpt, ui

_classes = (*preferences.CLASSES, *operators.CLASSES, *mocap.CLASSES, *materials.CLASSES, *ui.CLASSES, *sculpt.CLASSES, *expression_sculpt.CLASSES)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    mocap.register()
    materials.register()
    sculpt.register()
    bpy.types.TOPBAR_MT_file_import.append(operators.menu_import)


def unregister():
    sculpt.unregister()
    materials.unregister()
    mocap.unregister()
    bpy.types.TOPBAR_MT_file_import.remove(operators.menu_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
