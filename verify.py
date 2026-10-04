"""Check (and calibrate) the numpy model against the real RigLogic runtime.

The baked drivers are only trustworthy if they reproduce RigLogic. This module drives the native
RigLogic with test poses and compares, stage by stage, with :class:`RigLogicModel`:

1. GUI controls -> raw controls   (RigInstance.getRawControl)
2. raw -> PSD controls            (RigInstance.getPSDControl)
3. controls -> joint outputs      (RigInstance.getJointOutputs)

Stage 1 and 2 are *calibrated* from the oracle values (which clamp/product/sum interpretation each
raw/PSD control follows), because their exact algebra is an implementation detail of RigLogic.
Stage 3 is the final truth and decides pass/fail.

Two kinds of poses are used. *Face-only* poses move the face board and keep the head/neck driver
bones at rest; these must match. *Pose* poses also rotate the driver bones, where RigLogic adds RBF
pose correctives that are not baked; joints that only differ there are listed, not treated as errors.
Joints that RBF poses write to directly are excluded from the comparison and reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .constants import ATTRS_PER_JOINT
from .logicmodel import RigLogicModel, Variant

TOLERANCE = 5e-3  # max error relative to max(|reference|, 1.0), per attribute type
PSD_MODES = ("prod_w", "prod", "sum", "prod_w_c", "prod_c", "sum_c")
CLAMPS = (None, (0.0, 1.0), (0.0, None), (None, 1.0))


@dataclass
class VerifyResult:
    status: str = "unverified"  # "verified" | "failed" | "unverified"
    variant: Variant | None = None
    error: float = float("nan")
    errors_by_type: dict = field(default_factory=dict)
    blendshape_error: float | None = None
    samples: int = 0
    message: str = ""
    details: list = field(default_factory=list)
    pose_joints: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "verified"


@dataclass
class Oracle:
    joints: np.ndarray
    blendshapes: list
    raw: np.ndarray | None = None
    psd: np.ndarray | None = None
    notes: list = field(default_factory=list)


def run_oracle(model: RigLogicModel, riglogic, reader, gui, raw_default, release=None) -> Oracle:
    """Evaluate the poses with the native RigLogic."""
    # Same construction as Poly Hammer's rig_instance.py (default Configuration: Euler joint outputs)
    manager = riglogic.RigLogic(reader, riglogic.Configuration(), None)
    instance = riglogic.RigInstance(rigLogic=manager, memRes=None)
    joint_outputs, blendshape_outputs, raw_values, psd_values = [], [], [], []
    notes = []
    raw_ok = psd_ok = True
    try:
        for s in range(gui.shape[0]):
            for control in model.gui:
                instance.setGUIControl(control.index, float(gui[s, control.index]))
            manager.mapGUIToRawControls(instance)
            for raw_index in model.quat_inputs:
                instance.setRawControl(raw_index, float(raw_default[s, raw_index]))
            manager.calculate(instance)
            joint_outputs.append(np.asarray(list(instance.getJointOutputs()), dtype=np.float64))
            try:
                blendshape_outputs.append(np.asarray(list(instance.getBlendShapeOutputs()), dtype=np.float64))
            except Exception:  # noqa: BLE001
                blendshape_outputs.append(None)
            if raw_ok:
                try:
                    raw_values.append([float(instance.getRawControl(i)) for i in range(model.raw_count)])
                except Exception as error:  # noqa: BLE001
                    raw_ok = False
                    notes.append(f"getRawControl unavailable: {error}")
            if psd_ok and model.psd_count:
                try:
                    psd_values.append([float(instance.getPSDControl(i)) for i in range(model.psd_count)])
                except Exception as error:  # noqa: BLE001
                    psd_ok = False
                    notes.append(f"getPSDControl unavailable: {error}")
    finally:
        if release is not None:
            release(instance)
            release(manager)
    return Oracle(
        joints=np.vstack(joint_outputs),
        blendshapes=blendshape_outputs,
        raw=np.asarray(raw_values) if raw_ok and raw_values else None,
        psd=np.asarray(psd_values) if psd_ok and psd_values else None,
        notes=notes,
    )


def excluded_joints(model: RigLogicModel) -> set[int]:
    """Joints that are RigLogic *inputs* (driver bones) or that RBF poses write to directly."""
    skip = {model.joint_names.index(q.bone) for q in model.quat_inputs.values()}
    return skip | set(model.rbf_joints)


def comparison_mask(model: RigLogicModel) -> np.ndarray:
    mask = np.ones(model.joint_count * ATTRS_PER_JOINT, bool)
    for joint in excluded_joints(model):
        mask[joint * ATTRS_PER_JOINT : (joint + 1) * ATTRS_PER_JOINT] = False
    return mask


def attribute_errors(ours: np.ndarray, reference: np.ndarray, mask: np.ndarray) -> dict:
    errors = {}
    attr = np.arange(ours.shape[1]) % ATTRS_PER_JOINT
    for name, lo, hi in (("translation", 0, 3), ("rotation", 3, 6), ("scale", 6, 9)):
        cols = mask & (attr >= lo) & (attr < hi)
        if not cols.any() or ours.shape[0] == 0:
            errors[name] = 0.0
            continue
        diff = np.abs(ours[:, cols] - reference[:, cols]).max()
        scale = max(float(np.abs(reference[:, cols]).max()), 1.0)
        errors[name] = float(diff / scale)
    return errors


# ------------------------------------------------------------------ calibration
def calibrate_raw_clamps(model: RigLogicModel, gui, raw_default, oracle: Oracle, details: list) -> None:
    """Per raw control: pick the clamp (none, [0,1], ...) that reproduces the oracle's raw values."""
    if oracle.raw is None:
        return
    model.raw_clamp = {}
    ours = model.compute_raw(gui, raw_default)[:, : model.raw_count]
    rows_by_raw = {}
    for out in model.g2r_out.tolist():
        rows_by_raw[out] = True
    fixed = 0
    for r in rows_by_raw:
        if r in model.quat_inputs:
            continue
        reference = oracle.raw[:, r]
        best = None
        for clamp in CLAMPS:
            lo, hi = clamp if clamp else (None, None)
            value = np.clip(ours[:, r], -np.inf if lo is None else lo, np.inf if hi is None else hi)
            error = float(np.abs(value - reference).max())
            if best is None or error < best[0] - 1e-9:
                best = (error, clamp)
            if clamp is None and error < 1e-4:
                break
        if best[1] is not None:
            model.raw_clamp[r] = best[1]
            fixed += 1
    if fixed:
        details.append(f"Stage 1: {fixed} raw controls need clamping (calibrated from RigLogic)")


