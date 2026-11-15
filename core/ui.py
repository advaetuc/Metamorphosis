"""Sidebar panel (3D Viewport > N panel > MetaMorphosis)."""

import bpy
from pathlib import Path
import bpy.utils.previews
from bpy.props import FloatVectorProperty

from ..riglogic import bake
from ..capture import mocap
from .constants import LABEL
from . import materials

_previews = None


def icon(name):
    return _previews[name].icon_id if _previews and name in _previews else 0


class MM_PT_panel(bpy.types.Panel):
    bl_label = "MetaMorphosis DNA Addon"
    bl_idname = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL

    def draw_header(self, context):
        self.layout.label(text="", icon_value=icon('dna'))

    def draw_header_preset(self, context):
        self.layout.label(text="v2.80 PRO")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        # ---------------------------------------------------------------------
        # Studio Brand Header
        # ---------------------------------------------------------------------
        brand_card = layout.box()
        brand_row = brand_card.row(align=True)
        if icon('brand'):
            brand_row.template_icon(icon_value=icon('brand'), scale=4.2)
        col = brand_row.column(align=True)
        col.alignment = 'LEFT'
        title_row = col.row(align=True)
        title_row.label(text="METAMORPHOSIS")
        sub_row = col.row(align=True)
        sub_row.scale_y = 0.85
        sub_row.label(text="MetaHuman DNA & Rig Pipeline")
        badge_row = col.row(align=True)
        badge_row.scale_y = 0.85
        badge_row.label(text="v2.80 PRO · Blender 5.2", icon='CHECKMARK')

        # ---------------------------------------------------------------------
        # Assemble Character Card (Hero Section)
        # ---------------------------------------------------------------------
        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Assemble Character", icon='COMMUNITY')
        tag = hdr.row(align=True)
        tag.alignment = 'RIGHT'
        tag.label(text="ONE-CLICK")

        # Control Shapes Segmented Switch
        col = box.column(align=True)
        col.label(text="Rig Control Shapes:", icon='SHAPEKEY_DATA')
        seg_row = col.row(align=True)
        seg_row.scale_y = 1.2
        seg_row.prop(context.scene, "mm_assemble_custom_shapes", expand=True)

        # Join Face Board Toggle Button
        box.separator(factor=0.3)
        tgl_row = box.row(align=True)
        tgl_row.scale_y = 1.15
        is_joined = getattr(context.scene, "mm_assemble_join_face_board", False)
        tgl_row.prop(
            context.scene,
            "mm_assemble_join_face_board",
            text="Join Face Board Armature",
            toggle=True,
            icon='CHECKBOX_HLT' if is_joined else 'CHECKBOX_DEHLT',
        )

        # Hero Action Button
        box.separator(factor=0.4)
        hero = box.row(align=True)
        hero.scale_y = 1.6
        op = hero.operator("metamorphosis.import_character", text="Assemble MetaHuman Character", icon="IMPORT")
        op.body_custom_shapes = getattr(context.scene, "mm_assemble_custom_shapes", "UNREAL")
        op.join_face_board = getattr(context.scene, "mm_assemble_join_face_board", False)

        hint = box.row(align=True)
        hint.scale_y = 0.85
        hint.label(text="Body DNA · 565-Bone Rig · Head RigLogic · Grooms · Shaders", icon='INFO')

        # ---------------------------------------------------------------------
        # Character Pipeline Setup Card
        # ---------------------------------------------------------------------
        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Character Pipeline Setup", icon='PREFERENCES')
        box.prop(context.scene, 'mm_texture_folder', text="Textures", icon='FILE_IMAGE')

        head_rig, body_rig = materials.find_character_rigs(context)
        if head_rig or body_rig:
            mat_row = box.row(align=True)
            mat_row.scale_y = 1.25
            mat_row.operator('metamorphosis.setup_materials', text="Apply Shaders & Materials", icon='MATERIAL')

        row = box.row(align=True)
        row.scale_y = 1.3
        row.operator("metamorphosis.import_dna", text="Import Head DNA", icon="FILE_FOLDER")
        row.operator("metamorphosis.remove_all", text="Remove All", icon="TRASH")

        # ---------------------------------------------------------------------
        # Active Character Dashboard (Live HUD)
        # ---------------------------------------------------------------------
        rig = head_rig or body_rig
        if rig is None:
            empty_card = layout.box()
            ehdr = empty_card.row(align=True)
            ehdr.label(text="Character Status", icon="INFO")
            tag = ehdr.row(align=True)
            tag.alignment = 'RIGHT'
            tag.label(text="STANDBY")

            ecol = empty_card.column(align=True)
            ecol.scale_y = 0.9
            ecol.label(text="Ready for Character Import.", icon="FORWARD")
            ecol.label(text="Select Manifest or DNA above to assemble.", icon="BLANK1")
            return

        dash = layout.box()
        dhdr = dash.row(align=True)
        dhdr.label(text="Active Character Dashboard", icon="ARMATURE_DATA")
        tag = dhdr.row(align=True)
        tag.alignment = 'RIGHT'
        tag.label(text="ACTIVE", icon="RADIOBUT_ON")

        info = dash.column(align=True)
        info.label(text=f"  {rig.name}", icon="OUTLINER_OB_ARMATURE")
        if bake.RIG_KEY_DATA in rig:
            info.label(text=f"  {rig.get('mm_quality', 'LITE').title()} Rig · Native RigLogic Drivers", icon="DRIVER")
        elif rig.get('mm_body_rig'):
            info.label(text="  Body Rig · Native RBF Correctives", icon="DRIVER")
        if rig.get("mm_stats"):
            for part in str(rig["mm_stats"]).split(", "):
                info.label(text=f"  {part}", icon="DOT")

        if bake.RIG_KEY_DATA in rig:
            dash.separator(factor=0.5)
            ctrl_hdr = dash.row(align=True)
            ctrl_hdr.label(text="Facial RigLogic Drivers", icon="POSE_HLT")

            deck = dash.row(align=True)
            deck.scale_y = 1.3
            op1 = deck.operator("metamorphosis.toggle_rig", text="Enable Drivers", icon="PLAY")
            op1.enable = True
            op2 = deck.operator("metamorphosis.toggle_rig", text="Pause Drivers", icon="PAUSE")
            op2.enable = False

            rebuild_row = dash.row(align=True)
            rebuild_row.scale_y = 1.2
            rebuild_row.operator("metamorphosis.rebuild", text="Rebuild Native Drivers", icon="FILE_REFRESH")


