"""Locate the OpenRigLogic Python bindings and read DNA files.

The compiled ``dna`` / ``riglogic`` modules are MIT licensed (Epic Games, see LICENSE-OpenRigLogic.txt)
but they are native, per-platform binaries, so they are *not* generated here.

How the bindings work: ``dna.py`` and ``riglogic.py`` are SWIG wrappers that do ``import _py3dna13_2_7``
and ``import _py3riglogic13_2_7`` (compiled ``.pyd`` on Windows, ``.so`` elsewhere) as *top-level* modules.
So every folder that holds one of those files has to be on ``sys.path`` (and, on Windows, registered as a
DLL directory). This module searches for them, so you may point it at the ``bindings`` folder, at its
parent, or at a platform sub-folder - whatever contains them somewhere below.

Search order: already-loaded bindings (e.g. Poly Hammer's enabled add-on) -> the folder set in the
add-on preferences -> ``<addon>/bindings`` -> Blender's extension / add-on folders.
Only importing needs the bindings. The imported rig itself is plain Blender drivers.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys

from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {}
_dll_handles: list = []
NATIVE_SUFFIXES = (".pyd",) if os.name == "nt" else (".so",)
MAX_SEARCH_DEPTH = 5


def _scan(root: Path) -> dict:
    """Find dna.py, riglogic.py and the compiled modules below ``root`` (``root`` may also be a file)."""
    root = Path(root)
    if root.is_file():
        root = root.parent
    found = {"root": root, "exists": root.is_dir(), "dna_py": [], "riglogic_py": [], "dna_native": [], "rl_native": []}
    if not root.is_dir():
        return found
    base = len(root.parts)
    for current, dirs, files in os.walk(root):
        here = Path(current)
        if len(here.parts) - base >= MAX_SEARCH_DEPTH:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
        for name in files:
            if name == "dna.py":
                found["dna_py"].append(here)
            elif name == "riglogic.py":
                found["riglogic_py"].append(here)
            elif name.startswith("_py3dna") and name.endswith(NATIVE_SUFFIXES):
                found["dna_native"].append(here)
            elif name.startswith("_py3riglogic") and name.endswith(NATIVE_SUFFIXES):
                found["rl_native"].append(here)
    return found


def _describe(found: dict) -> str:
    root = found["root"]
    if not found["exists"]:
        return f"{root}: folder does not exist"
    parts = []
    for key, label in (
        ("dna_py", "dna.py"), ("riglogic_py", "riglogic.py"),
        ("dna_native", f"_py3dna*{'/'.join(NATIVE_SUFFIXES)}"), ("rl_native", f"_py3riglogic*{'/'.join(NATIVE_SUFFIXES)}"),
    ):
        where = sorted({str(p) for p in found[key]})
        parts.append(f"{label}: " + (", ".join(where) if where else "NOT FOUND"))
    return f"{root}:\n    " + "\n    ".join(parts)


def _usable(found: dict) -> bool:
    return bool(found["dna_py"] and found["dna_native"])


def _already_imported():
    """Bindings that are already loaded in this Blender session (ours earlier, or another add-on's)."""
    dna = sys.modules.get("dna")
    if dna is not None and hasattr(dna, "BinaryStreamReader"):
        return dna, sys.modules.get("riglogic"), Path(getattr(dna, "__file__", "") or ".").parent
    for name, module in list(sys.modules.items()):
        if not (name.endswith(".bindings") or name == "bindings"):
            continue
        sub = sys.modules.get(f"{name}.dna")
        if sub is not None and hasattr(sub, "BinaryStreamReader"):
            return sub, sys.modules.get(f"{name}.riglogic"), Path(getattr(sub, "__file__", "") or ".").parent
    return None


def _candidate_roots(extra: str) -> list[Path]:
    import bpy

    roots: list[Path] = []
    if extra:
        roots.append(Path(bpy.path.abspath(extra)))
    roots.append(Path(__file__).parent / "bindings")
    for kind in ("EXTENSIONS", "SCRIPTS"):
        try:
            base = Path(bpy.utils.user_resource(kind))
        except Exception:  # noqa: BLE001
            continue
        if kind == "EXTENSIONS":
            roots += sorted(base.glob("*/*dna*"))
        else:
            roots += sorted((base / "addons").glob("*dna*"))
    return roots


def _import_from(found: dict):
    paths: list[Path] = []
    for key in ("dna_py", "dna_native", "riglogic_py", "rl_native"):
        for path in found[key]:
            if path not in paths:
                paths.append(path)
    inserted = []
    for path in reversed(paths):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
            inserted.append(text)
        if hasattr(os, "add_dll_directory"):
            try:
                _dll_handles.append(os.add_dll_directory(text))
            except OSError:
                pass
    try:
        for stale in ("dna", "riglogic"):
            module = sys.modules.get(stale)
            if module is not None and not hasattr(module, "BinaryStreamReader") and stale == "dna":
                sys.modules.pop(stale, None)
        dna = importlib.import_module("dna")
    except Exception:
        for text in inserted:
            if text in sys.path:
                sys.path.remove(text)
        raise
    try:
        riglogic = importlib.import_module("riglogic")
    except Exception as error:  # noqa: BLE001
        logger.warning("RigLogic runtime bindings unavailable (%s); verification will be skipped.", error)
        riglogic = None
    return dna, riglogic


def load_bindings(extra_folder: str = "", force: bool = False):
    """Return ``(dna_module, riglogic_module_or_None, folder)``; raises ``RuntimeError`` if not found."""
    if _cache and not force:
        return _cache["dna"], _cache["riglogic"], _cache["folder"]

    loaded = _already_imported()
    if loaded is not None:
        dna, riglogic, folder = loaded
        _cache.update(dna=dna, riglogic=riglogic, folder=folder)
        return dna, riglogic, folder

    report: list[str] = []
    tried = set()
    for root in _candidate_roots(extra_folder):
        if str(root) in tried:
            continue
        tried.add(str(root))
        found = _scan(root)
        if not _usable(found):
            if found["exists"] and (found["dna_py"] or found["dna_native"]):
                report.append(_describe(found))
            elif root == Path(extra_folder) or str(root) == str(Path(extra_folder)):
                report.append(_describe(found))
            continue
        try:
            dna, riglogic = _import_from(found)
        except Exception as error:  # noqa: BLE001 - wrong Python version / missing DLL etc.
            report.append(_describe(found) + f"\n    IMPORT FAILED: {type(error).__name__}: {error}")
            continue
        folder = found["dna_py"][0]
        _cache.update(dna=dna, riglogic=riglogic, folder=folder)
        return dna, riglogic, folder

    if not report:
        report.append("No folder containing dna.py and a compiled _py3dna* module was found.")
    raise RuntimeError(
        "The OpenRigLogic bindings could not be loaded.\n"
        "Set 'OpenRigLogic Bindings Folder' in the MetaMorphosis preferences to a folder that contains (directly "
        f"or in sub-folders) dna.py, riglogic.py and the compiled _py3dna*{NATIVE_SUFFIXES[0]} / "
        f"_py3riglogic*{NATIVE_SUFFIXES[0]} files.\n" + "\n".join(report)
    )


def release_handle(handle: Any) -> None:
    """Destroy an OpenRigLogic wrapper now instead of waiting for garbage collection (see Poly Hammer misc.py)."""
    if handle is None:
        return
    instance = getattr(handle, "_instance", None)
    if instance is None:
        return
    try:
        type(handle).destroy(instance)
    except Exception as error:  # noqa: BLE001
        logger.warning("Failed to destroy %s: %s", type(handle).__name__, error)
    handle._instance = None  # noqa: SLF001
    if getattr(handle, "_args", None):
        handle._args = ()  # noqa: SLF001


def open_reader(file_path: Path, extra_folder: str = "", data_layer: str = "All"):
    """Open a binary ``.dna`` file. The coordinate system is forced to Maya Y-up (x=left, y=up, z=front)."""
    dna, _riglogic, _folder = load_bindings(extra_folder)
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File '{file_path}' does not exist.")

    stream = dna.FileStream(
        path=str(file_path), accessMode=dna.AccessMode_Read, openMode=dna.OpenMode_Binary, memRes=None
    )
    coordinate_system = dna.CoordinateSystem()
    coordinate_system.x = dna.Direction_left
    coordinate_system.y = dna.Direction_up
    coordinate_system.z = dna.Direction_front

    config = dna.Configuration()
    config.layer = getattr(dna, f"DataLayer_{data_layer}")
    config.unknownLayerPolicy = dna.UnknownLayerPolicy_Preserve
    config.coordinateSystemTransformPolicy = dna.CoordinateSystemTransformPolicy_Transform
    config.coordinateSystem = coordinate_system

    reader = dna.BinaryStreamReader(stream, config, None)
    try:
        reader.read()
    except IndexError as error:
        release_handle(reader)
        raise RuntimeError(f"Could not read '{file_path}': {error}") from error

    if not dna.Status.isOk():
        status = dna.Status.get()
        release_handle(reader)
        raise RuntimeError(f'Error loading DNA: {status.message} from "{file_path}"')
    return reader


def unit_flags(reader) -> tuple[bool, float]:
    """Return ``(rotation_is_degrees, translation_to_meters)`` according to the DNA's own unit fields."""
    dna, _riglogic, _folder = load_bindings()
    rotation_degrees = True
    translation_to_meters = 0.01
    try:
        if hasattr(dna, "RotationUnit_radians") and reader.getRotationUnit() == dna.RotationUnit_radians:
            rotation_degrees = False
    except Exception:  # noqa: BLE001
        pass
    try:
        if hasattr(dna, "TranslationUnit_m") and reader.getTranslationUnit() == dna.TranslationUnit_m:
            translation_to_meters = 1.0
    except Exception:  # noqa: BLE001
        pass
    return rotation_degrees, translation_to_meters
