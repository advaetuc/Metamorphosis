# Material asset provenance

- `wrinkle_materials.blend` contains the dependency graph rooted at
  `head_shader_logic.004` from the user-supplied Poly Hammer `materials.blend`.
  The supplied `combined_masks.tga` is packed into the graph. It uses the supplied
  `mask_names.json` mask ordering. Datablock/node names are normalized and UV nodes
  use `UVMap`; no Python callbacks, scripts or unrelated scene objects are included.
  The graph is saved with Blender 5.0 for compatibility with the add-on minimum.
- `T_SkinMicroNormal.PNG` and `T_SkinMicro3_N.PNG` are the user-supplied Detail Maps.
  They are packed into imported materials so disabling/removing the add-on does not
  remove the scene's detail textures.
- Skin settings and detail layering were informed by the user-supplied
  `MY_CUSTOM_METAHUMAN_SHADER.blend`; the new material construction is in materials.py.
- `Teeth_Color.png`, `Teeth_Normal.png` and `EyeLashes_Alpha.PNG` are the supplied
  universal Teeth Textures and Eyelashes Textures. Materials pack them into the scene.
- `eye_edge_materials.blend` contains only `ADA_eyeEdge.l` / `ADA_eyeEdge.r` and
  their packed micro-normal dependency from the supplied `Eye_Edge_material.blend`,
  renamed `MM_EYE_EDGE_L` / `MM_EYE_EDGE_R`. Saved with Blender 5.0; no source scene
  objects or GUI materials are bundled. Side-specific ramps/mappings are preserved.
- Update 1.2's layout and skin settings reference `Untitled_HEAD.json` and
  `My_Shader.json` and their supplied HTML/image previews. The wrinkle blending
  equations are preserved; the reference's unrelated wrinkle mixing is not substituted.

The source assets were supplied for this project. Their original creators retain
their rights; this file records provenance and does not grant additional asset rights.
