# Development history

[← Back to README](../README.md)

Release notes describe each version at the time it was developed. For current setup instructions, use the README.

## 1.2.2 — Native matrix evaluation

- Move large joint sums from thousands of individual expression drivers to a
  native Geometry Nodes field. Retain every rounded coefficient, all 413 mouth/jaw
  correctives, existing raw pruning, and 10,000x intermediate scaling. GUI, raw,
  PSD and wrinkle equations remain unchanged.
- Keep playback standalone: the generated data needs no Python handler, driver
  namespace function, installed add-on or extra dependency. Each driven bone
  channel reads one evaluated matrix result through a simple native driver.
- Rebuild preserves board values, actions and materials. Rebuild, rig toggling
  and scoped cleanup handle the helper meshes, their input drivers and node group.
- On the supplied corrected Logan scene in Blender 5.2, median dependency-graph
  update time fell from **60.78 to 11.67 ms**, and drivers from **34,959 to 5,653**.
  The largest mesh-coordinate difference across 32 poses was **0.00048 mm**.
  Timing is scene/hardware dependent and excludes viewport shading.
- Existing scenes need **Rebuild Drivers** after reloading the updated add-on.
  `tests/blender_native_sums.py` compares the old/native equations and actual
  skinned meshes, benchmarks both graphs, checks rebuild preservation/cleanup,
  and tests saved action playback with the add-on unregistered.

## 1.2.1 — Combined mouth deformation

- Fix excessive stretching and cheek bulges when several mouth controls reach
  maximum together. Lite had discarded their compensating DNA PSD combinations;
  the reported scene had unique deformation driver targets, not competing overrides.
- Retain mouth/jaw-dependent correctives, including mixed nose/cheek combinations,
  while preserving the existing raw-expression pruning, Lite-only UI, helper scaling,
  and omission of unrelated upper-face PSD and ML/RBF solvers.
- Calibrate weighted mouth PSDs using targeted endpoint poses against native
  RigLogic. Sparse samples alone could incorrectly select an unclamped product
  for a corrective that saturates at 1.
- Existing scenes receive the fix with **Rebuild Drivers**. Actions, board values
  and material assignments are preserved. More native drivers are required, with
  a corresponding playback cost; no new speed claim is made.
- Regression coverage includes the supplied `Distored Pose.blend`, bilateral and
  asymmetric maximum mouth controls, partial values, jaw combinations and mixed
  nose/cheek poses. Saved-scene playback is checked with the add-on unregistered.

## 1.2.0 — Shader organization and lip capture

- Organize the head material into texture/output frames and a compact DNA_MATERIAL
  group. Rename nested group sockets; keep the original wrinkle calculations and
  all 41 native mask inputs inside the group. Group micro-normal mixing separately.
- Use Blender 5.2's native DirectX normal convention. Blender 5.0 keeps an internal
  conversion group for compatibility.
- Bundle and pack the supplied universal teeth color/normal and eyelash alpha
  textures alongside the existing skin detail maps. Eyelash coverage reads the
  grayscale image, not its opaque PNG alpha channel.
- Omit eye-shell and cartilage on new imports. Split eye edges into anatomical
  left/right meshes while preserving UVs, custom normals and skin weights, and
  assign the supplied side-specific procedural materials.
- Show “MetaMorphosis DNA Addon” and “by TheClayMan3D” in the sidebar header.
- Restore full inward lip-roll range and remove the competing automatic bite.
  Suppress funnel/upper-raise/lower-depress inputs during closure; bilateral
  roll/press can also drive a seal. Preserve jaw motion and existing takes.
- Existing scenes can reapply materials. Reimport to receive the new eye mesh
  structure; legacy combined eye edges receive a report warning.
- Check skinned lip geometry on Ada, MH_BASE, Taro and Logan, native wrinkle
  parity, split-eye UV/weight preservation, packed textures, reapplication,
  standalone playback and cleanup. Real iPhone capture remains unverified.

