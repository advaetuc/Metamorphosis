# Update 1.90 - development status

Source version remains **1.8.1**. Update 1.90 is **in progress**, not marked release-complete.

## Refined native body rig & forensic bugfix checkpoint — 2026-11-11

`NATIVE_BRIDGE_2` supersedes the 796-bone `NATIVE_BRIDGE_1` converter and retires `Custom DEF Only` (`body_remap.py` is retained only as a guard stub that raises `ValueError` on `NATIVE_BRIDGE_2` or missing `DEF_SPINE_02`). Current body rigs contain **561 bones** (`219` custom control/mechanism bones + `342` original MetaHuman DNA bones), pruning dead custom `DEF_*`, `DEF_COR_*`, intermediate limb/muscle tweaks, and `ARM_BICEP_FLEXTION` properties/drivers while retaining native RBF/twist-swing correctives (`2,318` corrective drivers on LOD 0 import).

Implemented refinements and verified fixes across `body_refine.py`, `body_converter.py`, `body_geometry.py`, `body_rig.py`, `body_snap.py`, `body_merge.py`, and `body_remap.py`:
- **Spine & Pelvis hierarchy (0 depsgraph cycles):** Separate 5-joint FK spine chain + tweaks (`Spine FK` / `Spine Tweaks`), independent `HIPS` pelvis tilt control (`1:1` pelvis pitch without affecting upper spine/arms), and `CHEST` spine-bend macro parented cleanly under `SPINE_02_FK` with lower-FK `COPY_TRANSFORMS` helpers so `CHEST` stays attached without dependency cycles and works identically in Euler (`XYZ`) and `QUATERNION` rotation modes (location/scale locked).
- **Reverse-foot toe hold:** Unmuted `MCH_TOE.{L|R}` `Copy Rotation` constraint driven by `LEG_FK_IK.{L|R}` so heel rolls in IK hold toes smoothly against the ground (`~32.14°` on `ORG_TOE.L` at `+45° HEEL.L`) instead of rotating `77.14°` downward.
- **Digits, colors & widgets:** X-symmetrized finger/thumb controls and `20` individual constraint-free toe controls (`TOE_{A..E}_{01|02}.{L|R}` in `Toe.L`/`Toe.R`); fixed `.L`/`.R` digit normal colors across metacarpals/phalanges and added lightened `select`/`active` highlight contrast across custom-colored controls; restored anatomical tweak bone lengths/widget sizes; kept custom wire shapes only on final tweakers inside hidden `_WIDGETS` collections (renaming cleanly on upgrade without `.001` leftovers).
- **UI & container cleanup:** Separated torso/neck controls (`TORSO`: `TORSO`, `HIPS`, `CHEST`, `SHOULDER.L/R`, `NECK_01/02_FK`, `HEAD`; `TORSO_TWK`: `PELVIS_TWEAK`, `NECK_01/02_TWEAK`, `HEAD_TWEAK`, `HEAD_TIP_TWEAK`), updated distinct parent-space UI labels in both addon (`MM_PT_body`) and standalone (`MM_PT_standalone_body`) panels, removed empty `RIGLOGICDATA` collections after body import, and cleaned empty face-board bone collections plus hid `DEF_HEAD` when connecting head and body (`body_merge.py`).

All 7 body verification suites passed in **both Blender 5.2.0 LTS and Blender 5.0.0** after final code edits (`tests/blender_body_fixes.py`, `tests/blender_body_converter.py` + `tests/verify_body_converter.py`, `tests/blender_body_import.py`, `tests/blender_body_merge.py`, `tests/blender_body_snap.py`, `tests/blender_body_render.py`, and `tests/blender_body_converter_failures.py`), plus `tests/blender_body_rbf.py` in Blender 5.2.0 LTS:
- Rest precision `4.05e-6` (`< 1e-5`), skin upgrade baseline delta `2.98e-7`, `32`-pair bilateral fingertip/toe mirror parity (`0.000131 m` max diff), posed RigLogic joint parity (`0.000249` max error) & skinned mesh parity (`0.0619 mm` max error), zero invalid drivers, zero dependency cycles, clean Workbench render depsgraph parity, and clean failure/user-bone preservation.

The following `2026-11-10` notes are earlier checkpoint history.

## Custom body converter checkpoint — 2026-11-10 (superseded)

The current generator supersedes the 511-bone prototype described below. It fits the supplied 454-bone custom control topology and 115 widgets to body landmarks. Default native mode has 796 bones; explicit DEF-only mode has 461 bones. Original DNA rest matrices, parents, weights, RBF equations, quaternion blending and 10,000 helper scaling are retained in native mode.

The supplied single-CHILD_OF bridge failed root-motion testing by accumulating parent transforms. Pose-space resets plus the rest-offset bridge fix that while preserving native local quaternion inputs. The supplied underarm endpoint, stale prototype constraints, bilateral corrective differences and snapping endpoint offsets are corrected. See [Body Rig](BODY_RIG.md) for exact deviations and mode limitations.