def fit_psd_modes(model: RigLogicModel, oracle: Oracle):
    """Per PSD, pick the formula that reproduces the oracle PSD values from the oracle's own inputs.

    Returns ``(variant, modes, total_error)`` for the best table orientation, or ``None``.
    """
    if oracle.raw is None or oracle.psd is None:
        return None
    u_oracle = np.concatenate([oracle.raw, oracle.psd], axis=1)
    best = None
    for swap in (False, True):
        for base in sorted({0, model.raw_count}):
            groups = model.psd_groups(base, swap)
            if groups is None:
                continue
            modes, total = {}, 0.0
            covered = set()
            for k, cols, weights in groups:
                covered.add(k)
                errors = [
                    float(np.abs(model.psd_value(m, u_oracle[:, cols], weights) - oracle.psd[:, k]).max())
                    for m in PSD_MODES
                ]
                index = min(range(len(PSD_MODES)), key=lambda i: (round(errors[i], 5), i))
                modes[k] = PSD_MODES[index]
                total += errors[index]
            for k in range(model.psd_count):
                if k not in covered:
                    total += float(np.abs(oracle.psd[:, k]).max())
            if best is None or total < best[2]:
                best = (Variant(base, "mixed", swap), modes, total)
    return best


def _worst_cells(model, ours, reference, mask, limit=10):
    diff = np.abs(ours - reference)
    diff[:, ~mask] = 0.0
    flat = diff.max(axis=0)
    lines = []
    for col in np.argsort(flat)[::-1][:limit]:
        if flat[col] <= 0:
            break
        joint, attr = divmod(int(col), ATTRS_PER_JOINT)
        row = int(np.argmax(diff[:, col]))
        lines.append(
            f"  {model.joint_names[joint]} attr{attr}: RigLogic {reference[row, col]:+.5f} vs baked {ours[row, col]:+.5f}"
        )
    return lines


