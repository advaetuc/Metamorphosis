# MetaMorphosis Add-on Context for AI Agents

## Purpose

MetaMorphosis is a Blender add-on for importing MetaHuman DNA files, reconstructing the MetaHuman facial rig and face board, and compiling RigLogic behavior into native Blender data. The intended result is a character that can be animated in Blender and continue evaluating correctly when the add-on is disabled or removed.

Current development version: **1.8.0**. Supported Blender versions: **5.0+**. The production rig mode is **Lite only**; do not reintroduce Exact, Fast, or Balanced rebuild choices.

Repository: `https://github.com/advaetuc/Metamorphosis.git`

## Core guarantees

- Preserve the original DNA joint hierarchy, mesh topology, vertex ordering, UVs, skin weights, control indices, source layers, and unknown preserved layers unless a requested feature explicitly adds an authored expression target.
- Preserve native standalone playback: generated drivers and Geometry Nodes data must work without Python handlers and without the add-on being registered.
- Preserve the middle-eye control fix: the center eye control drives both eye controls.
- Preserve Lips Together, Jaw Open Extreme, and the restored mouth/jaw PSD correctives.
- Prioritize dependency-graph performance. Always benchmark representative changing mouth/jaw controls and verify skinned deformation before accepting rig changes.
- Never overwrite supplied DNA files or user scenes. Temporary scenes, logs, and test DNA belong in `work/`.
- Do not create ZIP archives unless the user explicitly requests one.
- Do not infer a request to commit or push from a request to edit files.

## Main user workflows

### Import DNA

The user selects **Import DNA** from the MetaMorphosis sidebar or Blender's import menu. The importer:

1. Locates compatible OpenRigLogic bindings for Blender's actual Python version.
2. Reads and validates the DNA with native RigLogic.
3. Imports the requested head meshes, source skeleton, and face board.
4. Organizes imported objects, bones, helper meshes, and collections.
5. Builds the Lite native driver graph.
6. Optionally applies materials from an Unreal DCC export root or `Maps` folder.

The imported rig stores source DNA path, scale, board references, ownership token, helper references, mesh kind/index metadata, and baked statistics in custom properties. Existing scenes require **Rebuild Drivers** to receive compiler or corrective changes.

Normal imports do not load the complete source corrective shape-key library. Explicitly authored expression targets are the exception and are marked in DNA metadata.

### Rebuild Drivers

Rebuild reads the rig's source DNA, verifies it, and regenerates the Lite native graph while preserving board values, actions, materials, and imported geometry. It must refuse to run while neutral or expression sculpt sessions are active unless the session workflow explicitly sets its internal rebuilding guard.

The rebuild pipeline includes GUI-to-raw controls, PSD controls, retained mouth/jaw correctives, raw-expression pruning, native matrix sums for large graphs, and simple expression drivers for smaller graphs. ML and head/neck RBF correctives remain preserved but are not baked into Lite.

### Neutral mesh sculpting

The **Sculpt Neutral Mesh** workflow edits neutral proportions. It stores session metadata and backups inside the `.blend`, follows joint and dependent-mesh displacement through a `SurfaceField`, supports topology protection and optional symmetry, and writes a validated DNA preparation or export.

Neutral sculpting preserves joint orientations and rotation/scale equations while adapting translations and translation equations. It transfers source corrective deltas across all LODs. It does not support remeshing, Dyntopo, topology-changing modifiers, manual UV/weight edits, manual rest-joint edits, or arbitrary posed-expression sculpting.

Only an active neutral sculpt session registers the 0.5-second update timer. No sculpt timer runs during normal playback or after cancellation/baking.

### Expression sculpting (1.6.0)

The **Sculpt Expression** workflow edits a facial expression while retaining a neutral base:

1. Pose the face board, such as a smile or lip control.
2. Select **Sculpt Expression** and choose one currently active existing raw DNA expression.
3. MetaMorphosis creates a frozen evaluated working copy of the posed head. The original head is hidden; the user sculpts the working copy while keeping the captured face-board pose unchanged.
4. **Apply Expression to DNA** fits changes that existing facial joints can represent, then stores remaining fine detail as a DNA corrective shape driven by the selected raw expression.
5. The add-on rebuilds native drivers, evaluates the actual skinned result, and accepts the edit only when the reconstruction error is within tolerance.

The selected expression remains the trigger in mixed poses. This is deliberately one existing raw expression per authored correction; it is not an arbitrary new combination trigger. Bilateral edits can be authored separately for left and right controls. Repeated edits to the same expression merge into its existing authored channel.

When the selected control is reset, the authored detail disappears and the original neutral geometry returns. When the control is activated again, the detail returns. Neutral rest geometry and rest-joint positions remain unchanged. Original bones are adapted where possible; a DNA corrective stores surface detail that bones cannot represent.

