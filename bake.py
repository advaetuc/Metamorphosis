"""Turn a :class:`bakeplan.Plan` into Blender drivers.

Everything created here is native Blender data (custom properties + drivers using *simple expressions*
or the built-in SUM driver). Nothing refers to this add-on, so the rig keeps working when the add-on
is disabled or removed, and it does not need "Auto Run Python Scripts".
"""

from __future__ import annotations

import logging
import time

import bpy

from .bakeplan import Plan
from .constants import DATA_OBJECT_NAME, MAX_EXPRESSION_LENGTH, REPORT_TEXT_NAME

logger = logging.getLogger(__name__)

RIG_KEY_BONES = "mm_driven_bones"
RIG_KEY_BOARD = "mm_board_bones"
RIG_KEY_DATA = "mm_data_object"
RIG_KEY_DNA = "mm_source_dna"
RIG_KEY_SCALE = "mm_scale"
RIG_KEY_BOARD_OBJECT = "mm_board_object"
RIG_KEY_PREFIX = "mm_prefix"
RIG_KEY_QUALITY = "mm_quality"
RIG_KEY_STATS = "mm_stats"


SHARD_SIZE = 250  # properties per data empty: driver_add and custom-property lookups both scale with this


def create_data_object(collection: bpy.types.Collection, prefix: str, index: int = 0) -> bpy.types.Object:
    """An empty that stores baked helper values. It is tiny, unselectable and must stay in the file."""
    name = f"{prefix}_{DATA_OBJECT_NAME}_{index:02d}".upper()
    empty = bpy.data.objects.new(name, None)
    if collection.get("mm_import_id"):
        empty["mm_import_id"] = collection["mm_import_id"]
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 0.001
    empty.hide_select = True
    empty.hide_render = True
    empty.hide_viewport = True
    collection.objects.link(empty)
    return empty


def _clean_driver(fcurve: bpy.types.FCurve) -> bpy.types.Driver:
    while fcurve.modifiers:
        fcurve.modifiers.remove(fcurve.modifiers[0])
    driver = fcurve.driver
    while driver.variables:
        driver.variables.remove(driver.variables[0])
    driver.use_self = False
    return driver


def _add_variable(driver, var, *, holder_of, rig, board) -> None:
    variable = driver.variables.new()
    variable.name = var.name
    variable.type = "SINGLE_PROP"
    target = variable.targets[0]
    target.id_type = "OBJECT"
    if var.kind == "prop":
        holder, index = holder_of[var.ref]
        target.id = holder
        target.data_path = f'["mm_values"][{index}]'
    elif var.kind == "loc":
        target.id = board
        target.data_path = f'pose.bones["{var.ref}"].location[{var.index}]'
    else:  # quat
        target.id = rig
        target.data_path = f'pose.bones["{var.ref}"].rotation_quaternion[{var.index}]'


def _add_driver(owner, data_path: str, index: int, node, *, holder_of, rig, board, counters) -> None:
    if index >= 0:
        fcurve = owner.driver_add(data_path, index)
    else:
        fcurve = owner.driver_add(data_path)
    driver = _clean_driver(fcurve)
    driver.type = node.dtype
    if node.dtype == "SCRIPTED":
        if len(node.expr) > MAX_EXPRESSION_LENGTH + 20:
            raise ValueError(f"Driver expression too long ({len(node.expr)}): {node.expr[:60]}...")
        driver.expression = node.expr
    for var in node.vars:
        _add_variable(driver, var, holder_of=holder_of, rig=rig, board=board)
    counters["drivers"] += 1
    counters["variables"] += len(node.vars)
    if node.dtype == "SCRIPTED" and not driver.is_simple_expression:
        counters["not_simple"] += 1


