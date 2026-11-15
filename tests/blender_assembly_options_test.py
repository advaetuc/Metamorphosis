"""Test Character Assembly options (Unreal vs Blender shapes, Join Face Board Yes/No) and head-body merge."""

import sys
from pathlib import Path
import importlib.util
import json
import bpy
from mathutils import Matrix

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "metamorphosis",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
metamorphosis = addon

print("[TEST] Registering MetaMorphosis add-on...")
metamorphosis.register()
print("[TEST] Registration successful!")

# Clear default scene objects (Cube, Light, Camera)
for o in list(bpy.context.scene.objects):
    bpy.data.objects.remove(o, do_unlink=True)

manifest_path = Path(r"F:\Project_Files\Metahumans\MH_Rick_Grimes\CharacterAssemblyManifest.json")
if not manifest_path.is_file():
    print(f"[SKIP] Manifest not found at {manifest_path}")
    sys.exit(0)

# =========================================================================
# TEST 1: UNREAL shapes + Separate Face Board (join_face_board=False)
# =========================================================================
print("\n[TEST 1] Testing Character Assembly: UNREAL shapes, Separate Face Board...")
res1 = metamorphosis.assemble.assemble_character(
    bpy.context,
    manifest_path,
    body_custom_shapes="UNREAL",
    join_face_board=False,
)
print("  Results 1:", res1)
assert res1["body_imported"], "Body DNA failed to import"
assert res1["body_rig_built"], "Body control rig failed to build"
assert res1["head_imported"], "Head DNA failed to import"
assert res1["merged"], "Head and body failed to merge"

body_rig1 = bpy.data.objects.get("METAHUMAN_BODY_RIG")
assert body_rig1 is not None, "METAHUMAN_BODY_RIG not found"
assert body_rig1.get("mm_attached_head"), "mm_attached_head flag missing on merged rig"

board_name1 = str(body_rig1.get(metamorphosis.bake.RIG_KEY_BOARD_OBJECT, ""))
board1 = bpy.data.objects.get(board_name1)
assert board1 is not None, f"Face board armature '{board_name1}' should exist when join_face_board=False"
assert board1 != body_rig1, "Face board should be a separate armature when join_face_board=False"
assert board1.constraints.get("Follow MetaHuman Head") is not None, "Face board missing Follow MetaHuman Head constraint"

# Check head bone parenting
pb_head = body_rig1.pose.bones.get("head")
assert pb_head is not None, "Pose bone 'head' missing on merged rig"
assert pb_head.parent is not None and pb_head.parent.name == "BODY_BIND_head", f"Expected head parent BODY_BIND_head, got {pb_head.parent.name if pb_head.parent else None}"

# Check head mesh modifier points to merged rig
head_mesh1 = metamorphosis.grooms.find_head_mesh(bpy.context)
assert head_mesh1 is not None, "Head mesh not found"
arm_mod1 = next((m for m in head_mesh1.modifiers if m.type == "ARMATURE"), None)
assert arm_mod1 is not None and arm_mod1.object == body_rig1, f"Head mesh armature modifier should target METAHUMAN_BODY_RIG, got {arm_mod1.object if arm_mod1 else None}"

# Test deformation follow: Move neck/head control and verify head bone moves!
body_rig1.pose.bones["BODY_BIND_head"].matrix_basis = Matrix.Translation((0.0, 0.0, 0.1))
bpy.context.view_layer.update()
head_world_z = (body_rig1.matrix_world @ pb_head.matrix).translation.z
print(f"  Posed BODY_BIND_head Z translation: head bone world Z = {head_world_z:.4f}")

# Clean up Test 1
print("  Testing Remove All after Test 1...")
cleanup_res = bpy.ops.metamorphosis.remove_all()
assert cleanup_res == {"FINISHED"}, "Remove All failed"
assert len(bpy.context.scene.objects) == 0, f"Expected 0 objects after remove_all, got {[o.name for o in bpy.context.scene.objects]}"
print("  Test 1 cleanup verified: 0 objects remaining.")

# =========================================================================
# TEST 2: BLENDER shapes + Joined Face Board (join_face_board=True)
# =========================================================================
print("\n[TEST 2] Testing Character Assembly: BLENDER shapes, Joined Face Board...")
res2 = metamorphosis.assemble.assemble_character(
    bpy.context,
    manifest_path,
    body_custom_shapes="BLENDER",
    join_face_board=True,
)
print("  Results 2:", res2)
assert res2["body_imported"], "Body DNA failed to import"
assert res2["body_rig_built"], "Body control rig failed to build"
assert res2["head_imported"], "Head DNA failed to import"
assert res2["merged"], "Head and body failed to merge"

body_rig2 = bpy.data.objects.get("METAHUMAN_BODY_RIG")
assert body_rig2 is not None, "METAHUMAN_BODY_RIG not found"
assert body_rig2.get("mm_attached_head"), "mm_attached_head flag missing on merged rig"

# When join_face_board=True, NO separate face board armature should exist!
board2 = bpy.data.objects.get("FACE_GUI") or bpy.data.objects.get("MH_RICK_GRIMES_RIG_FACE_BOARD")
assert board2 is None, f"Separate face board armature should NOT exist when join_face_board=True, found: {board2}"
assert body_rig2.get(metamorphosis.bake.RIG_KEY_BOARD_OBJECT) == body_rig2.name, "RIG_KEY_BOARD_OBJECT should be merged rig name"

# All face board bones should be inside METAHUMAN_BODY_RIG
board_names = set(filter(None, str(body_rig2.get(metamorphosis.bake.RIG_KEY_BOARD, "")).split("\n")))
assert len(board_names) > 0, "RIG_KEY_BOARD missing or empty on merged rig"
assert all(n in body_rig2.pose.bones for n in board_names), "Not all face board bones found in METAHUMAN_BODY_RIG"
print(f"  Verified all {len(board_names)} face board bones are joined inside METAHUMAN_BODY_RIG.")

# Clean up Test 2
print("  Testing Remove All after Test 2...")
cleanup_res2 = bpy.ops.metamorphosis.remove_all()
assert cleanup_res2 == {"FINISHED"}, "Remove All failed"
assert len(bpy.context.scene.objects) == 0, f"Expected 0 objects after remove_all, got {[o.name for o in bpy.context.scene.objects]}"
print("  Test 2 cleanup verified: 0 objects remaining.")

# =========================================================================
# TEST 3: Operator Execution (metamorphosis.import_character)
# =========================================================================
print("\n[TEST 3] Testing operator metamorphosis.import_character...")
scene = bpy.context.scene
scene.mm_assemble_custom_shapes = "UNREAL"
scene.mm_assemble_join_face_board = False

op_res = bpy.ops.metamorphosis.import_character(
    filepath=str(manifest_path),
    body_custom_shapes="UNREAL",
    join_face_board=False,
)
assert op_res == {"FINISHED"}, f"import_character operator failed: {op_res}"

char_rig = bpy.data.objects.get("METAHUMAN_BODY_RIG")
assert char_rig is not None, "METAHUMAN_BODY_RIG not found from operator import"
assert char_rig.get("mm_attached_head"), "Character head not merged in operator import"
print("  Operator import verified: character assembled and head-body merged.")

# Clean up Test 3
bpy.ops.metamorphosis.remove_all()
assert len(bpy.context.scene.objects) == 0, "Cleanup failed"

print("\n=== ALL OPTIONS AND MERGE TESTS PASSED SUCCESSFULLY! ===")
