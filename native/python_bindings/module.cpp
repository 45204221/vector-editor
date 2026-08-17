#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <string>
#include <vector>

#include "stroke_tessellation.hpp"
#include "visibility.hpp"
#include "mesh_extrusion.hpp"
#include "software_rasterizer.hpp"
#include "texture_sampling.hpp"

namespace {

bool parse_points(PyObject* object, std::vector<vector_engine::Point2>& points) {
    PyObject* sequence = PySequence_Fast(object, "points must be a sequence");
    if (!sequence) return false;
    const Py_ssize_t count = PySequence_Fast_GET_SIZE(sequence);
    points.reserve(static_cast<std::size_t>(count));
    PyObject** items = PySequence_Fast_ITEMS(sequence);
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* point = PySequence_Fast(items[index], "each point must be a sequence");
        if (!point) {
            Py_DECREF(sequence);
            return false;
        }
        if (PySequence_Fast_GET_SIZE(point) < 2) {
            Py_DECREF(point);
            Py_DECREF(sequence);
            PyErr_SetString(PyExc_ValueError, "each point needs x and y");
            return false;
        }
        PyObject** coordinates = PySequence_Fast_ITEMS(point);
        const double x = PyFloat_AsDouble(coordinates[0]);
        const double y = PyFloat_AsDouble(coordinates[1]);
        Py_DECREF(point);
        if (PyErr_Occurred()) {
            Py_DECREF(sequence);
            return false;
        }
        points.push_back({x, y});
    }
    Py_DECREF(sequence);
    return true;
}

bool parse_point(PyObject* object, vector_engine::Point2& result,
                 const char* error_message) {
    PyObject* point = PySequence_Fast(object, error_message);
    if (!point) return false;
    if (PySequence_Fast_GET_SIZE(point) < 2) {
        Py_DECREF(point);
        PyErr_SetString(PyExc_ValueError, error_message);
        return false;
    }
    PyObject** values = PySequence_Fast_ITEMS(point);
    result.x = PyFloat_AsDouble(values[0]);
    result.y = PyFloat_AsDouble(values[1]);
    Py_DECREF(point);
    return !PyErr_Occurred();
}

bool parse_segments(PyObject* object, std::vector<vector_engine::Segment2>& segments) {
    PyObject* sequence = PySequence_Fast(object, "segments must be a sequence");
    if (!sequence) return false;
    const Py_ssize_t count = PySequence_Fast_GET_SIZE(sequence);
    segments.reserve(static_cast<std::size_t>(count));
    PyObject** items = PySequence_Fast_ITEMS(sequence);
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* segment = PySequence_Fast(items[index],
                                             "each segment must contain two points");
        if (!segment || PySequence_Fast_GET_SIZE(segment) < 2) {
            Py_XDECREF(segment);
            Py_DECREF(sequence);
            PyErr_SetString(PyExc_ValueError, "each segment must contain two points");
            return false;
        }
        PyObject** endpoints = PySequence_Fast_ITEMS(segment);
        vector_engine::Segment2 value{};
        const bool valid = parse_point(endpoints[0], value.first, "invalid segment point") &&
                           parse_point(endpoints[1], value.second, "invalid segment point");
        Py_DECREF(segment);
        if (!valid) {
            Py_DECREF(sequence);
            return false;
        }
        segments.push_back(value);
    }
    Py_DECREF(sequence);
    return true;
}

PyObject* mesh2_to_tuple(const vector_engine::Mesh2& mesh) {
    PyObject* result = PyTuple_New(static_cast<Py_ssize_t>(mesh.size()));
    if (!result) return nullptr;
    for (Py_ssize_t index = 0; index < static_cast<Py_ssize_t>(mesh.size()); ++index) {
        PyObject* point = Py_BuildValue("(dd)", mesh[index].x, mesh[index].y);
        if (!point) {
            Py_DECREF(result);
            return nullptr;
        }
        PyTuple_SET_ITEM(result, index, point);
    }
    return result;
}

