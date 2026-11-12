"""Deterministic surface displacement transfer; no Blender animation callbacks.

An affine component exactly reproduces translation/scale/shear. Local residuals
use compact inverse-distance interpolation. This is an anatomical approximation,
not a reconstruction of muscles or of Epic's trained correctives.
"""
import numpy as np
from mathutils.kdtree import KDTree


class SurfaceField:
    def __init__(self, source, target, neighbors=12):
        self.source = np.asarray(source, dtype=np.float64)
        self.target = np.asarray(target, dtype=np.float64)
        if self.source.shape != self.target.shape or self.source.ndim != 2 or self.source.shape[1] != 3:
            raise ValueError('Sculpt vertex count does not match the DNA')
        if not np.isfinite(self.target).all():
            raise ValueError('Sculpt contains non-finite coordinates')
        self.center = self.source.mean(axis=0)
        self.size = max(float(np.ptp(self.source, axis=0).max()), 1e-8)
        self.x = (self.source-self.center)/self.size
        design = np.column_stack((self.x, np.ones(len(self.x))))
        self.affine = np.linalg.lstsq(design, (self.target-self.source)/self.size, rcond=None)[0]
        self.residual = (self.target-self.source)/self.size - design @ self.affine
        self.linear = np.eye(3) + self.affine[:3].T
        self.is_affine = np.max(np.abs(self.residual)) < 2e-7
        self.identity = np.max(np.abs(self.target-self.source)) < 2e-7*self.size
        if self.identity:
            self.affine[:] = 0
            self.residual[:] = 0
            self.linear = np.eye(3)
            self.is_affine = True
        self.k = min(neighbors, len(self.x))
        self.tree = KDTree(len(self.x))
        for i, p in enumerate(self.x):
            self.tree.insert(p, i)
        self.tree.balance()

    def evaluate(self, points, jacobian=False):
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        x = (points-self.center)/self.size
        delta = x @ self.affine[:3] + self.affine[3]
        jac = np.broadcast_to(self.linear, (len(x), 3, 3)).copy() if jacobian else None
        if not self.is_affine:
            # Batches bound memory for high-resolution LOD0 and sparse targets.
            for start in range(0, len(x), 4096):
                q = x[start:start+4096]
                nearest = [self.tree.find_n(p, self.k) for p in q]
                idx = np.array([[v[1] for v in row] for row in nearest])
                diff = q[:, None, :] - self.x[idx]
                dist2 = np.einsum('nki,nki->nk', diff, diff) + 1e-14
                w = 1/dist2**2
                w /= w.sum(axis=1, keepdims=True)
                residual = self.residual[idx]
                blend = np.einsum('nk,nki->ni', w, residual)
                delta[start:start+len(q)] += blend
                if jacobian:
                    # A local least-squares differential remains useful at an
                    # interpolation knot, where an IDW derivative is zero.
                    fit_w = 1/(dist2 + dist2.max(axis=1, keepdims=True)*.05)
                    fit_w /= fit_w.sum(axis=1, keepdims=True)
                    dx = -diff
                    dx -= np.einsum('nk,nki->ni', fit_w, dx)[:, None, :]
                    dy = residual-np.einsum('nk,nki->ni', fit_w, residual)[:, None, :]
                    gram = np.einsum('nk,nki,nkj->nij', fit_w, dx, dx)
                    ridge = np.maximum(np.trace(gram, axis1=1, axis2=2)*1e-4, 1e-12)
                    gram += ridge[:, None, None]*np.eye(3)
                    rhs = np.einsum('nk,nki,nkj->nij', fit_w, dx, dy)
                    jac[start:start+len(q)] += np.linalg.solve(gram, rhs).transpose(0, 2, 1)
        result = points + delta*self.size
        if jacobian:
            if not np.isfinite(jac).all() or np.any(np.linalg.det(jac) <= 0):
                raise ValueError('Sculpt folds the displacement field; reduce the edit before baking')
            return result, jac
        return result

    def deltas(self, points, deltas):
        return self.evaluate(np.asarray(points)+deltas)-self.evaluate(points)


def symmetry_pairs(points):
    """Mutual nearest pairs prevent multiple vertices overwriting one partner."""
    points = np.asarray(points)
    tree = KDTree(len(points))
    for i, p in enumerate(points):
        tree.insert(p, i)
    tree.balance()
    mirror = points.copy(); mirror[:, 0] *= -1
    pairs = np.array([tree.find(p)[1] for p in mirror], dtype=np.int32)
    valid = pairs[pairs] == np.arange(len(points))
    pairs[~valid] = np.flatnonzero(~valid)
    return pairs


def sync_symmetry(source, previous, current, pairs):
    result = np.asarray(current).copy()
    delta = result-source
    changed = np.linalg.norm(result-previous, axis=1) > 1e-8
    for i, j in enumerate(pairs):
        if i == j and abs(source[i, 0]) < 1e-6:
            delta[i, 0] = 0
        if j <= i:
            continue
        if changed[i] and not changed[j]:
            delta[j] = delta[i]*(-1, 1, 1)
        elif changed[j] and not changed[i]:
            delta[i] = delta[j]*(-1, 1, 1)
        elif changed[i] and changed[j]:
            mean = (delta[i] + delta[j]*(-1, 1, 1))*.5
            delta[i], delta[j] = mean, mean*(-1, 1, 1)
    return source+delta
