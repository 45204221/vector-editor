#pragma once

#include <string>
#include <vector>

#include "stroke_tessellation.hpp"

namespace vector_engine {

struct MeshVertex3D {
    double x{};
    double y{};
    double z{};
    double nx{};
    double ny{};
    double nz{};
};

using Mesh3D = std::vector<MeshVertex3D>;

Mesh3D extrude_mesh(const std::vector<Point2>& contour,
                    const std::vector<Point2>& triangles,
                    double depth);
Mesh3D cube_mesh();

}  // namespace vector_engine
