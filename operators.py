"""Operators and the import pipeline."""

import logging
import time
import traceback

from pathlib import Path

import bpy

from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import bake, bakeplan, dnaio, faceboard, importer, organization, pipeline, verify
from .constants import ADDON_ID, LABEL
from .logicmodel import RigLogicModel

logger = logging.getLogger(__name__)

QUALITY_ITEMS = pipeline.QUALITY_ITEMS


def get_preferences(context) -> "bpy.types.AddonPreferences | None":
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


class MM_OT_import_dna(bpy.types.Operator, ImportHelper):
    """Import a MetaHuman head DNA with the face board and bake RigLogic into drivers"""

    bl_idname = "metamorphosis.import_dna"
    bl_label = "Import MetaHuman DNA (MetaMorphosis)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".dna"
    filter_glob: StringProperty(default="*.dna", options={"HIDDEN"})  # type: ignore[valid-type]

    character_name: StringProperty(  # type: ignore[valid-type]
        name="Name", default="", description="Prefix for the created objects. Empty uses the file name"
    )
    scale: FloatProperty(  # type: ignore[valid-type]
        name="Scale", default=0.01, min=0.0001, max=100.0, precision=4,
        description="DNA files are in centimetres; 0.01 gives metres",
    )
    lod: IntProperty(name="LOD", default=0, min=0, max=7, description="Level of detail to import")  # type: ignore[valid-type]
    import_shape_keys: BoolProperty(  # type: ignore[valid-type]
        name="Corrective Shape Keys", default=True,
        description="Import the DNA blend shapes and drive them with the baked rig",
    )
    join_face_board: BoolProperty(  # type: ignore[valid-type]
        name="Join Face Board", default=True,
        description="Merge the face board into the face rig armature (one editable armature)",
    )
    face_board_file: StringProperty(  # type: ignore[valid-type]
        name="Face Board File", default="", subtype="FILE_PATH",
        description="face_board.blend to append. Empty uses the add-on preferences, then <addon>/assets",
    )
    face_board_location: FloatVectorProperty(  # type: ignore[valid-type]
        name="Face Board Location", default=(0.0, 0.0, 0.0), subtype="TRANSLATION", size=3,
        description="Extra location for the face board armature (0 keeps it where it is saved)",
    )
    quality: EnumProperty(name="Rig Quality", items=QUALITY_ITEMS, default="LITE")  # type: ignore[valid-type]
    force_bake: BoolProperty(  # type: ignore[valid-type]
        name="Bake Even If Verification Fails", default=False,
        description="Create the drivers even when they do not reproduce RigLogic (not recommended)",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "character_name")
        layout.prop(self, "scale")
        layout.prop(self, "lod")
        layout.prop(self, "import_shape_keys")
        layout.prop(self, "quality")
        box = layout.box()
        box.prop(self, "join_face_board")
        box.prop(self, "face_board_file")
        box.prop(self, "face_board_location")
        layout.prop(self, "force_bake")

    # -------------------------------------------------------------------------
    def execute(self, context):
        prefs = get_preferences(context)
        bindings_folder = prefs.bindings_folder if prefs else ""
        board_pref = prefs.face_board_file if prefs else ""
        wm = context.window_manager
        report_lines: list[str] = []

        board_path = faceboard.find_face_board_file(self.face_board_file or board_pref)
        if board_path is None:
            self.report(
                {"ERROR"},
                "face_board.blend not found. Put it in the add-on's 'assets' folder or set it in the add-on preferences.",
            )
            return {"CANCELLED"}

        try:
            dnaio.load_bindings(bindings_folder)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error).splitlines()[0])
            bake.write_report(["MetaMorphosis import failed", "", str(error)])
            return {"CANCELLED"}

        dna_path = Path(self.filepath)
        reader = None
        wm.progress_begin(0, 100)
        started = time.perf_counter()
        try:
            wm.progress_update(2)
            reader = dnaio.open_reader(dna_path, bindings_folder)
            rotation_degrees, _units = dnaio.unit_flags(reader)

            # ---- 1. read RigLogic and verify the numeric model
            wm.progress_update(8)
            model = RigLogicModel.from_reader(reader)
            _dna, riglogic, _folder = dnaio.load_bindings(bindings_folder)
            result = verify.verify_model(model, riglogic, reader, release=dnaio.release_handle)
            report_lines += ["MetaMorphosis import report", "", f"DNA: {dna_path}", f"Verification: {result.status}"]
            report_lines.append(result.message)
            report_lines += ["", *result.details, ""]
            if result.status == "failed" and not self.force_bake:
                report_lines += [
                    "",
                    "Errors by type: " + ", ".join(f"{k}={v:.3e}" for k, v in result.errors_by_type.items()),
                    "Nothing was imported. Send this report to the add-on author.",
                ]
                bake.write_report(report_lines)
                self.report({"ERROR"}, result.message + " (see the 'MetaMorphosis Report' text block)")
                return {"CANCELLED"}
            variant = result.variant or model.variants()[0]
            report_lines.append(f"PSD interpretation: {variant.label()}")
            if result.blendshape_error is not None:
                report_lines.append(f"Blend shape mismatch: {result.blendshape_error:.3e}")
            report_lines += [f"Note: {w}" for w in model.warnings]

            # ---- 2. meshes + rig
            wm.progress_update(15)
            prefix = importer.unique_prefix(self.character_name.strip() or dna_path.stem)
            options = importer.ImportOptions(
                scale=self.scale, lod=self.lod, prefix=prefix, shape_keys=self.import_shape_keys,
                rotation_degrees=rotation_degrees,
            )
            imported = importer.import_head(reader, options)
            report_lines += [f"Imported {len(imported.meshes)} meshes + rig '{imported.rig.name}'"]
            report_lines += [f"Warning: {w}" for w in imported.warnings]

            # ---- 3. face board
            wm.progress_update(55)
            board = faceboard.append_face_board(
                context, board_path, imported.collection, tuple(self.face_board_location)
            )
            organization.board_collections(board)
            organization.organize_board(board, imported.collection)
            board_bone_names = set(board.bone_names)
            collisions = board_bone_names & {b.name for b in imported.rig.data.bones}
            if collisions:
                report_lines.append(f"Warning: {len(collisions)} bone names exist in both rigs, e.g. {sorted(collisions)[:3]}")
            if self.join_face_board:
                faceboard.join_into_rig(context, imported.rig, board)
            report_lines += [f"Warning: {w}" for w in board.warnings]
            board_object = board.armature

            # ---- 4. bake
            wm.progress_update(65)
            orientation = bakeplan.joint_orientation_inverse(reader, model.joint_count, rotation_degrees)
            plan, stats = pipeline.run_bake(
                context,
                model=model,
                variant=variant,
                reader_orientation=orientation,
                rig=imported.rig,
                board_object=board_object,
                board_bone_names=board_bone_names,
                shape_key_map=imported.shape_key_map if self.import_shape_keys else {},
                meshes=imported.meshes,
                collection=imported.collection,
                prefix=prefix,
                quality=self.quality,
                scale=self.scale,
                rotation_degrees=rotation_degrees,
                dna_path=str(dna_path),
                report=report_lines,
                progress=lambda fraction: wm.progress_update(int(75 + 24 * fraction)),
            )
            report_lines += _stats_lines(plan, stats)
        except Exception as error:  # noqa: BLE001
            logger.exception("MetaMorphosis import failed")
            report_lines += ["", f"FAILED: {type(error).__name__}: {error}", "", traceback.format_exc()]
            bake.write_report(report_lines)
            self.report({"ERROR"}, f"Import failed: {error}")
            return {"CANCELLED"}
        finally:
            if reader is not None:
                dnaio.release_handle(reader)
            wm.progress_end()

        report_lines.append(f"Total time: {time.perf_counter() - started:.1f}s")
        bake.write_report(report_lines)
        self.report({"INFO"}, f"Imported {prefix}: {stats['drivers']} baked drivers. See 'MetaMorphosis Report'.")
        return {"FINISHED"}