class MM_PT_scene_settings(bpy.types.Panel):
    bl_label = "Scene Settings"
    bl_idname = "MM_PT_scene_settings"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="PREFERENCES")

    def draw(self, context):
        pass


class MM_PT_face_board_color(bpy.types.Panel):
    bl_label = "Face Board Color Settings"
    bl_idname = "MM_PT_face_board_color"
    bl_parent_id = "MM_PT_scene_settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="COLORSET_01_VEC")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Face Board Control Colour", icon="COLORSET_01_VEC")
        box.prop(context.scene, "mm_face_board_color", text="Control Colour")
        btn = box.row(align=True)
        btn.scale_y = 1.25
        btn.operator("metamorphosis.apply_face_board_color", text="Apply Colour to Controls", icon="CHECKMARK")


class MM_PT_diagnostics(bpy.types.Panel):
    bl_label = "Diagnostics"
    bl_idname = "MM_PT_diagnostics"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = LABEL
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="TOOL_SETTINGS")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Driver Verification & Benchmarking", icon="TOOL_SETTINGS")

        col = box.column(align=True)
        col.enabled = bake.find_baked_rig(context) is not None
        row = col.row(align=True)
        row.scale_y = 1.25
        row.operator("metamorphosis.validate", text="Check Drivers", icon="CHECKMARK")
        row.operator("metamorphosis.benchmark", text="Measure Speed", icon="TIME")

        if bpy.data.texts.get("MetaMorphosis Report"):
            box.separator(factor=0.4)
            rep = box.row(align=True)
            rep.label(text="Report available: Text Editor → MetaMorphosis Report", icon="TEXT")


class MM_PT_live_link(bpy.types.Panel):
    bl_label = "Live Link"
    bl_idname = "MM_PT_live_link"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = LABEL
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='OUTLINER_DATA_CAMERA')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.mm_capture
        live = mocap._live
        recording = bool(live and live['recording'])

        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Live Stream Setup", icon='RADIOBUT_ON' if live else 'RADIOBUT_OFF')
        tag = hdr.row(align=True)
        tag.alignment = 'RIGHT'
        tag.label(text="LIVE" if live else "OFFLINE")

        col = box.column(align=True)
        col.enabled = not live and not mocap._job
        col.prop(settings, 'target')
        col.prop(settings, 'mode')
        if settings.mode == 'MHA':
            col.prop(settings, 'phone_ip')
            col.prop(settings, 'phone_port')
            col.prop(settings, 'mha_dna')
        col.prop(settings, 'host')
        col.prop(settings, 'port')
        col.prop(settings, 'subject')

        info = box.box()
        info.label(text="Live Link Face · " + ('MetaHuman Animator' if settings.mode == 'MHA' else 'ARKit'), icon='INFO')
        info.label(text="Enable Realtime Animation on iPhone." if settings.mode == 'MHA'
                   else "Send the phone stream to this computer.")

        btn = box.row(align=True)
        btn.scale_y = 1.35
        btn.operator('metamorphosis.live_stop' if live else 'metamorphosis.live_start',
                     text='Stop Live Link' if live else 'Start Live Link Stream',
                     icon='PAUSE' if live else 'PLAY')

        stat_row = box.row(align=True)
        stat_row.label(text=settings.status, icon='DOT')
        if settings.last_take:
            stat_row.label(text=f"Last take: {settings.last_take}", icon='ACTION')

        # Recording Section
        rec_box = layout.box()
        rec_hdr = rec_box.row(align=True)
        rec_hdr.label(text="Performance Recording Deck", icon='REC')

        col = rec_box.column(align=True)
        col.enabled = not recording
        if settings.mode == 'ARKIT':
            col.prop(settings, 'mirror')
            col.prop(settings, 'gain')
            col.prop(settings, 'lips_gain')
            col.prop(settings, 'brow_gain')
        col.prop(settings, 'smoothing')
        if settings.mode == 'ARKIT':
            col.prop(settings, 'extreme')
        col.prop(settings, 'take_name')
        col.prop(settings, 'end_mode')

        rec_btn = rec_box.row(align=True)
        rec_btn.scale_y = 1.35
        rec_btn.enabled = bool(live)
        rec_btn.operator('metamorphosis.record_stop' if recording else 'metamorphosis.record_start',
                         text='Stop Recording Take' if recording else 'Record Take',
                         icon='PAUSE' if recording else 'REC')


