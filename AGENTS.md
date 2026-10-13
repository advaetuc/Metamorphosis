# Project memory

- This folder is the primary MetaMorphosis development checkout. Make future requested changes directly to its source files.
- Do not generate ZIP archives unless the user explicitly requests one.
- Git remote: https://github.com/advaetuc/Metamorphosis.git. Do not infer a request to commit or push from a request to edit files.
- Verified baseline on 2026-10-05: version 1.0.5, Blender 5.0+, 17 Python modules matching the previously tested release source; clean checkout before adding this memory.
- Preserve Lite-only import/rebuild, the middle-eye control fix, organized object/bone collections, and native drivers that work without the add-on.
- Version 1.0.5 accounts for raw/PSD/ML/RBF control indices in newer DNA. ML and head/neck RBF correctives remain unbaked; the 3–6 ms performance target has not been achieved.
- Existing test inputs: F:\BlendLAB\Metahumans\Ada.dna, MH_BASE.dna, and Taro.dna. Previous test scripts are in C:\Users\Advaet\Documents\Codex\2026-10-05\t\work (historical, not the active source checkout).
- Keep changes limited to the requested scope and run relevant checks. Preserve user edits.

- Current development version: 1.0.9. Body-rig combining and blendshape import are removed. New imports have ownership tags for a scene-scoped Remove All action; preserve unrelated/shared data and legacy shape keys. Sidebar diagnostics are collapsible.
- Lite retains only the PSD joint correctives required by Lips Together and Jaw Open Extreme; other PSD remains omitted. Preserve raw-expression pruning and native standalone drivers. Existing scenes need Rebuild Drivers to receive these fixes. Jaw Open Extreme extends the regular jaw opening and has no effect with a fully closed jaw, matching DNA behavior.
- tests/blender_lips_together.py compares Lips Together and Jaw Open Extreme deltas against native RigLogic on Ada, MH_BASE and Taro, including mixed mouth poses and unchanged 1.0.7 behavior when Extreme is zero.
- Regression tests: tests/blender_features.py and tests/blender_import_cleanup.py run inside Blender. Use work/ for temporary test scenes/logs; do not create release ZIPs.
- Phase 1 capture: mocap_core.py handles Epic Live Link Face ARKit UDP and timestamped recording; mocap_mapping.py maps 52 coefficients to existing board bones; mocap.py owns main-thread preview, countdown, actions and async video jobs. Never call bpy from the receiver thread. Preserve existing actions as separate takes. Head/body motion and MetaHuman Animator streaming are not supported.
- Video uses isolated MediaPipe 0.10.35/OpenCV 4.13.0.92 via video_worker.py. Setup is explicit; do not install dependencies into Blender's Python. Test tools are in work/video_tools; user default tools are in Blender's user data directory. Tested F:\AI\Training_Data\Facial video test for Gpt.mp4 (1,343 tracked frames). Phase 2 materials/textures awaits the promised files.
- Driver optimization retains coefficients, pruning and corrective selection. Shorter expressions and scaled weighted helper sums reduce drivers; native Blender small-value write tolerance required scaling helpers by 10,000 and restoring units at bone outputs. Do not remove this scaling or mistake the resulting precision improvement for dropped poses.
- Ada benchmark: 17,119 -> 12,961 drivers; median 23.05 -> 21.94 ms in Blender 5.2. 7–15 ms not reached. Native formula error improved (~1.94e-4 -> 1.00e-4, final RNA tolerance remains). tests/blender_performance.py compares with 1.0.8 compiler snapshots in work/ and checks native accuracy.
- Capture tests: tests/blender_mocap.py (local UDP requires network-enabled execution), tests/blender_video_job.py (async processing/cancel). Real phone capture is not yet device-tested. Keep tests explicit about this limit.