PyObject* mesh3_to_tuple(const vector_engine::Mesh3& mesh) {
    PyObject* result = PyTuple_New(static_cast<Py_ssize_t>(mesh.size()));
    if (!result) return nullptr;
    for (Py_ssize_t index = 0; index < static_cast<Py_ssize_t>(mesh.size()); ++index) {
        PyObject* point = Py_BuildValue("(ddd)", mesh[index].x, mesh[index].y,
                                        mesh[index].coverage);
        if (!point) {
            Py_DECREF(result);
            return nullptr;
        }
        PyTuple_SET_ITEM(result, index, point);
    }
    return result;
}

PyObject* mesh3d_to_tuple(const vector_engine::Mesh3D& mesh) {
    PyObject* result = PyTuple_New(static_cast<Py_ssize_t>(mesh.size()));
    if (!result) return nullptr;
    for (Py_ssize_t index = 0; index < static_cast<Py_ssize_t>(mesh.size()); ++index) {
        const auto& vertex = mesh[static_cast<std::size_t>(index)];
        PyObject* item = Py_BuildValue("(dddddd)", vertex.x, vertex.y, vertex.z,
                                       vertex.nx, vertex.ny, vertex.nz);
        if (!item) { Py_DECREF(result); return nullptr; }
        PyTuple_SET_ITEM(result, index, item);
    }
    return result;
}

bool parse_raster_vertices(PyObject* object,
                           std::vector<vector_engine::RasterVertex>& vertices) {
    PyObject* sequence = PySequence_Fast(object, "vertices must be a sequence");
    if (!sequence) return false;
    const Py_ssize_t count = PySequence_Fast_GET_SIZE(sequence);
    vertices.reserve(static_cast<std::size_t>(count));
    PyObject** items = PySequence_Fast_ITEMS(sequence);
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* vertex = PySequence_Fast(items[index],
                                           "each raster vertex must be a sequence");
        if (!vertex || PySequence_Fast_GET_SIZE(vertex) < 7) {
            Py_XDECREF(vertex); Py_DECREF(sequence);
            PyErr_SetString(PyExc_ValueError, "raster vertex needs clip.xyzw + rgb");
            return false;
        }
        PyObject** values = PySequence_Fast_ITEMS(vertex);
        vector_engine::RasterVertex parsed{};
        double* output[] = {&parsed.clip_x, &parsed.clip_y, &parsed.clip_z,
                            &parsed.clip_w, &parsed.r, &parsed.g, &parsed.b};
        for (int component = 0; component < 7; ++component) {
            *output[component] = PyFloat_AsDouble(values[component]);
        }
        Py_DECREF(vertex);
        if (PyErr_Occurred()) { Py_DECREF(sequence); return false; }
        vertices.push_back(parsed);
    }
    Py_DECREF(sequence);
    return true;
}

PyObject* raster_result_to_dict(const vector_engine::RasterResult& result) {
    PyObject* dictionary = PyDict_New();
    if (!dictionary) return nullptr;
    auto set = [dictionary](const char* name, PyObject* value) {
        if (!value || PyDict_SetItemString(dictionary, name, value) < 0) {
            Py_XDECREF(value); return false;
        }
        Py_DECREF(value); return true;
    };
    const auto bytes = [](const std::vector<std::uint8_t>& values) {
        return PyBytes_FromStringAndSize(
            reinterpret_cast<const char*>(values.data()),
            static_cast<Py_ssize_t>(values.size()));
    };
    if (!set("width", PyLong_FromLong(result.width)) ||
        !set("height", PyLong_FromLong(result.height)) ||
        !set("color", bytes(result.color)) ||
        !set("barycentric", bytes(result.barycentric)) ||
        !set("depth", bytes(result.depth)) ||
        !set("primitive_id", bytes(result.primitive_id)) ||
        !set("input_triangles", PyLong_FromSize_t(result.input_triangles)) ||
        !set("clipped_triangles", PyLong_FromSize_t(result.clipped_triangles)) ||
        !set("rasterized_triangles", PyLong_FromSize_t(result.rasterized_triangles)) ||
        !set("covered_fragments", PyLong_FromSize_t(result.covered_fragments)) ||
        !set("depth_passed_fragments",
             PyLong_FromSize_t(result.depth_passed_fragments)) ||
        !set("resolved_covered_pixels",
             PyLong_FromSize_t(result.resolved_covered_pixels)) ||
        !set("sample_count", PyLong_FromLong(result.sample_count)) ||
        !set("elapsed_ms", PyFloat_FromDouble(result.elapsed_ms))) {
        Py_DECREF(dictionary); return nullptr;
    }
    return dictionary;
}

