#include "stroke_tessellation.hpp"

#include <algorithm>
#include <cmath>
#include <optional>

namespace vector_engine {
namespace {

constexpr double kEpsilon = 1e-8;
constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr double kTau = kPi * 2.0;

Point2 add(Point2 a, Point2 b) { return {a.x + b.x, a.y + b.y}; }
Point2 sub(Point2 a, Point2 b) { return {a.x - b.x, a.y - b.y}; }
Point2 mul(Point2 point, double scalar) { return {point.x * scalar, point.y * scalar}; }
double length(Point2 point) { return std::hypot(point.x, point.y); }
double cross(Point2 a, Point2 b) { return a.x * b.y - a.y * b.x; }

std::optional<Point2> line_intersection(Point2 first, Point2 first_direction,
                                        Point2 second, Point2 second_direction) {
    const double denominator = cross(first_direction, second_direction);
    if (std::abs(denominator) <= kEpsilon) {
        return std::nullopt;
    }
    const Point2 offset = sub(second, first);
    const double distance = cross(offset, second_direction) / denominator;
    return add(first, mul(first_direction, distance));
}

std::vector<Point2> clean_points(const std::vector<Point2>& points, bool closed) {
    std::vector<Point2> result;
    result.reserve(points.size());
    for (const Point2 point : points) {
        if (result.empty() || length(sub(point, result.back())) > kEpsilon) {
            result.push_back(point);
        }
    }
    if (closed && result.size() > 1 &&
        length(sub(result.front(), result.back())) <= kEpsilon) {
        result.pop_back();
    }
    return result;
}

void triangle(Mesh2& result, Point2 first, Point2 second, Point2 third) {
    if (std::abs(cross(sub(second, first), sub(third, first))) > kEpsilon) {
        result.push_back(first);
        result.push_back(second);
        result.push_back(third);
    }
}

void round_fan(Mesh2& result, Point2 center, Point2 start, Point2 end,
               bool clockwise, int segments) {
    const double start_angle = std::atan2(start.y - center.y, start.x - center.x);
    double end_angle = std::atan2(end.y - center.y, end.x - center.x);
    if (clockwise) {
        while (end_angle >= start_angle) end_angle -= kTau;
    } else {
        while (end_angle <= start_angle) end_angle += kTau;
    }
    const double sweep = end_angle - start_angle;
    const int steps = std::max(
        1, static_cast<int>(std::ceil(
               std::abs(sweep) / kPi * std::max(2, segments) - 1e-12)));
    const double radius = length(sub(start, center));
    Point2 previous = start;
    for (int step = 1; step <= steps; ++step) {
        const double angle = start_angle + sweep * step / steps;
        const Point2 current{center.x + std::cos(angle) * radius,
                             center.y + std::sin(angle) * radius};
        triangle(result, center, previous, current);
        previous = current;
    }
}

struct Segment {
    int index;
    Point2 first;
    Point2 second;
    Point2 direction;
    Point2 normal;
};

std::vector<Segment> make_segments(const std::vector<Point2>& points, bool closed) {
    std::vector<Segment> result;
    const int count = closed ? static_cast<int>(points.size())
                             : static_cast<int>(points.size()) - 1;
    for (int index = 0; index < count; ++index) {
        const Point2 first = points[index];
        const Point2 second = points[(index + 1) % points.size()];
        const Point2 offset = sub(second, first);
        const double segment_length = length(offset);
        if (segment_length <= kEpsilon) continue;
        const Point2 direction = mul(offset, 1.0 / segment_length);
        result.push_back({index, first, second, direction,
                          {-direction.y, direction.x}});
    }
    return result;
}

void coverage_triangle(Mesh3& result, CoverageVertex first, CoverageVertex second,
                       CoverageVertex third) {
    if (std::abs(cross(sub({second.x, second.y}, {first.x, first.y}),
                       sub({third.x, third.y}, {first.x, first.y}))) > kEpsilon) {
        result.push_back(first);
        result.push_back(second);
        result.push_back(third);
    }
}

void coverage_quad(Mesh3& result, Point2 inner_first, Point2 inner_second,
                   Point2 outer_second, Point2 outer_first) {
    coverage_triangle(result, {inner_first.x, inner_first.y, 1.0},
                      {inner_second.x, inner_second.y, 1.0},
                      {outer_second.x, outer_second.y, 0.0});
    coverage_triangle(result, {inner_first.x, inner_first.y, 1.0},
                      {outer_second.x, outer_second.y, 0.0},
                      {outer_first.x, outer_first.y, 0.0});
}

void arc_ring(Mesh3& result, Point2 center, Point2 inner_start, Point2 inner_end,
              bool clockwise, double outer_radius, int segments) {
    const double start_angle =
        std::atan2(inner_start.y - center.y, inner_start.x - center.x);
    double end_angle = std::atan2(inner_end.y - center.y, inner_end.x - center.x);
    if (clockwise) {
        while (end_angle >= start_angle) end_angle -= kTau;
    } else {
        while (end_angle <= start_angle) end_angle += kTau;
    }
    const double sweep = end_angle - start_angle;
    const int steps = std::max(
        1, static_cast<int>(std::ceil(
               std::abs(sweep) / kPi * std::max(2, segments) - 1e-12)));
    const double inner_radius = length(sub(inner_start, center));
    Point2 previous_inner = inner_start;
    Point2 previous_outer{center.x + std::cos(start_angle) * outer_radius,
                          center.y + std::sin(start_angle) * outer_radius};
    for (int step = 1; step <= steps; ++step) {
        const double angle = start_angle + sweep * step / steps;
        const Point2 current_inner{center.x + std::cos(angle) * inner_radius,
                                   center.y + std::sin(angle) * inner_radius};
        const Point2 current_outer{center.x + std::cos(angle) * outer_radius,
                                   center.y + std::sin(angle) * outer_radius};
        coverage_quad(result, previous_inner, current_inner, current_outer,
                      previous_outer);
        previous_inner = current_inner;
        previous_outer = current_outer;
    }
}

std::string valid_join(const std::string& value) {
    return value == "miter" || value == "bevel" || value == "round" ? value : "miter";
}
std::string valid_cap(const std::string& value) {
    return value == "butt" || value == "square" || value == "round" ? value : "butt";
}

}  // namespace

Mesh2 tessellate_stroke(const std::vector<Point2>& input, double width, bool closed,
                        const std::string& join_value, const std::string& cap_value,
                        double miter_limit, int round_segments) {
    const std::vector<Point2> points = clean_points(input, closed);
    width = std::max(0.0, width);
    if (width <= kEpsilon || points.size() < 2) return {};
    const std::string join = valid_join(join_value);
    const std::string cap = valid_cap(cap_value);
    const double half = width / 2.0;
    const std::vector<Segment> segments = make_segments(points, closed);
    if (segments.empty()) return {};

    Mesh2 result;
    for (std::size_t position = 0; position < segments.size(); ++position) {
        Point2 first = segments[position].first;
        Point2 second = segments[position].second;
        const Point2 direction = segments[position].direction;
        const Point2 normal = segments[position].normal;
        if (!closed && cap == "square") {
            if (position == 0) first = sub(first, mul(direction, half));
            if (position + 1 == segments.size()) second = add(second, mul(direction, half));
        }
        const Point2 normal_offset = mul(normal, half);
        const Point2 first_left = add(first, normal_offset);
        const Point2 first_right = sub(first, normal_offset);
        const Point2 second_left = add(second, normal_offset);
        const Point2 second_right = sub(second, normal_offset);
        triangle(result, first_left, first_right, second_right);
        triangle(result, first_left, second_right, second_left);
    }

    const int join_start = closed ? 0 : 1;
    const int join_end = closed ? static_cast<int>(points.size())
                                : static_cast<int>(points.size()) - 1;
    for (int index = join_start; index < join_end; ++index) {
        const Segment& previous = segments[(index - 1 + segments.size()) % segments.size()];
        const Segment& following = segments[index % segments.size()];
        const Point2 center = points[index];
        const double turn = cross(previous.direction, following.direction);
        if (std::abs(turn) <= kEpsilon) continue;
        const double side = turn > 0 ? -1.0 : 1.0;
        const Point2 outer_previous = add(center, mul(previous.normal, half * side));
        const Point2 outer_next = add(center, mul(following.normal, half * side));
        if (join == "round") {
            round_fan(result, center, outer_previous, outer_next, turn < 0,
                      round_segments);
            continue;
        }
        if (join == "miter") {
            const auto miter = line_intersection(outer_previous, previous.direction,
                                                 outer_next, following.direction);
            if (miter && length(sub(*miter, center)) <= miter_limit * half) {
                triangle(result, outer_previous, *miter, outer_next);
                continue;
            }
        }
        triangle(result, outer_previous, center, outer_next);
    }

    if (!closed && cap == "round") {
        const Point2 first = points.front();
        const Point2 first_normal = segments.front().normal;
        round_fan(result, first, add(first, mul(first_normal, half)),
                  sub(first, mul(first_normal, half)), false, round_segments);
        const Point2 last = points.back();
        const Point2 last_normal = segments.back().normal;
        round_fan(result, last, sub(last, mul(last_normal, half)),
                  add(last, mul(last_normal, half)), false, round_segments);
    }
    return result;
}

Mesh3 tessellate_stroke_coverage(
    const std::vector<Point2>& input, double width, bool closed,
    const std::string& join_value, const std::string& cap_value,
    double antialias_width, double miter_limit, int round_segments) {
    const std::vector<Point2> points = clean_points(input, closed);
    width = std::max(0.0, width);
    antialias_width = std::max(0.0, antialias_width);
    const Mesh2 core = tessellate_stroke(points, width, closed, join_value, cap_value,
                                         miter_limit, round_segments);
    if (core.empty()) return {};
    if (antialias_width <= kEpsilon) {
        Mesh3 opaque;
        opaque.reserve(core.size());
        for (const Point2 point : core) opaque.push_back({point.x, point.y, 1.0});
        return opaque;
    }
    const std::string join = valid_join(join_value);
    const std::string cap = valid_cap(cap_value);
    const double half = width / 2.0;
    const double outer_half = half + antialias_width;
    const std::vector<Segment> segments = make_segments(points, closed);
    Mesh3 fringe;

    for (std::size_t position = 0; position < segments.size(); ++position) {
        Point2 first = segments[position].first;
        Point2 second = segments[position].second;
        const Point2 direction = segments[position].direction;
        const Point2 normal = segments[position].normal;
        if (!closed && cap == "square") {
            if (position == 0) first = sub(first, mul(direction, half));
            if (position + 1 == segments.size()) second = add(second, mul(direction, half));
        }
        const Point2 inner = mul(normal, half);
        const Point2 outer = mul(normal, outer_half);
        coverage_quad(fringe, add(first, inner), add(second, inner),
                      add(second, outer), add(first, outer));
        coverage_quad(fringe, sub(second, inner), sub(first, inner),
                      sub(first, outer), sub(second, outer));
    }

    const int join_start = closed ? 0 : 1;
    const int join_end = closed ? static_cast<int>(points.size())
                                : static_cast<int>(points.size()) - 1;
    for (int index = join_start; index < join_end; ++index) {
        const Segment& previous = segments[(index - 1 + segments.size()) % segments.size()];
        const Segment& following = segments[index % segments.size()];
        const Point2 center = points[index];
        const double turn = cross(previous.direction, following.direction);
        if (std::abs(turn) <= kEpsilon) continue;
        const double side = turn > 0 ? -1.0 : 1.0;
        const Point2 inner_previous = add(center, mul(previous.normal, half * side));
        const Point2 inner_next = add(center, mul(following.normal, half * side));
        const Point2 outer_previous = add(center, mul(previous.normal, outer_half * side));
        const Point2 outer_next = add(center, mul(following.normal, outer_half * side));
        if (join == "round") {
            arc_ring(fringe, center, inner_previous, inner_next, turn < 0,
                     outer_half, round_segments);
            continue;
        }
        if (join == "miter") {
            const auto inner_miter = line_intersection(
                inner_previous, previous.direction, inner_next, following.direction);
            const auto outer_miter = line_intersection(
                outer_previous, previous.direction, outer_next, following.direction);
            if (inner_miter && outer_miter &&
                length(sub(*inner_miter, center)) <= miter_limit * half &&
                length(sub(*outer_miter, center)) <= miter_limit * outer_half) {
                coverage_quad(fringe, inner_previous, *inner_miter,
                              *outer_miter, outer_previous);
                coverage_quad(fringe, *inner_miter, inner_next,
                              outer_next, *outer_miter);
                continue;
            }
        }
        coverage_quad(fringe, inner_previous, inner_next, outer_next, outer_previous);
    }

    if (!closed) {
        for (int endpoint = 0; endpoint < 2; ++endpoint) {
            const bool is_start = endpoint == 0;
            const Segment& segment = is_start ? segments.front() : segments.back();
            Point2 center = is_start ? segment.first : segment.second;
            const Point2 direction = segment.direction;
            const Point2 normal = segment.normal;
            if (cap == "round") {
                const Point2 inner_start = is_start ? add(center, mul(normal, half))
                                                    : sub(center, mul(normal, half));
                const Point2 inner_end = is_start ? sub(center, mul(normal, half))
                                                  : add(center, mul(normal, half));
                arc_ring(fringe, center, inner_start, inner_end, false, outer_half,
                         round_segments);
            } else {
                if (cap == "square") {
                    center = is_start ? sub(center, mul(direction, half))
                                      : add(center, mul(direction, half));
                }
                const Point2 outward = mul(direction, is_start ? -antialias_width
                                                               : antialias_width);
                const Point2 inner_left = add(center, mul(normal, half));
                const Point2 inner_right = sub(center, mul(normal, half));
                coverage_quad(fringe, inner_right, inner_left,
                              add(inner_left, outward), add(inner_right, outward));
            }
        }
    }

    fringe.reserve(fringe.size() + core.size());
    for (const Point2 point : core) fringe.push_back({point.x, point.y, 1.0});
    return fringe;
}

}  // namespace vector_engine