def _stats_lines(plan, stats) -> list:
    lines = [
        "",
        f"Baked drivers: {stats['drivers']} ({stats['variables']} variables) in {stats['seconds']:.1f}s",
        f"  driven bones: {plan.stats['driven_bones']} (skipped {stats['skipped_bones']} that deform nothing), "
        f"bone channels: {plan.stats['bone_channels']}, shape key drivers: {stats['shape_drivers']}",
        f"  weights kept: {plan.stats['terms']}, dropped within the error budget: {plan.stats['pruned_terms']}",
        f"  drivers that would need Python: {stats['not_simple']}",
    ]
    if stats["variables"] > 150_000:
        lines.append("  Large rig: viewport speed also depends on mesh complexity and scene settings.")
    return lines


class MM_OT_rebuild(bpy.types.Operator):
    """Rebuild the baked drivers in Lite mode (needs the DNA file and the bindings, no re-import)"""

    bl_idname = "metamorphosis.rebuild"
    bl_label = "Rebuild Drivers"
    bl_options = {"REGISTER", "UNDO"}

    quality: EnumProperty(name="Rig Quality", items=QUALITY_ITEMS, default="LITE")  # type: ignore[valid-type]

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rig = bake.find_baked_rig(context)
        if rig is None:
            self.report({"ERROR"}, "No MetaMorphosis rig found")
            return {"CANCELLED"}
        dna_path = Path(str(rig.get(bake.RIG_KEY_DNA, "")))
        if not dna_path.is_file():
            self.report({"ERROR"}, f"The DNA file is missing: {dna_path}")
            return {"CANCELLED"}
        prefs = get_preferences(context)
        bindings_folder = prefs.bindings_folder if prefs else ""
        wm = context.window_manager
        report_lines = ["MetaMorphosis rebuild report", "", f"DNA: {dna_path}"]
        reader = None
        wm.progress_begin(0, 100)
        try:
            dnaio.load_bindings(bindings_folder)
            reader = dnaio.open_reader(dna_path, bindings_folder)
            rotation_degrees, _units = dnaio.unit_flags(reader)
            model = RigLogicModel.from_reader(reader)
            _dna, riglogic, _folder = dnaio.load_bindings(bindings_folder)
            wm.progress_update(10)
            result = verify.verify_model(model, riglogic, reader, release=dnaio.release_handle)
            report_lines += [f"Verification: {result.status}", result.message, "", *result.details, ""]
            if result.status == "failed":
                bake.write_report(report_lines)
                self.report({"ERROR"}, result.message)
                return {"CANCELLED"}
            variant = result.variant or model.variants()[0]

            children = bake.head_meshes(rig)
            channel_of = {str(reader.getBlendShapeChannelName(i)): i for i in range(reader.getBlendShapeChannelCount())}
            shape_key_map: dict = {}
            for mesh in children:
                key = mesh.data.shape_keys
                if key is None:
                    continue
                for block in key.key_blocks:
                    channel = channel_of.get(block.name)
                    if channel is not None and block.name != "Basis":
                        shape_key_map.setdefault(channel, []).append((key, block.name))

            board_object = bpy.data.objects.get(str(rig.get(bake.RIG_KEY_BOARD_OBJECT, ""))) or rig
            board_bones = set(filter(None, str(rig.get(bake.RIG_KEY_BOARD, "")).split("\n")))
            collection = bpy.data.collections.get(str(rig.get("mm_character_collection", "")))
            if collection is None:
                collection = rig.users_collection[0] if rig.users_collection else context.scene.collection
            prefix = str(rig.get(bake.RIG_KEY_PREFIX, rig.name))
            scale = float(rig.get(bake.RIG_KEY_SCALE, 0.01))

            wm.progress_update(20)
            bake.remove_baked(rig)
            orientation = bakeplan.joint_orientation_inverse(reader, model.joint_count, rotation_degrees)
            plan, stats = pipeline.run_bake(
                context,
                model=model,
                variant=variant,
                reader_orientation=orientation,
                rig=rig,
                board_object=board_object,
                board_bone_names=board_bones,
                shape_key_map=shape_key_map,
                meshes=children,
                collection=collection,
                prefix=prefix,
                quality=self.quality,
                scale=scale,
                rotation_degrees=rotation_degrees,
                dna_path=str(dna_path),
                report=report_lines,
                progress=lambda fraction: wm.progress_update(int(30 + 69 * fraction)),
            )
            report_lines += _stats_lines(plan, stats)
        except Exception as error:  # noqa: BLE001
            logger.exception("MetaMorphosis rebuild failed")
            report_lines += ["", f"FAILED: {type(error).__name__}: {error}", "", traceback.format_exc()]
            bake.write_report(report_lines)
            self.report({"ERROR"}, f"Rebuild failed: {error}")
            return {"CANCELLED"}
        finally:
            if reader is not None:
                dnaio.release_handle(reader)
            wm.progress_end()
        bake.write_report(report_lines)
        self.report({"INFO"}, f"Rebuilt: {stats['drivers']} drivers ({self.quality}).")
        return {"FINISHED"}