def verify_model(model: RigLogicModel, riglogic, reader, release=None) -> VerifyResult:
    """Calibrate the stages against RigLogic and verify the joint outputs."""
    result = VerifyResult()
    details = result.details
    details.append(
        f"Rig: {len(model.gui)} GUI controls, {model.raw_count} raw, {model.psd_count} PSD, "
        f"{model.joint_count} joints, {int((model.matrix != 0).sum())} joint weights, "
        f"{model.g2r_in.size} GUI-to-raw rows, {model.psd_rows.size} PSD entries, "
        f"{len(model.quat_inputs)} quaternion inputs, {len(model.rbf_joints)} RBF-written joints"
    )
    if riglogic is None:
        result.message = "The bindings do not include the RigLogic runtime, so the baked rig could not be verified."
        return result

    gui, raw_default = model.make_samples()
    result.samples = gui.shape[0]
    try:
        oracle = run_oracle(model, riglogic, reader, gui, raw_default, release)
    except Exception as error:  # noqa: BLE001 - API differences between binding builds
        result.message = f"RigLogic could not be driven for verification ({type(error).__name__}: {error})."
        return result
    details.append(f"Oracle exposes raw controls: {oracle.raw is not None}, PSD controls: {oracle.psd is not None}")
    details += oracle.notes

    reference = oracle.joints - oracle.joints[0]
    mask = comparison_mask(model)
    if float(np.abs(reference[:, mask]).max()) < 1e-6:
        result.message = "RigLogic produced no joint motion for the test poses; the rig could not be verified."
        return result

    split = model.FACE_ONLY_SAMPLES
    face, pose = slice(0, split), slice(split, gui.shape[0])

    # ---- stage 1
    calibrate_raw_clamps(model, gui, raw_default, oracle, details)
    if oracle.raw is not None:
        ours_raw = model.compute_raw(gui, raw_default)[:, : model.raw_count]
        keep = np.ones(model.raw_count, bool)
        keep[list(model.quat_inputs)] = False
        per_raw = np.abs(ours_raw - oracle.raw).max(axis=0) * keep
        error = float(per_raw.max()) if keep.any() else 0.0
        details.append(f"Stage 1 (GUI -> raw) max abs error after calibration: {error:.3e}")
        if error > 1e-3:
            for r in np.argsort(per_raw)[::-1][:6]:
                details.append(
                    f"  raw {int(r)} '{model.raw_names[int(r)]}': RigLogic range "
                    f"[{oracle.raw[:, r].min():.4f}, {oracle.raw[:, r].max():.4f}] vs ours "
                    f"[{ours_raw[:, r].min():.4f}, {ours_raw[:, r].max():.4f}]"
                )

    # ---- stage 2 + candidates
    candidates = list(model.variants())
    fitted = fit_psd_modes(model, oracle)
    if fitted is not None:
        variant, modes, total = fitted
        model.psd_mode_map = modes
        candidates.insert(0, variant)
        counts = {m: sum(1 for v in modes.values() if v == m) for m in PSD_MODES}
        details.append(f"Stage 2 per-PSD fit ({variant.label()}): total abs error {total:.3e}, modes {counts}")

    best, table = None, []
    for variant in candidates:
        u = model.compute_u(gui, raw_default, variant)
        if u is None:
            continue
        ours = model.joint_delta(u)
        ours = ours - ours[0]
        errors = attribute_errors(ours[face], reference[face], mask)
        worst = max(errors.values())
        table.append(f"  {variant.label():<26} face-only error {worst:.3e}")
        if best is None or worst < best[0]:
            best = (worst, variant, errors, ours, u)
        if worst <= TOLERANCE:
            break
    details.append("Candidate interpretations (stage 3, joint outputs):")
    details += table[:14]

    if best is None:
        result.status = "failed"
        result.message = "No valid interpretation of the PSD table was found."
        return result

    worst, variant, errors, ours, u = best
    result.variant, result.error, result.errors_by_type = variant, worst, errors

    if model.bs_in.size and oracle.blendshapes and oracle.blendshapes[0] is not None:
        try:
            ref_bs = np.vstack(oracle.blendshapes)
            ours_bs = np.zeros_like(ref_bs)
            ours_bs[:, model.bs_out] = u[:, model.bs_in]
            result.blendshape_error = float(np.abs(ours_bs[face] - ref_bs[face]).max() / max(np.abs(ref_bs).max(), 1.0))
        except Exception:  # noqa: BLE001
            result.blendshape_error = None

    if worst > TOLERANCE:
        result.status = "failed"
        result.message = (
            f"The baked rig does NOT match RigLogic on face-board poses "
            f"(max relative error {worst:.2e} > {TOLERANCE:.0e}). Nothing was baked."
        )
        details.append("Worst mismatches in the best candidate (face-only poses):")
        details += _worst_cells(model, ours[face], reference[face], mask)
        return result

    attr = np.arange(ours.shape[1]) % ATTRS_PER_JOINT
    scale = np.ones(ATTRS_PER_JOINT)
    for lo, hi in ((0, 3), (3, 6), (6, 9)):
        cols = mask & (attr >= lo) & (attr < hi)
        scale[lo:hi] = max(float(np.abs(reference[:, cols]).max()), 1.0) if cols.any() else 1.0
    if pose.stop > pose.start:
        relative = np.abs(ours[pose] - reference[pose]) / scale[attr]
        relative[:, ~mask] = 0.0
        per_joint = relative.reshape(relative.shape[0], model.joint_count, ATTRS_PER_JOINT).max(axis=(0, 2))
        result.pose_joints = [model.joint_names[j] for j in np.flatnonzero(per_joint > TOLERANCE)]

    result.status = "verified"
    result.message = f"Baked rig matches RigLogic on {split} face-board test poses (max error {worst:.2e})."
    if model.rbf_joints:
        result.message += f" {len(model.rbf_joints)} RBF-driven joints are excluded (not baked)."
    if result.pose_joints:
        result.message += (
            f" {len(result.pose_joints)} joints also react to head/neck rotation in a way that is not baked."
        )
        details.append("Joints with un-baked head/neck pose correctives: " + ", ".join(result.pose_joints[:20]))
    return result
