# Install MetaMorphosis from this folder

This project root is the Blender extension package. Keep `blender_manifest.toml`
and `__init__.py` at its top level, beside the Python modules, `assets/` and
`bindings/`. No separate release directory or generated copy is required.

1. Finish downloading or copying the whole **Metamorphosis** folder.
2. Compress that folder to ZIP, or select its contents and compress them.
   Blender accepts the manifest at archive root or inside one enclosing folder.
3. In Blender, open **Edit → Preferences → Get Extensions → Install from Disk**,
   choose the ZIP and enable **MetaMorphosis**.

Supported package: **Windows x64, Blender 5.0+**. The included native bindings
cover Python 3.11 and 3.13. Other operating systems need compatible native binaries.
The add-on does not need the developer's local DNA, texture or reference folders.
Character DNA and optional exported textures are selected after installation.

## Folder layout

| Location | Purpose |
| --- | --- |
| `__init__.py`, `blender_manifest.toml` | Blender entry point and extension metadata |
| Root Python modules | Runtime import, rigging, materials, capture and sculpt code |
| `assets/` | Bundled face board, shader assets, textures and interface icons |
| `bindings/` | Native DNA / RigLogic libraries for supported Blender Python versions |
| `docs/`, `README.md`, licenses | Documentation and attribution |
| `tests/` | Developer regression scripts; not needed at runtime |

Generated test scenes, renders, videos and environments are stored **outside this
folder**, by default at `%USERPROFILE%/Documents/Codex/MetaMorphosis-development/work`.
Set `METAMORPHOSIS_WORK_DIR` to use another development artifact directory.
The existing 3.5 GB of artifacts were preserved there during the reorganization.

A normal manual ZIP may include developer text files; those do not stop Blender
from installing the extension. Omit hidden `.git` history, caches and test sources
when sharing publicly. Blender's optional extension builder uses the manifest's
exclusions automatically. No ZIP is created by opening or updating this project.

Official packaging reference:
[Blender extension creation](https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html).
