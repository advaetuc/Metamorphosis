"""HDRI lighting setup and controls for MetaMorphosis."""

from __future__ import annotations

import logging
from pathlib import Path
import bpy
import bpy.utils.previews
from bpy_extras.io_utils import ImportHelper
from bpy.props import FloatProperty, EnumProperty, StringProperty

from .constants import HDRI_PREVIEWS_DIR, DEFAULT_HDRI_DIR, ASSETS_DIR

logger = logging.getLogger(__name__)

_hdri_previews = None

BUILTIN_HDRIS = {
    "HDRI_4K": {
        "name": "HDRI 4K",
        "filename": "HDRI_4K.exr",
        "desc": "High dynamic range environment (4K)",
    },
    "studio_kontrast_01_4k": {
        "name": "Studio Kontrast 01",
        "filename": "studio_kontrast_01_4k.exr",
        "desc": "Studio Kontrast 01 high contrast lighting (4K)",
    },
    "studio_kontrast_04_4k": {
        "name": "Studio Kontrast 04",
        "filename": "studio_kontrast_04_4k.hdr",
        "desc": "Studio Kontrast 04 soft studio lighting (4K)",
    },
    "studio_small_09_4k": {
        "name": "Studio Small 09",
        "filename": "studio_small_09_4k.hdr",
        "desc": "Studio Small 09 neutral character lighting (4K)",
    },
}


def find_builtin_hdri_file(key: str) -> Path | None:
    """Find the HDRI file on disk."""
    info = BUILTIN_HDRIS.get(key)
    if not info:
        return None
    filename = info["filename"]
    # Check default directory
    p = DEFAULT_HDRI_DIR / filename
    if p.is_file():
        return p
    # Check assets
    p = ASSETS_DIR / "hdri" / filename
    if p.is_file():
        return p
    return None


def apply_hdri_to_world(context: bpy.types.Context, filepath: Path, intensity: float = 1.0) -> bool:
    """Load HDRI image and wire into the World node tree."""
    if not filepath.is_file():
        logger.warning("HDRI file not found: %s", filepath)
        return False

    world = context.scene.world
    if not world:
        world = bpy.data.worlds.new("MetaMorphosis_World")
        context.scene.world = world

    try:
        world.use_nodes = True
    except Exception:
        pass

    nodes = world.node_tree.nodes
    links = world.node_tree.links

    # Get or create environment node
    env_node = next((n for n in nodes if n.type == "TEX_ENVIRONMENT"), None)
    if not env_node:
        env_node = nodes.new("ShaderNodeTexEnvironment")
        env_node.location = (-300, 300)

    # Load image
    img = bpy.data.images.load(str(filepath), check_existing=True)
    env_node.image = img

    # Get or create background node
    bg_node = next((n for n in nodes if n.type == "BACKGROUND"), None)
    if not bg_node:
        bg_node = nodes.new("ShaderNodeBackground")
        bg_node.location = (0, 300)
    bg_node.inputs["Strength"].default_value = intensity

    # Get or create output node
    out_node = next((n for n in nodes if n.type == "OUTPUT_WORLD"), None)
    if not out_node:
        out_node = nodes.new("ShaderNodeOutputWorld")
        out_node.location = (200, 300)

    # Wire nodes
    links.new(env_node.outputs["Color"], bg_node.inputs["Color"])
    links.new(bg_node.outputs["Background"], out_node.inputs["Surface"])

    return True


def update_hdri_intensity(self, context):
    """Update background strength when intensity slider is moved."""
    world = context.scene.world
    if not world or not world.node_tree:
        return
    bg_node = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg_node:
        bg_node.inputs["Strength"].default_value = self.mm_hdri_intensity


def update_hdri_selection(self, context):
    """Apply the selected HDRI when user picks from dropdown."""
    choice = self.mm_hdri_selection
    if choice == "CUSTOM":
        path_str = self.mm_custom_hdri_path
        if path_str:
            p = Path(path_str)
            if p.is_file():
                apply_hdri_to_world(context, p, self.mm_hdri_intensity)
    elif choice in BUILTIN_HDRIS:
        p = find_builtin_hdri_file(choice)
        if p:
            apply_hdri_to_world(context, p, self.mm_hdri_intensity)


def get_hdri_enum_items(self, context):
    """Dynamic enum items with icons from the preview collection."""
    global _hdri_previews
    items = []
    p = _hdri_previews

    for i, (key, info) in enumerate(BUILTIN_HDRIS.items()):
        icon_id = p[key].icon_id if p and key in p else 0
        items.append((key, info["name"], info["desc"], icon_id, i))

    if hasattr(context.scene, "mm_custom_hdri_path") and context.scene.mm_custom_hdri_path:
        icon_id = p["CUSTOM"].icon_id if p and "CUSTOM" in p else 0
        items.append(("CUSTOM", "Custom HDRI", "User imported custom HDRI", icon_id, len(items)))

    return items


