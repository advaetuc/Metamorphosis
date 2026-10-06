"""Shared bake pipeline used by the import operator and by "Rebuild Drivers"."""

from __future__ import annotations

import bpy

from . import bake, bakeplan, faceboard, optimize, organization
from .logicmodel import RigLogicModel

# quality -> (translation m, rotation rad, scale) error budget per channel at scale 0.01, use correctives (PSD)
QUALITY = {
    "LITE": ((3e-4, 1e-3, 5e-4), False),
}
QUALITY_ITEMS = [
    ("LITE", "Lite", "Primary expressions, Lips Together and Jaw Open Extreme; other combination correctives are left out"),
]


def weighted_bones(meshes) -> set[str]:
    """Names of bones that at least one imported mesh is skinned to."""
    names: set[str] = set()
    for mesh in meshes:
        names.update(group.name for group in mesh.vertex_groups)
    return names


def unneeded_bones(model: RigLogicModel, used: set[str]) -> set[str]:
    """Bones that neither deform a mesh nor carry a deforming descendant (their motion is invisible)."""
    if not used:
        return set()
    index = {name: i for i, name in enumerate(model.joint_names)}
    needed: set[int] = set()
    for name in used:
        j = index.get(name)
        while j is not None and j >= 0 and j not in needed:
            needed.add(j)
            parent = model.joint_parents[j]
            j = parent if parent != j else None
    return {name for i, name in enumerate(model.joint_names) if i not in needed}


def run_bake(
    context,
    *,
    model: RigLogicModel,
    variant,
    reader_orientation,
    rig,
    board_object,
    board_bone_names: set,
    shape_key_map: dict,
    meshes,
    collection,
    prefix: str,
    quality: str,
    scale: float,
    rotation_degrees: bool,
    dna_path: str,
    report: list,
    progress=None,
):
    """Plan and create the drivers. Returns ``(plan, stats)``."""
    budget, use_psd = QUALITY[quality]
    linked_eyes = faceboard.link_center_eye(board_object)
    if linked_eyes:
        report.append("Middle eye control: drives both eyes with independent left/right offsets.")
    factor = scale / 0.01
    budget = (budget[0] * factor, budget[1], budget[2])
    skip = unneeded_bones(model, weighted_bones(meshes))
    plan = bakeplan.build_plan(
        model,
        variant,
        reader_orientation,
        scale=scale,
        rotation_degrees=rotation_degrees,
        budget=budget,
        use_psd=use_psd,
        face_board_bones=board_bone_names,
        shape_channels=set(shape_key_map.keys()),
        skip_bones=skip,
    )
    optimize.optimize_plan(plan)
    if plan.stats["lips_together_correctives"]:
        report.append("Lips Together: retained jaw/lip closure correctives for all four controls.")
    if plan.stats["jaw_open_extreme_correctives"]:
        report.append("Jaw Open Extreme: retained extreme jaw opening and its mouth combinations.")
    report.append(
        f"Lossless driver optimization: removed {plan.stats['optimized_drivers']} drivers "
        f"and {plan.stats['optimized_variables']} variables; quality settings unchanged."
    )
    variables = sum(len(node.vars) for node in plan.nodes)
    data_collection = organization.child_collection(collection, "RIGLOGICDATA")
    holders = [bake.create_data_object(data_collection, prefix, i) for i in range(bake.holders_needed(plan))]
    report.append(
        f"Quality '{quality}': skipping {len(skip)} bones that deform nothing; creating {len(plan.nodes)} drivers "
        f"with {variables} variables, {plan.stats['properties']} helper values on {len(holders)} data objects..."
    )
    bake.write_report(report)  # visible even if Blender is busy
    stats = bake.realize(
        plan,
        rig=rig,
        board=board_object,
        holders=holders,
        shape_key_map=shape_key_map,
        board_bone_names=board_bone_names,
        dna_path=dna_path,
        scale=scale,
        progress=progress,
    )
    rig[bake.RIG_KEY_BOARD_OBJECT] = board_object.name
    rig[bake.RIG_KEY_PREFIX] = prefix
    rig[bake.RIG_KEY_QUALITY] = quality
    rig[bake.RIG_KEY_STATS] = f"{stats['drivers']} drivers, {stats['variables']} variables"
    stats["skipped_bones"] = len(skip)
    stats["plan"] = plan.stats
    return plan, stats
