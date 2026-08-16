"""Optional C++ visibility facade with deterministic Python fallback."""

from . import native_geometry
from .visibility import VisibilityRay, VisibilityResult, visibility_polygon as _python


_runtime_error = ""


def backend_name():
    native = getattr(native_geometry, "_native", None)
    enabled = native_geometry.is_enabled() and hasattr(native, "visibility_polygon")
    return "C++ native" if enabled else "Python reference"


def visibility_polygon(light, segments, angle_epsilon=1e-5, use_native=True):
    global _runtime_error
    native = getattr(native_geometry, "_native", None)
    if use_native and native_geometry.is_enabled() and hasattr(native, "visibility_polygon"):
        try:
            polygon, raw_rays, tests = native.visibility_polygon(
                light, segments, angle_epsilon=angle_epsilon)
            rays = tuple(VisibilityRay(float(angle), (float(x), float(y)),
                                       float(distance), int(segment_index))
                         for angle, x, y, distance, segment_index in raw_rays)
            _runtime_error = ""
            return VisibilityResult(tuple(tuple(point) for point in polygon), rays,
                                    len(tuple(segments)), int(tests), "C++ native")
        except Exception as error:
            _runtime_error = str(error)
    result = _python(light, segments, angle_epsilon)
    return VisibilityResult(result.polygon, result.rays, result.segment_count,
                            result.intersection_tests, "Python reference",
                            _runtime_error)


def backend_info():
    return {"backend": backend_name(), "runtime_error": _runtime_error,
            "native_available": native_geometry.is_available()}
