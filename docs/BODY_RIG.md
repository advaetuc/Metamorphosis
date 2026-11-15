# Custom body rig converter

Version **2.80**.

## Use

1. In **MetaMorphosis > Body Rig > Import Settings**, choose **Custom Shapes** (`Unreal` or `Blender`).
2. Click **Import Body DNA** — imports the original MetaHuman skeleton (`342` bones) with **Native Correctives** (`RBF`, twist/swing, and quaternion drivers). Only the original rig is imported at this step.
3. Click **Build Control Rig** below **Import Body DNA** — builds or upgrades the `565`-bone control rig (`223` custom bones + `342` original bones) using only the selected custom shape preset (`Unreal` or `Blender`).
4. Leave the body neutral with limbs in FK, import the matching head, and use **Connect Head and Body** before creating animation takes.
5. Use **Rig UI** to toggle bone collections side by side with solo buttons, and click **Bake Rig UI** below it to generate `MetaMorphosis_Custom_RigUI.py` for standalone **N-Panel > Item** controls when the add-on is disabled.

Conversion of an already animated or already combined skeleton is rejected. Import/convert the body first and connect the head afterward. Existing prototype animation cannot be transferred by renaming controls because the local axes and hierarchy have changed.

## Body rig architecture (`NATIVE_BRIDGE_2`)

| Component | Result | Deformation |
| --- | --- | --- |
| Native Correctives (only supported mode) | `223` custom bones plus `342` original DNA bones: **`565` body bones** | Original vertex groups, rest matrices, hierarchy, RBF, ordered quaternion rotations and twist/swing remain intact. Custom controls drive the original bones via pose-space resets + `CHILD_OF` rest-offset bridges (`84` bridged landmarks). |
| Custom DEF Only (`body_remap.py`) | **Retired** | Removed from the import UI; calling `body_remap.remap()` on a `NATIVE_BRIDGE_2` rig (or without `DEF_SPINE_02`) raises `ValueError`. |

The control layer retains the torso (`TORSO` aligned horizontally along `+Y` with length `0.175` m, isolated `HIPS` pelvis tilt, `CHEST` uniform spine-bend macro supporting Euler & `QUATERNION` rotation), 4-joint visible FK spine (`SPINE_FK` with `SPINE_04_FK` extending directly to `NECK_01_FK` and `SPINE_05_FK` plus spine/torso tweaks `SPINE_01..05_TWEAK`, `PELVIS_TWEAK`, `NECK_01/02_TWEAK`, `HEAD_TWEAK`, `HEAD_TIP_TWEAK` moved to `MCH`), face-aligned `NECK_01_FK`/`NECK_02_FK`/`HEAD` controls, limb IK/FK chains with pole-indicator lines (`VIS_ARM_IK_POLE`, `VIS_LEG_IK_POLE`) and full upper-arm/thigh Y-twist & pole-angle falloff (`COPY_ROTATION` on `MCH_TWIST_ARM`/`MCH_THIGH_TWIST` preserving native `upperarm_twist_*` and `thigh_twist_*` falloff), palm cup (`HAND_SIDE_OPEN`), X-mirrored finger/thumb controls, `20` individual constraint-free toe controls (`TOE_{A..E}_{01|02}.{L|R}` in `TOE.L`/`TOE.R`), active reverse-foot toe hold (`MCH_TOE`), final limb tweakers (`NO_VOLUME` `STRETCH_TO`), custom side colors with selection/active highlight contrast, `show_in_front = False`, and selectable **Unreal** (`display_type = 'SOLID'`, bone `show_wire = False`) or **Blender** (`display_type = 'WIRE'`, `custom_shape_wire_width = 1.0`) custom shapes stored inside hidden `<rig>_WIDGETS` collections. Dead custom `DEF_*`, `DEF_COR_*`, intermediate limb/muscle tweaks, `ARM_BICEP_FLEXTION` properties/drivers, empty `ACC`/`ACC_TWK`/`SPINE_TWEAK`/`TORSO_TWK` collections, and empty `RIGLOGICDATA` collections are cleaned automatically; body imports use `<prefix>_ARMATURE` and `<prefix>_MESHES` so subsequent head DNA imports keep clean `ARMATURE` and `HEAD` collections without `.001` suffixes.

Coordinates use the actual DNA joint landmarks and mesh foot bounds. Limbs fit actual side landmarks directly, while finger/thumb/toe digit chains mirror from `.L` to `.R` for clean X-mirror posing. The body must be upright in armature space, facing -Y, left at +X. Foot pivots, finger/toe endpoints, hinge axes, poles, control lengths and internal mechanisms are fitted during conversion, with no Python playback handler.

## Corrections to the supplied engineering workflow

