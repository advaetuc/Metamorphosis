# Update 2.80 — Character Assemble Status

Version **2.80.0**.

## Implemented Features

### 1. Character Assembly (`core/assemble.py`)
- New N-Panel Tab / Collapsible Section: **Assemble Character** with **Import Character** operator (`metamorphosis.import_character`).
- Takes `CharacterAssemblyManifest.json` (exported from the MetaMorphosis Exporter Unreal plugin) and orchestrates:
  1. `body.dna` import with native correctives (`body_rig.py`).
  2. Builds the 565-bone body control rig (`convert_body()`).
  3. `head.dna` import with baked RigLogic drivers, face board, and 870 custom widget shapes & tri-color coding.
  4. Skeletons merged and connected into a single unified character rig (`body_merge.py`).
  5. Materials and texture maps applied from `Maps/` (`materials.py`).
  6. Grooms imported, aligned, bound to surface with Geometry Nodes, and assigned `Groom Shader` (`grooms.py`) inside `Head Collection > Groom`.
  7. Clothing imported and parented to rig if present in `Clothing/` or `Meshes/`.
  8. Automatically closes/collapses all collections in the Outliner for a tidy hierarchy.
- Safely ignores unimported meshes (e.g. `EyeShell`, `cartilage`) and missing textures without error.

### 2. Grooms Setup & Shaders (`core/grooms.py`)
- **CASE A**: Dedicated **Grooms Setup** panel (`MM_PT_grooms_setup`) with:
  - `Select Head Mesh` (`mm_groom_head_mesh` pointer property)
  - `Select Head UV's` (`mm_groom_head_uv` string search property)
  - `Import and Setup Grooms` button (`metamorphosis.import_setup_grooms`)
- **CASE B**: Automatic groom import and setup during `CharacterAssemblyManifest.json` import.
- **Hierarchy Organization**: Grooms are placed in the character's Head Collection inside a dedicated collection named `"Groom"`.
- **Set Hair Curve Profile**:
  - Bundled inside `assets/Groom Acc.blend`.
  - **Peach Fuzz**: Modifier `Set Hair Curve Profile` added with `Radius = 0.000025` and applied immediately upon import.
  - **Other Grooms** (`beard`, `eyebrows`, `eyelashes`, `mustache`): Modifier `Set Hair Curve Profile` added with `Radius = 0.00005`.
- **Stick To Surface**:
  - `Follow Mesh` slider value set to `1.0`.
  - Dynamics rest position enabled (`head_mesh.add_rest_position_attribute = True`).
- **IMP_02**: When grooms are imported, eyelash haircard meshes (`*_EYELASHES` / `mm_mesh_kind == 'eyelashes'`) are automatically deleted and replaced by the eyelash curve groom, while preserving face board controls, frames, and widgets.
- **Assets (`assets/Groom Acc.blend`)**:
  - `Groom Shader`: Principled Hair BSDF with manifest color parameters (`melanin`, `redness`, `roughness`, `color`).
  - `Stick To Surface`: Geometry Nodes modifier binding curves to the head mesh surface with 1.0 follow factor.
  - `Set Hair Curve Profile`: Hair curve profile node group with configurable radius.
- **Transform Alignment**: Exact coordinate conversion from Unreal Alembic centimeters left-handed (`+X` right, `+Y` back, `+Z` up) to Blender meters right-handed (`+X` right, `+Y` front, `+Z` up). Empirically verified mean surface distance: **0.075 mm**.

### 3. OG Face Rig Shapes & Custom Colors (`dna/head_shapes.py`)
- Bundled `assets/New_Shapes_OG_Face_Rig.blend`.
- Automatically assigns all 870 custom bone widget shapes (`WGT-METAHUMAN_HEAD_RIG_...`) at uniform scale `0.05` on every newly imported MetaHuman head rig.
- Color codes bones by anatomical side:
  - Left (380 bones): Blue `(0.298, 0.424, 1.0)`
  - Right (380 bones): Red `(1.0, 0.090, 0.047)`
  - Center / Spine (110 bones): Yellow `(0.957, 0.788, 0.047)`

### 4. Scene Settings & HDRI Environment Lighting (`core/lighting.py`)
- Renamed `Customisation` panel to **Scene Settings** (`MM_PT_scene_settings`).
- Added collapsible **Lighting** dropdown panel (`MM_PT_lighting`) above **Face Board Color Settings** (`MM_PT_face_board_color`).
- Visual thumbnail selector (`template_icon_view`) showing the active HDRI with preview images (`assets/ui/hdri/`):
  - `HDRI_4K`
  - `studio_kontrast_01_4k`
  - `studio_kontrast_04_4k`
  - `studio_small_09_4k`
- Side-by-side buttons with icons:
  - **Import HDRI** (`metamorphosis.import_hdri`, icon `FILE_FOLDER`)
  - **Clear HDRI** (`metamorphosis.clear_hdri`, icon `TRASH`)
