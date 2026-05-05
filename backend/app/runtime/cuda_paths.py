from __future__ import annotations

import ctypes
import os
import site
import sys
from pathlib import Path
from typing import Any


_DLL_DIRECTORY_HANDLES: list[Any] = []
_DLL_DIRECTORY_PATHS: set[str] = set()
_PATH_ENTRIES_ADDED: set[str] = set()
_PRELOADED_DLLS: list[Any] = []
_PRELOADED_DLL_PATHS: set[str] = set()


def ensure_local_cuda_dll_paths(*, preload_genai_cuda: bool = False) -> dict[str, Any]:
    """Expose repo-local CUDA DLLs installed by Python packages to Windows loaders.

    Some GPU wheels ship CUDA runtime DLLs inside ``site-packages/nvidia``. Native
    libraries loaded later by ONNX Runtime GenAI do not reliably see those paths
    unless they are present in PATH before provider initialization.
    """

    result: dict[str, Any] = {
        "ok": True,
        "platform": sys.platform,
        "added_paths": [],
        "preloaded": [],
        "errors": [],
    }
    if not sys.platform.startswith("win"):
        return result

    for path in _candidate_dll_dirs():
        added = _add_dll_search_path(path, result)
        if added:
            result["added_paths"].append(str(path))

    if preload_genai_cuda:
        for site_root in _site_package_roots():
            dll_path = site_root / "onnxruntime_genai" / "onnxruntime-genai-cuda.dll"
            if dll_path.exists():
                _preload_dll(dll_path, result)

    result["ok"] = not result["errors"]
    return result


def _candidate_dll_dirs() -> list[Path]:
    paths: list[Path] = []
    for site_root in _site_package_roots():
        paths.extend(
            [
                site_root / "onnxruntime" / "capi",
                site_root / "onnxruntime_genai",
            ]
        )
        nvidia_root = site_root / "nvidia"
        if nvidia_root.exists():
            paths.extend(path / "bin" for path in nvidia_root.iterdir() if (path / "bin").exists())
    return _unique_existing_dirs(paths)


def _site_package_roots() -> list[Path]:
    roots: list[Path] = []
    for value in [*site.getsitepackages(), site.getusersitepackages(), *sys.path]:
        if not value:
            continue
        path = Path(value)
        if path.name == "site-packages" and path.exists():
            roots.append(path)
    return _unique_existing_dirs(roots)


def _add_dll_search_path(path: Path, result: dict[str, Any]) -> bool:
    resolved = str(path.resolve())
    if resolved.lower() not in _PATH_ENTRIES_ADDED:
        current = os.environ.get("PATH", "")
        entries = [entry for entry in current.split(os.pathsep) if entry]
        if resolved.lower() not in {entry.lower() for entry in entries}:
            os.environ["PATH"] = os.pathsep.join([resolved, *entries])
        _PATH_ENTRIES_ADDED.add(resolved.lower())

    if hasattr(os, "add_dll_directory") and resolved.lower() not in _DLL_DIRECTORY_PATHS:
        try:
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(resolved))
            _DLL_DIRECTORY_PATHS.add(resolved.lower())
            return True
        except OSError as exc:
            result["errors"].append(f"Failed to add DLL directory {resolved}: {exc}")
            return False
    return False


def _preload_dll(path: Path, result: dict[str, Any]) -> None:
    resolved = str(path.resolve())
    if resolved.lower() in _PRELOADED_DLL_PATHS:
        return
    try:
        _PRELOADED_DLLS.append(ctypes.CDLL(resolved))
        _PRELOADED_DLL_PATHS.add(resolved.lower())
        result["preloaded"].append(resolved)
    except OSError as exc:
        result["errors"].append(f"Failed to preload {resolved}: {exc}")


def _unique_existing_dirs(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        if not path.exists() or not path.is_dir():
            continue
        resolved = str(path.resolve()).lower()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(path)
    return result
