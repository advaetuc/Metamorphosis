"""Shared constants for MetaMorphosis."""

# Name of the add-on package (e.g. ``bl_ext.user_default.metamorphosis``).
PACKAGE = __package__ or "metamorphosis"
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