class MM_OT_toggle_rig(bpy.types.Operator):
    """Mute or unmute all baked RigLogic drivers (muting resets the face to its rest pose)"""

    bl_idname = "metamorphosis.toggle_rig"
    bl_label = "Toggle Baked Rig"
    bl_options = {"REGISTER", "UNDO"}

    enable: BoolProperty(default=True)  # type: ignore[valid-type]

    def execute(self, context):
        rig = bake.find_baked_rig(context)
        if rig is None:
            self.report({"ERROR"}, "No MetaMorphosis rig found")
            return {"CANCELLED"}
        count = bake.set_baked_enabled(rig, self.enable)
        self.report({"INFO"}, f"{'Enabled' if self.enable else 'Disabled'} {count} drivers")
        return {"FINISHED"}


class MM_OT_benchmark(bpy.types.Operator):
    """Wiggle a few face board controls and measure the update time"""

    bl_idname = "metamorphosis.benchmark"
    bl_label = "Measure Rig Speed"

    def execute(self, context):
        rig = bake.find_baked_rig(context)
        if rig is None:
            self.report({"ERROR"}, "No MetaMorphosis rig found")
            return {"CANCELLED"}
        result = bake.benchmark(context, rig)
        self.report({"INFO"}, f"{result['ms']:.1f} ms per update (~{result['fps']:.0f} fps), {result['controls']} controls moved")
        return {"FINISHED"}


