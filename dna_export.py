"""Patch a complete source DNA without renumbering joints, meshes or vertices."""
from pathlib import Path
import os
import uuid

import numpy as np

from . import dnaio
from .bakeplan import euler_xyz_matrix


def positions(reader, mesh):
    return np.column_stack([getattr(reader, 'getVertexPosition'+axis+'s')(mesh) for axis in 'XYZ'])


def joint_rest(reader):
    translations = np.column_stack([getattr(reader, 'getNeutralJointTranslation'+a+'s')() for a in 'XYZ'])
    angles = np.column_stack([getattr(reader, 'getNeutralJointRotation'+a+'s')() for a in 'XYZ'])
    if dnaio.unit_flags(reader)[0]:
        angles = np.radians(angles)
    parents = np.array([reader.getJointParentIndex(i) for i in range(reader.getJointCount())])
    matrices = []
    for i, (t, a) in enumerate(zip(translations, angles)):
        m = np.eye(4); m[:3, :3] = euler_xyz_matrix(*a); m[:3, 3] = t
        parent = parents[i]
        if 0 <= parent != i:
            if parent >= i:
                raise ValueError('DNA joints must precede their children')
            m = matrices[parent] @ m
        matrices.append(m)
    return np.asarray(matrices), parents


def adapted_joints(reader, field):
    matrices, parents = joint_rest(reader)
    moved, jac = field.evaluate(matrices[:, :3, 3], jacobian=True)
    local, transforms = [], []
    for i, parent in enumerate(parents):
        rotation = matrices[parent, :3, :3] if 0 <= parent != i else np.eye(3)
        origin = moved[parent] if 0 <= parent != i else np.zeros(3)
        local.append(rotation.T @ (moved[i]-origin))
        transforms.append(rotation.T @ jac[i] @ rotation)
    return moved, np.asarray(local), np.asarray(transforms)


def adapt_joint_groups(reader, transforms):
    """Transform translation rows per LOD, retaining rotation/scale equations.

    Add cross-axis rows when required. Refuse incompatible per-axis LOD tiers
    rather than leaking high-detail coefficients into lower-detail LODs.
    """
    result = []
    for g in range(reader.getJointGroupCount()):
        indices = np.asarray(reader.getJointGroupOutputIndices(g), dtype=int)
        inputs = list(reader.getJointGroupInputIndices(g))
        values = np.asarray(reader.getJointGroupValues(g)).reshape(len(indices), len(inputs))
        lods = list(reader.getJointGroupLODs(g))
        if not len(inputs) or not len(indices):
            result.append((indices.tolist(), values.ravel().tolist(), lods)); continue
        # Keep each existing row in its original LOD tier. Transforming one
        # translation row can yield up to three rows with the same tier.
        rows, weights, boundaries = [], [], [0]
        for out, value in zip(indices, values):
            joint, axis = divmod(int(out), 9)
            if axis < 3:
                for dest in range(3):
                    coefficient = transforms[joint, dest, axis]
                    if abs(coefficient) > 1e-10:
                        rows.append(joint*9+dest); weights.append(value*coefficient)
            else:
                rows.append(int(out)); weights.append(value)
            boundaries.append(len(rows))
        # RigLogic overwrites, rather than sums, repeated output rows within a
        # group. A mixed-axis group must have the same active translation axes
        # at every LOD where that joint appears; otherwise refuse the edit.
        unique = list(dict.fromkeys(rows))
        tiers = {}
        for row in unique:
            contributions = [i for i, r in enumerate(rows) if r == row]
            counts = [sum(i < boundaries[n] for i in contributions) for n in lods]
            if any(c not in (0, len(contributions)) for c in counts):
                raise ValueError('This DNA uses per-axis LODs incompatible with this sculpt; use uniform scaling or translation')
            tiers[row] = tuple(c > 0 for c in counts)
        # Sort by inclusion in the lowest-detail LOD first, then retain order.
        unique.sort(key=lambda r: sum(tiers[r]), reverse=True)
        combined = {r: np.zeros(len(inputs)) for r in unique}
        for row, v in zip(rows, weights):
            combined[row] += v
        result.append((unique, np.array([combined[r] for r in unique]).ravel().tolist(),
                       [sum(tiers[r][lod] for r in unique) for lod in range(len(lods))]))
    return result


def _normals(reader, mesh, jac):
    normals = np.column_stack([getattr(reader, 'getVertexNormal'+a+'s')(mesh) for a in 'XYZ'])
    if not len(normals):
        return normals
    positions_ = np.asarray(reader.getVertexLayoutPositionIndices(mesh), dtype=int)
    indices = np.asarray(reader.getVertexLayoutNormalIndices(mesh), dtype=int)
    matrices = np.zeros((len(normals), 3, 3)); counts = np.zeros(len(normals))
    np.add.at(matrices, indices, jac[positions_]); np.add.at(counts, indices, 1)
    used = counts > 0
    matrices[used] /= counts[used, None, None]; matrices[~used] = np.eye(3)
    result = np.linalg.solve(matrices.transpose(0, 2, 1), normals[..., None])[..., 0]
    lengths = np.linalg.norm(result, axis=1)
    result /= np.maximum(lengths[:, None], 1e-12)
    return result


