"""Describe the baked rig as a graph of drivers (no ``bpy`` dependency).

The plan is a list of :class:`Node` objects in dependency order. Every node is one Blender
driver: it either writes a helper custom property on the data empty (``("prop", name)``),
a bone channel (``("bone", bone, path, index)``) or a shape key weight (``("shape", channel)``).
``bake.py`` realises the plan inside Blender; ``tests`` evaluate it in plain Python and compare
it with the numpy model, which is how the expressions are checked without Blender.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field

import numpy as np

from .constants import ATTRS_PER_JOINT
from .exprplan import fmt_num, plan_prod, plan_sum
from .logicmodel import RigLogicModel, Variant


@dataclass(frozen=True)
class Var:
    """A driver variable. ``kind``: ``prop`` (data-empty property), ``loc`` (face-board bone
    location axis) or ``quat`` (bone rotation_quaternion component)."""

    name: str
    kind: str
    ref: str
    index: int = 0


@dataclass
class Node:
    target: tuple
    dtype: str  # "SCRIPTED" | "SUM"
    expr: str
    vars: list[Var]
    level: str = ""


@dataclass
class Plan:
    nodes: list[Node] = field(default_factory=list)
    props: dict[str, float] = field(default_factory=dict)  # every helper property and its rest value
    euler_bones: set[str] = field(default_factory=set)
    quat_bones: set[str] = field(default_factory=set)
    shape_props: dict[int, str] = field(default_factory=dict)  # blend shape channel -> property to follow
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def gui_prop(index: int) -> str:
    return f"mm_g{index}"


def raw_prop(index: int) -> str:
    return f"mm_r{index}"


def psd_prop(index: int) -> str:
    return f"mm_p{index}"


class _Builder:
    def __init__(self, model: RigLogicModel, variant: Variant, plan: Plan):
        self.model = model
        self.variant = variant
        self.plan = plan
        self.helper_count = 0
        self.emitted: set[str] = set()
        self.in_progress: set[str] = set()
        self.raw_rows: dict[int, list[int]] = {}
        for i, out in enumerate(model.g2r_out.tolist()):
            self.raw_rows.setdefault(out, []).append(i)
        self.psd_group_by_index = {k: (cols, w) for k, cols, w in (model.psd_groups(variant.psd_row_base, variant.swap) or [])}
        self.clamp = model.clamp_ranges()
        self.gui_bone = {c.index: c for c in model.gui}
        self.gui_nodes_done: set[int] = set()
        self.face_board_bones: set[str] | None = None

    # -------------------------------------------------------------- helpers
    def new_helper(self) -> str:
        name = f"mm_h{self.helper_count}"
        self.helper_count += 1
        self.plan.props[name] = 0.0
        return name

    def add_node(self, target, dtype, expr, variables, level) -> None:
        self.plan.nodes.append(Node(target, dtype, expr, variables, level))

    @staticmethod
    def _clamped(expr: str, clamp) -> str:
        """Wrap ``expr`` so the result stays inside ``clamp = (lo, hi)`` (``None`` = unbounded)."""
        if not clamp:
            return expr
        lo, hi = clamp
        if lo is not None:
            expr = f"max({fmt_num(lo)},{expr})"
        if hi is not None:
            expr = f"min({fmt_num(hi)},{expr})"
        return expr

    def emit_chunked(self, terms, joiner: str, final_target, level: str, var_for_key, *, clamp=None):
        """Emit nodes for ``terms`` (sum or product). Returns nothing; writes ``final_target``."""
        chunks = plan_sum(terms) if joiner == "+" else plan_prod(terms)
        if not chunks:
            return False
        if len(chunks) == 1:
            expr, keys = chunks[0]
            variables = [var_for_key(f"v{i}", key) for i, key in enumerate(keys)]
            self.add_node(final_target, "SCRIPTED", self._clamped(expr, clamp), variables, level)
            return True
        helper_vars = []
        for expr, keys in chunks:
            helper = self.new_helper()
            variables = [var_for_key(f"v{i}", key) for i, key in enumerate(keys)]
            self.add_node(("prop", helper), "SCRIPTED", expr, variables, level + "-chunk")
            helper_vars.append(Var(f"h{len(helper_vars)}", "prop", helper))
        if joiner == "+" and not clamp:
            self.add_node(final_target, "SUM", "", helper_vars, level)
        else:
            joined = ("+" if joiner == "+" else "*").join(v.name for v in helper_vars)
            self.add_node(final_target, "SCRIPTED", self._clamped(joined, clamp), helper_vars, level)
        return True

    # ------------------------------------------------------------ GUI / raw
    def ensure_gui(self, g: int) -> str:
        name = gui_prop(g)
        self.plan.props.setdefault(name, 0.0)
        if g in self.gui_nodes_done:
            return name
        self.gui_nodes_done.add(g)
        control = self.gui_bone.get(g)
        span = self.clamp.get(g)
        if control is None or span is None or control.axis < 0:
            return name
        if self.face_board_bones is not None and control.bone not in self.face_board_bones:
            return name
        lo, hi = span
        variables = [Var("v0", "loc", control.bone, control.axis)]
        value = "v0"
        # The DNA lists only the individual gaze controls. Reading their raw
        # location does not include the board's Copy Location constraints.
        # Add the central gaze explicitly, keeping each side freely animatable.
        if (control.bone in {"CTRL_L_eye", "CTRL_R_eye"} and control.axis in {0, 1}
                and self.face_board_bones is not None and "CTRL_C_eye" in self.face_board_bones):
            variables.append(Var("v1", "loc", "CTRL_C_eye", control.axis))
            value = "v0+max(-1,min(1,v1))"
        expr = f"max({fmt_num(lo)},min({fmt_num(hi)},{value}))"
        self.add_node(
            ("prop", name), "SCRIPTED", expr, variables, "gui"
        )
        return name

    def ensure_raw(self, r: int) -> str:
        name = raw_prop(r)
        if name in self.emitted:
            return name
        self.emitted.add(name)
        model = self.model
        quat = model.quat_inputs.get(r)
        if quat is not None:
            self.plan.props[name] = 1.0 if quat.component == 0 else 0.0
            self.plan.quat_bones.add(quat.bone)
            self.add_node(("prop", name), "SUM", "", [Var("q0", "quat", quat.bone, quat.component)], "quat")
            return name
        self.plan.props[name] = 0.0
        rows = self.raw_rows.get(r, [])
        if not rows:
            return name
        terms = []
        for i in rows:
            g = int(model.g2r_in[i])
            gname = self.ensure_gui(g)
            lo, hi = self.clamp.get(g, (-10.0, 10.0))
            f, t = float(model.g2r_from[i]), float(model.g2r_to[i])
            s, c = float(model.g2r_slope[i]), float(model.g2r_cut[i])
            if s == 0.0 and c == 0.0:
                continue
            if s == 0.0:
                value = fmt_num(c, 6)
            elif c == 0.0:
                value = f"{{0}}*{fmt_num(s, 6)}"
            else:
                value = f"({{0}}*{fmt_num(s, 6)}+{fmt_num(c, 6)})"
            cond = ""
            if f > lo + 1e-9:
                cond += f"*({{0}}>={fmt_num(f, 6)})"
            if t < hi - 1e-9:
                cond += f"*({{0}}<={fmt_num(t, 6)})"
            template = value + cond
            keys = [gname] if "{0}" in template else []
            terms.append((template, keys))
        if terms:
            self.emit_chunked(
                terms, "+", ("prop", name), "raw", lambda vn, key: Var(vn, "prop", key),
                clamp=self.model.raw_clamp.get(r),
            )
        return name

    # ----------------------------------------------------------------- PSD
    def ensure_u(self, col: int) -> str:
        if col < self.model.raw_count:
            return self.ensure_raw(col)
        return self.ensure_psd(col - self.model.raw_count)

    def ensure_psd(self, k: int) -> str:
        name = psd_prop(k)
        if name in self.emitted:
            return name
        if name in self.in_progress:
            raise ValueError(f"PSD control {k} depends on itself")
        self.in_progress.add(name)
        self.plan.props[name] = 0.0
        entry = self.psd_group_by_index.get(k)
        if entry is not None:
            cols, weights = entry
            input_names = [self.ensure_u(int(c)) for c in cols]
            mode = self.variant.psd_mode
            if mode == "mixed":
                mode = self.model.psd_mode_map.get(k, "prod_w")
            clamp = (0.0, 1.0) if mode.endswith("_c") else None
            mode = mode[:-2] if mode.endswith("_c") else mode
            if mode == "sum":
                terms = [(f"{fmt_num(w, 6)}*{{0}}", [n]) for w, n in zip(weights.tolist(), input_names)]
                self.emit_chunked(
                    terms, "+", ("prop", name), "psd", lambda vn, key: Var(vn, "prop", key), clamp=clamp
                )
            else:
                coef = float(np.prod(weights)) if mode == "prod_w" else 1.0
                terms = []
                if mode == "prod_w" and abs(coef - 1.0) > 1e-9:
                    terms.append((fmt_num(coef, 6), []))
                terms += [("{0}", [n]) for n in input_names]
                self.emit_chunked(
                    terms, "*", ("prop", name), "psd", lambda vn, key: Var(vn, "prop", key), clamp=clamp
                )
        self.in_progress.discard(name)
        self.emitted.add(name)
        return name


def joint_orientation_inverse(reader, joint_count: int, rotation_degrees: bool) -> np.ndarray:
    """``(J, 3, 3)`` inverse of each joint's neutral orientation (``E^-1``), from Euler XYZ rotations."""
    rx = np.asarray(list(reader.getNeutralJointRotationXs()), np.float64)
    ry = np.asarray(list(reader.getNeutralJointRotationYs()), np.float64)
    rz = np.asarray(list(reader.getNeutralJointRotationZs()), np.float64)
    if rotation_degrees:
        rx, ry, rz = np.radians(rx), np.radians(ry), np.radians(rz)
    out = np.zeros((joint_count, 3, 3), np.float64)
    for j in range(joint_count):
        out[j] = euler_xyz_matrix(rx[j], ry[j], rz[j]).T
    return out


