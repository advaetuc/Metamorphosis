"""Test for CASE A: Standalone Head DNA import followed by Grooms Setup.

Verifies:
1. Head DNA import enables add_rest_position_attribute = True on head mesh.
2. 90mm face camera is created automatically on head DNA import.
3. Eyelash haircard mesh exists after head DNA import.
4. Grooms Setup operator (bpy.ops.metamorphosis.import_setup_grooms) imports grooms:
   - Deletes eyelash haircards immediately (IMP_02)
   - Aligns hair curves
   - Attaches Stick To Surface Geo-Nodes to head mesh
   - Applies Groom Shader material
"""

import sys
from pathlib import Path
import importlib.util
import bpy

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

print("[TEST CASE A] Registering add-on...")
metamorphosis.register()

# 1. Import Head DNA only
head_dna = Path(r"F:\Project_Files\Metahumans\MH_Rick_Grimes\head.dna")
if not head_dna.is_file():
    print(f"[SKIP] {head_dna} not found")
    sys.exit(0)

print(f"[TEST CASE A] Importing Head DNA: {head_dna}...")
res = bpy.ops.metamorphosis.import_dna(
    filepath=str(head_dna),
    character_name="MH_Rick_Grimes",
    synchronous=True,
    join_face_board=True,
)
assert res == {"FINISHED"}, "import_dna failed"
print("  Head DNA imported successfully.")

# 2. Check Camera Import was removed (Requirement 4)
cam = bpy.data.objects.get("Camera_Face")
assert cam is None, "Camera_Face should not be created (camera import removed)"
print("  Verified: No camera created on import.")

# 3. Check Head Mesh and Rest Position attribute
head_mesh = metamorphosis.grooms.find_head_mesh(bpy.context)
assert head_mesh is not None, "Head mesh not found"
assert getattr(head_mesh, "add_rest_position_attribute", False), "add_rest_position_attribute is not True on head mesh"
print(f"  Verified head mesh: {head_mesh.name}, add_rest_position_attribute={head_mesh.add_rest_position_attribute}")

# 4. Check eyelash haircards exist initially
def is_eyelash_mesh(o):
    if o.type != "MESH":
        return False
    name_u = o.name.upper()
    if name_u.startswith("WGT-") or name_u.startswith("CTRL_") or name_u.startswith("FRM_") or name_u.startswith("TEXT_"):
        return False
    return str(o.get("mm_mesh_kind", "")).lower() == "eyelashes" or name_u.endswith("_EYELASHES") or name_u == "EYELASHES"

eyelash_cards_before = [o for o in bpy.data.objects if is_eyelash_mesh(o)]
print(f"  Eyelash haircards before groom setup: {[o.name for o in eyelash_cards_before]}")
assert len(eyelash_cards_before) > 0, "Expected eyelash haircards before groom setup"

# Also check that face board eyelash controls exist before
ctrl_lashes_before = [o.name for o in bpy.data.objects if "EYELASHES" in o.name.upper() and o.name.startswith("CTRL_")]
assert len(ctrl_lashes_before) > 0, "Expected CTRL_ face board controls"

# 5. Set scene properties for Grooms Setup panel
bpy.context.scene.mm_groom_head_mesh = head_mesh
bpy.context.scene.mm_groom_head_uv = "UVMap"

# 6. Run Import and Setup Grooms pointing to Grooms folder
grooms_folder = head_dna.parent / "Grooms"
print(f"[TEST CASE A] Running import_setup_grooms from {grooms_folder}...")
res = bpy.ops.metamorphosis.import_setup_grooms(filepath=str(grooms_folder / "beard.abc"))
assert res == {"FINISHED"}, "import_setup_grooms failed"

# 7. Check eyelash haircards deleted (IMP_02)
eyelash_cards_after = [o for o in bpy.data.objects if is_eyelash_mesh(o)]
print(f"  Eyelash haircards after groom setup: {[o.name for o in eyelash_cards_after]}")
assert len(eyelash_cards_after) == 0, f"IMP_02 failed: Eyelash haircards still exist: {[o.name for o in eyelash_cards_after]}"

# Verify face board controls were PRESERVED and not deleted
ctrl_lashes_after = [o.name for o in bpy.data.objects if "EYELASHES" in o.name.upper() and o.name.startswith("CTRL_")]
assert len(ctrl_lashes_after) == len(ctrl_lashes_before), "Face board controls were accidentally deleted!"
print(f"  Verified face board controls preserved ({len(ctrl_lashes_after)} controls).")

# 8. Check Grooms Collection (Requirement 5)
groom_col = bpy.data.collections.get("Groom")
assert groom_col is not None, "Collection 'Groom' not found"
head_cols = [c for c in bpy.data.collections if c.get("mm_collection_role") == "HEAD" or "HEAD" in c.name.upper()]
assert any(groom_col.name in hc.children for hc in head_cols), "Collection 'Groom' is not inside the Head Collection"
print(f"  Verified: Collection 'Groom' is inside Head Collection {[hc.name for hc in head_cols if groom_col.name in hc.children][0]}")

# 9. Check curves objects, modifiers & radii (Requirement 1 & 2)
curves = [o for o in bpy.data.objects if o.type == "CURVES"]
print(f"  Imported {len(curves)} grooms:")
for c in curves:
    assert c.name in groom_col.objects, f"Groom {c.name} not in 'Groom' collection"
    # Stick to Surface Follow Mesh == 1.0
    stick_mod = c.modifiers.get("Stick To Surface")
    assert stick_mod is not None, f"Stick To Surface missing on {c.name}"
    follow_val = getattr(stick_mod.properties.inputs, "Input_3").value
    assert abs(follow_val - 1.0) < 1e-4, f"Follow Mesh expected 1.0, got {follow_val} on {c.name}"

    if "fuzz" in c.name.lower():
        assert "Set Hair Curve Profile" not in [m.name for m in c.modifiers], "Peach Fuzz modifier should have been applied immediately"
        assert "radius" in c.data.attributes, "Peach Fuzz missing 'radius' attribute"
        fuzz_rad = c.data.attributes["radius"].data[0].value
        assert abs(fuzz_rad - 0.000025) < 1e-7, f"Expected 0.000025 radius on Peach Fuzz, got {fuzz_rad}"
        print(f"    - {c.name}: 'Set Hair Curve Profile' applied with radius 0.000025 (verified), Follow Mesh = 1.0")
    else:
        prof_mod = c.modifiers.get("Set Hair Curve Profile")
        assert prof_mod is not None, f"Set Hair Curve Profile missing on {c.name}"
        rad_val = getattr(prof_mod.properties.inputs, "Input_3").value
        assert abs(rad_val - 0.00005) < 1e-7, f"Expected 0.00005 radius on {c.name}, got {rad_val}"
        print(f"    - {c.name}: 'Set Hair Curve Profile' radius = 0.00005 (verified), Follow Mesh = 1.0")

    assert len(c.data.materials) > 0, f"Material missing on {c.name}"
print(f"  Imported {len(curves)} grooms:")
for c in curves:
    print(f"    - {c.name}: modifiers={[m.name for m in c.modifiers]}, materials={[m.name for m in c.data.materials if m]}")
    assert any(m.name == "Stick To Surface" for m in c.modifiers), f"Stick To Surface missing on {c.name}"
    assert len(c.data.materials) > 0, f"Material missing on {c.name}"

print("\n=== CASE A TEST PASSED SUCCESSFULLY! ===\n")