class MM_OT_import_hdri(bpy.types.Operator, ImportHelper):
    """Import a custom HDRI (.hdr / .exr) for scene lighting"""

    bl_idname = "metamorphosis.import_hdri"
    bl_label = "Import HDRI"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.hdr;*.exr", options={"HIDDEN"})

    def execute(self, context):
        global _hdri_previews
        p = Path(self.filepath)
        if not p.is_file():
            self.report({"ERROR"}, "Selected file does not exist")
            return {"CANCELLED"}

        context.scene.mm_custom_hdri_path = str(p)

        # Update preview thumbnail
        if _hdri_previews is not None:
            if "CUSTOM" in _hdri_previews:
                _hdri_previews.remove(_hdri_previews["CUSTOM"])
            try:
                _hdri_previews.load("CUSTOM", str(p), "IMAGE")
            except Exception:
                pass

        context.scene.mm_hdri_selection = "CUSTOM"
        apply_hdri_to_world(context, p, context.scene.mm_hdri_intensity)
        self.report({"INFO"}, f"Applied custom HDRI: {p.name}")
        return {"FINISHED"}


class MM_OT_clear_hdri(bpy.types.Operator):
    """Clear HDRI lighting and reset world to neutral background"""

    bl_idname = "metamorphosis.clear_hdri"
    bl_label = "Clear HDRI"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        world = context.scene.world
        if world and world.node_tree:
            nodes = world.node_tree.nodes
            env_node = next((n for n in nodes if n.type == "TEX_ENVIRONMENT"), None)
            if env_node:
                nodes.remove(env_node)
            bg_node = next((n for n in nodes if n.type == "BACKGROUND"), None)
            if bg_node:
                bg_node.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1.0)
                bg_node.inputs["Strength"].default_value = 1.0
        self.report({"INFO"}, "Cleared HDRI lighting")
        return {"FINISHED"}


class MM_PT_lighting(bpy.types.Panel):
    """Lighting settings dropdown panel inside Scene Settings"""

    bl_label = "Lighting"
    bl_idname = "MM_PT_lighting"
    bl_parent_id = "MM_PT_scene_settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MetaMorphosis"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="LIGHT_SUN")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Environment Lighting (HDRI)", icon="WORLD")
        tag = hdr.row(align=True)
        tag.alignment = 'RIGHT'
        tag.label(text="STUDIO")

        # Showcase the image of the HDRI selected; clicking opens popup grid of all HDRIs
        col = box.column(align=True)
        col.template_icon_view(context.scene, "mm_hdri_selection", show_labels=True, scale=5.0)

        # Two buttons side by side with icons
        box.separator(factor=0.3)
        row = box.row(align=True)
        row.scale_y = 1.2
        row.operator("metamorphosis.import_hdri", text="Import HDRI", icon="FILE_FOLDER")
        row.operator("metamorphosis.clear_hdri", text="Clear HDRI", icon="TRASH")

        # Intensity bar
        box.prop(context.scene, "mm_hdri_intensity", text="Intensity", slider=True, icon="LIGHT_DATA")


CLASSES = (
    MM_OT_import_hdri,
    MM_OT_clear_hdri,
    MM_PT_lighting,
)


def register():
    global _hdri_previews
    _hdri_previews = bpy.utils.previews.new()

    for key in BUILTIN_HDRIS:
        preview_png = HDRI_PREVIEWS_DIR / f"{key}.png"
        if preview_png.is_file():
            _hdri_previews.load(key, str(preview_png), "IMAGE")

    bpy.types.Scene.mm_custom_hdri_path = StringProperty(
        name="Custom HDRI Path",
        description="Path to user-selected HDRI environment image",
        default="",
    )

    bpy.types.Scene.mm_hdri_selection = EnumProperty(
        name="HDRI",
        description="Select an environment HDRI map for scene lighting",
        items=get_hdri_enum_items,
        update=update_hdri_selection,
    )

    bpy.types.Scene.mm_hdri_intensity = FloatProperty(
        name="Intensity",
        description="HDRI environment lighting intensity / strength",
        default=1.0,
        min=0.0,
        max=50.0,
        update=update_hdri_intensity,
    )


def unregister():
    global _hdri_previews
    if _hdri_previews is not None:
        bpy.utils.previews.remove(_hdri_previews)
        _hdri_previews = None

    if hasattr(bpy.types.Scene, "mm_hdri_selection"):
        del bpy.types.Scene.mm_hdri_selection
    if hasattr(bpy.types.Scene, "mm_hdri_intensity"):
        del bpy.types.Scene.mm_hdri_intensity
    if hasattr(bpy.types.Scene, "mm_custom_hdri_path"):
        del bpy.types.Scene.mm_custom_hdri_path