Saved-scene Section 6 checks pass in Blender 5.0 and 5.2 with an explicitly documented custom-stack precision bound of 5e-5 (observed 2.9e-5); the literal 1e-5 bound for every custom bone does not pass. Original DNA bridge bones remain within 1e-5. Native joint/skin checks pass, with maximum sampled skin difference 0.0563 mm. The local moving-body check measured about 15.1 ms in 5.2; combined 104 moving mouth/jaw controls about 18.0 ms. These are local evaluation measurements, not FPS guarantees.

Both saved conversion modes, all four snaps, reverse-foot bounds, DEF weight normalization and finite skinning pass. Auto Key and embedded standalone UI pass in 5.0/5.2; injected fitting failure and user-added-bone protection pass in 5.2. Final combined mouth timing is 17.9 ms, and addon-free render evaluation passes. Additional imports at scales 0.008/0.012 with LOD1/2 pass. Combined face rebuild, standalone playback and scoped cleanup pass. Logs: `converter_complete52.log`, `converter_complete50.log`, `body_converter_oracle52.log`, `converter_oracle50.log`, `converter_merge52.log`, `converter_variants52.log` in the external work directory.

Version stays 1.8.1; Update 1.90 stays in progress. The following prototype notes are historical.

## Development checkpoint — 2026-11-10

Version remains **1.8.1** and Update 1.90 remains **in progress**. The following
implementation and fixture checks are now present; this is not a release-complete claim.

### Body prototype

`body_rbf.py`, `body_driverplan.py`, `body_fields.py`, and `body_rig.py` now import
the supplied body DNA with a control layer and native corrective evaluation.
The generated LOD 0 rig has 511 bones and 2,318 corrective/input drivers, plus
control-switch/follow/stretch drivers. It preserves interpolative RBF, quaternion
rotation blending and twist/swing. Controls include four IK/FK chains, matching
snaps, optional stretch, head/neck follow and blue/red/yellow side colors.

`body_merge.py` joins imported skeletons, preserves head DNA names, namespaces
shared body bind bones and keeps the face board separate with head follow.
Facial drivers and skin modifiers are explicitly retargeted. Joining is intended
before animation/sculpt sessions, with body controls neutral and limbs in FK.

Blender 5.0 and 5.2 checks pass for neutral alignment, sampled native joint/skin
parity, all four IK/FK snaps, combined facial rebuilding, saved standalone
playback and scoped cleanup. Maximum sampled skin difference is 0.046 mm.
The RBF reference matches native values within about 3.04e-6 over 387 poses.
Local body evaluation is about 13.7/15.1 ms in 5.2/5.0. The combined rig with 104
moving mouth/jaw controls measured about 16.7/18.2 ms. These are local evaluation
timings, not viewport FPS guarantees. The head/body fixtures are different
characters; these tests do not demonstrate a fitted neck seam or mesh welding.

### Import and interface prototype

`import_job.py` and `import_worker.py` run interactive head import in a separate
Blender process. The lime/white overlay keeps animating during heavy work; Escape
cancels. Background imports remain synchronous. The completed character appends
with its own ownership and remapped name references, including an existing-board
name collision. Real cancellation/append tests pass; an actual UI import ran
75 responsiveness ticks. The final append still runs briefly on the main thread.
Sidebar branding/icons are bundled and do not change Blender's global theme.

Eye closeups rendered in Eevee and Cycles. Current material/wrinkle tests and
ARKit recording tests pass again. Visual lip-sync superiority remains unproven.

### Packaging and evidence

The root remains the installable extension: manifest, entry point, modules,
assets and native bindings stay together. The Windows x64 manifest passes
Blender's directory validator. No ZIP was generated. See [INSTALL.md](../INSTALL.md).

All generated test artifacts were preserved outside the project at
`%USERPROFILE%/Documents/Codex/MetaMorphosis-development/work` (3.5 GB).
Tests use `tests/_paths.py`; `METAMORPHOSIS_WORK_DIR` overrides that location.
Historical `work/` references in this document now refer to that external folder.

Final checkpoint checks also passed for all four exposed body LODs, original Ada facial import/rebuild/cleanup, and standalone body/face render dependency graphs in Blender 5.0 and 5.2. Render logs: `body_render190_50.log` and `body_render190_52.log`.

Relevant new logs: `body_import190.log`, `body_import190_50.log`,
`body_merge190.log`, `body_merge190_50.log`, `body_import190_lod3.log`,
`blender_body_rbf_final190.log`, `blender_materials_final190.log`,
`blender_mocap_final190.log`, `import_job190.log`, `import_modal190.log`, and
`eyes190.log`. The later sidebar screenshot helper hit a read-only UI property
after the modal import passed; it did not affect addon source or imported data.

Remaining release review includes broader body/MHA coverage, matching-character
alignment and final interface review. Do not interpret these fixture checks as
complete validation of every DNA, custom rig mechanism or phone version.

## Earlier investigation notes

The following earlier checkpoint is retained for history; use the dated checkpoint above for current implementation details.

# Update 1.90 — implementation status

This is work in progress, not a completed 1.90 release. The installed extension
version remains 1.8.1 until the major features are implemented and validated.

## Implemented changes

