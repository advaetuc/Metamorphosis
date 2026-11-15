"""Character assembly orchestrator for MetaMorphosis Update 2.80.

Reads CharacterAssemblyManifest.json and automatically imports & sets up:
- head.dna (with baked RigLogic, face board, custom shapes & colors)
- body.dna (with native correctives)
- builds the body control rig
- merges/connects head and body into one skeleton
- applies texture maps and materials to all components
- imports, aligns, and binds Grooms with Stick To Surface geo-nodes and Groom Shader
- imports clothing (if present)
- creates a 90mm focal length face camera
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import bpy
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty

from ..body import body_merge
from ..riglogic import bake
from . import camera, cleanup, grooms, materials, organization, progress_ui

logger = logging.getLogger(__name__)


def assemble_character(
    context: bpy.types.Context,
    manifest_path: Path,
    body_custom_shapes: str = "UNREAL",
    join_face_board: bool = False,
) -> dict:
    """Execute the full character assembly workflow from CharacterAssemblyManifest.json."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    folder = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    char_name = manifest.get("name", folder.name)

    import time
    t_start = time.perf_counter()
    logger.info("Starting Character Assembly for: %s from %s (shapes=%s, join_face_board=%s)",
                char_name, folder, body_custom_shapes, join_face_board)
    results = {
        "name": char_name,
        "head_imported": False,
        "body_imported": False,
        "body_rig_built": False,
        "merged": False,
        "materials_applied": False,
        "grooms_count": 0,
        "clothing_count": 0,
    }

    dna_info = manifest.get("dna", {})
    body_rel = dna_info.get("body", "body.dna")
    head_rel = dna_info.get("head", "head.dna")
    body_path = folder / body_rel
    head_path = folder / head_rel
    char_token = cleanup.new_token()

    # -------------------------------------------------------------------------
    # STEP 1: Import Body DNA & Build Body Control Rig
    # -------------------------------------------------------------------------
    body_rig = None
    if body_path.is_file():
        progress_ui.update(10, "Importing Body DNA")
        logger.info("Importing Body DNA: %s", body_path)
        try:
            res = bpy.ops.metamorphosis.import_body(filepath=str(body_path))
            if res == {"FINISHED"}:
                results["body_imported"] = True
                body_rig = next((o for o in context.scene.objects if o.type == "ARMATURE" and o.get("mm_body_rig")), None)
                if body_rig:
                    progress_ui.update(25, "Building Body Control Rig")
                    logger.info("Building Body Control Rig with preset '%s'...", body_custom_shapes)
                    from ..body import body_converter
                    col = body_rig.users_collection[0] if body_rig.users_collection else context.scene.collection
                    body_converter.convert(body_rig, col, shape_preset=body_custom_shapes)
                    results["body_rig_built"] = True
                    logger.info("Body Control Rig built successfully (%s).", body_custom_shapes)
        except Exception as exc:
            logger.warning("Body DNA import / control rig failed: %s", exc)

    # -------------------------------------------------------------------------
    # STEP 2: Import Head DNA (baked RigLogic, face board, custom shapes & colors)
    # -------------------------------------------------------------------------
    head_rig = None
    if head_path.is_file():
        progress_ui.update(45, "Importing Head DNA & RigLogic")
        logger.info("Importing Head DNA: %s (join_face_board=%s)", head_path, join_face_board)
        try:
            # Synchronous import to allow pipeline to continue immediately
            res = bpy.ops.metamorphosis.import_dna(
                filepath=str(head_path),
                character_name=char_name,
                synchronous=True,
                join_face_board=join_face_board,
            )
            if res == {"FINISHED"}:
                results["head_imported"] = True
                head_rig = next((o for o in context.scene.objects if o.type == "ARMATURE" and bake.RIG_KEY_DATA in o and not o.get("mm_body_rig")), None)
                if head_rig is None:
                    head_rig = bake.find_baked_rig(context)
                logger.info("Head DNA imported successfully: %s", getattr(head_rig, "name", "None"))
        except Exception as exc:
            logger.warning("Head DNA import failed: %s", exc)

    # -------------------------------------------------------------------------
    # STEP 3: Connect Head and Body Skeletons
    # -------------------------------------------------------------------------
    # Re-verify live object references fresh from scene objects
    if not body_rig or body_rig.name not in bpy.data.objects:
        body_rig = next((o for o in context.scene.objects if o.type == "ARMATURE" and o.get("mm_body_rig") and not o.get("mm_attached_head")), None)
    if not head_rig or head_rig.name not in bpy.data.objects:
        head_rig = next((o for o in context.scene.objects if o.type == "ARMATURE" and bake.RIG_KEY_DATA in o and not o.get("mm_body_rig")), None)

    combined_rig = body_rig or head_rig
    face_board = None
    if body_rig and head_rig:
        progress_ui.update(65, "Connecting Head and Body Skeletons")
        try:
            logger.info("Connecting Head and Body skeletons (join_face_board=%s)...", join_face_board)
            # Ensure rest pose and FK on body controls before merge
            if "PROPERTIES" in body_rig.pose.bones:
                for k in body_rig.pose.bones["PROPERTIES"].keys():
                    if "_FK_IK." in k:
                        cur = body_rig.pose.bones["PROPERTIES"][k]
                        body_rig.pose.bones["PROPERTIES"][k] = 0 if isinstance(cur, int) else 0.0
            from mathutils import Matrix
            if "mm_body_control_map" in body_rig:
                controls = json.loads(body_rig["mm_body_control_map"]).values()
                for n in controls:
                    if n in body_rig.pose.bones:
                        body_rig.pose.bones[n].matrix_basis = Matrix.Identity(4)

            combined_rig, face_board = body_merge.merge(context, body_rig, head_rig, join_face_board=join_face_board)
            results["merged"] = True
            logger.info("Connected Head and Body into: %s (face_board=%s)", combined_rig.name, getattr(face_board, "name", "None"))
        except Exception as exc:
            logger.exception("Connecting head and body failed: %s", exc)
            raise
    elif body_rig:
        combined_rig = body_rig

    # -------------------------------------------------------------------------
    # STEP 4: Setup Materials and Textures
    # -------------------------------------------------------------------------
    maps_folder = folder / "Maps"
    if maps_folder.is_dir():
        progress_ui.update(80, "Applying Materials & Textures")
        context.scene.mm_texture_folder = str(maps_folder)
        try:
            logger.info("Applying materials from: %s", maps_folder)
            materials.setup_materials(context, str(maps_folder))
            results["materials_applied"] = True
        except Exception as exc:
            logger.warning("Applying materials failed: %s", exc)
        finally:
            materials.set_body_detail_tiling(value=45.0)

    # -------------------------------------------------------------------------
    # STEP 5: Import & Setup Grooms (Stick To Surface Geo-Nodes & Groom Shader)
    # -------------------------------------------------------------------------
    grooms_folder = folder / "Grooms"
    head_mesh = grooms.find_head_mesh(context)
    if head_mesh:
        # IMP: Ensure rest position attribute enabled
        head_mesh.add_rest_position_attribute = True

        # Check if grooms folder exists or components specified
        if grooms_folder.is_dir():
            progress_ui.update(90, "Importing & Binding Grooms")
            logger.info("Importing and setting up grooms from: %s", grooms_folder)
            try:
                g_list = grooms.import_all_grooms(
                    context,
                    grooms_folder,
                    head_mesh,
                    manifest_components=manifest.get("components", []),
                    head_rig=combined_rig,
                )
                results["grooms_count"] = len(g_list)
                logger.info("Setup %d grooms.", len(g_list))
            except Exception as exc:
                logger.warning("Groom setup failed: %s", exc)

    # -------------------------------------------------------------------------
    # STEP 6: Import Clothing (If present)
    # -------------------------------------------------------------------------
    clothing_folder = folder / "Clothing"
    meshes_folder = folder / "Meshes"
    for check_dir in (clothing_folder, meshes_folder):
        if check_dir.is_dir():
            for cloth_file in check_dir.iterdir():
                ext = cloth_file.suffix.lower()
                before_objs = set(bpy.data.objects.keys())
                try:
                    if ext == ".fbx":
                        bpy.ops.import_scene.fbx(filepath=str(cloth_file))
                    elif ext == ".obj":
                        bpy.ops.wm.obj_import(filepath=str(cloth_file))
                    elif ext == ".abc":
                        bpy.ops.wm.alembic_import(filepath=str(cloth_file), as_background_job=False)
                    elif ext in (".gltf", ".glb"):
                        bpy.ops.import_scene.gltf(filepath=str(cloth_file))
                except Exception as exc:
                    logger.warning("Failed importing clothing file %s: %s", cloth_file.name, exc)
                    continue

                new_cloth_objs = [bpy.data.objects[k] for k in bpy.data.objects.keys() if k not in before_objs]
                cloth_token = (combined_rig.get(cleanup.OWNER) if combined_rig else None) or cleanup.new_token()
                for c_obj in new_cloth_objs:
                    c_obj[cleanup.OWNER] = cloth_token
                    if c_obj.data:
                        c_obj.data[cleanup.OWNER] = cloth_token
                    c_obj["mm_clothing"] = True
                    if c_obj.type == "MESH":
                        organization.remove_custom_normals(c_obj)
                        if combined_rig:
                            arm_mod = c_obj.modifiers.get("Armature") or c_obj.modifiers.new(name="Armature", type="ARMATURE")
                            arm_mod.object = combined_rig
                            c_obj.parent = combined_rig
                            results["clothing_count"] += 1

    # Remove custom normals on imported character meshes
    for obj in list(context.scene.objects):
        if obj.type == "MESH":
            nu = obj.name.upper()
            if nu.startswith(("WGT-", "WGT_", "CTRL_", "FRM_", "TEXT_")) or obj.get("mm_widget"):
                continue
            organization.remove_custom_normals(obj)

    # -------------------------------------------------------------------------
    # STEP 7: Close All Collections in Outliner & Unify Character Ownership
    # -------------------------------------------------------------------------
    progress_ui.update(98, "Finalizing Character Assembly")
    try:
        organization.close_all_collections(context)
    except Exception as exc:
        logger.warning("Closing collections failed: %s", exc)

    # Stamp unified char_token across all character objects and collections for atomic cleanup
    if combined_rig:
        combined_rig[cleanup.OWNER] = char_token
    if face_board:
        face_board[cleanup.OWNER] = char_token
    for o in context.scene.objects:
        if (
            o.get("mm_body_mesh")
            or o.name.startswith("METAHUMAN_BODY")
            or o.get("mm_groom")
            or o.get("mm_groom_kind")
            or o.get("mm_clothing")
            or (combined_rig and (o.parent == combined_rig or any(m.type == "ARMATURE" and m.object == combined_rig for m in o.modifiers)))
        ):
            o[cleanup.OWNER] = char_token
            if o.data:
                o.data[cleanup.OWNER] = char_token
    for c in bpy.data.collections:
        if c.name.startswith("METAHUMAN_BODY") or c.name.startswith("MH_") or c.get("mm_collection_role"):
            c[cleanup.OWNER] = char_token

    context.view_layer.update()
    progress_ui.update(100, "Assembly Complete")
    logger.info("Finished Character Assembly for %s: %s", char_name, results)
    return results


