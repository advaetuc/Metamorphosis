"""Import the head meshes and the original facial deformation rig from a MetaHuman head DNA.

Only geometry, skinning, shape keys and the skeleton are created. No textures, no node trees, no
wrinkle-map logic. Every DNA mesh becomes one object with exactly one (empty) material slot, which is
how MetaHuman splits meshes by material (head, teeth, saliva, eyeLeft, eyeRight, eyeshell, eyelashes ...).
"""

from __future__ import annotations

import logging
import math
import re

from dataclasses import dataclass, field

import bpy
import numpy as np

from mathutils import Matrix, Vector

from .constants import ATTRS_PER_JOINT, NUMBER_OF_LODS  # noqa: F401
from .bakeplan import euler_xyz_matrix

logger = logging.getLogger(__name__)

# DNA is Maya Y-up (x=left, y=up, z=front). Blender is Z-up: rotate +90 degrees around X.
Y_UP_TO_Z_UP = Matrix.Rotation(math.radians(90.0), 4, "X")
_MESH_KIND = re.compile(r"^(?P<kind>.+?)_lod\d+_mesh$", re.IGNORECASE)


@dataclass
class ImportOptions:
    scale: float = 0.01
    lod: int = 0
    prefix: str = "MetaHuman"
    shape_keys: bool = True
    rotation_degrees: bool = True


@dataclass
class ImportResult:
    rig: bpy.types.Object
    meshes: list = field(default_factory=list)
    collection: bpy.types.Collection | None = None
    shape_key_map: dict = field(default_factory=dict)  # channel index -> [(Key datablock, block name)]
    warnings: list = field(default_factory=list)
    prefix: str = ""


def unique_prefix(prefix: str) -> str:
    """Return ``prefix`` or ``prefix_001``... so that nothing already in the file is overwritten."""
    candidate, n = prefix, 0
    while (
        f"{candidate}_rig" in bpy.data.objects
        or candidate in bpy.data.collections
        or f"{candidate}_rig" in bpy.data.armatures
    ):
        n += 1
        candidate = f"{prefix}_{n:03d}"
    return candidate


def _kind_of(mesh_name: str) -> str:
    match = _MESH_KIND.match(mesh_name)
    return match.group("kind") if match else mesh_name


def _to_blender(x, y, z, scale: float) -> np.ndarray:
    """Rotate DNA (Y-up) vectors to Blender (Z-up) and scale them: (x, y, z) -> (x, -z, y)."""
    return np.stack([x, -z, y], axis=1) * scale


def _create_rig(reader, options: ImportOptions, collection: bpy.types.Collection) -> bpy.types.Object:
    name = f"{options.prefix}_rig"
    armature = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, armature)
    collection.objects.link(rig)

    count = reader.getJointCount()
    tx = np.asarray(reader.getNeutralJointTranslationXs(), np.float64) * options.scale
    ty = np.asarray(reader.getNeutralJointTranslationYs(), np.float64) * options.scale
    tz = np.asarray(reader.getNeutralJointTranslationZs(), np.float64) * options.scale
    rx = np.asarray(reader.getNeutralJointRotationXs(), np.float64)
    ry = np.asarray(reader.getNeutralJointRotationYs(), np.float64)
    rz = np.asarray(reader.getNeutralJointRotationZs(), np.float64)
    if options.rotation_degrees:
        rx, ry, rz = np.radians(rx), np.radians(ry), np.radians(rz)

    names = [str(reader.getJointName(i)) for i in range(count)]
    parents = [int(reader.getJointParentIndex(i)) for i in range(count)]

    # global (DNA space) matrix of every joint: parent_global @ (T @ E)
    globals_: list[Matrix | None] = [None] * count
    for i in range(count):
        local = Matrix.Translation(Vector((tx[i], ty[i], tz[i]))) @ Matrix(euler_xyz_matrix(rx[i], ry[i], rz[i]).tolist()).to_4x4()
        parent = parents[i]
        if parent < 0 or parent == i:
            globals_[i] = local
        else:
            if globals_[parent] is None:
                raise RuntimeError(f"Joint '{names[i]}' is listed before its parent; unsupported DNA joint order")
            globals_[i] = globals_[parent] @ local

    view_layer = bpy.context.view_layer
    for obj in view_layer.objects.selected:
        obj.select_set(False)
    view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = armature.edit_bones
        bone_length = max(options.scale, 1e-4)
        created = []
        for i in range(count):
            bone = edit_bones.new(names[i])
            bone.length = bone_length
            bone.matrix = Y_UP_TO_Z_UP @ globals_[i]
            created.append(bone)
        for i in range(count):
            parent = parents[i]
            if 0 <= parent != i:
                created[i].parent = created[parent]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    armature.relation_line_position = "HEAD"
    try:
        collection_bones = armature.collections.new("MM Face Rig")
        for bone in armature.bones:
            collection_bones.assign(bone)
    except Exception as error:  # noqa: BLE001 - bone collections are cosmetic
        logger.debug("Bone collection assignment skipped: %s", error)
    return rig


