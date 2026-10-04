"""Locate the OpenRigLogic Python bindings and read DNA files.

The compiled ``dna`` / ``riglogic`` modules are MIT licensed (Epic Games, see LICENSE-OpenRigLogic.txt)
but they are native, per-platform binaries, so they are *not* generated here. MetaMorphosis looks for
them, in this order:

1. ``<addon>/bindings``                       (copy the folder from Poly Hammer's add-on here)
2. the folder set in the add-on preferences
3. an already-enabled Poly Hammer add-on      (its loaded modules are reused; checked first)
4. the extensions / add-ons folders on disk   (any ``*dna*/bindings`` folder)

The bindings are only needed while *importing* (and re-baking). The imported rig itself consists
of plain Blender drivers and does not need them.
"""

from __future__ import annotations

import importlib
import logging
import sys
import types

from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PKG_NAME = "mm_bindings"
_cache: dict[str, Any] = {}


def _valid_folder(folder: Path) -> bool:
    return folder.is_dir() and (folder / "dna.py").exists()


def _candidate_folders(extra: str = "") -> list[Path]:
    import bpy

    candidates: list[Path] = [Path(__file__).parent / "bindings"]
    if extra:
        candidates.append(Path(bpy.path.abspath(extra)))
    try:
        ext_root = Path(bpy.utils.user_resource("EXTENSIONS"))
        candidates += sorted(ext_root.glob("*/*dna*/bindings"))
    except Exception:  # noqa: BLE001
        pass
    try:
        scripts = Path(bpy.utils.user_resource("SCRIPTS"))
        candidates += sorted((scripts / "addons").glob("*dna*/bindings"))
    except Exception:  # noqa: BLE001
        pass
    return candidates


def _from_loaded_addon():
    """Reuse the already-imported bindings of an enabled Poly Hammer add-on (avoids loading the native module twice)."""
    for name, module in list(sys.modules.items()):
        if "mm_bindings" in name or not (name.endswith(".bindings") or name == "bindings"):
            continue
        folder = getattr(module, "__path__", None)
        dna = sys.modules.get(f"{name}.dna")
        if folder and dna is not None and _valid_folder(Path(list(folder)[0])):
            return dna, sys.modules.get(f"{name}.riglogic"), Path(list(folder)[0])
    return None


def _load_package(folder: Path):
    sys.modules.pop(_PKG_NAME, None)
    for key in [k for k in sys.modules if k.startswith(_PKG_NAME + ".")]:
        sys.modules.pop(key, None)
    package = types.ModuleType(_PKG_NAME)
    package.__path__ = [str(folder)]  # type: ignore[attr-defined]
    package.__package__ = _PKG_NAME
    sys.modules[_PKG_NAME] = package
    dna = importlib.import_module(f"{_PKG_NAME}.dna")
    try:
        riglogic = importlib.import_module(f"{_PKG_NAME}.riglogic")
    except Exception as error:  # noqa: BLE001
        logger.warning("RigLogic runtime bindings unavailable (%s); verification will be skipped.", error)
        riglogic = None
    return dna, riglogic


def load_bindings(extra_folder: str = "", force: bool = False):
    """Return ``(dna_module, riglogic_module_or_None, folder)``; raises ``RuntimeError`` if not found."""
    if _cache and not force:
        return _cache["dna"], _cache["riglogic"], _cache["folder"]

    loaded = _from_loaded_addon()
    if loaded is not None:
        dna, riglogic, folder = loaded
        _cache.update(dna=dna, riglogic=riglogic, folder=folder)
        return dna, riglogic, folder

    errors = []
    folders = _candidate_folders(extra_folder)

    seen = set()
    for folder in folders:
        key = str(folder)
        if key in seen or not _valid_folder(folder):
            continue
        seen.add(key)
        try:
            dna, riglogic = _load_package(folder)
        except Exception as error:  # noqa: BLE001 - wrong platform / python ABI etc.
            errors.append(f"{folder}: {type(error).__name__}: {error}")
            continue
        _cache.update(dna=dna, riglogic=riglogic, folder=folder)
        return dna, riglogic, folder

    detail = "\n".join(errors) if errors else "no folder containing dna.py was found"
    raise RuntimeError(
        "The OpenRigLogic bindings (dna.py + compiled modules) could not be loaded.\n"
        "Copy the 'bindings' folder from Poly Hammer's Character DNA add-on into the MetaMorphosis "
        "add-on folder (or set its path in the add-on preferences).\n" + detail
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
