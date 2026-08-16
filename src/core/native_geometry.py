"""Optional C++ geometry facade with an always-available Python reference path."""

import importlib
import importlib.util
import os
from pathlib import Path
import sys

from . import stroke_tessellation as _python


_native = None
_load_error = ""
_runtime_error = ""
_enabled = os.environ.get("VECTOR_EDITOR_NATIVE", "1").lower() not in {
    "0", "false", "off", "no"
}


def _load_native():
    global _native, _load_error
    try:
        _native = importlib.import_module("vector_engine_native")
        return
    except ImportError as error:
        _load_error = str(error)
    native_bin = Path(__file__).resolve().parents[2] / "native" / "bin"
    candidates = sorted(native_bin.glob("vector_engine_native*.pyd"))
    if not candidates:
        return
    try:
        spec = importlib.util.spec_from_file_location("vector_engine_native", candidates[0])
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot create module spec for {candidates[0]}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _native = module
        _load_error = ""
    except Exception as error:  # ABI/load failures must never prevent editor startup.
        sys.modules.pop("vector_engine_native", None)
        _load_error = str(error)


_load_native()


def is_available():
    return _native is not None


def is_enabled():
    return bool(_enabled and _native is not None)


def set_native_enabled(enabled):
    global _enabled
    _enabled = bool(enabled)


def backend_name():
    return "C++ native" if is_enabled() else "Python reference"


def backend_info():
    return {
        "available": is_available(),
        "enabled": is_enabled(),
        "backend": backend_name(),
        "version": getattr(_native, "__version__", None),
        "msvc_version": getattr(_native, "msvc_version", None),
        "load_error": _load_error,
        "runtime_error": _runtime_error,
    }


def tessellate_stroke(points, width, closed=False, join="miter", cap="butt",
                      miter_limit=4.0, round_segments=8):
    global _runtime_error
    if is_enabled():
        try:
            result = _native.tessellate_stroke(
                points, width, closed=closed, join=join, cap=cap,
                miter_limit=miter_limit, round_segments=round_segments)
            _runtime_error = ""
            return result
        except Exception as error:
            # Invalid input must retain the reference implementation's behavior.
            _runtime_error = str(error)
    return _python.tessellate_stroke(
        points, width, closed, join, cap, miter_limit, round_segments)


def tessellate_stroke_coverage(points, width, closed=False, join="miter", cap="butt",
                               antialias_width=1.0, miter_limit=4.0,
                               round_segments=8):
    global _runtime_error
    if is_enabled():
        try:
            result = _native.tessellate_stroke_coverage(
                points, width, closed=closed, join=join, cap=cap,
                antialias_width=antialias_width, miter_limit=miter_limit,
                round_segments=round_segments)
            _runtime_error = ""
            return result
        except Exception as error:
            _runtime_error = str(error)
    return _python.tessellate_stroke_coverage(
        points, width, closed, join, cap, antialias_width, miter_limit,
        round_segments)


def tessellate_segments_coverage(points, width, cap="butt", antialias_width=1.0,
                                 round_segments=8):
    result = []
    points = tuple(points)
    for index in range(0, len(points) - 1, 2):
        result.extend(tessellate_stroke_coverage(
            points[index:index + 2], width, cap=cap,
            antialias_width=antialias_width, round_segments=round_segments))
    return tuple(result)