def _create_mesh(
    reader, mesh_index: int, mesh_name: str, options: ImportOptions, rig, collection, joint_names, result
) -> bpy.types.Object:
    kind = _kind_of(mesh_name)
    object_name = f"{options.prefix}_{kind}"
    positions = _to_blender(
        np.asarray(reader.getVertexPositionXs(mesh_index), np.float64),
        np.asarray(reader.getVertexPositionYs(mesh_index), np.float64),
        np.asarray(reader.getVertexPositionZs(mesh_index), np.float64),
        options.scale,
    )
    layout_to_position = list(reader.getVertexLayoutPositionIndices(mesh_index))
    layout_to_uv = list(reader.getVertexLayoutTextureCoordinateIndices(mesh_index))
    layout_to_normal = list(reader.getVertexLayoutNormalIndices(mesh_index))

    face_layouts = [list(reader.getFaceVertexLayoutIndices(mesh_index, f)) for f in range(reader.getFaceCount(mesh_index))]
    faces = [tuple(layout_to_position[i] for i in layouts) for layouts in face_layouts]
    loop_layout = [i for layouts in face_layouts for i in layouts]

    mesh = bpy.data.meshes.new(object_name)
    try:
        mesh.from_pydata(positions.tolist(), [], faces, shade_flat=False)
    except TypeError:  # older signature without shade_flat
        mesh.from_pydata(positions.tolist(), [], faces)
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        mesh.update()

    # UVs (one per loop, in the order of the faces above)
    u_values = np.asarray(reader.getVertexTextureCoordinateUs(mesh_index), np.float32)
    v_values = np.asarray(reader.getVertexTextureCoordinateVs(mesh_index), np.float32)
    uv_index = np.asarray([layout_to_uv[i] for i in loop_layout], np.int64)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    if len(uv_layer.data) == len(loop_layout):
        uv_flat = np.empty((len(loop_layout), 2), np.float32)
        uv_flat[:, 0] = u_values[uv_index]
        uv_flat[:, 1] = v_values[uv_index]
        uv_layer.data.foreach_set("uv", uv_flat.ravel())
    else:
        result.warnings.append(f"{object_name}: UV count mismatch, UVs were skipped")

    # DNA normals as custom split normals (keeps seams and eye regions shading like in MetaHuman)
    try:
        nx = np.asarray(reader.getVertexNormalXs(mesh_index), np.float64)
        ny = np.asarray(reader.getVertexNormalYs(mesh_index), np.float64)
        nz = np.asarray(reader.getVertexNormalZs(mesh_index), np.float64)
        normal_index = np.asarray([layout_to_normal[i] for i in loop_layout], np.int64)
        normals = _to_blender(nx[normal_index], ny[normal_index], nz[normal_index], 1.0)
        lengths = np.linalg.norm(normals, axis=1)
        bad = lengths < 1e-8
        normals[bad] = (0.0, 0.0, 1.0)
        lengths[bad] = 1.0
        normals /= lengths[:, None]
        if len(mesh.loops) == len(normals):
            mesh.normals_split_custom_set(normals.tolist())
    except Exception as error:  # noqa: BLE001
        result.warnings.append(f"{object_name}: custom normals skipped ({type(error).__name__}: {error})")

    obj = bpy.data.objects.new(object_name, mesh)
    collection.objects.link(obj)

    # exactly one material slot per mesh; the material is a plain, empty datablock
    material = bpy.data.materials.get(f"{options.prefix}_{kind}") or bpy.data.materials.new(f"{options.prefix}_{kind}")
    mesh.materials.append(material)

    # skin weights
    groups: dict[int, bpy.types.VertexGroup] = {}
    for vertex in range(len(positions)):
        joint_indices = reader.getSkinWeightsJointIndices(mesh_index, vertex)
        weights = reader.getSkinWeightsValues(mesh_index, vertex)
        for joint, weight in zip(joint_indices, weights):
            if weight <= 0.0:
                continue
            group = groups.get(joint)
            if group is None:
                group = groups[joint] = obj.vertex_groups.new(name=joint_names[joint])
            group.add([vertex], float(weight), "REPLACE")

    obj.parent = rig
    modifier = obj.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = rig

    if options.shape_keys:
        _create_shape_keys(reader, mesh_index, obj, options, result)
    return obj


