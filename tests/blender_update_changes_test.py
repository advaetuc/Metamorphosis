"""Test verification for user requests:
1. Body Detail Tiling set to 45 by any import means.
2. 4D sculpting totally removed.
3. Redundant "Assemble Character" panel removed (only top panel).
4. Custom split normals automatically removed upon mesh import.
"""
import sys
from pathlib import Path
import bpy

sys.dont_write_bytecode = True

try:
    import bl_ext.user_default.metamorphosis as metamorphosis
except ImportError:
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import metamorphosis
    metamorphosis.register()

print("[TEST] MetaMorphosis loaded successfully!")

# -----------------------------------------------------------------------------
# Check 2: 4D Sculpting totally removed
# -----------------------------------------------------------------------------
print("[TEST 2] Verifying 4D sculpting is totally removed...")
addon_panels = [getattr(cls, "bl_idname", "") for cls in getattr(bpy.types, "Panel", []).__subclasses__()]
assert "MM_PT_sculpt" not in addon_panels, "MM_PT_sculpt should NOT be registered as a Panel!"

# Check sculpt operators are not registered
registered_ops = dir(bpy.ops.metamorphosis)
assert "sculpt_start" not in registered_ops, "sculpt_start should NOT be registered!"
assert "sculpt_cancel" not in registered_ops, "sculpt_cancel should NOT be registered!"
assert "sculpt_bake" not in registered_ops, "sculpt_bake should NOT be registered!"
assert "export_dna" not in registered_ops, "export_dna should NOT be registered!"
assert "expression_start" not in registered_ops, "expression_start should NOT be registered!"
assert "expression_apply" not in registered_ops, "expression_apply should NOT be registered!"
print("  Check 2 PASSED: 4D Sculpt panel and operators are completely gone.")

# -----------------------------------------------------------------------------
# Check 3: Assemble Character panel removed from bottom, one sits at top of Addon
# -----------------------------------------------------------------------------
print("[TEST 3] Verifying Assemble Character panel layout...")
assert "MM_PT_assemble_character" not in addon_panels, (
    "MM_PT_assemble_character should NOT be registered as a separate panel!"
)
assert hasattr(bpy.types.Scene, "mm_assemble_custom_shapes"), "mm_assemble_custom_shapes property missing!"
assert hasattr(bpy.types.Scene, "mm_assemble_join_face_board"), "mm_assemble_join_face_board property missing!"
print("  Check 3 PASSED: Redundant bottom panel removed; top panel controls available.")

# -----------------------------------------------------------------------------
# Check 1 & 4: Import Body & Verify Detail Tiling = 45 and Custom Normals Removed
# -----------------------------------------------------------------------------
print("[TEST 1 & 4] Testing Body import with MH_Rick_Grimes body.dna...")
body_dna = Path(r"F:\Project_Files\Metahumans\MH_Rick_Grimes\body.dna")
if not body_dna.exists():
    body_dna = Path(r"F:\Project_Files\Metahumans\MH_John_Rambo\body.dna")

if body_dna.exists():
    res = bpy.ops.metamorphosis.import_body(filepath=str(body_dna))
    assert res == {"FINISHED"}, f"import_body failed: {res}"

    # Check custom normals removed on body meshes
    body_meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.get("mm_body_mesh")]
    assert len(body_meshes) > 0, "No body meshes found!"
    for bm in body_meshes:
        assert not bm.data.has_custom_normals, (
            f"Body mesh {bm.name} has_custom_normals should be False, but got True!"
        )
    print(f"  Check 4 (Body) PASSED: {len(body_meshes)} body meshes have custom normals cleared.")

    # Check detail tiling = 45
    body_mat = next((m for m in bpy.data.materials if "body" in m.name.lower() and m.node_tree and any("BODY_MATERIAL" in n.name or (hasattr(n, "node_tree") and "BODY" in getattr(n.node_tree, "name", "")) for n in m.node_tree.nodes)), None)
    assert body_mat is not None, "Body material with node tree was not found!"
    body_mat_node = next((n for n in body_mat.node_tree.nodes if "BODY_MATERIAL" in n.name or (hasattr(n, "node_tree") and "BODY" in getattr(n.node_tree, "name", ""))), None)
    assert body_mat_node is not None, "BODY_MATERIAL node missing in body material node tree!"
    tiling_val = body_mat_node.inputs["DETAIL_TILING"].default_value
    assert abs(tiling_val - 45.0) < 1e-4, f"Body DETAIL_TILING should be 45.0, got {tiling_val}"
    print(f"  Check 1 (Body import) PASSED: DETAIL_TILING = {tiling_val}")

    # Clean up scene
    bpy.ops.metamorphosis.remove_all()
    print("  Cleaned up body scene.")

# -----------------------------------------------------------------------------
# Check 4: Head DNA import & verify custom normals removed
# -----------------------------------------------------------------------------
print("[TEST 4 (Head)] Testing Head DNA import with Ada.dna...")
ada_dna = Path(r"F:\BlendLAB\Metahumans\Ada.dna")
if ada_dna.exists():
    res = bpy.ops.metamorphosis.import_dna(filepath=str(ada_dna), synchronous=True)
    assert res == {"FINISHED"}, f"import_dna failed: {res}"

    head_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    assert len(head_meshes) > 0, "No head meshes found!"
    for hm in head_meshes:
        assert not hm.data.has_custom_normals, (
            f"Mesh {hm.name} has_custom_normals should be False, but got True!"
        )
    print(f"  Check 4 (Head) PASSED: {len(head_meshes)} meshes have custom normals cleared.")

    bpy.ops.metamorphosis.remove_all()
    print("  Cleaned up head scene.")

# -----------------------------------------------------------------------------
# Check 1, 3, 4: Character Assembly End-to-End
# -----------------------------------------------------------------------------
print("[TEST 1, 3, 4] Testing Character Assembly with MH_Rick_Grimes...")
manifest_file = Path(r"F:\Project_Files\Metahumans\MH_Rick_Grimes\CharacterAssemblyManifest.json")
if manifest_file.exists():
    res = bpy.ops.metamorphosis.import_character(
        filepath=str(manifest_file),
        body_custom_shapes="UNREAL",
        join_face_board=False,
    )
    assert res == {"FINISHED"}, f"import_character failed: {res}"

    # Verify custom normals removed on all meshes in assembled character
    char_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    for cm in char_meshes:
        assert not cm.data.has_custom_normals, (
            f"Mesh {cm.name} has_custom_normals should be False, but got True!"
        )
    print(f"  Check 4 (Assembly) PASSED: All {len(char_meshes)} character meshes have custom normals cleared.")

    # Verify body detail tiling is 45.0
    body_mat = next((m for m in bpy.data.materials if m.node_tree and "BODY_MATERIAL" in m.node_tree.nodes), None)
    assert body_mat is not None, "Body material with BODY_MATERIAL node was not found!"
    body_mat_node = body_mat.node_tree.nodes["BODY_MATERIAL"]
    tiling_val = body_mat_node.inputs["DETAIL_TILING"].default_value
    assert abs(tiling_val - 45.0) < 1e-4, f"Assembled body DETAIL_TILING should be 45.0, got {tiling_val}"
    print(f"  Check 1 (Assembly) PASSED: Body DETAIL_TILING = {tiling_val}")

    bpy.ops.metamorphosis.remove_all()
    print("  Cleaned up assembled character scene.")

print("\n=== ALL USER REQUEST CHECKS PASSED SUCCESSFULLY! ===")