PyObject* py_tessellate_stroke(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* points_object = nullptr;
    double width = 0.0;
    int closed = 0;
    const char* join = "miter";
    const char* cap = "butt";
    double miter_limit = 4.0;
    int round_segments = 8;
    static const char* names[] = {"points", "width", "closed", "join", "cap",
                                  "miter_limit", "round_segments", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Od|pssdi",
                                     const_cast<char**>(names), &points_object, &width,
                                     &closed, &join, &cap, &miter_limit,
                                     &round_segments)) {
        return nullptr;
    }
    std::vector<vector_engine::Point2> points;
    if (!parse_points(points_object, points)) return nullptr;
    try {
        return mesh2_to_tuple(vector_engine::tessellate_stroke(
            points, width, closed != 0, join, cap, miter_limit, round_segments));
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    }
}

PyObject* py_tessellate_stroke_coverage(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* points_object = nullptr;
    double width = 0.0;
    int closed = 0;
    const char* join = "miter";
    const char* cap = "butt";
    double antialias_width = 1.0;
    double miter_limit = 4.0;
    int round_segments = 8;
    static const char* names[] = {"points", "width", "closed", "join", "cap",
                                  "antialias_width", "miter_limit", "round_segments",
                                  nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Od|pssddi",
                                     const_cast<char**>(names), &points_object, &width,
                                     &closed, &join, &cap, &antialias_width,
                                     &miter_limit, &round_segments)) {
        return nullptr;
    }
    std::vector<vector_engine::Point2> points;
    if (!parse_points(points_object, points)) return nullptr;
    try {
        return mesh3_to_tuple(vector_engine::tessellate_stroke_coverage(
            points, width, closed != 0, join, cap, antialias_width, miter_limit,
            round_segments));
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    }
}

PyObject* py_visibility_polygon(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* light_object = nullptr;
    PyObject* segments_object = nullptr;
    double angle_epsilon = 1e-5;
    static const char* names[] = {"light", "segments", "angle_epsilon", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OO|d",
                                     const_cast<char**>(names), &light_object,
                                     &segments_object, &angle_epsilon)) {
        return nullptr;
    }
    vector_engine::Point2 light{};
    std::vector<vector_engine::Segment2> segments;
    if (!parse_point(light_object, light, "light must contain x and y") ||
        !parse_segments(segments_object, segments)) {
        return nullptr;
    }
    try {
        const auto output = vector_engine::visibility_polygon(
            light, segments, angle_epsilon);
        PyObject* polygon = mesh2_to_tuple(output.polygon);
        PyObject* rays = PyTuple_New(static_cast<Py_ssize_t>(output.rays.size()));
        if (!polygon || !rays) {
            Py_XDECREF(polygon); Py_XDECREF(rays);
            return nullptr;
        }
        for (Py_ssize_t index = 0;
             index < static_cast<Py_ssize_t>(output.rays.size()); ++index) {
            const auto& ray = output.rays[static_cast<std::size_t>(index)];
            PyObject* item = Py_BuildValue("(ddddn)", ray.angle, ray.point.x,
                                           ray.point.y, ray.distance,
                                           static_cast<Py_ssize_t>(ray.segment_index));
            if (!item) {
                Py_DECREF(polygon); Py_DECREF(rays);
                return nullptr;
            }
            PyTuple_SET_ITEM(rays, index, item);
        }
        PyObject* result = PyTuple_New(3);
        if (!result) { Py_DECREF(polygon); Py_DECREF(rays); return nullptr; }
        PyTuple_SET_ITEM(result, 0, polygon);
        PyTuple_SET_ITEM(result, 1, rays);
        PyTuple_SET_ITEM(result, 2, PyLong_FromSize_t(output.intersection_tests));
        return result;
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return nullptr;
    }
}

