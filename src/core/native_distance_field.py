"""C++-preferred signed-distance facade with deterministic fallback."""

from . import native_geometry
from .distance_field import signed_distance_field as python_signed_distance_field


_runtime_error = ""


def signed_distance_field(mask, width, height):
    global _runtime_error
    values = bytes(255 if value else 0 for value in mask)
    module = getattr(native_geometry, "_native", None) if native_geometry.is_enabled() else None
    if module is not None and hasattr(module, "signed_distance_field"):
        try:
            result = module.signed_distance_field(values, int(width), int(height))
            _runtime_error = ""
            return tuple(map(float, result)), "C++ native exact EDT"
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            _runtime_error = str(error)
    return python_signed_distance_field(values, width, height), "Python exact EDT"


def runtime_error():
    return _runtime_error
