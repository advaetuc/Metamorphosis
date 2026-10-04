"""Append the face board (armature + bone widgets) from a .blend file and join it with the face rig."""

from __future__ import annotations

import logging
import re

from dataclasses import dataclass, field
from pathlib import Path

import bpy

from .constants import FACE_BOARD_FILE_NAME

logger = logging.getLogger(__name__)


@dataclass
class FaceBoard:
    armature: bpy.types.Object | None = None
    bone_names: set = field(default_factory=set)
    widgets: list = field(default_factory=list)
    extras: list = field(default_factory=list)
    joined: bool = False
    warnings: list = field(default_factory=list)


def find_face_board_file(preference_path: str = "") -> Path | None:
    """Preference path first, then ``<addon>/assets/face_board.blend``."""
    if preference_path:
        path = Path(bpy.path.abspath(preference_path))
        if path.is_file():
            return path
    bundled = Path(__file__).parent / "assets" / FACE_BOARD_FILE_NAME
    return bundled if bundled.is_file() else None


def _score(obj: bpy.types.Object) -> tuple[int, int]:
    squashed = re.sub(r"[^a-z]", "", obj.name.lower())
    name_hit = 1 if "faceboard" in squashed else 0
    controls = sum(1 for bone in obj.data.bones if bone.name.startswith("CTRL_"))
    return name_hit, controls


def append_face_board(
    context: bpy.context, filepath: Path, collection: bpy.types.Collection, location: tuple[float, float, float]
) -> FaceBoard:
    """Append every object of ``filepath`` into ``collection`` and identify the face board armature."""
    board = FaceBoard()
    before = set(bpy.data.objects.keys())
    with bpy.data.libraries.load(str(filepath), link=False) as (source, target):
        target.objects = list(source.objects)
    appended = [obj for obj in target.objects if obj is not None]
    if not appended:
        raise RuntimeError(f"'{filepath.name}' does not contain any objects")
    del before

    for obj in appended:
        collection.objects.link(obj)

    armatures = [obj for obj in appended if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError(f"'{filepath.name}' does not contain an armature (the face board)")
    board.armature = max(armatures, key=_score)
    if _score(board.armature)[1] == 0:
        board.warnings.append(
            f"The face board armature '{board.armature.name}' has no bones named CTRL_*; "
            "check that face_board.blend is the MetaHuman face board."
        )
    board.bone_names = {bone.name for bone in board.armature.data.bones}

    # widgets = objects used as custom bone shapes; hide them like Blender expects
    widget_objects = {pb.custom_shape for pb in board.armature.pose.bones if pb.custom_shape is not None}
    for obj in appended:
        if obj is board.armature:
            continue
        if obj in widget_objects:
            obj.hide_viewport = True
            obj.hide_render = True
            board.widgets.append(obj)
        else:
            board.extras.append(obj)

    board.armature.location = location
    return board


def _constraints_missing_target(armature: bpy.types.Object) -> int:
    missing = 0
    for pose_bone in armature.pose.bones:
        for constraint in pose_bone.constraints:
            if hasattr(constraint, "target") and constraint.target is None:
                missing += 1
    return missing


def join_into_rig(context: bpy.context, rig: bpy.types.Object, board: FaceBoard) -> bool:
    """Join the face board armature into ``rig`` (one armature, every bone editable).

    Returns ``True`` on success. On failure nothing is lost: the face board stays a separate armature and the
    drivers simply read from it.
    """
    fb = board.armature
    fb_name = fb.name
    children = [(child, child.matrix_world.copy(), child.parent_type, child.parent_bone) for child in fb.children]
    missing_before = _constraints_missing_target(fb)
    view_layer = context.view_layer

    try:
        if context.object and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:  # noqa: BLE001
        pass

    for obj in view_layer.objects.selected:
        obj.select_set(False)
    fb.hide_viewport = False
    fb.hide_set(False)
    rig.hide_set(False)
    fb.select_set(True)
    rig.select_set(True)
    view_layer.objects.active = rig

    try:
        with context.temp_override(
            active_object=rig,
            object=rig,
            selected_objects=[rig, fb],
            selected_editable_objects=[rig, fb],
        ):
            bpy.ops.object.join()
    except Exception as error:  # noqa: BLE001
        board.warnings.append(f"Joining the face board failed ({error}); it was kept as a separate armature.")
        return False

    # After a successful join the face board object no longer exists (never touch ``fb`` again).
    if bpy.data.objects.get(fb_name) is not None:
        board.warnings.append("Joining the face board did not run; it was kept as a separate armature.")
        return False

    # children of the old face board armature (frames, labels...) now follow the joined armature
    for child, world, parent_type, parent_bone in children:
        try:
            child.parent = rig
            if parent_type == "BONE" and parent_bone in rig.data.bones:
                child.parent_type = "BONE"
                child.parent_bone = parent_bone
            child.matrix_world = world
        except Exception as error:  # noqa: BLE001
            board.warnings.append(f"Could not re-parent '{child.name}' after joining: {error}")

    missing_after = _constraints_missing_target(rig)
    if missing_after > missing_before:
        board.warnings.append(
            f"{missing_after - missing_before} face board constraints lost their target when joining. "
            "Re-import with 'Join Face Board' turned off if the board behaves incorrectly."
        )

    board.armature = rig
    board.joined = True
    return True