PyObject* py_extrude_mesh(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* contour_object = nullptr;
    PyObject* triangles_object = nullptr;
    double depth = 0.7;
    static const char* names[] = {"contour", "triangles", "depth", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OO|d",
                                     const_cast<char**>(names), &contour_object,
                                     &triangles_object, &depth)) return nullptr;
    std::vector<vector_engine::Point2> contour, triangles;
    if (!parse_points(contour_object, contour) ||
        !parse_points(triangles_object, triangles)) return nullptr;
    try {
        return mesh3d_to_tuple(vector_engine::extrude_mesh(contour, triangles, depth));
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what()); return nullptr;
    }
}

PyObject* py_cube_mesh(PyObject*, PyObject*) {
    try { return mesh3d_to_tuple(vector_engine::cube_mesh()); }
    catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what()); return nullptr;
    }
}

PyObject* py_software_rasterize(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* vertices_object = nullptr;
    int width = 0, height = 0, perspective_correct = 1, cull_back_faces = 1;
    int clip_volume = 1, sample_count = 1;
    static const char* names[] = {"vertices", "width", "height",
                                  "perspective_correct", "cull_back_faces",
                                  "clip_volume", "sample_count", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Oii|pppi",
                                     const_cast<char**>(names), &vertices_object,
                                     &width, &height, &perspective_correct,
                                     &cull_back_faces, &clip_volume,
                                     &sample_count)) return nullptr;
    std::vector<vector_engine::RasterVertex> vertices;
    if (!parse_raster_vertices(vertices_object, vertices)) return nullptr;
    try {
        return raster_result_to_dict(vector_engine::software_rasterize(
            vertices, width, height, perspective_correct != 0,
            cull_back_faces != 0, clip_volume != 0, sample_count));
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what()); return nullptr;
    }
}

bool parse_rgba_buffer(PyObject* object, std::vector<std::uint8_t>& output) {
    Py_buffer view{};
    if (PyObject_GetBuffer(object, &view, PyBUF_CONTIG_RO) < 0) return false;
    const auto* first = static_cast<const std::uint8_t*>(view.buf);
    output.assign(first, first + view.len);
    PyBuffer_Release(&view);
    return true;
}

PyObject* mip_levels_to_tuple(const std::vector<vector_engine::TextureLevel>& levels) {
    PyObject* result = PyTuple_New(static_cast<Py_ssize_t>(levels.size()));
    if (!result) return nullptr;
    for (Py_ssize_t index = 0; index < static_cast<Py_ssize_t>(levels.size()); ++index) {
        const auto& level = levels[static_cast<std::size_t>(index)];
        PyObject* pixels = PyBytes_FromStringAndSize(
            reinterpret_cast<const char*>(level.rgba.data()),
            static_cast<Py_ssize_t>(level.rgba.size()));
        if (!pixels) { Py_DECREF(result); return nullptr; }
        PyObject* value = Py_BuildValue("(iiN)", level.width, level.height, pixels);
        if (!value) { Py_DECREF(result); return nullptr; }
        PyTuple_SET_ITEM(result, index, value);
    }
    return result;
}

PyObject* py_generate_mipmaps(PyObject*, PyObject* args) {
    PyObject* rgba_object = nullptr;
    int width = 0, height = 0;
    if (!PyArg_ParseTuple(args, "Oii", &rgba_object, &width, &height)) return nullptr;
    std::vector<std::uint8_t> rgba;
    if (!parse_rgba_buffer(rgba_object, rgba)) return nullptr;
    try {
        return mip_levels_to_tuple(vector_engine::generate_mipmaps(rgba, width, height));
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_ValueError, error.what()); return nullptr;
    }
}

PyObject* py_sample_texture(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* rgba_object = nullptr;
    int width = 0, height = 0, repeat = 1;
    double u = 0.0, v = 0.0, lod = 0.0;
    const char* filter = "nearest";
    static const char* names[] = {"rgba", "width", "height", "u", "v", "lod",
                                  "filter", "repeat", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Oiiddd|sp",
                                     const_cast<char**>(names), &rgba_object,
                                     &width, &height, &u, &v, &lod, &filter,
                                     &repeat)) return nullptr;
    std::vector<std::uint8_t> rgba;
    if (!parse_rgba_buffer(rgba_object, rgba)) return nullptr;
    try {
        const auto levels = vector_engine::generate_mipmaps(rgba, width, height);
        const auto color = vector_engine::sample_mipmaps(
            levels, u, v, lod, filter, repeat != 0);
        return Py_BuildValue("(BBBB)", color[0], color[1], color[2], color[3]);
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_ValueError, error.what()); return nullptr;
    }
}