class MM_OT_validate(bpy.types.Operator):
    """Check that every baked driver is valid and evaluates without Python"""

    bl_idname = "metamorphosis.validate"
    bl_label = "Validate Baked Rig"

    def execute(self, context):
        rig = bake.find_baked_rig(context)
        if rig is None:
            self.report({"ERROR"}, "No MetaMorphosis rig found")
            return {"CANCELLED"}
        info = bake.validate_rig(rig)
        level = {"INFO"} if not info["invalid"] and not info["needs_python"] else {"WARNING"}
        self.report(
            level,
            f"{info['drivers']} drivers, {info['invalid']} invalid, {info['needs_python']} need Python, {info['muted']} muted",
        )
        return {"FINISHED"}


class MM_OT_test_bindings(bpy.types.Operator):
    """Try to load the OpenRigLogic bindings and write the result to the 'MetaMorphosis Report' text block"""

    bl_idname = "metamorphosis.test_bindings"
    bl_label = "Test Bindings"

    def execute(self, context):
        prefs = get_preferences(context)
        try:
            dna, riglogic, folder = dnaio.load_bindings(prefs.bindings_folder if prefs else "", force=True)
        except RuntimeError as error:
            bake.write_report(["MetaMorphosis bindings test: FAILED", "", str(error)])
            self.report({"ERROR"}, "Bindings not found - details are in the 'MetaMorphosis Report' text block")
            return {"CANCELLED"}
        lines = [
            "MetaMorphosis bindings test: OK",
            f"dna.py loaded from: {folder}",
            f"RigLogic runtime: {'available' if riglogic is not None else 'NOT available (verification will be skipped)'}",
        ]
        bake.write_report(lines)
        self.report({"INFO"}, lines[1])
        return {"FINISHED"}


def menu_import(self, _context):
    self.layout.operator(MM_OT_import_dna.bl_idname, text="MetaHuman Head DNA (MetaMorphosis)")


CLASSES = (MM_OT_import_dna, MM_OT_rebuild, MM_OT_toggle_rig, MM_OT_benchmark, MM_OT_validate, MM_OT_test_bindings)
__all__ = ["CLASSES", "LABEL", "menu_import", "get_preferences"]