- A lone CHILD_OF on each original bone double-applies inherited parent motion. In the supplied fixture, a 0.1 m ROOT move displaced the hand by 1.1 m. The converter first resets the inherited pose using pose-space limits, then applies the target transform with `target_rest.inverse() @ original_rest`. Original bone parenting and local quaternion evaluation remain intact.
- The underarm mechanism's `ORG_*` chain had endpoint drift and `MCH_TOE.L/R` Copy Rotation started muted; unused `DEF_COR`/muscle intermediates are pruned while `MCH_TOE.L/R` is unmuted so toes hold the floor during reverse-foot heel rolls.
- Deleted prototype controls left dangling `MetaMorphosis Control` constraints in the supplied OG file, including latissimus bones. The converter replaces these named legacy constraints. It classifies the 84 kinematic bones explicitly, never by missing drivers.
- Bilateral transform ranges, arm twist influences, thigh B-Bone handles and knee-helper parenting are made consistent; the duplicate tricep transform and removed bicep-flex properties are cleaned up.
- `CHEST` bends `MCH_SPINE_01..05_BEND` cleanly across all 5 spine vertebrae without dependency cycles (parented under `SPINE_02_FK` with lower-FK copy helpers) and reads `LOCAL_SPACE` transforms so `QUATERNION` rotation mode works identically to `XYZ`. `HIPS` provides isolated `1:1` pelvis tilt/sway separate from `TORSO`, making all `ARM_IK_PARENTS` (`5`) and `LEG_IK_PARENTS` (`4`) slots distinct.
- Limit Rotation/Location/Scale constraints have no target in Blender. The verifier checks their bounds, rather than requiring an impossible target/subtarget.
- Both the original DNA bridge and the pruned `NATIVE_BRIDGE_2` custom stack meet the `1e-5` rest-matrix bound (observed ~`4.05e-6`). Legacy `NATIVE_BRIDGE_1` / `DEF_ONLY_1` custom thigh stacks required a `5e-5` tolerance (~`2.9e-5`) and are now superseded.
- FK matching reads the evaluated MCH endpoint, including reverse-foot offsets. Matching to IK resets heel offsets and preserves the endpoint. Ordinary hinge poses retain hinge locks; an off-axis FK pose preserves stored custom locks and pole angles without mutating lock flags.

## Saved scenes

All deformation is native Blender data and works with the addon disabled. Clicking **Bake Rig UI** creates an embedded `MetaMorphosis_Custom_RigUI.py` Text datablock (`use_module=True`) that registers **N-Panel → Item** UI panels (**Rig UI** with side-by-side collection toggles + solo buttons, **Rig Properties** subpanels with icons, and **Snap Utilities**) and standalone IK/FK snapping operators that continue working when MetaMorphosis is disabled; Blender controls whether trusted Text scripts run automatically on file open. No script is needed for normal rig playback. The addon panel resolves the selected rig, with no hard-coded armature object name.

The control asset `assets/body_controls.blend` contains only the body skeleton and its referenced wire widgets, extracted from the user-supplied `Custom Rig.blend`. It contains no character mesh, face rig, hair or accessory system. The source fixture is never overwritten. The implementation is split between `body_converter.py`, `body_geometry.py`, `body_refine.py`, `body_snap.py`, `body_rig.py`, `body_merge.py`, and the native corrective compiler (`body_remap.py` is retained only as a retired guard stub).

## Verification

Run in Blender 5.0 or 5.2:

```powershell
& $Blender --factory-startup -b --python-exit-code 1 --python tests/blender_body_converter.py
```

That test converts the supplied OG fixture, checks unchanged original rest matrices/parents/weights, saves the converted `NATIVE_BRIDGE_2` file outside the addon, and automatically launches a fresh Blender process:

```powershell
& $Blender --factory-startup -b $ConvertedBlend --python-exit-code 1 --python tests/verify_body_converter.py
```

The Section 6 verifier checks structure (`565` bones), driver links, constraint links, rest precision (`< 1e-5`), root double transforms, all four IK/FK operators, hinge motion, native corrective activation, foot-roll limits and finite skinning. `blender_body_fixes.py` validates `NATIVE_BRIDGE_1` -> `NATIVE_BRIDGE_2` upgrades, spine pitch/twist (Euler & Quaternion), `CHEST` attachment, isolated `HIPS` rotation, all distinct parent-space slots, `MCH_TOE` reverse-foot hold, `32`-pair bilateral X-mirror symmetry, `.L`/`.R` digit colors + highlight contrast, `NO_VOLUME` IK stretch, restored tweak sizes, clean widget/scene collections, and `body_remap` rejection. `blender_body_import.py` additionally compares native RigLogic joint outputs and actual skin deformation across changing poses. `blender_body_merge.py` covers head connection (including empty face-board bone-collection cleanup & hiding `DEF_HEAD`), face rebuild, standalone playback and scoped cleanup. `blender_body_snap.py` verifies Auto Key records the endpoint, pole, mechanism offsets and pole angle, then reopens and runs the embedded standalone UI. `blender_body_render.py` compares viewport and Workbench animation render dependency graphs. `blender_body_converter_failures.py` injects fitting failure and verifies temporary-data cleanup, active-rig recovery and preservation of user-added bones.

The supplied OG and body DNA are validated; arbitrary body schemas are not promised. Head connection preserves existing positions rather than fitting different characters or welding a neck seam. Generated test scenes/logs stay in the external development work folder, not the installable addon. No ZIP is generated.