Expression metadata key: `MetaMorphosis.ExpressionSculpts`.

Expression sessions use `mm_expression_session`, an owned `MM_EXPRESSION_SCULPT` working object, a source DNA hash, captured pose, topology fingerprint, selected control, activation, and captured head geometry. Apply validates unchanged source DNA, pose, topology, transforms, standard armature skinning, and original weights. On failure it restores the previous mesh, DNA path, drivers, and keeps the working sculpt available for retry or cancellation.

Only metadata-marked authored targets are loaded as shape keys during import/rebuild. Existing source corrective targets and control indices are not renumbered. Authored expression columns are retained through Lite pruning. Head target and mesh-channel mappings are written for all DNA LODs.

Expression fitting and lower-LOD residual transfer are geometric approximations. They are not a muscle solver, learned-corrective retraining system, or replacement for Unreal's full ML/RBF behavior. Actual Unreal Editor reimport remains untested.

## Performance architecture

Large rigs use `native_sums.py` and hidden helper meshes with a Geometry Nodes graph using Sample Index and Accumulate Field. The graph retains rounded coefficients and uses the established 10,000x intermediate scaling to avoid Blender RNA small-value write loss; units are restored at bone outputs. Do not remove this scaling.

Smaller plans use the expression backend. Drivers are compiled from native data and must not depend on Python functions, handlers, or an installed add-on at playback time.

Recorded Blender 5.2 native benchmark results:

| Fixture | Before | After | Notes |
| --- | ---: | ---: | --- |
| Logan saved scene | 60.78 ms | 11.67 ms | 34,959 → 5,653 drivers |
| Ada | 70.66 ms | 15.74 ms | fresh import |
| MH_BASE | 75.24 ms | 16.01 ms | fresh import |
| Taro | 70.27 ms | 15.64 ms | fresh import |
| Logan, 104 mouth/jaw controls | 59.76 ms | 11.81 ms | local dependency graph |

Expression sculpt regression timings with one authored expression remain approximately 11–15 ms for moving mouth/jaw controls. These are local dependency-graph measurements, not guaranteed viewport FPS.

## Facial correctives and controls

- Lite retains primary expressions and mouth/jaw-dependent PSD correctives.
- Lips Together seals the lips while the jaw can remain open.
- Jaw Open Extreme extends an already-open jaw and has no effect with a fully closed jaw.
- Combined mouth controls preserve compensating DNA correctives and avoid the previous extreme stretching/cheek distortion.
- Middle-eye movement drives both eyes together.
- Raw/PSD/ML/RBF indices in newer DNA must remain distinct and correctly offset.
- ML and head/neck RBF correctives remain preserved but unbaked.

## Materials and wrinkle system

`materials.py` accepts an Unreal DCC export root or its `Maps` folder. Character textures remain external unless packed by the user. Bundled assets include masks, micro normals, teeth color/normal maps, and eyelash alpha.

The head material uses a compact `DNA_MATERIAL` node group and `SKIN_DETAIL` micro-normal mixing. Wrinkle color and normal animated maps are driven by DNA animated-map equations independently of the joint driver graph. Generated materials and sockets use uppercase underscore names. Blender 5.2 uses the native DirectX normal convention; Blender 5.0 uses an internal compatibility group.

Eye-edge geometry is split anatomically by X (positive = left). Eyeshell/cartilage are omitted. Imported position/layout mappings preserve UVs, normals, and skin weights.

The 1.8 update adds a **Customization** panel with a Face Board Colour picker and an apply operation for `CTRL_*` pose-bone colors. Eye Principled BSDF settings add a separate corneal coat compatible with Eevee and Cycles.

## Facial capture

`mocap_core.py` receives Epic Live Link Face ARKit UDP. `mocap_mapping.py` maps 52 coefficients to existing face-board controls. `mocap.py` owns main-thread preview, countdown, recording actions, and asynchronous video jobs. Never call `bpy` from the receiver thread.

Live Link supports expressions and eye gaze, not MetaHuman Animator streaming or head/body motion. Existing takes remain separate Blender actions. Jaw-relative closure, inward lip roll, bilateral press/roll seals, lip/brow strength, and speech smoothing are implemented. ARKit lacks independent bite/tighten/towards coefficients, so those mappings are approximations and real iPhone accuracy is not device-validated.

Video tracking uses an isolated Windows environment with MediaPipe `0.10.35` and `opencv-contrib-python` `4.13.0.92`. Do not install these into Blender's Python and do not install the non-contrib OpenCV wheel alongside them. The add-on stores tools under `%LOCALAPPDATA%/MetaMorphosis/VideoTools`, remembers the installation path, and supports repair/upgrade. Video processing runs asynchronously and can be cancelled.

