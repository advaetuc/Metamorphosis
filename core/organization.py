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
