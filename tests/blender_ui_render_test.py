"""Test rendering of MM_PT_panel to verify layout runs cleanly without errors."""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("metamorphosis", ROOT / "__init__.py",
                                            submodule_search_locations=[str(ROOT)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()

import bpy
from metamorphosis.core import ui

class DummyLayout:
    def __init__(self, depth=0):
        self.depth = depth
        self.use_property_split = False
        self.use_property_decorate = False
        self.scale_y = 1.0
        self.alignment = 'EXPAND'
        self.enabled = True

    def row(self, align=False):
        return DummyLayout(self.depth + 1)

    def column(self, align=False):
        return DummyLayout(self.depth + 1)

    def box(self):
        return DummyLayout(self.depth + 1)

    def label(self, text="", icon='NONE', icon_value=0):
        pass

    def prop(self, data, prop_name, text="", toggle=False, expand=False, icon='NONE', slider=False):
        pass

    def prop_search(self, data, prop_name, search_data, search_prop_name, text=""):
        pass

    def operator(self, op_id, text="", icon='NONE', icon_value=0):
        class DummyOp:
            def __setattr__(self, key, value):
                pass
        return DummyOp()

    def template_icon(self, icon_value=0, scale=1.0):
        pass

    def template_icon_view(self, data, prop_name, show_labels=True, scale=1.0):
        pass

    def separator(self, factor=1.0):
        pass

class DummyPanel:
    def __init__(self):
        self.layout = DummyLayout()

# Test draw on clean scene
context = bpy.context
dp = DummyPanel()
ui.MM_PT_panel.draw(dp, context)
print("MM_PT_panel.draw (clean scene) PASSED!")

# Now test child panels
for cls in ui.CLASSES:
    if issubclass(cls, bpy.types.Panel):
        p = DummyPanel()
        try:
            cls.draw(p, context)
            print(f"{cls.__name__}.draw PASSED!")
        except Exception as e:
            print(f"{cls.__name__}.draw FAILED: {e}")
            raise e

print("ALL UI PANELS DRAW SUCCESSFULLY!")