PyObject* py_sample_anisotropic(PyObject*, PyObject* args, PyObject* kwargs) {
    PyObject* rgba_object = nullptr;
    int width = 0, height = 0, max_taps = 8, repeat = 1;
    double u = 0.0, v = 0.0, dudx = 0.0, dvdx = 0.0, dudy = 0.0, dvdy = 0.0;
    static const char* names[] = {"rgba", "width", "height", "u", "v",
        "dudx", "dvdx", "dudy", "dvdy", "max_taps", "repeat", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "Oiiddddddip",
            const_cast<char**>(names), &rgba_object, &width, &height, &u, &v,
            &dudx, &dvdx, &dudy, &dvdy, &max_taps, &repeat)) return nullptr;
    std::vector<std::uint8_t> rgba;
    if (!parse_rgba_buffer(rgba_object, rgba)) return nullptr;
    try {
        const auto levels = vector_engine::generate_mipmaps(rgba, width, height);
        const auto result = vector_engine::sample_anisotropic(
            levels, u, v, dudx, dvdx, dudy, dvdy, max_taps, repeat != 0);
        const auto& color = result.first;
        const auto& footprint = result.second;
        return Py_BuildValue("(BBBBdddddddi)", color[0], color[1], color[2],
            color[3], footprint.major, footprint.minor, footprint.ratio,
            footprint.isotropic_lod, footprint.anisotropic_lod,
            footprint.direction_u, footprint.direction_v, footprint.taps);
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_ValueError, error.what()); return nullptr;
    }
}

PyMethodDef methods[] = {
    {"tessellate_stroke", reinterpret_cast<PyCFunction>(py_tessellate_stroke),
     METH_VARARGS | METH_KEYWORDS, "Tessellate a polyline into 2D triangles."},
    {"tessellate_stroke_coverage",
     reinterpret_cast<PyCFunction>(py_tessellate_stroke_coverage),
     METH_VARARGS | METH_KEYWORDS,
     "Tessellate a polyline into x/y/coverage triangles."},
    {"visibility_polygon", reinterpret_cast<PyCFunction>(py_visibility_polygon),
     METH_VARARGS | METH_KEYWORDS,
     "Compute a 2D visibility polygon and nearest-hit rays."},
    {"extrude_mesh", reinterpret_cast<PyCFunction>(py_extrude_mesh),
     METH_VARARGS | METH_KEYWORDS, "Extrude a 2D contour and fill triangles."},
    {"cube_mesh", py_cube_mesh, METH_NOARGS, "Build a normalized cube mesh."},
    {"software_rasterize", reinterpret_cast<PyCFunction>(py_software_rasterize),
     METH_VARARGS | METH_KEYWORDS,
     "Rasterize clip-space triangles into CPU color/depth/barycentric buffers."},
    {"generate_mipmaps", py_generate_mipmaps, METH_VARARGS,
     "Generate a complete RGBA8 mip chain with a 2x2 box filter."},
    {"sample_texture", reinterpret_cast<PyCFunction>(py_sample_texture),
     METH_VARARGS | METH_KEYWORDS,
     "Sample an RGBA8 mip chain with nearest, bilinear or trilinear filtering."},
    {"sample_anisotropic", reinterpret_cast<PyCFunction>(py_sample_anisotropic),
     METH_VARARGS | METH_KEYWORDS,
     "Sample an RGBA8 mip chain along a derivative footprint major axis."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {PyModuleDef_HEAD_INIT, "vector_engine_native",
                      "Optional C++ geometry kernel for vector_editor.", -1, methods};

}  // namespace

PyMODINIT_FUNC PyInit_vector_engine_native() {
    PyObject* result = PyModule_Create(&module);
    if (!result) return nullptr;
    PyModule_AddStringConstant(result, "__version__", "0.1.0");
#ifdef _MSC_VER
    PyModule_AddIntConstant(result, "msvc_version", _MSC_VER);
#endif
    return result;
}
