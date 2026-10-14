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

The source assets were supplied for this project. Their original creators retain
their rights; this file records provenance and does not grant additional asset rights.