def euler_xyz_matrix(x: float, y: float, z: float) -> np.ndarray:
    """Matrix of a Blender ``XYZ`` Euler (X applied first): ``Rz @ Ry @ Rx``."""
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _keep_within_budget(row: np.ndarray, eps: float) -> np.ndarray:
    """Indices of ``row`` to keep: drop smallest weights while their summed magnitude stays <= ``eps``."""
    nonzero = np.flatnonzero(row)
    if nonzero.size == 0 or eps <= 0.0:
        return nonzero
    magnitude = np.abs(row[nonzero])
    order = np.argsort(magnitude, kind="stable")
    dropped = int(np.searchsorted(np.cumsum(magnitude[order]), eps, side="right"))
    return np.sort(nonzero[order[dropped:]])


def lips_together_columns(model: RigLogicModel, variant: Variant) -> set[int]:
    """Joint correctives driven by the four Lips Together raw controls.

    These controls have no direct joint weights in MetaHuman DNA: their primary
    action is encoded as PSD combinations with jaw motion (and mouth press).
    Discover columns from names/dependencies, since DNA control indices vary.
    """
    names = {f"mouthLipsTogether{side}" for side in ("UL", "UR", "DL", "DR")}
    seeds = {i for i, name in enumerate(model.raw_names) if name.rsplit(".", 1)[-1] in names}
    dependent = set(seeds)
    groups = model.psd_groups(variant.psd_row_base, variant.swap) or []
    while True:
        added = {model.raw_count + k for k, cols, _weights in groups
                 if any(int(col) in dependent for col in cols)} - dependent
        if not added:
            return dependent - seeds
        dependent.update(added)