- Facial capture accepts a face board directly or an armature containing the
  required facial controls. Joining the head into a body no longer requires the
  original head object's metadata for capture targeting. Multiple unselected
  character boards require an explicit selection.
- Eye materials separate the textured iris normal from the smooth coat normal,
  strengthen the tear-film coat, and add a small scale-aware subsurface component.
  These use Principled BSDF nodes supported by the existing material workflow.
- Import overlay colors are lime and white, with a perimeter glow. Background
  imports skip the overlay, draw calls restore the GPU blending state, and addon
  disable removes the handler. This still redraws at import progress callbacks;
  continuous animation through blocking operations is not implemented.

## Actual custom-rig inspection

The supplied Custom Rig.blend was opened in a separate Blender 5.2 background
process with embedded scripts disabled; the input file was not saved or changed.

- Armature: 1,324 bones, 4,233 drivers. FACE_GUI: 416 bones.
- 156 Copy Transforms, 68 Stretch To, 51 Copy Rotation, 33 Transform,
  13 Copy Location, 10 Copy Scale, 8 Armature, 8 Limit Rotation, 4 Damped Track,
  4 IK, and 4 Limit Distance constraints.
- Four two-bone IK limb chains. MCH_SWITCH bones blend FK and IK transforms;
  ORG and tweak chains feed DEF bones. This is not a simple bone-name remap.
- PROPERTIES controls bilateral arm/leg FK/IK switching, rotation follow,
  stretch, parent spaces, and head/neck follow.
- Collection families: ROOT, TORSO, TORSO_FK/TWK/MUSCLE, bilateral ARM and LEG
  IK/FK/TWK, HAND, ACC, MCH, ORG, DEF and corrective/deformation subdivisions.
- The reference UI contains hard-coded armature datablock names and a fixed rig
  ID. A generated UI must resolve the selected character instead to support
  multiple characters safely.
- Required generated control colors: left #4C6CFF, right #FF170C, center #F4C90C.

Full machine-readable inspection: work/custom190.json. Inspection utility:
work/inspect_custom190.py. These are development artifacts, not bundled assets.

## MetaHuman Animator direct-stream investigation

The user requires direct iPhone-to-Blender streaming; an Unreal bridge is excluded.
The installed UE 5.7 source contains enough protocol detail to investigate an
independent receiver without inventing a packet format:

- MetaHumanLiveLink/Source/LiveLinkFaceSource describes TCP control sessions and
  UDP animation packets. Default phone control port: 14785.
- CaptureManagerCore/Source/CaptureProtocolStack describes CPS protocol version 1,
  CPSCONTROL-null framing, UTF-8 JSON requests, session start/stop, subject
  metadata, stream start/stop, and five-second keep-alives.
- Streaming subjects advertise animation type (arkit or mha), version and control
  names. UDP frames carry subject ID, qualified time, unsigned 16-bit control
  values normalized by 65535, and six head-pose floats.
- A read-only subject-discovery utility is prepared in work/probe_mha190.py. It
  opens a control session, reads metadata, and closes the session; it does not
  start recording. A real phone address/app version has been requested.

The addon now includes a direct receiver and ARKit/MHA mode switch. An actual
iPhone running Live Link Face 1.7.3 (185) advertised 251 MHA controls and supplied
582 frames in a ten-second connection check, with zero malformed packets or
queue drops. No Unreal Engine process or bridge is used at runtime.

mha_live.py owns the TCP session and UDP receiver on a worker thread. mha_mapping.py
uses the bundled DNA library's native mapRawToGUIControls on the main thread.
All 251 advertised controls matched Logan's head DNA; they drive 174 available
face-board channels. This is a raw-to-GUI conversion, not direct raw-control
playback, so GUI representability still limits conflicting simultaneous inputs.
Head-pose floats are validated but not applied. MHA mode does not apply ARKit gains,
mirroring, or inferred mouth corrections. Objective lip-sync accuracy has not been
compared against Unreal's output.

The real phone sequence baked to a 299-frame action, deformed the face, and played
back after saving/reopening with the addon disabled. Local mapping time averaged
0.24 ms/frame (conversion only, not total viewport time). Existing ARKit tests pass.

## Remaining implementation

- Broader MHA version/character coverage and visual lip-sync comparison.
- Body import, template-driven controls and rig UI, independent native body RBF
  corrective evaluation, and head/body merge with a separate following board.
  The supplied engine.py delegates solving to a separate native module; reference
  JSON topology and rig definitions do not replace that runtime.
- Scoped lime/white sidebar presentation and uninterrupted import animation.
- Visual validation of the new eye appearance in Eevee and Cycles.
- Body deformation parity and changing-pose performance benchmarks before release.

## Checks completed

- work/check_capture_target190.py passed in Blender 5.2 on the supplied custom
  rig: separate face board, joined armature, metadata loss, and ambiguous selection.
- tests/blender_materials.py passed in Blender 5.2: real Logan import, native
  wrinkle parity, standalone save/reopen, and scoped cleanup. Log:
  work/materials190.log. This verifies material construction, not visual realism.

No ZIP, commit, or push was created.