def validate_copy(source, output, expected=None, extra_shapes=False):
    """Read-back guards for index tables used by downstream RigLogic."""
    for name in ('JointCount', 'MeshCount', 'LODCount', 'RawControlCount', 'PSDCount',
                 'BlendShapeChannelCount', 'AnimatedMapCount', 'FileFormatGeneration', 'FileFormatVersion'):
        if extra_shapes and name == 'BlendShapeChannelCount':
            continue
        if getattr(source, 'get'+name)() != getattr(output, 'get'+name)():
            raise ValueError('Export changed DNA '+name)
    for lod in range(source.getLODCount()):
        for name in ('MeshIndicesForLOD', 'JointIndicesForLOD'):
            if list(getattr(source, 'get'+name)(lod)) != list(getattr(output, 'get'+name)(lod)):
                raise ValueError('Export changed LOD membership')
    for m in range(source.getMeshCount()):
        for name in ('VertexPositionCount', 'FaceCount', 'BlendShapeTargetCount', 'MeshName'):
            if extra_shapes and name == 'BlendShapeTargetCount':
                continue
            if getattr(source, 'get'+name)(m) != getattr(output, 'get'+name)(m):
                raise ValueError('Export changed mesh structure')
        actual = positions(output, m)
        if not np.isfinite(actual).all():
            raise ValueError('Export has invalid vertex positions')
        if expected is not None and not np.allclose(actual, expected[m], atol=2e-5, rtol=2e-6):
            raise ValueError('Export vertex read-back differs from the sculpt')
    for j in range(source.getJointCount()):
        if (source.getJointName(j), source.getJointParentIndex(j)) != (output.getJointName(j), output.getJointParentIndex(j)):
            raise ValueError('Export changed the DNA joint hierarchy')
    for a in 'XYZ':
        if not np.isfinite(getattr(output, 'getNeutralJointTranslation'+a+'s')()).all():
            raise ValueError('Export has invalid joint positions')


def write_dna(source_path, destination, field=None, overrides=None, *, edit=None, validate=None):
    """Copy all layers, patch geometry and write atomically after read-back.

    Source files are never overwritten. The caller owns the prepared target,
    and can validate the native RigLogic model before switching its rig to it.
    """
    source_path, destination = Path(source_path).resolve(), Path(destination).resolve()
    if source_path == destination:
        raise ValueError('Choose a new DNA filename; the source DNA is protected')
    if not destination.parent.is_dir():
        raise ValueError('Choose an existing export folder')
    reader = writer = stream = check = None
    temporary = destination.with_name('.'+destination.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        reader = dnaio.open_reader(source_path)
        dna, _, _ = dnaio.load_bindings()
        stream = dna.FileStream(str(temporary), dna.AccessMode_Write, dna.OpenMode_Binary, None)
        writer = dna.BinaryStreamWriter(stream, None)
        writer.setFrom(reader, dna.DataLayer_All, dna.UnknownLayerPolicy_Preserve, None)
        expected = None
        expected_translations = None
        if field is not None and not field.identity:
            _, translations, transforms = adapted_joints(reader, field)
            expected_translations = translations
            writer.setNeutralJointTranslations(translations.tolist())
            for g, (indices, values, lods) in enumerate(adapt_joint_groups(reader, transforms)):
                writer.setJointGroupOutputIndices(g, indices)
                writer.setJointGroupValues(g, values)
                writer.setJointGroupLODs(g, lods)
            expected = []
            for mesh in range(reader.getMeshCount()):
                base = positions(reader, mesh)
                moved, jac = field.evaluate(base, jacobian=True)
                if overrides and mesh in overrides:
                    moved = np.asarray(overrides[mesh])
                expected.append(moved)
                writer.setVertexPositions(mesh, moved.tolist())
                writer.setVertexNormals(mesh, _normals(reader, mesh, jac).tolist())
                for target in range(reader.getBlendShapeTargetCount(mesh)):
                    vertices = np.asarray(reader.getBlendShapeTargetVertexIndices(mesh, target), dtype=int)
                    delta = np.column_stack([getattr(reader, 'getBlendShapeTargetDelta'+a+'s')(mesh, target) for a in 'XYZ'])
                    delta = np.einsum('nij,nj->ni', jac[vertices], delta)
                    writer.setBlendShapeTargetDeltas(mesh, target, delta.tolist())
        if edit is not None:
            edit(reader, writer)
        writer.write()
        if not dna.Status.isOk():
            raise RuntimeError(dna.Status.get().message)
        dnaio.release_handle(writer); writer = None
        dnaio.release_handle(stream); stream = None
        check = dnaio.open_reader(temporary)
        validate_copy(reader, check, expected, extra_shapes=edit is not None)
        if validate is not None:
            validate(reader, check)
        if expected_translations is not None:
            actual = np.column_stack([getattr(check, 'getNeutralJointTranslation'+a+'s')() for a in 'XYZ'])
            if not np.allclose(actual, expected_translations, atol=2e-5, rtol=2e-6):
                raise ValueError('Export joint read-back differs from the sculpt')
        dnaio.release_handle(check); check = None
        os.replace(temporary, destination)
    finally:
        for handle in (check, writer, stream, reader):
            dnaio.release_handle(handle)
        if temporary.exists():
            temporary.unlink()
    return destination