def build_plan(
    model: RigLogicModel,
    variant: Variant,
    orientation_inverse: np.ndarray,
    *,
    scale: float = 0.01,
    rotation_degrees: bool = True,
    budget: tuple = (0.0, 0.0, 0.0),
    use_psd: bool = True,
    face_board_bones: set[str] | None = None,
    shape_channels: set[int] | None = None,
    skip_bones: set[str] | None = None,
) -> Plan:
    """Build the driver graph.

    Args:
        orientation_inverse: ``(J, 3, 3)`` ``E^-1`` per joint (see :func:`joint_orientation_inverse`).
        scale: multiplier from DNA length units to Blender units (0.01 for centimetres).
        budget: per attribute type (translation m, rotation rad, scale) the largest total error that may be
            dropped from one channel. Weights are removed smallest-first while the sum of the removed
            absolute weights stays within the budget (worst case, with every control at 1.0).
        use_psd: ``False`` drops combination correctives except those required by
            the four Lips Together controls ("Lite").
        face_board_bones: names of the face-board bones that exist; ``None`` means "assume all".
        shape_channels: blend shape channel indices that exist as shape keys in Blender.
        skip_bones: bones that must not be driven (RigLogic inputs, i.e. the quaternion bones).
    """
    plan = Plan()
    builder = _Builder(model, variant, plan)
    builder.face_board_bones = face_board_bones
    skip = set(skip_bones or ()) | {q.bone for q in model.quat_inputs.values()}

    u0 = model.compute_u(np.zeros((1, len(model.gui))), model.default_raw(), variant)
    if u0 is None:
        raise ValueError("The PSD table is not valid for the selected interpretation")
    u0 = u0[0]
    matrix = model.matrix.astype(np.float64)
    lip_columns = lips_together_columns(model, variant) if not use_psd else set()
    if not use_psd:
        matrix = matrix.copy()
        matrix[:, model.raw_count :] = 0.0
        if lip_columns:
            cols = sorted(lip_columns)
            matrix[:, cols] = model.matrix[:, cols]
    base = matrix @ u0  # outputs at the neutral pose (should be ~0)

    angle_factor = math.pi / 180.0 if rotation_degrees else 1.0
    rows_built = 0
    pruned_terms = 0
    kept_terms = 0
    channel_plans = []  # (bone, path, index, cols, weights, const)
    for joint, bone in enumerate(model.joint_names):
        if bone in skip:
            continue
        block = matrix[joint * ATTRS_PER_JOINT : (joint + 1) * ATTRS_PER_JOINT]
        if not block.any():
            continue
        base_block = base[joint * ATTRS_PER_JOINT : (joint + 1) * ATTRS_PER_JOINT]
        q = orientation_inverse[joint]
        combined = np.zeros_like(block)
        combined[0:3] = (q @ block[0:3]) * scale
        combined[3:6] = block[3:6] * angle_factor
        combined[6:9] = block[6:9]
        base_combined = np.zeros(9)
        base_combined[0:3] = (q @ base_block[0:3]) * scale
        base_combined[3:6] = base_block[3:6] * angle_factor
        base_combined[6:9] = base_block[6:9]
        for a in range(9):
            row = combined[a]
            if not use_psd:
                # Preserve the existing Lite pruning of primary expressions.
                # Lip closure weights must not spend that budget or be removed.
                keep = np.concatenate((
                    _keep_within_budget(row[:model.raw_count], budget[a // 3]),
                    np.flatnonzero(row[model.raw_count:]) + model.raw_count,
                ))
            else:
                keep = _keep_within_budget(row, budget[a // 3])
            pruned_terms += int(np.count_nonzero(row)) - keep.size
            const = -float(base_combined[a])
            if a >= 6:
                const += 1.0
            if keep.size == 0 and abs(const - (1.0 if a >= 6 else 0.0)) < 1e-9:
                continue
            path = ("location", "rotation_euler", "scale")[a // 3]
            channel_plans.append((bone, path, a % 3, keep, row[keep], const))
            kept_terms += keep.size
            rows_built += 1

    # shape key channels
    wanted_bs = {}
    if shape_channels:
        for col, channel in zip(model.bs_in.tolist(), model.bs_out.tolist()):
            if channel in shape_channels and (use_psd or col < model.raw_count):
                wanted_bs[channel] = col

    # emit upstream nodes first (GUI -> raw -> PSD), only for columns that something reads
    needed_cols = set()
    for _bone, _path, _idx, cols, _w, _c in channel_plans:
        needed_cols.update(int(c) for c in cols)
    needed_cols.update(wanted_bs.values())
    for col in sorted(needed_cols):
        builder.ensure_u(col)

    # then the bone channels
    for bone, path, index, cols, weights, const in channel_plans:
        terms = []
        if abs(const) > 1e-9:
            terms.append((fmt_num(const, 6), []))
        for col, w in zip(cols.tolist(), weights.tolist()):
            precision = 6 if col in lip_columns else 4
            terms.append((f"{fmt_num(w, precision)}*{{0}}", [builder.ensure_u(int(col))]))
        if not terms:
            continue
        builder.emit_chunked(
            terms, "+", ("bone", bone, path, index), "channel", lambda vn, key: Var(vn, "prop", key)
        )
        plan.euler_bones.add(bone)

    for channel, col in wanted_bs.items():
        plan.shape_props[channel] = builder.ensure_u(col)

    plan.stats = {
        "driven_bones": len(plan.euler_bones),
        "bone_channels": rows_built,
        "terms": kept_terms,
        "pruned_terms": pruned_terms,
        "nodes": len(plan.nodes),
        "properties": len(plan.props),
        "shape_channels": len(plan.shape_props),
        "quat_bones": len(plan.quat_bones),
        "gui_controls": len(builder.gui_nodes_done),
        "lips_together_correctives": len(lip_columns & needed_cols),
    }
    return plan


# ----------------------------------------------------------------- evaluation
def evaluate_plan(plan: Plan, loc: dict, quat: dict | None = None) -> dict:
    """Evaluate the plan in plain Python (used by the tests and the benchmark).

    ``loc[(bone, axis)]`` is a face-board location, ``quat[(bone, component)]`` a bone quaternion
    component (default identity). Returns ``{target: value}`` for bone and shape targets.
    """
    quat = quat or {}
    props = dict(plan.props)
    results = {}
    for node in plan.nodes:
        values = {}
        for var in node.vars:
            if var.kind == "prop":
                values[var.name] = props[var.ref]
            elif var.kind == "loc":
                values[var.name] = float(loc.get((var.ref, var.index), 0.0))
            else:
                values[var.name] = float(quat.get((var.ref, var.index), 1.0 if var.index == 0 else 0.0))
        if node.dtype == "SUM":
            value = sum(values.values())
        else:
            value = float(eval(node.expr, {"__builtins__": {}, "min": min, "max": max}, values))  # noqa: S307
        if node.target[0] == "prop":
            props[node.target[1]] = value
        else:
            results[node.target] = value
    return results