class MM_PT_video(bpy.types.Panel):
    bl_label = "Video to Mocap"
    bl_idname = "MM_PT_video"
    bl_parent_id = "MM_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = LABEL
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='SEQUENCE')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.mm_capture

        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Video Facial Tracking", icon='SEQUENCE')

        col = box.column(align=True)
        col.enabled = not mocap._job and not mocap._live
        col.prop(settings, 'target')
        col.prop(settings, 'video')
        col.prop(settings, 'take_name')
        col.prop(settings, 'mirror')
        col.prop(settings, 'gain')
        col.prop(settings, 'lips_gain')
        col.prop(settings, 'brow_gain')
        col.prop(settings, 'smoothing')
        col.prop(settings, 'extreme')

        p_row = box.row(align=True)
        p_row.scale_y = 1.35
        p_row.operator('metamorphosis.video_process', text='Process Video Mocap', icon='ACTION')
        if mocap._job:
            c_row = box.row(align=True)
            c_row.scale_y = 1.2
            c_row.operator('metamorphosis.video_cancel', text='Cancel Video Job', icon='CANCEL')

        box.label(text=settings.video_status, icon='INFO')

        t_box = layout.box()
        thdr = t_box.row(align=True)
        thdr.label(text="Local Video AI Tools", icon='PREFERENCES')
        if mocap.video_ready(mocap.video_folder(settings)):
            t_box.label(text='MediaPipe tools ready on this computer.', icon='CHECKMARK')
        else:
            s_btn = t_box.row(align=True)
            s_btn.scale_y = 1.25
            s_btn.operator('metamorphosis.video_setup', text='Install Video AI Tools', icon='IMPORT')

        t_box.prop(settings, 'video_advanced')
        if settings.video_advanced:
            t_box.prop(settings, 'video_python')
            t_box.prop(settings, 'video_folder')
            t_box.operator('metamorphosis.video_setup', text='Repair Video Tools', icon='FILE_REFRESH').repair = True


class MM_OT_apply_face_board_color(bpy.types.Operator):
    bl_idname = "metamorphosis.apply_face_board_color"
    bl_label = "Apply Face Board Colour"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..riglogic import bake
        rig = bake.find_baked_rig(context)
        if rig is None:
            self.report({'ERROR'}, 'Select an imported MetaHuman rig first')
            return {'CANCELLED'}
        board = bpy.data.objects.get(str(rig.get(bake.RIG_KEY_BOARD_OBJECT, '')))
        if board is None or board.type != 'ARMATURE':
            self.report({'ERROR'}, 'The face board armature is missing')
            return {'CANCELLED'}
        rgb = tuple(context.scene.mm_face_board_color)
        normal = rgb
        select = tuple(c + (1 - c) * .4 for c in rgb)
        active = tuple(c + (1 - c) * .7 for c in rgb)
        changed = 0
        for bone in board.pose.bones:
            if not bone.name.startswith('CTRL_') or bone.color is None:
                continue
            bone.color.palette = 'CUSTOM'
            bone.color.custom.normal = normal
            bone.color.custom.select = select
            bone.color.custom.active = active
            changed += 1
        self.report({'INFO'}, f'Updated {changed} face-board controls')
        return {'FINISHED'}


CLASSES = (
    MM_PT_panel,
    MM_PT_scene_settings,
    MM_OT_apply_face_board_color,
    MM_PT_live_link,
    MM_PT_video,
    MM_PT_diagnostics,
)


def register():
    global _previews
    _previews = bpy.utils.previews.new()
    for name in ('brand', 'dna', 'capture', 'body'):
        _previews.load(name, str(Path(__file__).resolve().parents[1] / 'assets' / 'ui' / (name + '.png')), 'IMAGE')
    bpy.types.Scene.mm_face_board_color = FloatVectorProperty(
        name='Face Board Colour', subtype='COLOR', size=3,
        min=0.0, max=1.0, default=(0.956, 0.788, 0.047),
        description='Color used for all face-board control bones',
    )


def unregister():
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    if hasattr(bpy.types.Scene, 'mm_face_board_color'):
        del bpy.types.Scene.mm_face_board_color
