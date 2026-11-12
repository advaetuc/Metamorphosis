"""Body DNA RBF equations prepared offline for a native Blender compiler.

No playback handler is installed by this module. The evaluator is an independent
numeric reference used to validate the equations before constructing a rig.
"""
from dataclasses import dataclass
import math
import numpy as np


def project_quaternions(values, method, axis):
    q = np.asarray(values, dtype=np.float32).reshape(-1, 4).copy()
    if method not in (2, 3):
        return q.reshape(-1)
    a = q[:, axis].copy()
    w = q[:, 3].copy()
    length = np.sqrt(a*a + w*w)
    if np.any(length < 1e-10):
        raise ValueError('Singular body swing/twist input')
    if method == 3:
        q[:] = 0
        q[:, axis], q[:, 3] = a/length, w/length
    else:
        b, c = (axis+1) % 3, (axis+2) % 3
        qb, qc = q[:, b].copy(), q[:, c].copy()
        q[:, axis] = 0
        q[:, b] = -(w*qb - a*qc)/length
        q[:, c] = -(w*qc + a*qb)/length
        q[:, 3] = -length
    return q.reshape(-1)


def distances(targets, sample, method):
    if method == 0:
        return np.linalg.norm(targets-sample, axis=1)
    dots = np.sum(targets.reshape(len(targets), -1, 4)*sample.reshape(-1, 4), axis=2)
    angles = np.arccos(np.clip(2*dots*dots-1, -1, 1))
    return np.linalg.norm(angles, axis=1)


def kernel(distance, radius, function):
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('Invalid body solver radius')
    if function == 0:
        return np.exp(-distance/(radius*radius))
    if function == 1:
        return np.exp(-2*distance/radius)
    power = {2: 1, 3: 3, 4: 5}.get(function)
    if power is None:
        raise ValueError('Unsupported body RBF kernel')
    return np.maximum(0, 1-(distance/radius)**power)


@dataclass
class Solver:
    name: str
    inputs: np.ndarray
    poses: list
    source_targets: np.ndarray
    targets: np.ndarray
    method: int
    axis: int
    radius: float
    function: int
    coefficients: np.ndarray
    normalize: bool
    threshold: float
    scales: np.ndarray

    def weights(self, raw):
        sample = project_quaternions(raw[self.inputs], self.method, self.axis) if self.method else raw[self.inputs]
        weights = kernel(distances(self.targets, sample, self.method), self.radius, self.function)
        weights = np.clip(self.coefficients @ weights, 0, 1)
        total = float(weights.sum())
        if total > 1 or self.normalize:
            weights = weights/total if total > 0 else np.zeros_like(weights)
        weights *= self.scales
        return np.where(weights > self.threshold, weights, 0)


class BodyRBF:
    def __init__(self, reader, dna, lod=0):
        self.raw_count = reader.getRawControlCount()
        self.count = reader.getRBFPoseControlCount()
        self.offset = self.raw_count + reader.getPSDCount() + reader.getMLControlCount()
        self.raw_names = [str(reader.getRawControlName(i)) for i in range(self.raw_count)]
        self.pose_outputs = [list(reader.getRBFPoseOutputControlIndices(i)) for i in range(reader.getRBFPoseCount())]
        self.pose_weights = [list(reader.getRBFPoseOutputControlWeights(i)) for i in range(reader.getRBFPoseCount())]
        self.pose_inputs = [list(reader.getRBFPoseInputControlIndices(i)) for i in range(reader.getRBFPoseCount())]
        self.solvers = []
        for index in reader.getRBFSolverIndicesForLOD(lod):
            if reader.getRBFSolverType(index) != dna.RBFSolverType_Interpolative:
                raise ValueError('Only interpolative body solvers are currently supported')
            inputs = np.array(list(reader.getRBFSolverRawControlIndices(index)), dtype=np.int64)
            poses = list(reader.getRBFSolverPoseIndices(index))
            source = np.array(list(reader.getRBFSolverRawControlValues(index)), dtype=np.float32).reshape(len(poses), len(inputs))
            method, axis = int(reader.getRBFSolverDistanceMethod(index)), int(reader.getRBFSolverTwistAxis(index))
            targets = np.array([project_quaternions(t, method, axis) for t in source]) if method else source.copy()
            pairwise = np.array([distances(targets, target, method) for target in targets])
            # The native implementation fills one triangle then mirrors it.
            pairwise = np.triu(pairwise) + np.triu(pairwise, 1).T
            radius = math.radians(reader.getRBFSolverRadius(index))
            if reader.getRBFSolverAutomaticRadius(index) == dna.AutomaticRadius_On:
                if len(poses) < 2:
                    raise ValueError('Automatic radius needs at least two body poses')
                radius = float(pairwise[np.triu_indices(len(poses), 1)].mean())
            function = int(reader.getRBFSolverFunctionType(index))
            matrix = kernel(pairwise, radius, function)
            try:
                coefficients = np.linalg.inv(matrix)
            except np.linalg.LinAlgError as exc:
                raise ValueError('Singular body RBF target matrix') from exc
            self.solvers.append(Solver(str(reader.getRBFSolverName(index)), inputs, poses,
                source, targets, method, axis, radius, function, coefficients,
                reader.getRBFSolverNormalizeMethod(index) == dna.RBFNormalizeMethod_AlwaysNormalize,
                reader.getRBFSolverWeightThreshold(index),
                np.array([reader.getRBFPoseScale(p) for p in poses], dtype=np.float32)))

    def evaluate(self, raw):
        controls = np.zeros(self.offset+self.count, dtype=np.float32)
        controls[:self.raw_count] = raw
        for solver in self.solvers:
            outputs = {out for pose in solver.poses for out in self.pose_outputs[pose]}
            for out in outputs:
                controls[out] = 0
            for pose, weight in zip(solver.poses, solver.weights(controls)):
                multiplier = float(np.prod(controls[self.pose_inputs[pose]]))
                for out, scale in zip(self.pose_outputs[pose], self.pose_weights[pose]):
                    controls[out] += weight*scale*multiplier
        return controls[self.offset:]
