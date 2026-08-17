"""C++-preferred facade for M19 mipmap generation and sampling."""

from . import native_geometry
from .texture_sampling import (MipLevel, TextureFootprint,
                               generate_mipmaps as python_generate,
                               sample_anisotropic as python_anisotropic,
                               sample_mipmaps as python_sample)


_runtime_error = ""


def _module():
    module = getattr(native_geometry, "_native", None)
    return module if native_geometry.is_enabled() else None


def is_available():
    module = _module()
    return bool(module is not None and hasattr(module, "generate_mipmaps") and
                hasattr(module, "sample_texture") and
                hasattr(module, "sample_anisotropic"))


def runtime_error():
    return _runtime_error


def generate_mipmaps(rgba, width, height):
    global _runtime_error
    module = _module()
    if module is not None and hasattr(module, "generate_mipmaps"):
        try:
            result = module.generate_mipmaps(bytes(rgba), int(width), int(height))
            _runtime_error = ""
            return tuple(MipLevel(int(w), int(h), bytes(pixels))
                         for w, h, pixels in result), "C++ native"
        except Exception as error:
            _runtime_error = str(error)
    return python_generate(rgba, width, height), "Python reference"


def sample_texture(rgba, width, height, u, v, lod, filter="nearest", repeat=True):
    global _runtime_error
    module = _module()
    if module is not None and hasattr(module, "sample_texture"):
        try:
            result = module.sample_texture(
                bytes(rgba), int(width), int(height), float(u), float(v), float(lod),
                filter=str(filter), repeat=bool(repeat))
            _runtime_error = ""
            return tuple(map(int, result)), "C++ native"
        except Exception as error:
            _runtime_error = str(error)
    levels = python_generate(rgba, width, height)
    return python_sample(levels, u, v, lod, filter, repeat), "Python reference"


def sample_anisotropic(rgba, width, height, u, v, dudx, dvdx, dudy, dvdy,
                       max_taps=8, repeat=True):
    global _runtime_error
    module = _module()
    if module is not None and hasattr(module, "sample_anisotropic"):
        try:
            result = module.sample_anisotropic(
                bytes(rgba), int(width), int(height), float(u), float(v),
                float(dudx), float(dvdx), float(dudy), float(dvdy),
                int(max_taps), bool(repeat))
            footprint = TextureFootprint(
                *map(float, result[4:11]), int(result[11]))
            _runtime_error = ""
            return tuple(map(int, result[:4])), footprint, "C++ native"
        except Exception as error:
            _runtime_error = str(error)
    levels = python_generate(rgba, width, height)
    color, footprint = python_anisotropic(
        levels, u, v, dudx, dvdx, dudy, dvdy, max_taps, repeat)
    return color, footprint, "Python reference"