def realize(
    plan: Plan,
    *,
    rig: bpy.types.Object,
    board: bpy.types.Object,
    holders: list,
    shape_key_map: dict,
    board_bone_names: set,
    dna_path: str,
    scale: float,
    progress=None,
) -> dict:
    """Create the properties and drivers. ``holders`` are the data empties (helper properties are spread
    over them). Returns statistics."""
    started = time.perf_counter()
    counters = {"drivers": 0, "variables": 0, "not_simple": 0}

    # spread the helper properties over the holders: dependency order -> consecutive blocks
    holder_of: dict = {}
    for holder, group in zip(holders, helper_groups(plan)):
        if group:
            # One array lookup replaces a linear search through hundreds of ID properties.
            # A separate driver still writes each element, preserving all rounding boundaries.
            holder["mm_values"] = [float(plan.props[name]) for name in group]
            for index, name in enumerate(group):
                holder_of[name] = (holder, index)

    for pose_bone in rig.pose.bones:
        if pose_bone.name in plan.quat_bones:
            pose_bone.rotation_mode = "QUATERNION"
        elif pose_bone.name in plan.euler_bones:
            pose_bone.rotation_mode = "XYZ"

    if rig.animation_data is None:
        rig.animation_data_create()
    for holder in holders:
        if holder.animation_data is None:
            holder.animation_data_create()

    total = max(len(plan.nodes), 1)
    for number, node in enumerate(plan.nodes):
        kind = node.target[0]
        if kind == "prop":
            owner, index = holder_of[node.target[1]]
            _add_driver(owner, '["mm_values"]', index, node, holder_of=holder_of, rig=rig, board=board, counters=counters)
        elif kind == "bone":
            _, bone, path, index = node.target
            _add_driver(
                rig, f'pose.bones["{bone}"].{path}', index, node, holder_of=holder_of, rig=rig, board=board,
                counters=counters,
            )
        if progress is not None and number % 500 == 0:
            progress(number / total)

    # blend shape weights follow the matching RigLogic value
    shape_driver_count = 0
    from .bakeplan import Node, Var

    for channel, prop in plan.shape_props.items():
        for key, block_name in shape_key_map.get(channel, []):
            if key.animation_data is None:
                key.animation_data_create()
            node = Node(("shape", channel), "SUM", "", [Var("s0", "prop", prop)], "shape")
            _add_driver(
                key, f'key_blocks["{block_name}"].value', -1, node, holder_of=holder_of, rig=rig, board=board,
                counters=counters,
            )
            shape_driver_count += 1

    rig[RIG_KEY_BONES] = "\n".join(sorted(plan.euler_bones))
    rig[RIG_KEY_BOARD] = "\n".join(sorted(board_bone_names))
    rig[RIG_KEY_DATA] = "\n".join(h.name for h in holders)
    rig[RIG_KEY_DNA] = dna_path
    rig[RIG_KEY_SCALE] = float(scale)

    counters["shape_drivers"] = shape_driver_count
    counters["seconds"] = time.perf_counter() - started
    return counters


def remove_baked(rig: bpy.types.Object) -> None:
    """Delete every driver / data empty created by a previous bake and put the driven bones back to rest."""
    driven = set(filter(None, str(rig.get(RIG_KEY_BONES, "")).split("\n")))
    if rig.animation_data:
        for fcurve in list(rig.animation_data.drivers):
            path = fcurve.data_path
            if path.startswith('pose.bones["'):
                bone = path[len('pose.bones["') : path.index('"]')]
                if bone in driven:
                    rig.animation_data.drivers.remove(fcurve)
    for mesh in head_meshes(rig):
        key = mesh.data.shape_keys
        if key and key.animation_data:
            for fcurve in list(key.animation_data.drivers):
                if fcurve.data_path.startswith("key_blocks["):
                    key.animation_data.drivers.remove(fcurve)
            for block in key.key_blocks:
                if block.name != "Basis":
                    block.value = 0.0
    for holder_name in filter(None, str(rig.get(RIG_KEY_DATA, "")).split("\n")):
        holder = bpy.data.objects.get(holder_name)
        if holder is not None:
            bpy.data.objects.remove(holder, do_unlink=True)
    for pose_bone in rig.pose.bones:
        if pose_bone.name in driven:
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.rotation_euler = (0.0, 0.0, 0.0)
            pose_bone.scale = (1.0, 1.0, 1.0)


def holders_needed(plan: Plan) -> int:
    return max(1, len(helper_groups(plan)))


def helper_groups(plan: Plan) -> list:
    """Array properties must not contain drivers which read from that same array.

    Blender tracks array dependencies at property level. Separate dependency depths
    prevent cycles while allowing constant-time indexed access to helper values.
    """
    depth = dict.fromkeys(plan.props, 0)
    for node in plan.nodes:
        if node.target[0] == "prop":
            depth[node.target[1]] = 1 + max((depth[v.ref] for v in node.vars if v.kind == "prop"), default=0)
    levels = {}
    for name in plan.props:
        levels.setdefault(depth[name], []).append(name)
    return [names[i:i + SHARD_SIZE] for level, names in sorted(levels.items())
            for i in range(0, len(names), SHARD_SIZE)]


def head_meshes(rig):
    """Restrict rebuild/toggle to the imported head, including after a body join."""
    scoped = rig.get("mm_mesh_scope", False)
    return [o for o in bpy.data.objects if o.type == "MESH" and o.parent == rig
            and (not scoped or o.get("mm_head_mesh", False))]


