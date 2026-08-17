"""C++-preferred facade for the M20 tone-mapping reference."""

from . import native_geometry
from .hdr_postprocess import tone_map_rgb as python_tone_map


_runtime_error = ""


def _module():
    module = getattr(native_geometry, "_native", None)
    return module if native_geometry.is_enabled() else None


def is_available():
    module = _module()
    return bool(module is not None and hasattr(module, "tone_map_rgb"))


def runtime_error():
    return _runtime_error


def tone_map_rgb(rgb, exposure=1.0, tone_mapper="reinhard", gamma=2.2):
    global _runtime_error
    values = tuple(rgb)
    module = _module()
    if module is not None and hasattr(module, "tone_map_rgb"):
        try:
            result = module.tone_map_rgb(
                float(values[0]), float(values[1]), float(values[2]),
                float(exposure), str(tone_mapper), float(gamma))
            _runtime_error = ""
            return tuple(map(float, result)), "C++ native"
        except Exception as error:
            _runtime_error = str(error)
    return python_tone_map(values, exposure, tone_mapper, gamma), "Python reference"