class MM_OT_import_character(bpy.types.Operator, ImportHelper):
    """Import and fully assemble a character from CharacterAssemblyManifest.json"""

    bl_idname = "metamorphosis.import_character"
    bl_label = "Import Character"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(
        default="CharacterAssemblyManifest.json;*.json",
        options={"HIDDEN"},
    )

    body_custom_shapes: bpy.props.EnumProperty(
        name="Control Shapes",
        description="Control widget shape preset for the body control rig",
        items=(
            ("UNREAL", "Unreal", "Unreal Engine MetaHuman-style control shapes"),
            ("BLENDER", "Blender", "Blender wireframe control shapes"),
        ),
        default="UNREAL",
    )

    join_face_board: bpy.props.BoolProperty(
        name="Join Face Board Armature",
        description="Merge the face board into the character armature (one single armature) or keep it separate",
        default=False,
    )

    def invoke(self, context, event):
        if hasattr(context.scene, "mm_assemble_custom_shapes"):
            self.body_custom_shapes = context.scene.mm_assemble_custom_shapes
        if hasattr(context.scene, "mm_assemble_join_face_board"):
            self.join_face_board = context.scene.mm_assemble_join_face_board
        return super().invoke(context, event)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Assembly Options", icon="PREFERENCES")
        box.prop(self, "body_custom_shapes", text="Control Shapes")
        box.prop(self, "join_face_board", text="Join Face Board Armature")

    def execute(self, context):
        # Sync scene properties with user choices from operator
        if hasattr(context.scene, "mm_assemble_custom_shapes"):
            context.scene.mm_assemble_custom_shapes = self.body_custom_shapes
        if hasattr(context.scene, "mm_assemble_join_face_board"):
            context.scene.mm_assemble_join_face_board = self.join_face_board

        manifest_path = Path(self.filepath)
        if not manifest_path.is_file():
            self.report({"ERROR"}, f"Manifest file not found: {manifest_path}")
            return {"CANCELLED"}

        if manifest_path.name.lower() != "characterassemblymanifest.json":
            # Check if CharacterAssemblyManifest.json exists in the selected folder
            alt = manifest_path.parent / "CharacterAssemblyManifest.json"
            if alt.is_file():
                manifest_path = alt

        try:
            progress_ui.begin("Assembling Character")
            results = assemble_character(
                context,
                manifest_path,
                body_custom_shapes=self.body_custom_shapes,
                join_face_board=self.join_face_board,
            )
            parts = []
            if results["head_imported"]:
                parts.append("Head")
            if results["body_imported"]:
                parts.append("Body")
            if results["body_rig_built"]:
                parts.append(f"Control Rig ({self.body_custom_shapes.title()})")
            if results["merged"]:
                parts.append("Connected")
            if results["materials_applied"]:
                parts.append("Materials")
            if results["grooms_count"]:
                parts.append(f"{results['grooms_count']} Grooms")
            if results["clothing_count"]:
                parts.append(f"{results['clothing_count']} Clothes")

            summary = ", ".join(parts) if parts else "Complete"
            self.report({"INFO"}, f"Successfully assembled {results['name']} ({summary})")
            return {"FINISHED"}
        except Exception as exc:
            logger.exception("Character Assembly failed")
            self.report({"ERROR"}, f"Character Assembly failed: {exc}")
            return {"CANCELLED"}
        finally:
            progress_ui.end()


CLASSES = (
    MM_OT_import_character,
)


def register():
    bpy.types.Scene.mm_assemble_custom_shapes = bpy.props.EnumProperty(
        name="Control Shapes",
        description="Body control rig widget shape preset",
        items=(
            ("UNREAL", "Unreal", "Unreal Engine MetaHuman-style control shapes"),
            ("BLENDER", "Blender", "Blender wireframe control shapes"),
        ),
        default="UNREAL",
    )
    bpy.types.Scene.mm_assemble_join_face_board = bpy.props.BoolProperty(
        name="Join Face Board Armature",
        description="Merge the face board into the character armature (one single armature) or keep it separate",
        default=False,
    )


def unregister():
    if hasattr(bpy.types.Scene, "mm_assemble_custom_shapes"):
        del bpy.types.Scene.mm_assemble_custom_shapes
    if hasattr(bpy.types.Scene, "mm_assemble_join_face_board"):
        del bpy.types.Scene.mm_assemble_join_face_board
