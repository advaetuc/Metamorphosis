import re
from pathlib import Path
import bpy

valid_icons = set(bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items.keys())

ROOT = Path(r"c:\Users\Advaet\Documents\Projects\Metamorphosis")
icon_pattern = re.compile(r'icon\s*=\s*[\'"]([A-Za-z0-9_]+)[\'"]')

invalid = []
for py_file in ROOT.rglob("*.py"):
    if ".git" in py_file.parts or "tests" in py_file.parts:
        continue
    text = py_file.read_text(encoding="utf-8")
    for match in icon_pattern.finditer(text):
        icon_name = match.group(1)
        if icon_name not in valid_icons:
            invalid.append((py_file.name, icon_name, match.start()))

print(f"INVALID ICONS FOUND: {len(invalid)}")
for f, name, pos in invalid:
    print(f"  File: {f}, Icon: {name}")
