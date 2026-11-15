"""Track imported data so Remove All never performs a global orphan purge."""

import uuid

import bpy

from ..riglogic import bake

OWNER = "mm_import_id"
POOLS = tuple(p for p in (
    "objects", "collections", "meshes", "armatures", "curves", "hair_curves", "materials",
    "shape_keys", "actions", "node_groups", "textures", "images", "fonts", "cameras", "lights"
) if hasattr(bpy.data, p))


def snapshot():
    return {name: {item.as_pointer() for item in getattr(bpy.data, name)} for name in POOLS}


def mark_created(before, token):
    for name in POOLS:
        for item in getattr(bpy.data, name):
            if item.library is None and item.as_pointer() not in before[name]:
                item[OWNER] = token


def new_token():
    return uuid.uuid4().hex


def scene_collections(scene):
    return {scene.collection, *scene.collection.children_recursive}


def targets(scene):
    collections = scene_collections(scene)
    scene_objects = set(scene.objects)
    tokens = {item.get(OWNER) for item in [*scene_objects, *collections] if item.get(OWNER)}
    objects = {o for o in scene_objects if o.get(OWNER) in tokens}
    containers = {c for c in collections if c.get(OWNER) in tokens}

    # MetaMorphosis character armatures (Head, Body, Connected, Converted)
    for rig in scene_objects:
        if rig.type != "ARMATURE":
            continue
        is_mm_rig = bool(
            bake.RIG_KEY_DATA in rig
            or rig.get("mm_body_rig")
            or rig.get("mm_attached_head")
            or rig.get("mm_body_converter")
            or rig.name.startswith(("METAHUMAN_BODY", "MH_"))
        )
        if not is_mm_rig:
            continue
        if rig.get("mm_combined_body"):
            # Older Combine Body operations merged user-owned bones into this ID.
            # Removing that armature would also destroy the user's body rig.
            continue
        objects.add(rig)
        objects.update(bake.head_meshes(rig))

        # Body meshes deformed by or parented to this rig
        for o in scene_objects:
            if o.type == "MESH":
                if o.get("mm_body_mesh") or o.name.startswith("METAHUMAN_BODY"):
                    objects.add(o)
                elif o.parent == rig or any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers):
                    if o.get("mm_body_mesh") or o.get("mm_clothing") or o.name.startswith(("METAHUMAN_BODY", "MH_")):
                        objects.add(o)

        # Face board
        board = bpy.data.objects.get(str(rig.get(bake.RIG_KEY_BOARD_OBJECT, ""))) or rig
        if board in scene_objects:
            objects.add(board)
            objects.update(b.custom_shape for b in board.pose.bones if b.custom_shape is not None)

        # Rig custom bone widget shapes (including body control shapes WGT_UNREAL_*)
        for b in rig.pose.bones:
            if b.custom_shape is not None and b.custom_shape in scene_objects:
                objects.add(b.custom_shape)

        # Native sum helper data objects
        for name in str(rig.get(bake.RIG_KEY_DATA, "")).split("\n"):
            obj = bpy.data.objects.get(name)
            if obj is not None and obj in scene_objects:
                objects.add(obj)

        # Character root collection
        char_col_name = rig.get("mm_character_collection")
        if char_col_name and char_col_name in bpy.data.collections:
            root = bpy.data.collections[char_col_name]
            if root in collections:
                containers.add(root)
                containers.update(c for c in root.children_recursive if c.get("mm_collection_role"))

        # Associated user collections of this rig
        for col in rig.users_collection:
            if col in collections:
                containers.add(col)
                containers.update(c for c in col.children_recursive if c.get("mm_collection_role"))

    # Include grooms, clothing and body meshes associated with the imported character or containers
    for obj in scene_objects:
        if obj in objects:
            continue
        is_groom = bool(
            obj.get("mm_groom_kind")
            or obj.get("mm_groom")
            or (obj.type == "CURVES" and any(c.get("mm_collection_role") == "Groom" for c in obj.users_collection))
        )
        if is_groom:
            surface = getattr(obj.data, "surface", None) if hasattr(obj, "data") else None
            if (
                obj.parent in objects
                or (surface is not None and surface in objects)
                or any(c in containers for c in obj.users_collection)
                or any(c.get("mm_collection_role") == "Groom" for c in obj.users_collection)
            ):
                objects.add(obj)
        elif obj.get("mm_clothing") or obj.get("mm_body_mesh"):
            objects.add(obj)
        elif obj.type == "MESH" and obj.parent in objects and any(m.type == "ARMATURE" and m.object in objects for m in obj.modifiers):
            if obj.parent in objects or any(c in containers for c in obj.users_collection):
                objects.add(obj)
        # Any object inside METAHUMAN_BODY collections or MetaMorphosis role collections
        elif any(c.name.startswith("METAHUMAN_BODY") or c.get("mm_collection_role") in ("BODY", "HEAD", "RIGLOGICDATA", "Groom") for c in obj.users_collection):
            objects.add(obj)

    # Ensure character, body, and groom collections are tracked in containers
    for c in collections:
        if c.get("mm_collection_role") in ("BODY", "HEAD", "ARMATURE", "FACE_BOARD", "Groom", "RIGLOGICDATA"):
            containers.add(c)
        elif c.name == "METAHUMAN_BODY" or c.name.startswith("METAHUMAN_BODY_") or c.name.startswith("WGTS_"):
            containers.add(c)
        elif any(parent in containers for parent in collections if c.name in parent.children) or any(o.name in c.objects for o in objects):
            if c.get("mm_collection_role") or c.name.startswith(("METAHUMAN_BODY", "MH_")):
                containers.add(c)

    return objects, containers, tokens


def remove_all(context):
    scene = context.scene
    objects, containers, tokens = targets(scene)
    others = set().union(*(set(s.objects) for s in bpy.data.scenes if s != scene))
    other_collections = set().union(*(scene_collections(s) for s in bpy.data.scenes if s != scene))
    removed = 0
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    # Protect children users attached after import by preserving their world pose.
    for obj in objects - others:
        for child in list(obj.children):
            if child not in objects:
                world = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = world
    legacy_data = set()
    for obj in objects - others:
        if obj.data is not None:
            legacy_data.add(obj.data)
            legacy_data.update(slot.material for slot in obj.material_slots if slot.material)
            if hasattr(obj.data, "materials"):
                legacy_data.update(m for m in obj.data.materials if m)
        if obj.get('mm_native_sum_data'):
            legacy_data.update(mod.node_group for mod in obj.modifiers
                               if mod.type == 'NODES' and mod.node_group
                               and mod.node_group.get('mm_native_sum_data'))
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1
    # Objects also used in another scene must not be deleted globally.
    for obj in objects & others:
        for collection in list(obj.users_collection):
            if collection in scene_collections(scene) and collection not in other_collections:
                collection.objects.unlink(obj)
    # Empty imported containers only; user-added objects/collections stay intact.
    for _ in range(len(containers) + 1):
        empty = [c for c in containers if c not in other_collections and not c.objects and not c.children]
        if not empty:
            break
        for collection in empty:
            containers.remove(collection)
            bpy.data.collections.remove(collection)
    # Remove only owned, unused data, in repeated passes for material -> node/image dependencies.
    for _ in range(len(POOLS)):
        unused = [item for name in POOLS[2:] for item in getattr(bpy.data, name)
                  if item.library is None and item.users == 0
                  and (item.get(OWNER) in tokens or item in legacy_data)]
        if not unused:
            break
        for item in unused:
            legacy_data.discard(item)
        bpy.data.batch_remove(ids=unused)
    return removed
