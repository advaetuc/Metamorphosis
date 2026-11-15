"""MetaMorphosis - MetaHuman head DNA importer that bakes RigLogic into Blender drivers.

Everything the importer creates is plain Blender data (bones, meshes, shape keys, custom
properties and drivers), so the face board keeps working after this add-on is disabled or removed.
"""

import sys
from pathlib import Path
import bpy

_ROOT = Path(__file__).resolve().parent
_subpackages = [_ROOT / name for name in ("core", "dna", "riglogic", "sculpting", "capture", "body")]
for _p in _subpackages:
    _s = str(_p)
    if _s not in __path__:
        __path__.append(_s)

# Import subpackages
from . import core
from . import dna
from . import riglogic
from . import sculpting
from . import capture
from . import body

# Expose modules at package level for 100% backward compatibility
from .body import (
    body_converter, body_driverplan, body_fields, body_geometry,
    body_merge, body_rbf, body_refine, body_remap, body_rig, body_snap
)
from .capture import (
    mha_live, mha_mapping, mocap, mocap_core, mocap_mapping, video_worker
)
from .core import (
    assemble, camera, cleanup, constants, grooms, lighting, materials, operators, organization,
    preferences, progress_ui, ui
)
from .dna import (
    dnaio, faceboard, head_shapes, import_job, import_worker, importer
)
from .riglogic import (
    bake, bakeplan, exprplan, logicmodel, native_sums, optimize, pipeline, verify
)
from .sculpting import (
    dna_export, expression_dna, expression_sculpt, sculpt, sculpt_field
)

# Populate sys.modules for any direct imports like `import metamorphosis.logicmodel`
_prefix = __name__ + "."
for _name in (
    "assemble", "camera", "grooms", "lighting", "head_shapes",
    "body_converter", "body_driverplan", "body_fields", "body_geometry",
    "body_merge", "body_rbf", "body_refine", "body_remap", "body_rig", "body_snap",
    "mha_live", "mha_mapping", "mocap", "mocap_core", "mocap_mapping", "video_worker",
    "cleanup", "constants", "materials", "operators", "organization",
    "preferences", "progress_ui", "ui",
    "dnaio", "faceboard", "import_job", "import_worker", "importer",
    "bake", "bakeplan", "exprplan", "logicmodel", "native_sums", "optimize", "pipeline", "verify",
    "dna_export", "expression_dna", "expression_sculpt", "sculpt", "sculpt_field",
):
    if _name in locals():
        sys.modules[_prefix + _name] = locals()[_name]

_classes = (
    *preferences.CLASSES,
    *operators.CLASSES,
    *mocap.CLASSES,
    *materials.CLASSES,
    *ui.CLASSES,
    *lighting.CLASSES,
    ui.MM_PT_face_board_color,
    *grooms.CLASSES,
    *assemble.CLASSES,
    *body_rig.CLASSES,
    *body_merge.CLASSES,
    *body_converter.CLASSES,
    *body_snap.CLASSES,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    mocap.register()
    materials.register()
    body_rig.register()
    ui.register()
    lighting.register()
    grooms.register()
    assemble.register()
    bpy.types.TOPBAR_MT_file_import.append(operators.menu_import)


def unregister():
    import_job.shutdown()
    progress_ui.end()
    assemble.unregister()
    grooms.unregister()
    lighting.unregister()
    ui.unregister()
    body_rig.unregister()
    materials.unregister()
    mocap.unregister()
    bpy.types.TOPBAR_MT_file_import.remove(operators.menu_import)
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