# ------------------------------------------------------------------ utilities
def find_baked_rig(context) -> bpy.types.Object | None:
    obj = context.active_object
    candidates = [obj] if obj else []
    if obj and obj.type == "MESH" and obj.parent:
        candidates.append(obj.parent)
    candidates += [o for o in context.scene.objects if o.type == "ARMATURE"]
    for candidate in candidates:
        if candidate is not None and candidate.type == "ARMATURE" and RIG_KEY_DATA in candidate:
            return candidate
    return None


def baked_fcurves(rig: bpy.types.Object):
    """Yield every driver F-curve that belongs to the baked rig."""
    for holder_name in filter(None, str(rig.get(RIG_KEY_DATA, "")).split("\n")):
        holder = bpy.data.objects.get(holder_name)
        if holder is not None and holder.animation_data:
            yield from holder.animation_data.drivers
    driven = set(filter(None, str(rig.get(RIG_KEY_BONES, "")).split("\n")))
    if rig.animation_data:
        for fcurve in rig.animation_data.drivers:
            path = fcurve.data_path
            if path.startswith('pose.bones["'):
                bone = path[len('pose.bones["') : path.index('"]')]
                if bone in driven:
                    yield fcurve
    for mesh in head_meshes(rig):
        key = mesh.data.shape_keys
        if key and key.animation_data:
            yield from key.animation_data.drivers


def set_baked_enabled(rig: bpy.types.Object, enabled: bool) -> int:
    """Mute / unmute the baked drivers. Muting also resets the driven channels to the rest pose."""
    count = 0
    for fcurve in baked_fcurves(rig):
        fcurve.mute = not enabled
        count += 1
    if not enabled:
        driven = set(filter(None, str(rig.get(RIG_KEY_BONES, "")).split("\n")))
        for pose_bone in rig.pose.bones:
            if pose_bone.name in driven:
                pose_bone.location = (0.0, 0.0, 0.0)
                pose_bone.rotation_euler = (0.0, 0.0, 0.0)
                pose_bone.scale = (1.0, 1.0, 1.0)
        for mesh in head_meshes(rig):
            if mesh.data.shape_keys:
                for block in mesh.data.shape_keys.key_blocks:
                    if block.name != "Basis" and block.relative_key is not block:
                        block.value = 0.0
    bpy.context.view_layer.update()
    return count


def validate_rig(rig: bpy.types.Object) -> dict:
    """Count drivers and flag any that Blender cannot evaluate natively."""
    total = invalid = python_needed = muted = 0
    for fcurve in baked_fcurves(rig):
        total += 1
        driver = fcurve.driver
        if fcurve.mute:
            muted += 1
        if not driver.is_valid:
            invalid += 1
        if driver.type == "SCRIPTED" and not driver.is_simple_expression:
            python_needed += 1
    return {"drivers": total, "invalid": invalid, "needs_python": python_needed, "muted": muted}


def benchmark(context, rig: bpy.types.Object, iterations: int = 20) -> dict:
    """Time depsgraph updates while wiggling a few face board controls."""
    board_names = [n for n in str(rig.get(RIG_KEY_BOARD, "")).split("\n") if n]
    board = bpy.data.objects.get(str(rig.get(RIG_KEY_BOARD_OBJECT, ""))) or rig
    bones = [board.pose.bones[n] for n in board_names if n in board.pose.bones and n.startswith("CTRL_")][:12]
    if not bones:
        return {"ms": float("nan"), "fps": float("nan"), "controls": 0}
    saved = [tuple(b.location) for b in bones]
    context.view_layer.update()
    started = time.perf_counter()
    try:
        for i in range(iterations):
            amount = 0.15 + 0.02 * (i % 5)
            for bone in bones:
                bone.location.y = amount if i % 2 else -amount * 0.0
            context.view_layer.update()
        elapsed = (time.perf_counter() - started) / iterations
    finally:
        for bone, location in zip(bones, saved):
            bone.location = location
        context.view_layer.update()
    return {"ms": elapsed * 1000.0, "fps": 1.0 / elapsed if elapsed > 0 else float("inf"), "controls": len(bones)}


def write_report(lines: list[str]) -> bpy.types.Text:
    text = bpy.data.texts.get(REPORT_TEXT_NAME) or bpy.data.texts.new(REPORT_TEXT_NAME)
    text.clear()
    text.write("\n".join(lines) + "\n")
    return text