## 1.0.10 — Phase 2

- Choose the Unreal DCC export root (or its Maps folder) under Materials and Textures,
  then Import DNA. Existing heads can use Apply Materials to Rig. This replaces the
  selected rig's material assignments; unrelated materials are preserved. Reapplying
  removes obsolete generated wrinkle graphs only when they are not shared with other data.
- Head skin includes subsurface scattering, SRMF specular/roughness/metallic/fuzz channels,
  DirectX-to-Blender normal conversion, and the supplied tiled micro-normal detail maps.
  Eyes and teeth receive their exported maps. Missing eyelash alpha uses transparent
  cards instead of covering the eyes. Saliva/eye overlay meshes use clear fallback materials.
  DCC exports do not contain hair grooms; this feature does not generate hair or eyelashes.
- Wrinkles use the supplied Poly Hammer mask atlas and blending groups, with animated
  color/normal maps from the character's export. The atlas is bundled and packed; separate
  DCC Masks files are not needed by this shader. Material and node-group names are uppercase
  with underscores. The supplied custom shader informed the skin, fuzz and detail settings.
- DNA animated-map weights, including their PSD combinations, are compiled to native
  simple-expression drivers. No frame-change Python or add-on callback is needed after
  import. This independent graph survives Rebuild Drivers. The Lite joint correctives
  remain unchanged. Logan adds 223 wrinkle drivers, rather than another full facial rig.
  Shader evaluation still has a rendering cost; no new viewport frame-rate target is claimed.
- Texture maps stay linked to the export folder. Bundled masks and micro normals are packed
  into the scene. Keep the export folder available, or pack external resources in Blender
  when moving a scene to another computer. Missing animated normals produce static skin
  and a report warning. DNA with differing color/normal mask weights or ML/RBF animated-map
  inputs reports an incompatibility rather than silently generating incorrect wrinkles.
- Live Link and video retargeting now include towards, lip-bite, tightening, upper lip press
  and brow-lateral controls. Closure is normalized against jaw opening; conflicting upper/lower
  lip opening is reduced during closure. Lip and Brow Strength tune the capture range.
  Mouth/jaw smoothing is capped at 15 ms for speech transients; other channels retain the
  selected smoothing time. These are practical ARKit retargeting approximations: ARKit has no
  independent bite/tighten/towards coefficients. Existing actions are unchanged; new captures
  use the updated mapping. Actual iPhone lip-sync quality still requires a device test.
- Install Video Tools now chooses a compatible 64-bit Python automatically and keeps a
  shared installation under `%LOCALAPPDATA%/MetaMorphosis/VideoTools` on Windows. Successful
  custom installs are remembered across scenes and Blender versions. Manual paths and Repair
  are under Advanced Setup. The first install/upgrade still needs Blender's Allow Online Access.
  Existing 1.0.9 environments need one click on Install Video Tools to migrate their packages.
- Video packages are pinned to MediaPipe 0.10.35 and **opencv-contrib-python 4.13.0.92**.
  MediaPipe requires the contrib variant; installing opencv-python alongside it can overwrite
  the shared cv2 runtime. Setup removes overlapping OpenCV packages only inside its isolated
  environment, installs the pinned variant, checks dependencies and initializes the tracker
  before marking setup complete. It does not modify Blender's Python packages.
- DNA binding discovery now excludes folders for other Python versions, fixing automatic
  selection when py311 and py313 bindings are both installed.
- Verified the Logan export in Blender 5.0/5.2, all 41 wrinkle inputs against native RigLogic,
  standalone save/reopen, material reapplication and shared-data preservation. Additional
  wrinkle-equation comparisons pass on Ada, MH_BASE and Taro; their 108-pose Lips Together /
  Jaw Open Extreme regressions still pass. Capture, video cancellation/baking, and automatic
  Python selection/persistent setup were also exercised. Render previews are in work/.

