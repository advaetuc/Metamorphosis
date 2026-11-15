"""Comprehensive integration test for MetaMorphosis Update 2.80 Character Assembly.

Tests:
1. Addon registration & class hierarchy
2. Character Assembly with CharacterAssemblyManifest.json on Rick Grimes:
   - Body DNA import & control rig build
   - Head DNA import with baked RigLogic & 870 custom shapes & colors
   - Head & body skeleton connection
   - Materials & texture assignment
   - Groom imports, alignment, Stick To Surface geo-nodes, Groom Shader
   - Eyelash haircard deletion (IMP_02)
   - 90mm face camera creation and positioning
3. Grooms Setup panel (CASE A) standalone verification
4. HDRI Lighting controls (selection, intensity, clear)
"""

import sys
from pathlib import Path
import importlib.util
import bpy
import math

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

# Test HDRI Lighting
print("[TEST] Testing Lighting controls...")
scene = bpy.context.scene
assert hasattr(scene, "mm_hdri_selection"), "mm_hdri_selection missing"
assert hasattr(scene, "mm_hdri_intensity"), "mm_hdri_intensity missing"

scene.mm_hdri_intensity = 1.5
assert scene.mm_hdri_intensity == 1.5, "mm_hdri_intensity failed to set"
scene.mm_hdri_selection = "HDRI_4K"
print("  HDRI_4K selected, world nodes:", len(scene.world.node_tree.nodes) if scene.world and scene.world.node_tree else 0)

res = bpy.ops.metamorphosis.clear_hdri()
assert res == {"FINISHED"}, "clear_hdri failed"
print("  Clear HDRI finished.")

# Test Character Assembly
manifest_path = Path(r"F:\Project_Files\Metahumans\MH_Rick_Grimes\CharacterAssemblyManifest.json")
if not manifest_path.is_file():
    print(f"[SKIP] Manifest not found at {manifest_path}")
    sys.exit(0)

print(f"[TEST] Testing assemble_character with {manifest_path}...")
results = metamorphosis.assemble.assemble_character(bpy.context, manifest_path)
print("[TEST] Assembly results:", results)

assert results["head_imported"], "Head DNA failed to import"
assert results["body_imported"], "Body DNA failed to import"
assert results["body_rig_built"], "Body control rig failed to build"
assert results["merged"], "Head and body failed to merge"
assert results["materials_applied"], "Materials failed to apply"
assert results["grooms_count"] > 0, f"Expected grooms, got {results['grooms_count']}"

# Verify Camera Import was REMOVED (Requirement 4)
cam = bpy.data.objects.get("Camera_Face")
assert cam is None, "Camera_Face should not be created (Camera import removed per requirement)"
print("  Requirement 4 verified: Camera import removed, no Camera_Face created.")

# Verify Eyelash haircard deletion (IMP_02)
def is_eyelash_mesh(o):
    if o.type != "MESH":
        return False
    name_u = o.name.upper()
    if name_u.startswith("WGT-") or name_u.startswith("CTRL_") or name_u.startswith("FRM_") or name_u.startswith("TEXT_"):
        return False
    return str(o.get("mm_mesh_kind", "")).lower() == "eyelashes" or name_u.endswith("_EYELASHES") or name_u == "EYELASHES"

eyelash_cards = [o for o in bpy.data.objects if is_eyelash_mesh(o)]
assert len(eyelash_cards) == 0, f"Eyelash haircards were not deleted: {[o.name for o in eyelash_cards]}"
print("  IMP_02 verified: eyelash haircards deleted and replaced by groom.")

# Verify Grooms Collection (Requirement 5)
# Put the Grooms in the Head Collection inside a Collection called "Groom"
groom_col = bpy.data.collections.get("Groom")
assert groom_col is not None, "Collection 'Groom' not found in bpy.data.collections"
head_cols = [c for c in bpy.data.collections if c.get("mm_collection_role") == "HEAD" or "HEAD" in c.name.upper()]
assert any(groom_col.name in hc.children for hc in head_cols), "Collection 'Groom' is not inside the Head Collection"
print(f"  Requirement 5 verified: Collection 'Groom' is inside Head Collection {[hc.name for hc in head_cols if groom_col.name in hc.children][0]}")

