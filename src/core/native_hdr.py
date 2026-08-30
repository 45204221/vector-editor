"""C++-preferred facade for the M20 tone-mapping reference."""

from . import native_geometry
from .hdr_postprocess import (bloom_soft_threshold as python_bloom_threshold,
                              exposure_from_histogram,
                              log_luminance_histogram,
                              tone_map_rgb as python_tone_map)


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


def bloom_soft_threshold(rgb, threshold=1.0, knee=0.5):
    global _runtime_error
    values = tuple(float(value) for value in rgb)
    module = _module()
    if module is not None and hasattr(module, "bloom_soft_threshold"):
        try:
            result = module.bloom_soft_threshold(
                values[0], values[1], values[2], float(threshold), float(knee))
            _runtime_error = ""
            return tuple(float(value) for value in result), "C++ native"
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            _runtime_error = str(error)
    return python_bloom_threshold(values, threshold, knee), "Python reference"


def auto_exposure_from_luminance(luminances, bins=64, min_ev=-12.0,
                                 max_ev=4.0, low_percentile=0.02,
                                 high_percentile=0.98, middle_grey=0.18,
                                 compensation_ev=0.0):
    global _runtime_error
    values = tuple(float(value) for value in luminances)
    module = _module()
    if module is not None and hasattr(module, "auto_exposure_from_luminance"):
        try:
            result = module.auto_exposure_from_luminance(
                values, int(bins), float(min_ev), float(max_ev),
                float(low_percentile), float(high_percentile),
                float(middle_grey), float(compensation_ev))
            _runtime_error = ""
            return float(result), "C++ native"
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            _runtime_error = str(error)
    histogram = log_luminance_histogram(values, bins, min_ev, max_ev)
    return exposure_from_histogram(
        histogram, min_ev, max_ev, low_percentile, high_percentile,
        middle_grey, compensation_ev), "Python reference"