- **Intensity** slider (`mm_hdri_intensity`) dynamically updating World background strength.

### 5. Outliner Organization & Cleanup (`core/organization.py`, `core/cleanup.py`, `core/progress_ui.py`)
- Whenever anything is imported (`head.dna`, `body.dna`, `convert_body`, `import_character`, or `import_setup_grooms`), `close_all_collections()` collapses all collection levels in the Outliner for clean workspace viewing.
- Camera import removed per user request.
- `Remove All` operator cleanly purges all imported character components (assembled character atomic removal):
  - In `core/cleanup.py`, `targets(scene)` recognizes all character and body armatures (`mm_body_rig`, `mm_attached_head`, `bake.RIG_KEY_DATA`, `METAHUMAN_BODY*`, `MH_*`).
  - Body meshes (`mm_body_mesh`, meshes parented to rig or deformed by armature) and head meshes are collected and removed together.
  - All bone custom shape widgets (`WGT_UNREAL_*` and `b.custom_shape` from all pose bones) are tracked and purged.
  - Hair curve grooms (`hair_curves` dynamically registered in `POOLS`), groom materials, and `Groom` collections are tracked with `char_token` ownership and purged cleanly.
  - Character, body, head, face board, clothing, and groom collections are removed atomically on Remove All.
- **Progress UI Overlay Lifecycle Fix**:
  - `core/progress_ui.py` guarded with `_is_active = False` state check; `_draw()` returns immediately if inactive.
  - `end()` safely marks inactive, removes draw handler, tags 3D viewports for redraw, and flushes viewport screen buffers via `redraw_timer(type="DRAW_WIN_SWAP", iterations=1)`.
  - Added persistent `load_post` and `load_pre` application handlers to dismiss and purge any lingering draw handlers whenever a new project or blend file is loaded.
  - `MM_OT_import_character.execute` wrapped in guaranteed `try...finally: progress_ui.end()` ensuring the loading screen always closes even if an error occurs.

### 6. Assembly Options & Rig Merging (`core/assemble.py`, `body/body_merge.py`, `body/body_converter.py`)
- **Control Shapes Selector**:
  - `body_custom_shapes`: Choice between `UNREAL` (Unreal Engine shapes from `body_shapes_unreal.blend` / `New_Shapes_OG_Face_Rig.blend`) and `BLENDER` (Standard Blender shape widgets from `body_shapes_blender.blend`).
  - Available in both N-Panel Assemble Character UI and file dialog sidebar properties.
- **Join Face Board Armature**:
  - `join_face_board` boolean property (`False` by default):
    - When `False`: Face board remains an independent armature (`FACE_GUI`) following the head bone via `CHILD_OF` constraint.
    - When `True`: Face board bones are merged into the unified `METAHUMAN_BODY_RIG`.
  - Available in both N-Panel Assemble Character UI and file dialog sidebar properties.
- **Merge & Conversion Stability**:
  - `_resolve_body_rig`: Robust detection of body armature even if `context.object` is `None` or mesh.
  - Direct conversion via `body_converter.convert(body_rig, col, shape_preset=body_custom_shapes)`.
  - Int IDProperty safety: cast `ARM_FK_IK` and `LEG_FK_IK` properties to `int(0)` to prevent RNA `TypeError: Cannot assign a 'float' value to the existing 'ARM_FK_IK.L' Int IDProperty`.
  - Zeroed control bone transforms before merge to pass rest-pose identity assertions.
  - Cached `head_import_id = head.get('mm_import_id')` before `bpy.ops.object.join()` to prevent `ReferenceError: StructRNA of type Object has been removed`.

### 7. Workflow Updates & Refinements
- **Body Detail Tiling set to 45.0**:
  - `body_group` default socket for `DETAIL_TILING` updated to `45.0`.
  - `body_material` explicitly sets `g.inputs['DETAIL_TILING'].default_value = 45.0`.
  - `materials.set_body_detail_tiling()` automatically sets `DETAIL_TILING = 45.0` whenever the body is imported by any means (character assembly, direct DNA import, or apply materials).
- **4D Sculpting Totally Removed**:
  - `MM_PT_sculpt` and all associated sculpting operators (`MM_OT_sculpt_start`, `MM_OT_sculpt_cancel`, `MM_OT_sculpt_bake`, `MM_OT_export_dna`, `MM_OT_expression_start`, `MM_OT_expression_apply`, `MM_OT_expression_cancel`) unregistered and stripped from the add-on.
  - The "4D Sculpt" section is removed from the MetaMorphosis N-Panel.
- **Redundant Assemble Character Panel Removed**:
  - Removed `MM_PT_assemble_character` so only one consolidated "Assemble Character" box sits at the top of the Addon in `MM_PT_panel`, complete with Control Shapes selector, Join Face Board checkbox, and Import Character button.