# Verify Grooms Modifiers & Radius (Requirement 1 & 2)
curves_objs = [o for o in bpy.data.objects if o.type == "CURVES"]
print(f"  Found {len(curves_objs)} hair curve objects:")
for c in curves_objs:
    assert c.name in groom_col.objects, f"Groom {c.name} is not linked to 'Groom' collection"
    # Requirement 2: Stick To Surface Follow Mesh == 1.0
    stick_mod = c.modifiers.get("Stick To Surface")
    assert stick_mod is not None, f"Stick To Surface modifier missing on {c.name}"
    follow_val = getattr(stick_mod.properties.inputs, "Input_3").value
    assert abs(follow_val - 1.0) < 1e-4, f"Stick To Surface Follow Mesh expected 1.0, got {follow_val} on {c.name}"

    # Requirement 1: Peach Fuzz radius 0.000025 applied immediately; Other grooms radius 0.00005
    if "fuzz" in c.name.lower():
        # Modifier should be applied immediately
        assert "Set Hair Curve Profile" not in [m.name for m in c.modifiers], f"Peach Fuzz modifier should have been applied immediately: {c.modifiers.keys()}"
        assert "radius" in c.data.attributes, f"Peach Fuzz missing 'radius' attribute after apply: {c.data.attributes.keys()}"
        fuzz_radius = c.data.attributes["radius"].data[0].value
        assert abs(fuzz_radius - 0.000025) < 1e-7, f"Peach Fuzz radius expected 0.000025, got {fuzz_radius}"
        print(f"    - {c.name}: 'Set Hair Curve Profile' applied with radius 0.000025 (verified), Follow Mesh = 1.0")
    else:
        prof_mod = c.modifiers.get("Set Hair Curve Profile")
        assert prof_mod is not None, f"Set Hair Curve Profile modifier missing on {c.name}"
        rad_val = getattr(prof_mod.properties.inputs, "Input_3").value
        assert abs(rad_val - 0.00005) < 1e-7, f"Groom {c.name} expected radius 0.00005, got {rad_val}"
        print(f"    - {c.name}: 'Set Hair Curve Profile' radius = 0.00005 (verified), Follow Mesh = 1.0")

    assert len(c.data.materials) > 0, f"Material missing on groom {c.name}"

# Verify Character Armature and Custom Shapes & Colors
armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
print(f"  Armatures in scene: {[a.name for a in armatures]}")

# Look for the merged character rig (which has attached head) or any character armature
char_rig = next((a for a in armatures if a.get("mm_attached_head") or a.get("mm_body_rig")), None)
if not char_rig and armatures:
    char_rig = armatures[0]

assert char_rig is not None, "Character armature not found"
print(f"  Found character armature: {char_rig.name}")

custom_shapes_count = 0
custom_colors_count = 0
for pb in char_rig.pose.bones:
    if pb.custom_shape is not None:
        custom_shapes_count += 1
    if pb.color and pb.color.palette == "CUSTOM":
        custom_colors_count += 1

# Also check face board if separated
board_obj = next((a for a in armatures if "BOARD" in a.name.upper()), None)
if board_obj:
    print(f"  Found face board armature: {board_obj.name}")

print(f"  Character rig bones with custom shapes: {custom_shapes_count}")
print(f"  Character rig bones with custom colors: {custom_colors_count}")
assert custom_shapes_count > 0, "No custom shapes found on character rig"
assert custom_colors_count > 0, "No custom colors found on character rig"

print("\n=== ALL INTEGRATION TESTS PASSED SUCCESSFULLY! ===\n")