## Ownership and cleanup

Every imported ID receives an `mm_import_id` ownership token. **Remove All** removes only imported content belonging to the current scene, preserving unrelated objects, shared data, and user-added content. Native helper meshes, node groups, materials, and authored expression working copies are cleaned only when owned and unused.

## Important source files

| File | Responsibility |
| --- | --- |
| `__init__.py` | Add-on registration order and lifecycle |
| `operators.py` | Import, rebuild, validation, benchmark, export, cleanup operators |
| `importer.py` | DNA mesh/skeleton import and source index metadata |
| `pipeline.py` | Bake orchestration and Lite quality configuration |
| `logicmodel.py` | DNA behavior model and control-index handling |
| `bakeplan.py` | Driver plan, pruning, retained correctives, authored columns |
| `bake.py` | Native driver creation, validation, benchmark, rig lookup |
| `native_sums.py` | Geometry Nodes matrix backend |
| `expression_sculpt.py` | Posed expression session, joint fitting, residual transport, apply/cancel |
| `expression_dna.py` | Authored expression metadata, joint/shape target patching, validation |
| `sculpt.py` | Neutral sculpt sessions, context-safe mode switching, DNA export UI |
| `sculpt_field.py` | Affine/local displacement transfer and symmetry |
| `dna_export.py` | Atomic DNA copying, patching, read-back validation |
| `materials.py` | Character textures, shader groups, wrinkle animated maps |
| `mocap.py` | Capture UI, recording, video jobs |
| `mocap_core.py` | ARKit UDP receiver and recording data |
| `mocap_mapping.py` | ARKit-to-board mapping |
| `video_worker.py` | Isolated MediaPipe/OpenCV worker |
| `cleanup.py` | Scene-scoped ownership cleanup |
| `tests/` | Blender integration and regression tests |

## Testing expectations

Tests run inside Blender, not ordinary system Python. Use Blender 5.0 with Python 3.11 and Blender 5.2 with Python 3.13 where relevant. Use temporary files/logs only under `work/`.

Key suites:

- `blender_features.py`: removed body/blendshape options and UI invariants.
- `blender_import_cleanup.py`: import, middle-eye behavior, rebuild, standalone playback, ownership cleanup.
- `blender_lips_together.py`: Lips Together and Jaw Open Extreme against native RigLogic.
- `blender_native_sums.py` and `blender_native_sums_render.py`: native matrix parity, render depsgraph, standalone playback, cleanup, performance.
- `blender_sculpt_export.py`, `blender_sculpt_modes.py`, `blender_sculpt_context.py`: neutral sculpt, topology, mode/context safety, DNA export.
- `blender_expression_sculpt.py`: expression reconstruction, partial activation, repeated edits, save/reopen, export/reimport, standalone actions, timing.
- `blender_expression_recovery.py`: rollback, missing context, Sculpt Mode entry, neutral/expression coexistence, independent authored channels, cleanup.
- `blender_materials.py`, `blender_material_reapply.py`, `blender_update12.py`: material and wrinkle graph parity.
- `blender_capture_response.py`, `blender_capture_geometry.py`, `blender_mocap.py`, `blender_video_job.py`, `blender_video_setup.py`: capture and video behavior.

For every rig change, check: no invalid/muted/Python-dependent drivers, actual skinned geometry against native RigLogic, preserved actions/materials, neutral pose unchanged, and performance on representative mouth/jaw movement.

## Known limits and safe assumptions

- No Premium Poly Hammer DNA sculpt implementation was available; MetaMorphosis uses its own geometric approximation.
- Expression sculpting follows one selected existing raw expression, not arbitrary pose combinations.
- ML/RBF correctives are preserved, not retrained or baked.
- Real iPhone capture accuracy and Unreal Editor DNA reimport are unverified.
- Standard armature vertex-group skinning is required for expression sculpting; Preserve Volume, envelopes, masks, changed weights, topology edits, and changed captured poses are rejected.
- MetaHuman Animator streaming is deferred at the user's request. John Rambo's supplied `body.dna` contains 342 joints, 176 raw controls, 215 RBF pose controls and 72 RBF solvers. Current Lite does not evaluate body RBF solvers. The supplied MH2Rigify script is a manual skeleton-preparation utility and the PolyHammer body files rely on its own private rig-instance framework; do not describe them as a generated standalone body control rig.
- Do not overwrite `F:\AI\Training_Data\Distored Pose.blend` or the supplied DNA fixtures.

## Current development rule

When another AI agent changes this project, it should first read this file, `AGENTS.md`, and the relevant source/test files. It should preserve existing user changes, make only requested changes, run the smallest relevant Blender regressions, and report measurable deformation/performance evidence rather than claiming unverified Unreal or device behavior.
