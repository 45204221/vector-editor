#include "mesh_extrusion.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace vector_engine {
namespace {

constexpr std::size_t kMaxVertices = 100000;

void append_triangle(Mesh3D& result, const Point2& a, const Point2& b,
                     const Point2& c, double z, double nx, double ny, double nz) {
    result.push_back({a.x, a.y, z, nx, ny, nz});
    result.push_back({b.x, b.y, z, nx, ny, nz});
    result.push_back({c.x, c.y, z, nx, ny, nz});
}

void normalize_inputs(const std::vector<Point2>& contour,
                      const std::vector<Point2>& triangles,
                      std::vector<Point2>& normalized_contour,
                      std::vector<Point2>& normalized_triangles) {
    if (contour.size() < 3 || triangles.size() < 3) {
        throw std::invalid_argument("extrusion needs a closed contour and fill triangles");
    }
    double min_x = contour.front().x, max_x = contour.front().x;
    double min_y = contour.front().y, max_y = contour.front().y;
    for (const auto& point : contour) {
        min_x = std::min(min_x, point.x); max_x = std::max(max_x, point.x);
        min_y = std::min(min_y, point.y); max_y = std::max(max_y, point.y);
    }
    const double cx = (min_x + max_x) * 0.5;
    const double cy = (min_y + max_y) * 0.5;
    const double scale = 2.0 / std::max({max_x - min_x, max_y - min_y, 1e-9});
    auto convert = [=](const Point2& point) {
        return Point2{(point.x - cx) * scale, -(point.y - cy) * scale};
    };
    normalized_contour.reserve(contour.size());
    normalized_triangles.reserve(triangles.size());
    for (const auto& point : contour) normalized_contour.push_back(convert(point));
    for (const auto& point : triangles) normalized_triangles.push_back(convert(point));
}

}  // namespace

Mesh3D extrude_mesh(const std::vector<Point2>& input_contour,
                    const std::vector<Point2>& input_triangles,
                    double depth) {
    if (depth <= 0.0) throw std::invalid_argument("extrusion depth must be positive");
    std::vector<Point2> contour, triangles;
    normalize_inputs(input_contour, input_triangles, contour, triangles);
    const double front_z = depth * 0.5;
    const double back_z = -front_z;
    Mesh3D result;
    result.reserve(triangles.size() * 2 + contour.size() * 6);
    for (std::size_t index = 0; index + 2 < triangles.size(); index += 3) {
        auto first = triangles[index];
        auto second = triangles[index + 1];
        auto third = triangles[index + 2];
        const double cross = (second.x - first.x) * (third.y - first.y) -
                             (second.y - first.y) * (third.x - first.x);
        if (std::abs(cross) <= 1e-12) continue;
        if (cross < 0.0) std::swap(second, third);
        append_triangle(result, first, second, third, front_z, 0.0, 0.0, 1.0);
        append_triangle(result, first, third, second, back_z, 0.0, 0.0, -1.0);
    }
    double twice_area = 0.0;
    for (std::size_t index = 0; index < contour.size(); ++index) {
        const auto& first = contour[index];
        const auto& second = contour[(index + 1) % contour.size()];
        twice_area += first.x * second.y - second.x * first.y;
    }
    const double orientation = twice_area >= 0.0 ? 1.0 : -1.0;
    for (std::size_t index = 0; index < contour.size(); ++index) {
        const auto& first = contour[index];
        const auto& second = contour[(index + 1) % contour.size()];
        const double dx = second.x - first.x;
        const double dy = second.y - first.y;
        const double length = std::hypot(dx, dy);
        if (length <= 1e-12) continue;
        const double nx = orientation * dy / length;
        const double ny = -orientation * dx / length;
        result.push_back({first.x, first.y, front_z, nx, ny, 0.0});
        result.push_back({first.x, first.y, back_z, nx, ny, 0.0});
        result.push_back({second.x, second.y, back_z, nx, ny, 0.0});
        result.push_back({first.x, first.y, front_z, nx, ny, 0.0});
        result.push_back({second.x, second.y, back_z, nx, ny, 0.0});
        result.push_back({second.x, second.y, front_z, nx, ny, 0.0});
    }
    if (result.size() > kMaxVertices) {
        throw std::invalid_argument("mesh exceeds 100000 vertices");
    }
    return result;
}

Mesh3D cube_mesh() {
    const std::vector<Point2> contour{{-1.0, -1.0}, {1.0, -1.0},
                                      {1.0, 1.0}, {-1.0, 1.0}};
    const std::vector<Point2> triangles{contour[0], contour[1], contour[2],
                                        contour[0], contour[2], contour[3]};
    return extrude_mesh(contour, triangles, 2.0);
}

}  // namespace vector_engine
