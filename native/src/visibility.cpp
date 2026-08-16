#include "visibility.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace vector_engine {
namespace {

constexpr double kParallelEpsilon = 1e-9;
constexpr double kPointEpsilonSquared = 1e-10;

double cross(double ax, double ay, double bx, double by) {
    return ax * by - ay * bx;
}

bool ray_segment_hit(const Point2& origin, double dx, double dy,
                     const Segment2& segment, double& distance, Point2& point) {
    const double sx = segment.second.x - segment.first.x;
    const double sy = segment.second.y - segment.first.y;
    const double denominator = cross(dx, dy, sx, sy);
    if (std::abs(denominator) <= kParallelEpsilon) return false;
    const double qx = segment.first.x - origin.x;
    const double qy = segment.first.y - origin.y;
    const double ray_distance = cross(qx, qy, sx, sy) / denominator;
    const double along_segment = cross(qx, qy, dx, dy) / denominator;
    if (ray_distance < 0.0 || along_segment < -kParallelEpsilon ||
        along_segment > 1.0 + kParallelEpsilon) {
        return false;
    }
    distance = ray_distance;
    point = {origin.x + ray_distance * dx, origin.y + ray_distance * dy};
    return true;
}

bool same_point(const Point2& first, const Point2& second) {
    const double dx = first.x - second.x;
    const double dy = first.y - second.y;
    return dx * dx + dy * dy <= kPointEpsilonSquared;
}

}  // namespace

VisibilityOutput visibility_polygon(const Point2& light,
                                    const std::vector<Segment2>& segments,
                                    double angle_epsilon) {
    if (!(angle_epsilon > 0.0)) {
        throw std::invalid_argument("angle_epsilon must be positive");
    }
    std::vector<double> angles;
    angles.reserve(segments.size() * 6);
    for (const auto& segment : segments) {
        for (const Point2 point : {segment.first, segment.second}) {
            const double angle = std::atan2(point.y - light.y, point.x - light.x);
            angles.push_back(angle - angle_epsilon);
            angles.push_back(angle);
            angles.push_back(angle + angle_epsilon);
        }
    }

    VisibilityOutput output;
    std::vector<VisibilityRay> hits;
    hits.reserve(angles.size());
    for (const double angle : angles) {
        const double dx = std::cos(angle);
        const double dy = std::sin(angle);
        double nearest = std::numeric_limits<double>::infinity();
        Point2 nearest_point{};
        std::size_t nearest_index = 0;
        bool found = false;
        for (std::size_t index = 0; index < segments.size(); ++index) {
            ++output.intersection_tests;
            double distance = 0.0;
            Point2 point{};
            if (ray_segment_hit(light, dx, dy, segments[index], distance, point) &&
                distance < nearest) {
                nearest = distance;
                nearest_point = point;
                nearest_index = index;
                found = true;
            }
        }
        if (found) hits.push_back({angle, nearest_point, nearest, nearest_index});
    }
    std::sort(hits.begin(), hits.end(), [](const auto& first, const auto& second) {
        return first.angle < second.angle;
    });
    for (const auto& hit : hits) {
        if (!output.rays.empty() && same_point(output.rays.back().point, hit.point)) {
            continue;
        }
        output.rays.push_back(hit);
    }
    if (output.rays.size() > 1 &&
        same_point(output.rays.front().point, output.rays.back().point)) {
        output.rays.pop_back();
    }
    output.polygon.reserve(output.rays.size());
    for (const auto& ray : output.rays) output.polygon.push_back(ray.point);
    return output;
}

}  // namespace vector_engine
