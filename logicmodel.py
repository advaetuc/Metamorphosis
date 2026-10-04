"""Numpy model of a MetaHuman head's RigLogic behavior (no ``bpy`` dependency).

RigLogic turns face-board (GUI) controls into joint transforms in four stages:

1. GUI controls -> raw controls   (piece-wise linear "conditional table")
2. raw controls -> PSD controls   (products of raw controls)
3. [raw | PSD] -> joint deltas    (a plain *linear* matrix per joint group)
4. [raw | PSD] -> blend shape weights (copy)

Stage 3 and 4 are exact linear maps that are read straight from the DNA. Stage 1
and 2 are small enough to express as Blender drivers. Because the exact algebra of
stage 1/2 is an implementation detail of RigLogic, this module keeps a short list
of candidate interpretations ("variants") and ``verify.py`` picks the one that
reproduces the real RigLogic output. If none does, nothing gets baked.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import ATTRS_PER_JOINT

# DNA raw-control quaternion axis -> index into a Blender quaternion (w, x, y, z)
QUAT_AXES = {"qw": 0, "qx": 1, "qy": 2, "qz": 3}
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


@dataclass
class GuiControl:
    index: int
    name: str
    bone: str
    axis: int  # 0=x 1=y 2=z, -1 if unknown


@dataclass
class QuatInput:
    raw_index: int
    bone: str
    component: int  # index into Blender (w, x, y, z)


@dataclass(frozen=True)
class Variant:
    """One candidate interpretation of the PSD stage."""

    psd_row_base: int  # value subtracted from the PSD *output* indices to get a 0-based PSD index
    psd_mode: str  # "prod_w" | "prod" | "sum" | "mixed" (per-PSD modes in ``RigLogicModel.psd_mode_map``)
    swap: bool = False  # True: DNA "columns" are the PSD outputs and "rows" the inputs

    def label(self) -> str:
        side = "cols" if self.swap else "rows"
        return f"psd_{side}-{self.psd_row_base}/{self.psd_mode}"


def _arr(seq, dtype):
    return np.asarray(list(seq), dtype=dtype)


class RigLogicModel:
    def __init__(self):
        self.joint_names: list[str] = []
        self.joint_parents: list[int] = []
        self.gui: list[GuiControl] = []
        self.raw_names: list[str] = []
        self.quat_inputs: dict[int, QuatInput] = {}
        self.raw_count = 0
        self.psd_count = 0
        self.g2r_in = np.zeros(0, np.int64)
        self.g2r_out = np.zeros(0, np.int64)
        self.g2r_from = np.zeros(0, np.float64)
        self.g2r_to = np.zeros(0, np.float64)
        self.g2r_slope = np.zeros(0, np.float64)
        self.g2r_cut = np.zeros(0, np.float64)
        self.psd_rows = np.zeros(0, np.int64)
        self.psd_cols = np.zeros(0, np.int64)
        self.psd_vals = np.zeros(0, np.float64)
        self.psd_base_auto = 0
        self.psd_base_auto_swapped = 0
        self.psd_mode_map: dict[int, str] = {}
        self.raw_clamp: dict[int, tuple] = {}  # raw index -> (lo, hi); ``None`` means unbounded on that side
        self.matrix = np.zeros((0, 0), np.float32)
        self.bs_in = np.zeros(0, np.int64)
        self.bs_out = np.zeros(0, np.int64)
        self.rbf_joints: set[int] = set()
        self.warnings: list[str] = []
        self._psd_cache: dict = {}

    # ------------------------------------------------------------------ reading
    @classmethod
    def from_reader(cls, reader) -> "RigLogicModel":
        m = cls()
        joint_count = int(reader.getJointCount())
        m.joint_names = [str(reader.getJointName(i)) for i in range(joint_count)]
        m.joint_parents = [int(reader.getJointParentIndex(i)) for i in range(joint_count)]
        joint_lookup = {name: i for i, name in enumerate(m.joint_names)}

        for index in range(int(reader.getGUIControlCount())):
            full = str(reader.getGUIControlName(index))
            bone, _, axis = full.rpartition(".")
            axis_index = _AXIS_INDEX.get(axis[-1:].lower(), -1)
            m.gui.append(GuiControl(index, full, bone or full, axis_index))

        m.raw_count = int(reader.getRawControlCount())
        for index in range(m.raw_count):
            full = str(reader.getRawControlName(index))
            m.raw_names.append(full)
            bone, _, axis = full.rpartition(".")
            if bone in joint_lookup and axis in QUAT_AXES:
                m.quat_inputs[index] = QuatInput(index, bone, QUAT_AXES[axis])

        m.g2r_in = _arr(reader.getGUIToRawInputIndices(), np.int64)
        m.g2r_out = _arr(reader.getGUIToRawOutputIndices(), np.int64)
        m.g2r_from = _arr(reader.getGUIToRawFromValues(), np.float64)
        m.g2r_to = _arr(reader.getGUIToRawToValues(), np.float64)
        m.g2r_slope = _arr(reader.getGUIToRawSlopeValues(), np.float64)
        m.g2r_cut = _arr(reader.getGUIToRawCutValues(), np.float64)
        sizes = {a.size for a in (m.g2r_in, m.g2r_out, m.g2r_from, m.g2r_to, m.g2r_slope, m.g2r_cut)}
        if len(sizes) > 1:
            raise ValueError("GUI-to-raw conditional table arrays have different lengths")

        m.psd_count = int(reader.getPSDCount())
        m.psd_rows = _arr(reader.getPSDRowIndices(), np.int64)
        m.psd_cols = _arr(reader.getPSDColumnIndices(), np.int64)
        m.psd_vals = _arr(reader.getPSDValues(), np.float64)
        if not (m.psd_rows.size == m.psd_cols.size == m.psd_vals.size):
            raise ValueError("PSD matrix arrays have different lengths")
        m.psd_base_auto = m._auto_base(m.psd_rows)
        m.psd_base_auto_swapped = m._auto_base(m.psd_cols)

        # ---- joint matrix: rows = joint attributes, cols = [raw | psd]
        ucount = m.ucount
        rows_total = joint_count * ATTRS_PER_JOINT
        matrix = np.zeros((rows_total, ucount), dtype=np.float32)
        for group in range(int(reader.getJointGroupCount())):
            out_idx = _arr(reader.getJointGroupOutputIndices(group), np.int64)
            in_idx = _arr(reader.getJointGroupInputIndices(group), np.int64)
            values = _arr(reader.getJointGroupValues(group), np.float32)
            rows, cols = out_idx.size, in_idx.size
            if rows == 0 or cols == 0:
                continue
            if rows * cols != values.size:
                raise ValueError(
                    f"Joint group {group}: {rows} outputs x {cols} inputs does not match {values.size} values"
                )
            if out_idx.max() >= rows_total or in_idx.max() >= ucount:
                raise ValueError(f"Joint group {group} references indices outside of the rig")
            matrix[np.ix_(out_idx, in_idx)] += values.reshape(rows, cols)
        m.matrix = matrix

        m.bs_in = _arr(reader.getBlendShapeChannelInputIndices(), np.int64)
        m.bs_out = _arr(reader.getBlendShapeChannelOutputIndices(), np.int64)

        try:
            for solver in range(int(reader.getRBFSolverCount())):
                for pose in reader.getRBFSolverPoseIndices(solver):
                    for attr in reader.getRBFPoseJointOutputIndices(pose):
                        m.rbf_joints.add(int(attr) // ATTRS_PER_JOINT)
        except Exception as error:  # noqa: BLE001 - RBF data is optional
            m.warnings.append(f"RBF data could not be read ({type(error).__name__}: {error})")
        if m.rbf_joints:
            m.warnings.append(
                f"{len(m.rbf_joints)} joints are also driven by RBF solvers (neck/head pose correctives). "
                "Those pose-based correctives are not baked; the face-board driven part is."
            )
        return m

    # ------------------------------------------------------------------ helpers
    def _auto_base(self, indices: np.ndarray) -> int:
        if indices.size and indices.min() >= self.raw_count and indices.max() < self.raw_count + self.psd_count:
            return self.raw_count
        return 0

    @property
    def ucount(self) -> int:
        return self.raw_count + self.psd_count

    @property
    def joint_count(self) -> int:
        return len(self.joint_names)

    def default_raw(self) -> np.ndarray:
        raw = np.zeros(self.raw_count, np.float64)
        for index, quat in self.quat_inputs.items():
            if quat.component == 0:  # qw
                raw[index] = 1.0
        return raw

    def gui_ranges(self) -> np.ndarray:
        """(G, 2) array with the value range every GUI control can usefully take."""
        ranges = np.zeros((len(self.gui), 2), np.float64)
        ranges[:, 1] = 1.0
        for g in range(len(self.gui)):
            sel = self.g2r_in == g
            if sel.any():
                lo = float(self.g2r_from[sel].min())
                hi = float(self.g2r_to[sel].max())
                ranges[g] = (max(lo, -1.0), min(hi, 1.0)) if lo < hi else (0.0, 1.0)
        return ranges

    def clamp_ranges(self) -> dict[int, tuple[float, float]]:
        """Per GUI control: the span covered by its conditional-table rows (clamped to +-10)."""
        out = {}
        for g in range(len(self.gui)):
            sel = self.g2r_in == g
            if sel.any():
                out[g] = (max(float(self.g2r_from[sel].min()), -10.0), min(float(self.g2r_to[sel].max()), 10.0))
        return out

    def variants(self) -> list[Variant]:
        out: list[Variant] = []
        for swap in (False, True):
            auto = self.psd_base_auto_swapped if swap else self.psd_base_auto
            bases = [auto] + [b for b in (0, self.raw_count) if b != auto]
            for base in bases:
                for mode in ("prod_w", "prod", "sum"):
                    out.append(Variant(base, mode, swap))
        return out

    def psd_groups(self, base: int, swap: bool = False):
        """PSD entries grouped per PSD index: list of ``(psd_index, input_cols, weights)`` or ``None`` if invalid."""
        cache_key = (base, swap)
        if cache_key in self._psd_cache:
            return self._psd_cache[cache_key]
        outputs = self.psd_cols if swap else self.psd_rows
        inputs = self.psd_rows if swap else self.psd_cols
        rel = outputs - base
        valid = True
        if rel.size and (rel.min() < 0 or rel.max() >= self.psd_count):
            valid = False
        if inputs.size and inputs.max() >= self.ucount:
            valid = False
        if not valid:
            self._psd_cache[cache_key] = None
            return None
        groups = []
        if rel.size:
            order = np.argsort(rel, kind="stable")
            rel_s, cols_s, vals_s = rel[order], inputs[order], self.psd_vals[order]
            cuts = np.flatnonzero(np.diff(rel_s)) + 1
            for idx in np.split(np.arange(rel_s.size), cuts):
                groups.append((int(rel_s[idx[0]]), cols_s[idx], vals_s[idx]))
        self._psd_cache[cache_key] = groups
        return groups

    def psd_value(self, mode: str, values: np.ndarray, weights: np.ndarray) -> np.ndarray:
        """Evaluate one PSD from its input values ``(S, n)`` and weights ``(n,)``.

        ``mode`` is ``prod_w`` / ``prod`` / ``sum``; a ``_c`` suffix additionally clamps the result to [0, 1]."""
        clamp = mode.endswith("_c")
        base = mode[:-2] if clamp else mode
        if base == "prod_w":
            value = np.prod(values * weights, axis=1)
        elif base == "prod":
            value = np.prod(values, axis=1)
        else:
            value = (values * weights).sum(axis=1)
        return np.clip(value, 0.0, 1.0) if clamp else value

    # --------------------------------------------------------------- evaluation
    def compute_u(self, gui: np.ndarray, raw_default: np.ndarray, variant: Variant) -> np.ndarray | None:
        """Evaluate GUI -> raw -> PSD for ``S`` samples. Returns ``(S, ucount)`` or ``None`` if invalid."""
        groups = self.psd_groups(variant.psd_row_base, variant.swap)
        if groups is None:
            return None
        u = self.compute_raw(gui, raw_default)
        for k, cols, weights in groups:
            mode = self.psd_mode_map.get(k, "prod_w") if variant.psd_mode == "mixed" else variant.psd_mode
            u[:, self.raw_count + k] = self.psd_value(mode, u[:, cols], weights)
        return u

    def compute_raw(self, gui: np.ndarray, raw_default: np.ndarray) -> np.ndarray:
        """``(S, ucount)`` array with the raw controls filled in and the PSD part zero."""
        u = np.zeros((gui.shape[0], self.ucount), np.float64)
        u[:, : self.raw_count] = raw_default
        for i in range(self.g2r_in.size):
            x = gui[:, self.g2r_in[i]]
            active = (x >= self.g2r_from[i]) & (x <= self.g2r_to[i])
            u[:, self.g2r_out[i]] += np.where(active, x * self.g2r_slope[i] + self.g2r_cut[i], 0.0)
        for r, (lo, hi) in self.raw_clamp.items():
            u[:, r] = np.clip(u[:, r], -np.inf if lo is None else lo, np.inf if hi is None else hi)
        return u

    def joint_delta(self, u: np.ndarray) -> np.ndarray:
        """Joint attribute deltas ``(S, joints*9)`` for the given ``[raw | psd]`` values."""
        return (u.astype(np.float32) @ self.matrix.T).astype(np.float64)

    FACE_ONLY_SAMPLES = 20  # samples [0, 20) keep every driver-bone quaternion at identity

    def make_samples(self, count: int = 28, seed: int = 20240607):
        """Deterministic GUI/quaternion test poses: neutral, single controls, sparse and dense mixes.

        The first ``FACE_ONLY_SAMPLES`` poses only move the face board; the rest also rotate the
        driver bones (head/neck), which is where RigLogic's pose-based correctives (RBF) act."""
        rng = np.random.default_rng(seed)
        ranges = self.gui_ranges()
        n_gui = len(self.gui)
        gui = np.zeros((count, n_gui), np.float64)
        raw = np.tile(self.default_raw(), (count, 1))
        span = ranges[:, 1] - ranges[:, 0]
        for s in range(1, count):
            if s <= 6 and n_gui:  # one control at a time
                pick = rng.integers(0, n_gui)
                gui[s, pick] = ranges[pick, 0] + span[pick] * rng.uniform(0.3, 1.0)
            else:
                density = 0.08 if s % 2 else 0.5
                mask = rng.random(n_gui) < density
                gui[s] = np.where(mask, ranges[:, 0] + span * rng.random(n_gui), 0.0)
            if s >= self.FACE_ONLY_SAMPLES and self.quat_inputs:
                bones: dict[str, dict[int, int]] = {}
                for index, quat in self.quat_inputs.items():
                    bones.setdefault(quat.bone, {})[quat.component] = index
                for comps in bones.values():
                    axis = rng.normal(size=3)
                    axis /= np.linalg.norm(axis) + 1e-12
                    angle = np.radians(rng.uniform(0.0, 15.0))
                    q = np.array([np.cos(angle / 2), *(np.sin(angle / 2) * axis)])
                    for comp, index in comps.items():
                        raw[s, index] = q[comp]
        return gui, raw
