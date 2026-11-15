"""Shared constants for MetaMorphosis."""
from pathlib import Path

# Addon root directory and central asset / bindings paths
ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT_DIR / "assets"
BINDINGS_DIR = ROOT_DIR / "bindings"

# Name of the add-on package (e.g. ``bl_ext.user_default.metamorphosis`` or ``metamorphosis``).
if __package__:
    _parts = __package__.split(".")
    if _parts[0] == "bl_ext" and len(_parts) >= 3:
        PACKAGE = ".".join(_parts[:3])
    else:
        PACKAGE = _parts[0]
else:
    PACKAGE = "metamorphosis"
ADDON_ID = PACKAGE  # key used by bpy.context.preferences.addons
LABEL = "MetaMorphosis"

# RigLogic Euler joint layout: tx ty tz rx ry rz sx sy sz
ATTRS_PER_JOINT = 9
NUMBER_OF_LODS = 8

# Custom-property prefix used for every baked RigLogic value. Every driver that
# MetaMorphosis creates reads or writes a property that starts with this prefix,
# which is how the toggle/benchmark tools find "their" drivers again.
PROP_PREFIX = "mm_"
DATA_OBJECT_NAME = "MM_RigLogicData"
REPORT_TEXT_NAME = "MetaMorphosis Report"

# Blender stores driver expressions in a 256 byte buffer; stay well below it.
MAX_EXPRESSION_LENGTH = 235

FACE_BOARD_FILE_NAME = "face_board.blend"
GROOM_ACC_FILE_NAME = "Groom Acc.blend"
NEW_SHAPES_OG_FACE_RIG_FILE_NAME = "New_Shapes_OG_Face_Rig.blend"
HDRI_PREVIEWS_DIR = ASSETS_DIR / "ui" / "hdri"
DEFAULT_HDRI_DIR = Path(r"F:\AI\Training_Data\Materials\HDRI's")
DEFAULT_GROOM_ACC_DIR = Path(r"F:\AI\Training_Data\Materials\Grooms")
DEFAULT_FACE_RIG_DIR = Path(r"F:\AI\Training_Data\Face_Rig")