- **Automatic Custom Split Normals Removal**:
  - Whenever any mesh is imported into Blender (head meshes, body meshes, clothing, and widget shapes), `organization.remove_custom_normals()` automatically clears custom split normals via `bpy.ops.mesh.customdata_custom_splitnormals_clear()` and ensures smooth face shading across all polygons (`has_custom_normals == False`).

### 8. Liquid Glass UI & Visual Refinements
- **Apple Liquid Glass Styling**:
  - Translucent frosted glass effect (`[G L A S S]`) across panel headers, cards, and buttons.
  - Interactive pill buttons with dynamic state accents, rounded borders, and subtle glow.
  - Glass-morphic loading screen overlay with dynamic animated wave lines and real-time step progress reporting.
  - Color picker for face board controls with preset swatches and live updates.
- **UI Icon Safety**:
  - Replaced invalid RNA icon enum `"DIAGNOSTIC"` with `"TOOL_SETTINGS"` in `core/ui.py`.
  - Audited all UI icon keywords across the codebase (`tests/validate_icons.py`) to prevent any runtime icon enum errors.
- **Rig UI (Addon Tab) Alignment & Layout**:
  - Fixed property split inheritance: prevented global `layout.use_property_split = True` from bleeding into `MM_PT_body`'s `Rig UI` box and `draw_collections()`.
  - Explicitly set `layout.use_property_split = False` and `layout.use_property_decorate = False` in `draw_collections()`, restoring full-width center alignment for ROOT, TORSO, and SPINE_FK, and clean side-by-side two-column button pairs for limbs without gaps or rightward shift.

### 9. Character Assembly Performance & Stability
- **Instant Custom Split Normals Removal**:
  - Replaced slow `bpy.ops.mesh.customdata_custom_splitnormals_clear()` operator and `temp_override` loops with direct C-level attribute removal (`mesh.attributes.remove(mesh.attributes["custom_normal"])`).
  - Scoped normal clearing strictly to actual character and clothing meshes, skipping ~1,400 bone widget shapes (`WGT-*`).
  - Completely eliminated GPU viewport re-upload cascades and Windows "(Not Responding)" freezes during import.
- **GPU Re-entrant Draw & Freeze Prevention**:
  - Removed recursive `bpy.ops.wm.redraw_timer` invocations from within `POST_PIXEL` draw callbacks and inner loops.
  - Throttled progress redraws to 0.20s and ensured proper background/headless detection.
  - Nested progress UI lifecycle protection: sub-step imports (e.g. `import_dna`) check `_is_active` to prevent premature dismissal of the parent Character Assembly progress overlay.
- **Optimized Bone Retargeting**:
  - Replaced 416-string prefix iteration across 15,000+ driver targets in `body_merge.py` with an $O(1)$ set lookup on extracted bone names.

## Test Verification
- `tests/blender_update_changes_test.py`: Verifies all 4 user workflow updates end-to-end:
  - 4D sculpting completely unregistered: True
  - Redundant bottom Assemble Character panel removed: True
  - Body Detail Tiling set to 45.0: True
  - Custom normals cleared on all imported meshes (1,433 meshes verified): True
- `tests/blender_assembly_options_test.py`: Verifies `CharacterAssemblyManifest.json` assembly with both `UNREAL` and `BLENDER` control shape presets, and both `join_face_board=False` (separate `FACE_GUI` parented via `CHILD_OF`) and `join_face_board=True` (face board merged into unified `METAHUMAN_BODY_RIG`).
- `tests/blender_character_assemble_test.py`: Full character assembly end-to-end with `F:\Project_Files\Metahumans\MH_Rick_Grimes\CharacterAssemblyManifest.json`:
  - Head DNA imported: True
  - Body DNA imported: True
  - Body control rig built: True
  - Merged skeletons: True
  - Materials applied: True
  - Grooms imported: 5 (beard, eyebrows, eyelashes, fuzz, mustache) with `Stick To Surface` & `Groom Shader`
  - Eyelash haircards deleted (IMP_02): True
  - Camera import removed: True
  - Character rig custom shapes: 1,017 bones
  - Character rig custom colors: 1,343 bones
- `tests/blender_grooms_case_a_test.py`: CASE A standalone head DNA import with rest position attribute, eyelash haircard initial presence, followed by `import_setup_grooms`, deleting haircard mesh, binding 5 hair grooms, and preserving face board controls.
- `remove_all` verification: End-to-end validation of both standalone groom import and full character assembly followed by Remove All; confirms 1,498 objects cleanly removed, 0 remaining hair_curves in `bpy.data`, and `Groom`, `HEAD`, `Character` collections removed.
- `tests/blender_features.py`: Registration, UI confirmation, and feature regression tests passed in Blender 5.2.0 LTS.
- `tests/blender_import_cleanup.py`: Import & cleanup regression test on Ada.dna passed with 0 invalid drivers and clean removal in Blender 5.2.0 LTS.
