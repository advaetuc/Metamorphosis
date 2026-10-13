# MetaMorphosis 1.0.9 (Blender 5.0+)

Imports a MetaHuman head DNA (head, eyes, teeth, ... one object + material slot each, original facial
deformation rig, face board with widgets) and bakes RigLogic into native Blender drivers.

Setup (one time)
1. Install the zip: Edit > Preferences > Get Extensions > (v) Install from Disk, then restart Blender.
2. Face board: `face_board.blend` in the add-on `assets` folder, or set its path in the add-on preferences.
3. Bindings: Poly Hammer's `bindings` folder copied into the add-on `bindings` folder, or its path in the
   preferences. Press "Test Bindings" in the preferences to check.

Use: File > Import > MetaHuman Head DNA (MetaMorphosis), or the MetaMorphosis tab in the sidebar.

Lite is the only import and rebuild mode. It retains primary expressions and the combination
correctives required by Lips Together and Jaw Open Extreme; other combination correctives remain omitted.
Details of every import are in the text block "MetaMorphosis Report".

Changes in 1.0.9 — Phase 1
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

Capture implementation references
- The supplied Faceit and LiveLinkFace receiver files were used to understand packet layouts and
  capture workflows. Their shape-key-dependent animation code is not installed or required.
- [PyLiveLinkFace protocol](https://github.com/JimWest/PyLiveLinkFace),
  [Epic's iOS facial capture guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/recording-face-animation-on-ios-device-in-unreal-engine),
  and [Google's Face Landmarker API](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python).
- Phase 2 material/texture setup is awaiting the separately promised files.

Changes in 1.0.8
- Fixed the Jaw Open Extreme face-board control by retaining its DNA joint correctives, including
  combinations with other mouth expressions. These combinations were previously omitted by Lite.
- Open the regular jaw control first, then raise Jaw Open Extreme to extend the opening. This
  follows the DNA's behavior: Extreme has no effect while the regular jaw is fully closed.
- The Lips Together fix and existing Lite primary-expression settings are preserved. Existing
  scenes receive this fix by selecting the head rig and pressing Rebuild Drivers after loading the update.
- Checked 108 poses per DNA against native RigLogic on Ada, MH_BASE and Taro. Import/rebuild tests
  pass in Blender 5.0 and 5.2 with joined/separate face boards, including mesh movement, valid native
  drivers, the previous eye/lip fixes and save/reopen with the add-on unregistered.

Changes in 1.0.7
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

Changes in 1.0.6
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

Changes in 1.0.5
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

Changes in 1.0.4
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

Changes in 1.0.3
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

Performance and verification
The requested 3–6 ms target was not reached. On the supplied Ada scene in Blender 5.2, the
original and updated rigs both measured about 27 ms per update (Lite, the scene's saved quality).
The 1.0.3 storage change produced no difference in the tested facial transforms and did not lower the
quality level. Version 1.0.4 deliberately uses Lite exclusively. Timing depends on the character, scene,
hardware and Blender version.
The 1.0.3 release's Ada DNA imports with joined and separate boards, bone/scene collections, standalone native
drivers, corrective shape drivers, body joins and extension registration were tested in Blender 5.0;
additional native-driver and body-join checks were run in Blender 5.2.

The add-on requires face_board.blend and platform-matched bindings as described above. Existing scenes are not automatically reorganized.
