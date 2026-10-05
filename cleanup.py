"""Track imported data so Remove All never performs a global orphan purge."""

import uuid

import bpy

from . import bake

OWNER = "mm_import_id"
POOLS = ("objects", "collections", "meshes", "armatures", "curves", "materials",
         "shape_keys", "actions", "node_groups", "textures", "images", "fonts", "cameras", "lights")


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
    # Older releases have no ownership tags. Use their explicit rig references,
    # never assume every object placed in a character collection is imported.
    for rig in scene_objects:
        if rig.type != "ARMATURE" or bake.RIG_KEY_DATA not in rig:
            continue
        if rig.get("mm_combined_body"):
            # Older Combine Body operations merged user-owned bones into this ID.
            # Removing that armature would also destroy the user's body rig.
            continue
        objects.add(rig)
        objects.update(bake.head_meshes(rig))
        board = bpy.data.objects.get(str(rig.get(bake.RIG_KEY_BOARD_OBJECT, ""))) or rig
        if board in scene_objects:
            objects.add(board)
            objects.update(b.custom_shape for b in board.pose.bones if b.custom_shape is not None)
        for name in str(rig.get(bake.RIG_KEY_DATA, "")).split("\n"):
            obj = bpy.data.objects.get(name)
            if obj is not None and obj in scene_objects:
                objects.add(obj)
        root = bpy.data.collections.get(str(rig.get("mm_character_collection", "")))
        if root in collections:
            containers.add(root)
            containers.update(c for c in root.children_recursive if c.get("mm_collection_role"))
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
