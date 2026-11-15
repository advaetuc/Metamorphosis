"""Collection layout for imported characters; DNA bone names stay unchanged."""

import bpy

BODY_BONES = {"spine_04", "spine_05", "clavicle_l", "clavicle_r", "neck_01", "neck_02", "head"}


def child_collection(parent, role):
    # A role tag allows multiple characters, despite Blender's globally unique names.
    for child in parent.children:
        if child.get("mm_collection_role") == role:
            return child
    child = bpy.data.collections.new(role)
    child["mm_collection_role"] = role
    if parent.get("mm_import_id"):
        child["mm_import_id"] = parent["mm_import_id"]
    parent.children.link(child)
    return child


def move_object(obj, collection):
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for old in list(obj.users_collection):
        if old != collection:
            old.objects.unlink(obj)


def armature_display(rig):
    rig.display_type = "WIRE"
    rig.show_in_front = True


def deformation_collections(rig):
    head = rig.data.collections.new("DEF_HEAD")
    body = rig.data.collections.new("DEF_BODY")
    for bone in rig.data.bones:
        (body if bone.name in BODY_BONES else head).assign(bone)
    armature_display(rig)


def board_collections(board):
    armature = board.armature.data
    roots = list(armature.collections)
    master = armature.collections.new("MH_FACE_BOARD")
    for root in roots:
        root.parent = master
    for bone in armature.bones:
        if not bone.collections:
            master.assign(bone)
    armature_display(board.armature)


def organize_board(board, parent):
    armatures = child_collection(parent, "ARMATURE")
    head = child_collection(parent, "HEAD")
    data = child_collection(parent, "RIGLOGICDATA")
    for obj in [board.armature, *board.widgets, *board.extras]:
        obj.name = obj.name.upper()
        target = armatures if obj.type == "ARMATURE" else data if obj.type == "EMPTY" else head
        move_object(obj, target)
        if obj.type == "ARMATURE":
            obj.data.name = obj.data.name.upper()
            armature_display(obj)


def remove_custom_normals(obj_or_objs):
    """Automatically clear/remove custom split normals on imported mesh(es).

    Uses direct attribute removal for instant C-level execution without operator
    overhead, avoiding depsgraph evaluation cycles and UI freezes.
    """
    if obj_or_objs is None:
        return
    objs = obj_or_objs if isinstance(obj_or_objs, (list, tuple, set)) else [obj_or_objs]
    for obj in objs:
        if not obj or getattr(obj, "type", "") != "MESH":
            continue
        mesh = getattr(obj, "data", None)
        if not mesh:
            continue

        changed = False

        # 1. Direct attribute removal (Blender 4.1+, 5.x)
        # Custom normals are stored as 'custom_normal' corner attribute.
        # Removing this attribute clears custom split normals instantly in C.
        if hasattr(mesh, "attributes") and "custom_normal" in mesh.attributes:
            try:
                mesh.attributes.remove(mesh.attributes["custom_normal"])
                changed = True
            except Exception:
                pass

        # 2. Fallback for legacy format if has_custom_normals remains True
        if getattr(mesh, "has_custom_normals", False):
            try:
                with bpy.context.temp_override(
                    object=obj,
                    active_object=obj,
                    selected_objects=[obj],
                    selected_editable_objects=[obj],
                ):
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
                changed = True
            except Exception:
                pass

        # 3. Ensure smooth face shading across all polygons if any are flat
        try:
            if hasattr(mesh, "polygons") and len(mesh.polygons):
                if any(not p.use_smooth for p in mesh.polygons):
                    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
                    changed = True
        except Exception:
            pass

        # Only trigger mesh.update() if normals or shading actually changed
        if changed:
            try:
                mesh.update()
            except Exception:
                pass


def close_all_collections(context: bpy.types.Context | None = None):
    """Close/collapse all collection entries in the Outliner."""
    wm = bpy.context.window_manager if context is None else getattr(context, "window_manager", bpy.context.window_manager)
    if not wm:
        return
    for window in wm.windows:
        screen = window.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.type == "OUTLINER":
                for region in area.regions:
                    if region.type == "WINDOW":
                        try:
                            with bpy.context.temp_override(window=window, area=area, region=region):
                                for _ in range(8):
                                    bpy.ops.outliner.show_one_level(open=False)
                        except Exception:
                            pass
