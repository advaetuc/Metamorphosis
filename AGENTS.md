# Project memory

- This folder is the primary MetaMorphosis development checkout. Make future requested changes directly to its source files.
- Do not generate ZIP archives unless the user explicitly requests one.
- Git remote: https://github.com/advaetuc/Metamorphosis.git. Do not infer a request to commit or push from a request to edit files.
- Verified baseline on 2026-10-05: version 1.0.5, Blender 5.0+, 17 Python modules matching the previously tested release source; clean checkout before adding this memory.
- Preserve Lite-only import/rebuild, the middle-eye control fix, organized object/bone collections, and native drivers that work without the add-on.
- Version 1.0.5 accounts for raw/PSD/ML/RBF control indices in newer DNA. ML and head/neck RBF correctives remain unbaked; the 3–6 ms performance target has not been achieved.
- Existing test inputs: F:\BlendLAB\Metahumans\Ada.dna, MH_BASE.dna, and Taro.dna. Previous test scripts are in C:\Users\Advaet\Documents\Codex\2026-10-05\t\work (historical, not the active source checkout).
- Keep changes limited to the requested scope and run relevant checks. Preserve user edits.

- Current development version: 1.0.6. Per the latest feature list, body-rig combining and blendshape import are removed. New imports have ownership tags for a scene-scoped Remove All action; preserve unrelated/shared data and legacy shape keys. Sidebar diagnostics are collapsible.
- Regression tests: tests/blender_features.py and tests/blender_import_cleanup.py run inside Blender. Use work/ for temporary test scenes/logs; do not create release ZIPs.
