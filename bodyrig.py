"""Join an aligned body armature into the DNA rig while preserving facial drivers."""

import bpy
from bpy.props import PointerProperty, StringProperty

from . import bake, organization


def _armature_only(_self, obj):
    return obj.type == "ARMATURE"


def _property_value(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_list"):
        return value.to_list()
    return value


class MM_BodySettings(bpy.types.PropertyGroup):
    body: PointerProperty(name="Body Rig", type=bpy.types.Object, poll=_armature_only)
    attach_bone: StringProperty(
        name="Attach to Bone", default="head",
        description="Body bone that the original head skeleton will follow; align the rigs in their rest poses first",
    )


def combine(context, rig, body, attach_bone):
    """Keep the DNA armature active so its metadata, action and drivers survive.

    Body bones with duplicate names receive a BODY_ prefix before joining; skin
    groups and bone-parented objects are explicitly remapped. Never delete a bone.
    """
    if body is None or body.type != "ARMATURE" or body == rig:
        raise ValueError("Choose a different body armature")
    if body.name not in context.view_layer.objects or not body.visible_get():
        raise ValueError("The body rig must be visible in the current view layer")
    if attach_bone not in body.data.bones:
        raise ValueError("Choose an existing attachment bone on the body rig")
    if bake.RIG_KEY_DATA in body:
        raise ValueError("The body selection is another MetaMorphosis facial rig")
    for obj in (rig, body):
        if obj.library or obj.data.library or obj.override_library:
            raise ValueError("Make both armatures local before combining")
        if obj.data.users > 1:
            raise ValueError("Make both armature data blocks single-user before combining")
    animation = body.animation_data
    if animation and (animation.action or animation.nla_tracks):
        raise ValueError("Combine the body before animating it; joining would lose its active action or NLA tracks")
    if body.constraints or body.parent:
        raise ValueError("The body rig must have no object constraints or parent; bone constraints are supported")
    if animation and any(not f.data_path.startswith(('pose.bones[', '["')) for f in animation.drivers):
        raise ValueError("Body object-transform drivers cannot be transferred by an armature join")
    if any(key in rig for key in body.keys()):
        raise ValueError("The armatures have conflicting object custom properties; rename those on the body first")
    if body.data.animation_data:
        raise ValueError("Animated body armature-data properties must be removed before joining")

    meshes = [o for o in bpy.data.objects if o.type == "MESH" and (
        o.parent == body or any(m.type == "ARMATURE" and m.object == body for m in o.modifiers))]
    collisions = set(body.data.bones.keys()) & set(rig.data.bones.keys())
    for mesh in meshes:
        if collisions and (mesh.data.users > 1 or any(m.type == "ARMATURE" and m.object == rig for m in mesh.modifiers)):
            raise ValueError("A body mesh is shared or already uses both rigs; make its skinning unambiguous first")
    used = set(body.data.bones.keys()) | set(rig.data.bones.keys())
    used.update(g.name for mesh in meshes for g in mesh.vertex_groups)
    renames = {}
    for name in sorted(collisions):
        base, number = "BODY_" + name, 0
        new = base
        while new in used:
            number += 1
            new = f"{base}_{number:03d}"
        used.add(new)
        renames[name] = new
    board_names = set(str(rig.get(bake.RIG_KEY_BOARD, "")).split("\n"))
    roots = [b.name for b in rig.data.bones if b.parent is None and b.name not in board_names]
    if not roots:
        raise ValueError("The head rig has no separate deformation-skeleton root to attach")
    children = [(o, o.matrix_world.copy(), o.parent_type, o.parent_bone) for o in body.children]
    modifiers = [m for o in meshes for m in o.modifiers if m.type == "ARMATURE" and m.object == body]
    properties = {key: _property_value(body[key]) for key in body.keys()}
    property_ui = {}
    for key in properties:
        try:
            property_ui[key] = body.id_properties_ui(key).as_dict()
        except TypeError:  # Nested groups have no UI metadata.
            pass
    if not rig.get("mm_mesh_scope", False):
        for mesh in bake.head_meshes(rig):
            mesh["mm_head_mesh"] = True
        rig["mm_mesh_scope"] = True
    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for old, new in renames.items():
        body.data.bones[old].name = new  # Blender also updates bone constraints and driver paths.
        for mesh in meshes:
            group = mesh.vertex_groups.get(old)
            if group:
                group.name = new
    target_name = renames.get(attach_bone, attach_bone)
    body_name = body.name
    body_bones = set(body.data.bones.keys())
    for obj in list(context.selected_objects):
        obj.select_set(False)
    rig.hide_set(False)
    rig.select_set(True)
    body.select_set(True)
    context.view_layer.objects.active = rig
    try:
        with context.temp_override(active_object=rig, object=rig, selected_objects=[rig, body],
                                   selected_editable_objects=[rig, body]):
            result = bpy.ops.object.join()
    except RuntimeError:
        result = {"CANCELLED"}
    if result != {"FINISHED"} or bpy.data.objects.get(body_name) is not None:
        # Recover names if Blender rejected the join before modifying the armatures.
        for old, new in renames.items():
            body.data.bones[new].name = old
            for mesh in meshes:
                if new in mesh.vertex_groups:
                    mesh.vertex_groups[new].name = old
        raise RuntimeError("Blender could not join the body armature")
    for key, value in properties.items():
        rig[key] = value
        if key in property_ui:
            rig.id_properties_ui(key).update(**property_ui[key])
    for modifier in modifiers:
        modifier.object = rig
    for obj, world, parent_type, parent_bone in children:
        obj.parent = rig
        obj.parent_type = parent_type
        if parent_type == "BONE":
            obj.parent_bone = renames.get(parent_bone, parent_bone)
        obj.matrix_world = world
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        target = rig.data.edit_bones[target_name]
        for name in roots:
            bone = rig.data.edit_bones[name]
            bone.use_connect = False
            bone.parent = target
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    body_collection = rig.data.collections.get("DEF_BODY") or rig.data.collections.new("DEF_BODY")
    for name in body_bones:
        body_collection.assign(rig.data.bones[name])
    organization.armature_display(rig)
    rig["mm_combined_body"] = body_name
    context.view_layer.update()
    return len(body_bones), len(renames)


class MM_OT_combine_body(bpy.types.Operator):
    """Join an aligned, unanimated body rig into the head rig and attach the head skeleton"""
    bl_idname = "metamorphosis.combine_body"
    bl_label = "Combine Body with Head Rig"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig = bake.find_baked_rig(context)
        if rig is None:
            self.report({"ERROR"}, "Select a MetaMorphosis head rig first")
            return {"CANCELLED"}
        settings = context.scene.mm_body_settings
        try:
            count, renamed = combine(context, rig, settings.body, settings.attach_bone)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Combined {count} body bones; renamed {renamed} duplicate body bones")
        return {"FINISHED"}


CLASSES = (MM_BodySettings, MM_OT_combine_body)
