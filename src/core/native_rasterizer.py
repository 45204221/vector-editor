"""Optional-native facade for the M18 software rasterizer."""

from . import native_geometry
from .software_rasterizer import RasterResult, software_rasterize as python_rasterize


_runtime_error = ""


def _module():
    module = getattr(native_geometry, "_native", None)
    return module if native_geometry.is_enabled() else None


def is_available():
    module = _module()
    return bool(module is not None and hasattr(module, "software_rasterize"))


def runtime_error():
    return _runtime_error


def software_rasterize(vertices, width, height, perspective_correct=True,
                       cull_back_faces=True, clip_volume=True, sample_count=1):
    global _runtime_error
    module = _module()
    if module is not None and hasattr(module, "software_rasterize"):
        try:
            result = module.software_rasterize(
                vertices, int(width), int(height),
                perspective_correct=bool(perspective_correct),
                cull_back_faces=bool(cull_back_faces),
                clip_volume=bool(clip_volume), sample_count=int(sample_count))
            _runtime_error = ""
            return RasterResult(
                int(result["width"]), int(result["height"]),
                bytes(result["color"]), bytes(result["barycentric"]),
                bytes(result["depth"]), bytes(result["primitive_id"]),
                int(result["input_triangles"]),
                int(result["clipped_triangles"]),
                int(result["rasterized_triangles"]),
                int(result["covered_fragments"]),
                int(result["depth_passed_fragments"]),
                int(result["resolved_covered_pixels"]),
                int(result["sample_count"]),
                float(result["elapsed_ms"]), "C++ native")
        except Exception as error:
            _runtime_error = str(error)
    result = python_rasterize(vertices, width, height, perspective_correct,
                              cull_back_faces, clip_volume, sample_count)
    return RasterResult(result.width, result.height, result.color,
                        result.barycentric, result.depth,
                        result.primitive_id,
                        result.input_triangles, result.clipped_triangles,
                        result.rasterized_triangles,
                        result.covered_fragments, result.depth_passed_fragments,
                        result.resolved_covered_pixels, result.sample_count,
                        result.elapsed_ms, "Python reference", _runtime_error)