def _create_shape_keys(reader, mesh_index: int, obj: bpy.types.Object, options: ImportOptions, result) -> None:
    target_count = reader.getBlendShapeTargetCount(mesh_index)
    if target_count == 0:
        return
    basis = obj.shape_key_add(name="Basis", from_mix=False)
    vertex_count = len(basis.data)
    base = np.empty(vertex_count * 3, np.float32)
    basis.data.foreach_get("co", base)
    base = base.reshape(-1, 3)
    key = obj.data.shape_keys

    for target in range(target_count):
        channel = reader.getBlendShapeChannelIndex(mesh_index, target)
        name = str(reader.getBlendShapeChannelName(channel))
        indices = np.asarray(reader.getBlendShapeTargetVertexIndices(mesh_index, target), np.int64)
        block = obj.shape_key_add(name=name, from_mix=False)
        block.value = 0.0
        if indices.size:
            deltas = _to_blender(
                np.asarray(reader.getBlendShapeTargetDeltaXs(mesh_index, target), np.float64),
                np.asarray(reader.getBlendShapeTargetDeltaYs(mesh_index, target), np.float64),
                np.asarray(reader.getBlendShapeTargetDeltaZs(mesh_index, target), np.float64),
                options.scale,
            )
            valid = indices < vertex_count
            if not valid.all():
                result.warnings.append(f"{obj.name}: shape '{name}' references vertices that do not exist")
            shaped = base.copy()
            shaped[indices[valid]] += deltas[valid].astype(np.float32)
            block.data.foreach_set("co", shaped.ravel())
        result.shape_key_map.setdefault(int(channel), []).append((key, block.name))


def import_head(reader, options: ImportOptions) -> ImportResult:
    """Create the collection, rig and meshes for the head DNA in ``reader``."""
    scene = bpy.context.scene
    collection = bpy.data.collections.new(options.prefix)
    scene.collection.children.link(collection)

    result = ImportResult(rig=None, collection=collection, prefix=options.prefix)  # type: ignore[arg-type]
    joint_names = [str(reader.getJointName(i)) for i in range(reader.getJointCount())]
    result.rig = _create_rig(reader, options, collection)

    lod_meshes = list(reader.getMeshIndicesForLOD(options.lod))
    if not lod_meshes:
        raise RuntimeError(f"The DNA file has no meshes for LOD{options.lod}")
    for mesh_index in lod_meshes:
        mesh_name = str(reader.getMeshName(mesh_index))
        try:
            obj = _create_mesh(reader, mesh_index, mesh_name, options, result.rig, collection, joint_names, result)
            result.meshes.append(obj)
        except Exception as error:  # noqa: BLE001 - keep importing the other meshes
            logger.exception("Mesh '%s' failed", mesh_name)
            result.warnings.append(f"Mesh '{mesh_name}' failed to import: {error}")
    return result
