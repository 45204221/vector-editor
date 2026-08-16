#pragma once

#include <string>
#include <vector>

namespace vector_engine {

struct Point2 {
    double x;
    double y;
};

struct CoverageVertex {
    double x;
    double y;
    double coverage;
};

using Mesh2 = std::vector<Point2>;
using Mesh3 = std::vector<CoverageVertex>;

Mesh2 tessellate_stroke(const std::vector<Point2>& points, double width,
                        bool closed = false, const std::string& join = "miter",
                        const std::string& cap = "butt", double miter_limit = 4.0,
                        int round_segments = 8);

Mesh3 tessellate_stroke_coverage(
    const std::vector<Point2>& points, double width, bool closed = false,
    const std::string& join = "miter", const std::string& cap = "butt",
    double antialias_width = 1.0, double miter_limit = 4.0,
    int round_segments = 8);

}  // namespace vector_engine
