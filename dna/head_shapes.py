"""Custom bone shapes and colors for the OG MetaHuman Face Rig.

Applies the custom widget meshes and color schemes from New_Shapes_OG_Face_Rig.blend
to the imported MetaHuman head rig.
"""

from __future__ import annotations

import logging
from pathlib import Path
import bpy

from ..core.constants import ASSETS_DIR, DEFAULT_FACE_RIG_DIR, NEW_SHAPES_OG_FACE_RIG_FILE_NAME
from ..core import organization

logger = logging.getLogger(__name__)

COLOR_BLUE = (0.2980392, 0.4235294, 1.0)
COLOR_RED = (1.0, 0.0901961, 0.0470588)
COLOR_YELLOW = (0.9568628, 0.7882354, 0.0470588)
WIDGET_PREFIX = "WGT-METAHUMAN_HEAD_RIG_FACIAL_C_12IPV_NeckB2"


def find_head_shapes_file() -> Path | None:
    """Find New_Shapes_OG_Face_Rig.blend in assets or the training data directory."""
    bundled = ASSETS_DIR / NEW_SHAPES_OG_FACE_RIG_FILE_NAME
    if bundled.is_file():
        return bundled
    external = DEFAULT_FACE_RIG_DIR / NEW_SHAPES_OG_FACE_RIG_FILE_NAME
    if external.is_file():
        return external
    return None


def _get_bone_color(name: str) -> tuple[float, float, float]:
    """Determine bone color: Blue for Left, Red for Right, Yellow for Center/Spine."""
    upper = name.upper()
    if "_L_" in upper or upper.endswith(("_L", ".L")) or upper.startswith("FACIAL_L_"):
        return COLOR_BLUE
    if "_R_" in upper or upper.endswith(("_R", ".R")) or upper.startswith("FACIAL_R_"):
        return COLOR_RED
    return COLOR_YELLOW


def _set_bone_color(pb: bpy.types.PoseBone, rgb: tuple[float, float, float]) -> None:
    pb.color.palette = "CUSTOM"
    pb.color.custom.normal = rgb
    pb.color.custom.select = tuple(v + (1.0 - v) * 0.4 for v in rgb)
    pb.color.custom.active = tuple(v + (1.0 - v) * 0.7 for v in rgb)


def apply_head_rig_shapes(rig: bpy.types.Object, collection: bpy.types.Collection | None = None) -> int:
    """Append widget shapes from New_Shapes_OG_Face_Rig.blend and apply to rig pose bones."""
    blend_path = find_head_shapes_file()
    if not blend_path:
        logger.warning("New_Shapes_OG_Face_Rig.blend not found; skipping custom shapes")
        return 0

    if collection is None:
        char_col_name = rig.get("mm_character_collection")
        if char_col_name and char_col_name in bpy.data.collections:
            char_col = bpy.data.collections[char_col_name]
            wgt_col_name = f"WGTS_{rig.name}"
            wgt_col = organization.child_collection(char_col, wgt_col_name)
        else:
            wgt_col = bpy.context.scene.collection
    else:
        wgt_col = collection

    # Check available widget objects in blend file
    needed_widgets: dict[str, str] = {}
    for pb in rig.pose.bones:
        wgt_name = f"{WIDGET_PREFIX}_{pb.name}" if pb.name != "FACIAL_C_12IPV_NeckB2" else WIDGET_PREFIX
        needed_widgets[pb.name] = wgt_name

    existing_objs = bpy.data.objects
    to_load = [w for w in set(needed_widgets.values()) if w not in existing_objs]

    if to_load:
        with bpy.data.libraries.load(str(blend_path), link=False) as (src, dst):
            available = set(src.objects)
            dst.objects = [w for w in to_load if w in available]

        for obj in dst.objects:
            if obj is not None:
                if obj.name not in wgt_col.objects:
                    wgt_col.objects.link(obj)
                obj.hide_viewport = True
                obj.hide_render = True
                obj.hide_select = True
                if hasattr(obj, "use_fake_user"):
                    obj.use_fake_user = False

    applied_count = 0
    for pb in rig.pose.bones:
        wgt_name = needed_widgets.get(pb.name)
        wgt_obj = bpy.data.objects.get(wgt_name) if wgt_name else None
        if wgt_obj:
            pb.custom_shape = wgt_obj
            pb.custom_shape_scale_xyz = (0.05, 0.05, 0.05)
            pb.use_custom_shape_bone_size = True
            applied_count += 1

        color = _get_bone_color(pb.name)
        _set_bone_color(pb, color)

    if applied_count > 0:
        rig.display_type = "WIRE"

    logger.info("Applied custom shapes & colors to %d bones on %s", applied_count, rig.name)
    return applied_count