Phase 2 references: [Epic texture channels](https://dev.epicgames.com/documentation/metahuman/materials-and-textures),
[OpenCV packaging guidance](https://pypi.org/project/opencv-contrib-python/4.13.0.92/),
and the user-supplied shader assets described in [asset provenance](../assets/README.md).

## 1.0.9 — Phase 1

- Added Live Link and Video to Mocap panels. Both animate existing face-board bones, including
  Lips Together, and bake editable native Blender actions. No shape keys are required.
- Live Link receives Epic Live Link Face's ARKit UDP stream. Select the head rig, use port 11111,
  set the phone's target to the computer's LAN IP, and select **Live Link (ARKit)** mode in the app.
  Keep both devices on the same network and allow Blender through the local firewall if needed.
  This is the ARKit stream, not MetaHuman Animator's newer streaming protocol.
- Connect for preview, position the timeline, then press Start Recording. A three-second countdown
  precedes recording from that frame. Stop Recording bakes a separate take. At Timeline End offers
  Extend Timeline or Stop Keyframing; stopping at the end keeps live preview connected.
  Recording uses packet timestamps rather than viewport speed. Each new action preserves the previous
  action with a fake user; choose previous takes in Blender's Action Editor. Stop recording before
  loading another file. Disconnect or disabling the add-on finishes an active take.
- Expression Strength, Mirror Left / Right and Smoothing apply to facial capture. Extreme Jaw is
  optional and defaults to zero; raising it adds the preserved extreme opening near full jaw opening.
  Retargeting is a practical ARKit-to-MetaHuman mapping, not an exact reproduction of Apple's face mesh.
  Capture covers facial expressions and eye gaze; head/body rotation is not captured in this phase.
- Video to Mocap: press Install Video Tools once, choose an MP4/MOV or other OpenCV-readable video,
  select the head rig and starting frame, then Process Video and Bake. Processing runs in a separate
  process with progress and Cancel. One visible face is tracked; frames without a detected face go
  neutral. Videos with no detected face produce an error and do not replace an action.
  Video results are resampled to the scene frame rate and extend the timeline to fit.
- Video setup downloads an isolated Python environment's packages and Google's Face Landmarker model
  into Blender's user data folder. It does not install packages into Blender's own Python environment.
  An optional Python Executable and Video Tools Folder allow an existing local installation.
  The tested dependencies are MediaPipe 0.10.35 and OpenCV 4.13.0.92. Face processing runs locally;
  MediaPipe's published binaries include usage telemetry, which its maintainers state excludes input
  video/images ([maintainer explanation](https://github.com/google-ai-edge/mediapipe/issues/6291)).
  Video tracking has no tongue-out coefficient and may be less accurate with occlusion or strong head turns.
- Native driver expressions now use shorter equivalent coefficient and variable spellings, fitting
  more terms into each expression. Corrective selection, coefficient precision and Lite pruning are
  unchanged; existing scenes receive the optimization with Rebuild Drivers. Weighted helper sums use
  larger internal units to avoid Blender zeroing tiny intermediate values; final bone channels retain
  their original units. This also corrects small-motion errors in the previous helper calculations.
- Measured on the supplied Ada rig in Blender 5.2: 17,119 → 12,961 drivers (24.3% fewer),
  median update time 23.05 → 21.94 ms across five batches of mixed facial poses. The 7–15 ms target
  was not reached; this measurement includes the imported head meshes and is not a claim about
  the user's separate body/proxy scene. MH_BASE imports now have 14,115 drivers versus 18,616.
- Tests cover malformed packets, UDP receive/stop/rebind, all 52 input mappings, countdown timing,
  both timeline-end policies, preservation of previous actions, cancellation, and native playback.
  The supplied video tracked 1,343/1,343 frames and baked successfully. A real iPhone connection
  has not been tested here; Live Link protocol tests use locally generated ARKit packets.
  The 108-pose RigLogic comparisons pass on Ada, MH_BASE and Taro, and native-driver checks confirm
  reduced intermediate precision loss without changing which deformations Lite includes.

### Capture implementation references

- The supplied Faceit and LiveLinkFace receiver files were used to understand packet layouts and
  capture workflows. Their shape-key-dependent animation code is not installed or required.
- [PyLiveLinkFace protocol](https://github.com/JimWest/PyLiveLinkFace),
  [Epic's iOS facial capture guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/recording-face-animation-on-ios-device-in-unreal-engine),
  and [Google's Face Landmarker API](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python).
- Phase 2 material/texture setup was added in 1.0.10.

## 1.0.8

- Fixed the Jaw Open Extreme face-board control by retaining its DNA joint correctives, including
  combinations with other mouth expressions. These combinations were previously omitted by Lite.
- Open the regular jaw control first, then raise Jaw Open Extreme to extend the opening. This
  follows the DNA's behavior: Extreme has no effect while the regular jaw is fully closed.
- The Lips Together fix and existing Lite primary-expression settings are preserved. Existing
  scenes receive this fix by selecting the head rig and pressing Rebuild Drivers after loading the update.
- Checked 108 poses per DNA against native RigLogic on Ada, MH_BASE and Taro. Import/rebuild tests
  pass in Blender 5.0 and 5.2 with joined/separate face boards, including mesh movement, valid native
  drivers, the previous eye/lip fixes and save/reopen with the add-on unregistered.

## 1.0.7

- Fixed all four Lips Together face-board controls. Their motion is stored in DNA as combinations
  with jaw movement, so dropping every combination in Lite had left these controls disconnected.
  Lite now retains their jaw-opening, sideways-jaw and mouth-press combinations.
- Existing primary-expression pruning is unchanged. Lip closure uses the DNA's joint weights,
  native drivers and existing bone skinning; no shape keys or extra quality modes are added.
- For existing scenes, select the imported head rig and press Rebuild Drivers after loading this
  update. New imports receive the fix automatically. Open the jaw, then raise the four Lips Together
  controls to bring the lips together while keeping the jaw open.
- Regression tests compare individual and combined lip movement against native RigLogic on
  Ada, MH_BASE and Taro, and check that other Lite expressions are unchanged with these controls at zero.
  Imports and rebuilds also pass in Blender 5.0 (MH_BASE, joined board) and 5.2 (Ada, separate board),
  including mesh movement from each control, valid native drivers and save/reopen with the add-on unregistered.

## 1.0.6

- Remove All sits beside Import DNA. It removes MetaMorphosis imports from the current scene,
  including the head, armatures, face board, widgets and RigLogic helpers, plus unused imported data.
  A confirmation dialog identifies the scope; Blender Undo can restore the removal.
- New imports carry persistent ownership tags, so renaming or moving imported objects does not
  prevent cleanup. Rebuilt helper objects retain ownership. Partial imports can also be removed.
  Unrelated objects (even inside imported collections), shared data and objects used in other scenes
  are preserved. Legacy imports are identified through their rig, mesh, board and widget references;
  unidentifiable legacy extras are preserved rather than guessed at. No global orphan purge is used.
  Legacy characters previously joined with an external body rig are preserved and require manual removal,
  because deleting the combined armature would also delete the external body's bones.
- Removed the Combine Body Rig feature and its settings. Previously combined rigs remain intact.
- Removed blendshape import: new imports contain geometry, skinning and bone-driven expressions,
  without DNA shape keys. Existing shape keys in older scenes are not deleted by updating the add-on;
  rebuilding those scenes continues to support their existing drivers.
- Simplified the sidebar with adjacent import/removal controls, rig status, grouped controls and
  a collapsible Diagnostics panel. Panel headers and controls have icons; Blender's vertical sidebar
  category tabs remain text-only.
- Tested real MH_BASE and Ada imports with joined/separate face boards in Blender 5.0 and 5.2,
  including save/reopen, middle-eye motion, no newly imported shape keys and complete owned-object cleanup.
  Additional tests cover unrelated objects, shared materials/scenes, renamed objects and partial imports.

## 1.0.5

- Fixed "Joint group 1 references indices outside of the rig" on the supplied UE 5.7 MH_BASE.dna.
  Control tables now reserve the DNA's declared raw, PSD, ML and RBF control slots. The previous
  reader omitted the additional RBF slots; simply using JointColumnCount would also be insufficient
  for this export. Invalid input/output indices still produce explicit errors.
- RigLogic verification now includes ML/RBF control values when calibrating the PSD table.
- Successfully imported MH_BASE.dna in Blender 5.0 with 12,145 valid native drivers, and checked
  the saved rig and middle-eye behavior in Blender 5.2 without the add-on loaded. Ada and Taro
  still pass native RigLogic model verification. Malformed-index rejection was also tested.
- Lite remains the only mode, and the middle-eye fix is retained. Head/neck RBF pose correctives
  and ML correctives remain unbaked; this release fixes reading their control indices, not their baking.

## 1.0.4

- Removed Exact, Fast and Balanced from import and rebuild options; Lite is the default and only choice.
- CTRL_C_eye (the middle eye control on the face board) now moves both eyes horizontally and vertically.
  Each individual eye control adds its own adjustment to the middle control, within the existing gaze limits.
  Native offset constraints make the side widgets follow the center without taking over their keyframes.
  The baked drivers explicitly include the center input, so this also works after removing the add-on.
- Rebuilding an existing rig applies the eye fix and reuses existing center-eye Copy Location constraints
  instead of adding duplicate offsets. New imports receive the fix automatically, with joined or separate boards.

For an existing scene: install this update, select the MetaMorphosis head rig, and use Rebuild Drivers.
The original DNA file and bindings must still be available. Rebuilding replaces the rig's previous quality with Lite.
The eye fix was checked on Ada in Blender 5.0 and 5.2: both axes, independent offsets, gaze limits,
existing manually added constraints, joined/separate boards, and save/reopen without the add-on.

## 1.0.3

- Imported characters contain ARMATURE, HEAD and RIGLOGICDATA collections.
  Blender adds numeric suffixes when another character already uses those collection names.
- Original skeleton bones are grouped in DEF_HEAD, except spine_04, spine_05, clavicle_l,
  clavicle_r, neck_01, neck_02 and head, which belong to DEF_BODY.
  The face board's existing bone collections are nested under MH_FACE_BOARD, whether joined or separate.
- Imported object names and armature data names are uppercase. Bone names remain unchanged so
  DNA lookup, skin weights and driver references retain their original meanings.
  Armatures use Wire object display with In Front enabled.
- Helper drivers use indexed storage separated by dependency depth, and identical helper
  calculations can be shared. All weights, corrective settings and calculation boundaries are retained.
  Existing rigs can use this storage through Rebuild Drivers.
- The speed measurement also supports a separate face board and restores its controls after measuring.

### Historical performance and verification

The requested 3–6 ms target was not reached. On the supplied Ada scene in Blender 5.2, the
original and updated rigs both measured about 27 ms per update (Lite, the scene's saved quality).
The 1.0.3 storage change produced no difference in the tested facial transforms and did not lower the
quality level. Version 1.0.4 deliberately uses Lite exclusively. Timing depends on the character, scene,
hardware and Blender version.
The 1.0.3 release's Ada DNA imports with joined and separate boards, bone/scene collections, standalone native
drivers, corrective shape drivers, body joins and extension registration were tested in Blender 5.0;
additional native-driver and body-join checks were run in Blender 5.2.

The add-on requires face_board.blend and platform-matched bindings as described above. Existing scenes are not automatically reorganized.
