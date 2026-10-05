# MetaMorphosis 1.0.6 (Blender 5.0+)

Imports a MetaHuman head DNA (head, eyes, teeth, ... one object + material slot each, original facial
deformation rig, face board with widgets) and bakes RigLogic into native Blender drivers.

Setup (one time)
1. Install the zip: Edit > Preferences > Get Extensions > (v) Install from Disk, then restart Blender.
2. Face board: `face_board.blend` in the add-on `assets` folder, or set its path in the add-on preferences.
3. Bindings: Poly Hammer's `bindings` folder copied into the add-on `bindings` folder, or its path in the
   preferences. Press "Test Bindings" in the preferences to check.

Use: File > Import > MetaHuman Head DNA (MetaMorphosis), or the MetaMorphosis tab in the sidebar.

Lite is the only import and rebuild mode. It retains the existing Lite settings, with no combination correctives.
Details of every import are in the text block "MetaMorphosis Report".

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
