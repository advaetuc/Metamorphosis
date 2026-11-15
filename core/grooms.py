"""Groom (hair curves) importing, alignment, shader setup and surface sticking."""

from __future__ import annotations

import logging
from pathlib import Path
import bpy
from mathutils import Matrix
from bpy.props import PointerProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .constants import ASSETS_DIR, DEFAULT_GROOM_ACC_DIR, GROOM_ACC_FILE_NAME
from . import cleanup, organization

logger = logging.getLogger(__name__)

UNREAL_TO_BLENDER_GROOM_MATRIX = Matrix((
    (0.01, 0.0, 0.0, 0.0),
    (0.0, 0.0, -0.01, 0.0),
    (0.0, -0.01, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
))


def find_groom_acc_file() -> Path | None:
    """Find Groom Acc.blend in assets or the training data directory."""
    bundled = ASSETS_DIR / GROOM_ACC_FILE_NAME
    if bundled.is_file():
        return bundled
    external = DEFAULT_GROOM_ACC_DIR / GROOM_ACC_FILE_NAME
    if external.is_file():
        return external
    return None


def ensure_groom_assets() -> tuple[bpy.types.NodeTree | None, bpy.types.Material | None, bpy.types.NodeTree | None]:
    """Ensure 'Stick To Surface', 'Groom Shader', and 'Set Hair Curve Profile' exist in bpy.data."""
    nt = bpy.data.node_groups.get("Stick To Surface")
    mat = bpy.data.materials.get("Groom Shader")
    profile_ng = bpy.data.node_groups.get("Set Hair Curve Profile")

    if nt is not None and mat is not None and profile_ng is not None:
        return nt, mat, profile_ng

    acc_path = find_groom_acc_file()
    if acc_path and acc_path.is_file():
        with bpy.data.libraries.load(str(acc_path), link=False) as (src, dst):
            wanted_ngs = []
            if nt is None and "Stick To Surface" in src.node_groups:
                wanted_ngs.append("Stick To Surface")
            if profile_ng is None and "Set Hair Curve Profile" in src.node_groups:
                wanted_ngs.append("Set Hair Curve Profile")
            if wanted_ngs:
                dst.node_groups = wanted_ngs
            if mat is None and "Groom Shader" in src.materials:
                dst.materials = ["Groom Shader"]

    if nt is None:
        nt = bpy.data.node_groups.get("Stick To Surface")
    if mat is None:
        mat = bpy.data.materials.get("Groom Shader")
    if profile_ng is None:
        profile_ng = bpy.data.node_groups.get("Set Hair Curve Profile")

    # Fallback: check Blender installation's procedural hair assets
    if profile_ng is None:
        try:
            app_dir = Path(bpy.app.binary_path).parent
            hair_blends = list(app_dir.glob("**/procedural_hair_node_assets.blend"))
            if hair_blends and hair_blends[0].is_file():
                with bpy.data.libraries.load(str(hair_blends[0]), link=False) as (src, dst):
                    if "Set Hair Curve Profile" in src.node_groups:
                        dst.node_groups = ["Set Hair Curve Profile"]
                profile_ng = bpy.data.node_groups.get("Set Hair Curve Profile")
        except Exception as exc:
            logger.warning("Could not load procedural_hair_node_assets.blend: %s", exc)

    return nt, mat, profile_ng


def find_head_mesh(context: bpy.types.Context) -> bpy.types.Object | None:
    """Find the active character's head mesh."""
    # 1. User manual selection in scene property
    if hasattr(context.scene, "mm_groom_head_mesh") and context.scene.mm_groom_head_mesh:
        obj = context.scene.mm_groom_head_mesh
        if obj and obj.type == "MESH":
            return obj

    # 2. Context active or selected object if it's a head mesh
    if context.active_object and context.active_object.type == "MESH" and context.active_object.get("mm_mesh_kind") == "head":
        return context.active_object

    # 3. Search scene objects for head mesh
    for obj in context.scene.objects:
        if obj.type == "MESH" and obj.get("mm_mesh_kind") == "head":
            return obj

    # 4. Fallback search by name
    for obj in context.scene.objects:
        if obj.type == "MESH" and ("HEAD" in obj.name.upper() or "FACE" in obj.name.upper()):
            return obj

    return None


def delete_eyelash_haircards(context: bpy.types.Context) -> int:
    """Delete eyelash haircard meshes (IMP_02: replaced by eyelash grooms)."""
    to_delete = []
    for obj in list(context.scene.objects):
        if obj.type == "MESH":
            name_u = obj.name.upper()
            # Do NOT delete rig widgets, face board controls, frames, or text labels
            if (
                name_u.startswith("WGT-")
                or name_u.startswith("CTRL_")
                or name_u.startswith("FRM_")
                or name_u.startswith("TEXT_")
                or obj.get("mm_widget")
            ):
                continue

            kind = str(obj.get("mm_mesh_kind", "")).lower()
            if kind == "eyelashes" or name_u.endswith("_EYELASHES") or name_u == "EYELASHES":
                to_delete.append(obj)

    count = len(to_delete)
    for obj in to_delete:
        logger.info("Removing eyelash haircard mesh: %s", obj.name)
        bpy.data.objects.remove(obj, do_unlink=True)
    return count


def set_geo_node_input(modifier: bpy.types.Modifier, item_name: str, item_identifier: str, value):
    """Set an input on a Geometry Nodes modifier across Blender 4.x and 5.x."""
    if hasattr(modifier, "properties") and hasattr(modifier.properties, "inputs"):
        inp = getattr(modifier.properties.inputs, item_identifier, None)
        if inp is not None and hasattr(inp, "value"):
            try:
                inp.value = value
                return
            except Exception:
                pass
        inp = getattr(modifier.properties.inputs, item_name, None)
        if inp is not None and hasattr(inp, "value"):
            try:
                inp.value = value
                return
            except Exception:
                pass

    try:
        modifier[item_identifier] = value
        return
    except Exception:
        pass

    try:
        modifier[item_name] = value
    except Exception:
        pass


def setup_single_groom(
    context: bpy.types.Context,
    abc_path: Path,
    head_mesh: bpy.types.Object,
    uv_map_name: str = "UVMap",
    stick_node_group: bpy.types.NodeTree | None = None,
    groom_shader: bpy.types.Material | None = None,
    hair_color_params: dict | None = None,
    collection: bpy.types.Collection | None = None,
    head_rig: bpy.types.Object | None = None,
    profile_node_group: bpy.types.NodeTree | None = None,
) -> bpy.types.Object | None:
    """Import an Alembic groom file, align, apply shader and Stick To Surface geo-nodes."""
    if not abc_path.is_file():
        logger.warning("Groom file not found: %s", abc_path)
        return None

    # Track newly imported objects
    before = set(bpy.data.objects.keys())
    bpy.ops.wm.alembic_import(filepath=str(abc_path), as_background_job=False)
    new_objs = [bpy.data.objects[k] for k in bpy.data.objects.keys() if k not in before]
    curves_objs = [o for o in new_objs if o.type == "CURVES"]

    if not curves_objs:
        logger.warning("No CURVES object imported from %s", abc_path.name)
        return None

    groom = curves_objs[0]
    groom_name = abc_path.stem
    groom.name = f"{head_mesh.name.removesuffix('_HEAD')}_{groom_name}"
    groom["mm_groom_kind"] = groom_name
    groom["mm_groom"] = True

    token = (
        head_mesh.get(cleanup.OWNER)
        or (head_rig.get(cleanup.OWNER) if head_rig else None)
        or (collection.get(cleanup.OWNER) if collection else None)
        or cleanup.new_token()
    )
    groom[cleanup.OWNER] = token
    if groom.data:
        groom.data[cleanup.OWNER] = token
    if collection and not collection.get(cleanup.OWNER):
        collection[cleanup.OWNER] = token

    # Check if eyelash groom -> delete haircard meshes
    if "eyelash" in groom_name.lower():
        delete_eyelash_haircards(context)

    # Link to character grooms collection
    if collection is not None:
        organization.move_object(groom, collection)

    # 1. Transform alignment: Unreal cm left-handed to Blender m Z-up
    groom.matrix_world = UNREAL_TO_BLENDER_GROOM_MATRIX

    # Apply transform
    for o in context.selected_objects:
        o.select_set(False)
    groom.select_set(True)
    context.view_layer.objects.active = groom
    try:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    except Exception as exc:
        logger.warning("transform_apply failed on groom %s: %s", groom.name, exc)

    # 2. Surface Binding setup
    head_mesh.add_rest_position_attribute = True
    groom.data.surface = head_mesh
    actual_uv = uv_map_name if uv_map_name in head_mesh.data.uv_layers else (head_mesh.data.uv_layers[0].name if head_mesh.data.uv_layers else "UVMap")
    groom.data.surface_uv_map = actual_uv

    # Snap curves to surface
    try:
        bpy.ops.curves.snap_curves_to_surface(attach_mode="NEAREST")
    except Exception as exc:
        logger.warning("snap_curves_to_surface on %s: %s", groom.name, exc)

    # 3. Geometry Nodes: Set Hair Curve Profile
    # Peach Fuzz: radius 0.000025, applied as soon as imported
    # Other Grooms: radius 0.00005
    is_fuzz = "fuzz" in groom_name.lower()
    if profile_node_group is not None:
        prof_mod = groom.modifiers.new(name="Set Hair Curve Profile", type="NODES")
        prof_mod.node_group = profile_node_group
        target_radius = 0.000025 if is_fuzz else 0.00005
        set_geo_node_input(prof_mod, "Radius", "Input_3", target_radius)

        if is_fuzz:
            for o in context.selected_objects:
                o.select_set(False)
            groom.select_set(True)
            context.view_layer.objects.active = groom
            try:
                bpy.ops.object.modifier_apply(modifier=prof_mod.name)
            except Exception as exc:
                logger.warning("Could not apply Set Hair Curve Profile on %s: %s", groom.name, exc)

    # 4. Geometry Nodes: Stick To Surface
    # Follow Mesh slider value set to 1.0
    if stick_node_group is not None:
        mod = groom.modifiers.new(name="Stick To Surface", type="NODES")
        mod.node_group = stick_node_group
        for item in stick_node_group.interface.items_tree:
            if item.name == "Object":
                set_geo_node_input(mod, item.name, item.identifier, head_mesh)
            elif item.name == "Follow Mesh":
                set_geo_node_input(mod, item.name, item.identifier, 1.0)

    # 5. Material Setup
    if groom_shader is not None:
        mat = groom_shader.copy()
        mat.name = f"M_Groom_{groom_name.capitalize()}"
        mat[cleanup.OWNER] = token
        if hair_color_params:
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_HAIR_PRINCIPLED":
                    if "color" in hair_color_params:
                        c = hair_color_params["color"]
                        node.inputs["Color"].default_value = (c[0], c[1], c[2], 1.0)
                    if "melanin" in hair_color_params:
                        node.inputs["Melanin"].default_value = float(hair_color_params["melanin"])
                    if "redness" in hair_color_params:
                        node.inputs["Melanin Redness"].default_value = float(hair_color_params["redness"])
                    if "roughness" in hair_color_params:
                        node.inputs["Roughness"].default_value = float(hair_color_params["roughness"])
        groom.data.materials.append(mat)

    # 6. Parent to Head Rig
    if head_rig is not None:
        groom.parent = head_rig
    elif head_mesh.parent:
        groom.parent = head_mesh.parent

    logger.info("Setup groom %s attached to %s", groom.name, head_mesh.name)
    return groom


def import_all_grooms(
    context: bpy.types.Context,
    grooms_folder: Path,
    head_mesh: bpy.types.Object,
    uv_map_name: str = "UVMap",
    manifest_components: list | None = None,
    collection: bpy.types.Collection | None = None,
    head_rig: bpy.types.Object | None = None,
) -> list[bpy.types.Object]:
    """Import and setup all grooms from a folder or manifest."""
    stick_node_group, groom_shader, profile_node_group = ensure_groom_assets()
    imported_grooms = []

    if collection is None:
        # Put the Grooms in the Head Collection inside a Collection called "Groom"
        head_col = None
        if head_mesh:
            for c in head_mesh.users_collection:
                if c.get("mm_collection_role") == "HEAD" or c.name.upper().endswith("HEAD"):
                    head_col = c
                    break
            if not head_col and head_mesh.users_collection:
                head_col = head_mesh.users_collection[0]

        if not head_col:
            char_col_name = head_mesh.get("mm_character_collection") if head_mesh else None
            if char_col_name and char_col_name in bpy.data.collections:
                char_col = bpy.data.collections[char_col_name]
                head_col = organization.child_collection(char_col, "HEAD")

        if not head_col:
            head_col = context.scene.collection

        collection = organization.child_collection(head_col, "Groom")

    token = (
        head_mesh.get(cleanup.OWNER)
        or (head_rig.get(cleanup.OWNER) if head_rig else None)
        or (collection.get(cleanup.OWNER) if collection else None)
        or cleanup.new_token()
    )
    if collection and not collection.get(cleanup.OWNER):
        collection[cleanup.OWNER] = token

    if head_rig is None and head_mesh.parent and head_mesh.parent.type == "ARMATURE":
        head_rig = head_mesh.parent

    # Build component parameter lookup if manifest components are supplied
    comp_map = {}
    if manifest_components:
        for c in manifest_components:
            name = c.get("name", "")
            comp_map[name.lower()] = c

    # Find all .abc files in grooms_folder
    abc_files = sorted(grooms_folder.glob("*.abc"))
    for abc_path in abc_files:
        groom_key = abc_path.stem.lower()
        comp_info = comp_map.get(groom_key, {})
        hair_params = {}
        for m in comp_info.get("materials", []):
            if "hair_color" in m:
                hair_params = m["hair_color"]
                break

        groom_obj = setup_single_groom(
            context,
            abc_path,
            head_mesh,
            uv_map_name=uv_map_name,
            stick_node_group=stick_node_group,
            groom_shader=groom_shader,
            hair_color_params=hair_params,
            collection=collection,
            head_rig=head_rig,
            profile_node_group=profile_node_group,
        )
        if groom_obj:
            imported_grooms.append(groom_obj)

    return imported_grooms


class MM_OT_import_setup_grooms(bpy.types.Operator, ImportHelper):
    """Import and setup MetaHuman hair grooms with Stick To Surface Geo-Nodes"""

    bl_idname = "metamorphosis.import_setup_grooms"
    bl_label = "Import and Setup Grooms"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.abc;*.json", options={"HIDDEN"})

    def execute(self, context):
        head_mesh = find_head_mesh(context)
        if not head_mesh:
            self.report({"ERROR"}, "No head mesh found. Please select or import a head mesh first.")
            return {"CANCELLED"}

        path = Path(self.filepath)
        grooms_folder = path if path.is_dir() else path.parent
        if path.name.lower() == "characterassemblymanifest.json":
            # Grooms folder is subfolder Grooms
            if (grooms_folder / "Grooms").is_dir():
                grooms_folder = grooms_folder / "Grooms"
        elif path.suffix.lower() == ".abc" and path.is_file():
            grooms_folder = path.parent

        uv_name = getattr(context.scene, "mm_groom_head_uv", "UVMap") or "UVMap"
        grooms = import_all_grooms(context, grooms_folder, head_mesh, uv_map_name=uv_name)

        if not grooms:
            self.report({"WARNING"}, f"No .abc groom files found in {grooms_folder}")
            return {"CANCELLED"}

        # Close all collections in outliner
        try:
            organization.close_all_collections(context)
        except Exception:
            pass

        self.report({"INFO"}, f"Successfully imported and set up {len(grooms)} grooms on {head_mesh.name}")
        return {"FINISHED"}


class MM_PT_grooms_setup(bpy.types.Panel):
    """Grooms Setup panel for importing and sticking hair curves to head mesh"""

    bl_label = "Grooms Setup"
    bl_idname = "MM_PT_grooms_setup"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MetaMorphosis"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="STRANDS")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Hair Curves & Surface Binding", icon="STRANDS")
        tag = hdr.row(align=True)
        tag.alignment = 'RIGHT'
        tag.label(text="GEOMETRY NODES")

        col = box.column(align=True)
        col.prop_search(context.scene, "mm_groom_head_mesh", context.scene, "objects", text="Head Mesh")

        head_mesh = find_head_mesh(context)
        if head_mesh and head_mesh.data.uv_layers:
            col.prop_search(context.scene, "mm_groom_head_uv", head_mesh.data, "uv_layers", text="Head UV")
        else:
            col.prop(context.scene, "mm_groom_head_uv", text="Head UV")

        box.separator(factor=0.4)
        row = box.row(align=True)
        row.scale_y = 1.35
        row.operator("metamorphosis.import_setup_grooms", text="Bind Hair Curves to Head", icon="MOD_PARTICLES")


CLASSES = (
    MM_OT_import_setup_grooms,
    MM_PT_grooms_setup,
)


def register():
    bpy.types.Scene.mm_groom_head_mesh = PointerProperty(
        name="Head Mesh",
        description="Head mesh to which hair curves are aligned and bound",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == "MESH",
    )
    bpy.types.Scene.mm_groom_head_uv = StringProperty(
        name="Head UV",
        description="UV map used for hair curve surface positioning",
        default="UVMap",
    )


def unregister():
    if hasattr(bpy.types.Scene, "mm_groom_head_mesh"):
        del bpy.types.Scene.mm_groom_head_mesh
    if hasattr(bpy.types.Scene, "mm_groom_head_uv"):
        del bpy.types.Scene.mm_groom_head_uv
