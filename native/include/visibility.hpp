#pragma once

#include <cstddef>
#include <vector>

#include "stroke_tessellation.hpp"

namespace vector_engine {

struct Segment2 {
    Point2 first;
    Point2 second;
};

struct VisibilityRay {
    double angle;
    Point2 point;
    double distance;
    std::size_t segment_index;
};

struct VisibilityOutput {
    std::vector<Point2> polygon;
    std::vector<VisibilityRay> rays;
    std::size_t intersection_tests = 0;
};

VisibilityOutput visibility_polygon(const Point2& light,
                                    const std::vector<Segment2>& segments,
                                    double angle_epsilon = 1e-5);

}  // namespace vector_engine
