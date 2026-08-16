"""Narrow optional-native facade for M17 3D mesh generation."""

from . import native_geometry
from .mesh3d import Mesh3D, cube_mesh as python_cube, extrude_mesh as python_extrude


_runtime_error = ""


def _module():
    module = getattr(native_geometry, "_native", None)
    return module if native_geometry.is_enabled() else None


def is_available():
    return bool(_module() is not None and hasattr(_module(), "extrude_mesh"))


def backend_name():
    return "C++ native" if is_available() else "Python reference"


def runtime_error():
    return _runtime_error


def extrude_mesh(contour, triangles, depth=0.7):
    global _runtime_error
    module = _module()
    if module is not None and hasattr(module, "extrude_mesh"):
        try:
            vertices = tuple(tuple(float(value) for value in vertex)
                             for vertex in module.extrude_mesh(
                                 contour, triangles, depth=depth))
            _runtime_error = ""
            return Mesh3D(vertices, "C++ native")
        except Exception as error:
            _runtime_error = str(error)
    result = python_extrude(contour, triangles, depth)
    return Mesh3D(result.vertices, "Python reference", _runtime_error)


def cube_mesh():
    global _runtime_error
    module = _module()
    if module is not None and hasattr(module, "cube_mesh"):
        try:
            vertices = tuple(tuple(float(value) for value in vertex)
                             for vertex in module.cube_mesh())
            _runtime_error = ""
            return Mesh3D(vertices, "C++ native")
        except Exception as error:
            _runtime_error = str(error)
    result = python_cube()
    return Mesh3D(result.vertices, "Python reference", _runtime_error)
